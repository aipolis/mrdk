# -*- coding: utf-8 -*-
"""明日当空 API 服务"""
from __future__ import annotations

import copy
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Header, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from config import APP_ENV, CRON_SECRET, SUBSCRIBE_FIELD_KEYS, SUBSCRIBE_TEMPLATES, SYNC_HISTORY_DAYS
from intraday import (
    build_intraday_payload,
    calc_display_score,
    intraday_session_phase,
    order_indicator_sections,
)
from fetcher import (
    build_auction_sentiment,
    build_day_metrics,
    build_home_trend,
    build_indicator_sections,
    build_indicators,
    build_ref_day_metrics,
    build_section_metas,
    build_yesterday_sentiment,
    date_str,
    display_level_class,
    display_level_label,
    fetch_foreign_sentiment,
    fetch_peripheral_sentiment,
    fetch_sse_index_change,
    get_recent_trade_dates,
    invalidate_intraday_caches,
    invalidate_peripheral_cache,
    load_advice_metrics,
    load_auction_snapshot,
    load_ref_day_snapshot,
    _fill_metrics_breadth,
)
from home_cache import (
    build_and_store,
    cache_status,
    ensure_memory_loaded,
    get_snapshot,
    is_stale,
    patch_home_cache,
    start_background_refresh,
    stop_background_refresh,
    trigger_async_build,
)
from history_store import fetch_daily_detail, fetch_history_list, build_history_item
from history_sync import (
    persist_auction_snapshot,
    persist_day,
    persist_from_home,
    persist_peripheral_db_0900,
    persist_trading_day_snapshot,
    request_stop_sync,
    sync_history_days,
    trigger_sync_history_days,
)
from ocr import ocr_image
from scheduler import run_async_coro, start_internal_cron, stop_internal_cron
from sentiment import (
    apply_display_longkong,
    calc_sentiment,
    position_desc,
    strategy_note_for_home,
)
from subscribe_msg import (
    broadcast_daily_sentiment,
    build_subscribe_message,
    code_to_openid,
    code_to_session,
    register_subscriber,
    send_subscribe_message,
)
from user_store import upsert_user_login, users_status

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mingri.app")

MAX_OCR_BYTES = 5 * 1024 * 1024


def _is_production() -> bool:
    return APP_ENV in ("prod", "production")


def _cron_auth_error(x_cron_secret: str = "") -> Optional[dict]:
    """定时/管理类接口鉴权。生产环境必须配置 CRON_SECRET。"""
    if CRON_SECRET:
        if x_cron_secret != CRON_SECRET:
            return {"code": 403, "message": "unauthorized"}
        return None
    if _is_production():
        return {"code": 503, "message": "CRON_SECRET not configured"}
    log.warning("CRON_SECRET 未配置，管理类接口处于开放状态（仅限开发环境）")
    return None


def _fmt_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def resolve_advice_dates() -> tuple[str, Optional[str], str, bool]:
    """返回参考数据日、对比日、建议适用日、是否已过当日09:15"""
    dates = get_recent_trade_dates(15)
    now = datetime.now()
    today = date_str(now)

    if not dates:
        return today, None, today, False

    if today in dates:
        advice_d = today
        idx = dates.index(today)
        ref_d = dates[idx - 1] if idx > 0 else dates[0]
    else:
        # 非交易日：指标仍用最近收盘日 ref_d，展示日期用自然日 today
        ref_d = dates[-1]
        advice_d = today

    ref_idx = dates.index(ref_d)
    prev_d = dates[ref_idx - 1] if ref_idx > 0 else None

    is_ready = True
    if advice_d == today and today in dates:
        is_ready = now.hour > 9 or (now.hour == 9 and now.minute >= 15)

    return ref_d, prev_d, advice_d, is_ready


def _build_home_payload(ref_d: str, prev_d: Optional[str], advice_d: str, is_ready: bool = True) -> dict:
    metrics, prev_metrics, grid9 = load_ref_day_snapshot(ref_d, prev_d)
    advice_metrics = load_advice_metrics(advice_d)
    peripheral = fetch_peripheral_sentiment()
    auction = load_auction_snapshot(
        advice_d, ref_d, prev_d, metrics, prev_metrics, is_ready=is_ready
    )
    sentiment = calc_sentiment(
        metrics,
        peripheral=peripheral,
        auction=auction,
        grid9=grid9,
    )
    indicators = build_indicators(metrics, prev_metrics)

    trend = build_home_trend(ref_d)

    intraday_payload = build_intraday_payload(metrics, ref_d=ref_d, auction=auction)
    baseline_score = int(sentiment["score"])
    intraday_score = intraday_payload.get("intradayScore")
    display_score, score_mode = calc_display_score(baseline_score, intraday_score)
    longkong = apply_display_longkong(
        sentiment, display_score, score_mode=score_mode
    )
    strategy_note = strategy_note_for_home(
        sentiment, display_score, score_mode=score_mode, longkong=longkong
    )

    sentiment_for_sub = {**sentiment, **longkong, "displayScore": display_score}
    subscribe_preview = build_subscribe_message(
        sentiment_for_sub,
        ref_date=metrics["date"],
        advice_date=_fmt_date(advice_d),
    )
    ui_level = display_level_label(display_score)
    ui_level_class = display_level_class(display_score)
    indicator_sections = build_indicator_sections(
        ref_d, prev_d, metrics, prev_metrics, advice_d=advice_d, is_ready=is_ready
    )
    metas, gauge_label, now_hm = build_section_metas(
        ref_d, advice_d, is_ready, ref_metrics=metrics, advice_metrics=advice_metrics
    )
    for sec in indicator_sections:
        sid = sec.get("id")
        if sid == "yesterday":
            sec["items"] = grid9
            sec["meta"] = metas["yesterday"]
        elif sid == "peripheral":
            sec["items"] = peripheral
            sec["meta"] = metas["peripheral"]
        elif sid == "auction":
            sec["items"] = auction
            sec["meta"] = metas["auction"]

    if intraday_payload.get("items"):
        indicator_sections.append(
            {
                "id": "intraday",
                "title": "盘中实时情绪",
                "meta": metas.get("intraday") or f"今日 {intraday_payload.get('updatedAt', now_hm)} 更新",
                "layout": "grid3",
                "cols": 3,
                "items": intraday_payload["items"],
                "pending": not intraday_payload.get("active"),
            }
        )
    indicator_sections = order_indicator_sections(indicator_sections)

    gauge_display = gauge_label
    if score_mode == "live" and intraday_payload.get("updatedAt"):
        gauge_display = f"盘中 {intraday_payload['updatedAt']} 更新"
    elif score_mode == "live" and intraday_score is not None:
        gauge_display = "竞价更新"

    return {
        "adviceDate": _fmt_date(advice_d),
        "refDate": metrics["date"],
        "date": _fmt_date(advice_d),
        "generatedAt": gauge_display,
        "generatedAtLabel": gauge_display,
        "generatedAtTime": intraday_payload.get("updatedAt") or now_hm,
        "dailyQuote": "买在分歧，卖在一致",
        "overview": peripheral,
        "foreignCards": fetch_foreign_sentiment(),
        "grid9": grid9,
        "peripheral": peripheral,
        "auction": auction,
        "intraday": intraday_payload.get("items") or [],
        "indicatorSections": indicator_sections,
        "subscribePreview": {
            "strategy": subscribe_preview["strategy"],
            "keyData": subscribe_preview["keyData"],
            "time": subscribe_preview["time"],
            "tips": subscribe_preview["tips"],
        },
        "score": baseline_score,
        "baselineScore": baseline_score,
        "liveScore": intraday_score,
        "displayScore": display_score,
        "scoreMode": score_mode,
        "levelLabel": ui_level,
        "displayLevel": ui_level,
        "levelClass": ui_level_class,
        "levelColor": sentiment["levelColor"],
        "longkongSignal": longkong["longkongSignal"],
        "positionPercent": longkong["positionPercent"],
        "positionLabel": longkong["positionLabel"],
        "positionDesc": position_desc(display_score, longkong["emptyWarning"]),
        "emptyWarning": longkong["emptyWarning"],
        "emptyReasons": longkong["emptyReasons"],
        "strategyNote": strategy_note,
        "baselineEmptyWarning": sentiment["emptyWarning"],
        "baselineEmptyReasons": sentiment["emptyReasons"],
        "baselinePositionPercent": sentiment["positionPercent"],
        "baselinePositionLabel": sentiment["positionLabel"],
        "indicators": [
            {**ind, "yesterday": ind["yesterday"].replace("前日 ", "") if str(ind["yesterday"]).startswith("前日") else ind["yesterday"]}
            for ind in indicators
        ],
        "trend": trend,
        "metrics": metrics,
        "prevMetrics": prev_metrics,
    }


def _build_home_for_cache() -> tuple[dict, dict]:
    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    data = _build_home_payload(ref_d, prev_d, advice_d, is_ready)
    data["isReportReady"] = is_ready
    context = {
        "ref_d": ref_d,
        "prev_d": prev_d,
        "advice_d": advice_d,
        "is_ready": is_ready,
        "calendar_d": date_str(datetime.now()),
    }
    _persist_home_days(ref_d, prev_d, advice_d, data)
    return data, context


def _persist_home_days(
    ref_d: str,
    prev_d: Optional[str],
    advice_d: str,
    home_data: dict,
) -> None:
    """参考日完整归档；若 advice_d 为今日则额外写入实时外围/竞价/18项。"""
    try:
        persist_day(ref_d, prev_d, advice_d=ref_d, force=False)
        if advice_d != ref_d:
            persist_from_home(advice_d, ref_d, home_data, advice_d=advice_d)
    except Exception:
        log.exception("persist home days failed ref=%s advice=%s", ref_d, advice_d)


def _run_snapshot_1505() -> None:
    persist_trading_day_snapshot(freeze=False)
    build_and_store(_build_home_for_cache)


def _run_snapshot_1800() -> None:
    persist_trading_day_snapshot(freeze=True)
    build_and_store(_build_home_for_cache)


def _refresh_peripheral_live() -> None:
    """外围情绪：交易时段每 10 分钟刷新展示（入库仍以 9:00 快照为准）。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 or hm > 15 * 60:
        return

    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    advice_metrics = load_advice_metrics(advice_d)

    def patch(p: dict) -> dict:
        invalidate_peripheral_cache()
        peripheral = fetch_peripheral_sentiment()
        metas, _, _ = build_section_metas(
            ref_d,
            advice_d,
            is_ready,
            ref_metrics=p.get("metrics") or {},
            advice_metrics=advice_metrics,
        )
        p["peripheral"] = peripheral
        p["overview"] = peripheral
        for sec in p.get("indicatorSections") or []:
            if sec.get("id") == "peripheral":
                sec["items"] = peripheral
                sec["meta"] = metas["peripheral"]
        return p

    if not patch_home_cache(patch):
        build_and_store(_build_home_for_cache)


def _run_peripheral_0900() -> None:
    persist_peripheral_db_0900()
    _refresh_peripheral_live()


def _run_auction_0926() -> None:
    persist_auction_snapshot(freeze=False)
    build_and_store(_build_home_for_cache)


def _run_auction_0935() -> None:
    persist_auction_snapshot(freeze=True)
    build_and_store(_build_home_for_cache)


def _refresh_intraday_live() -> None:
    """盘中实时情绪：9:00 起含竞价，9:30 后每 2 分钟刷新指标与展示分。"""
    phase = intraday_session_phase()
    if phase not in ("waiting", "live"):
        return

    invalidate_intraday_caches()

    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    advice_metrics = load_advice_metrics(advice_d)

    def patch(p: dict) -> dict:
        metrics = p.get("metrics") or {}
        intraday_payload = build_intraday_payload(
            metrics, ref_d=ref_d, auction=p.get("auction")
        )
        live_raw = intraday_payload.get("intradayScore")
        if live_raw is None:
            return p

        baseline = int(p.get("baselineScore") or p.get("score") or 0)
        display_score, score_mode = calc_display_score(baseline, live_raw)
        baseline_sentiment = {
            "emptyWarning": bool(p.get("baselineEmptyWarning")),
            "emptyReasons": list(p.get("baselineEmptyReasons") or []),
            "positionPercent": p.get("baselinePositionPercent"),
            "positionLabel": p.get("baselinePositionLabel") or "",
        }
        longkong = apply_display_longkong(
            baseline_sentiment, display_score, score_mode=score_mode
        )
        metas, _, _ = build_section_metas(
            ref_d,
            advice_d,
            is_ready,
            ref_metrics=metrics,
            advice_metrics=advice_metrics,
        )
        updated = intraday_payload.get("updatedAt") or datetime.now().strftime("%H:%M")
        p["intraday"] = intraday_payload["items"]
        p["liveScore"] = live_raw
        p["displayScore"] = display_score
        p["scoreMode"] = score_mode
        if score_mode == "live" and intraday_payload.get("updatedAt"):
            p["generatedAt"] = f"盘中 {updated} 更新"
        elif score_mode == "live":
            p["generatedAt"] = f"竞价 {updated} 更新"
        p["generatedAtLabel"] = p["generatedAt"]
        p["generatedAtTime"] = updated
        p["levelLabel"] = display_level_label(display_score)
        p["displayLevel"] = p["levelLabel"]
        p["levelClass"] = display_level_class(display_score)
        p["longkongSignal"] = longkong["longkongSignal"]
        p["emptyWarning"] = longkong["emptyWarning"]
        p["emptyReasons"] = longkong["emptyReasons"]
        p["positionPercent"] = longkong["positionPercent"]
        p["positionLabel"] = longkong["positionLabel"]
        p["positionDesc"] = position_desc(display_score, longkong["emptyWarning"])
        baseline_sentiment_ref = {
            "emptyWarning": bool(p.get("baselineEmptyWarning")),
            "emptyReasons": p.get("baselineEmptyReasons") or [],
        }
        p["strategyNote"] = strategy_note_for_home(
            baseline_sentiment_ref,
            display_score,
            score_mode=score_mode,
            longkong=longkong,
        )

        sections = list(p.get("indicatorSections") or [])
        intraday_sec = {
            "id": "intraday",
            "title": "盘中实时情绪",
            "meta": metas.get("intraday") or p["generatedAt"],
            "layout": "grid3",
            "cols": 3,
            "items": intraday_payload["items"],
        }
        replaced = False
        for i, sec in enumerate(sections):
            if sec.get("id") == "intraday":
                sections[i] = intraday_sec
                replaced = True
                break
        if not replaced:
            sections.append(intraday_sec)
        p["indicatorSections"] = order_indicator_sections(sections)
        return p

    if not patch_home_cache(patch):
        build_and_store(_build_home_for_cache)


def _auction_section_empty(data: dict) -> bool:
    if data.get("auction"):
        return False
    for sec in data.get("indicatorSections") or []:
        if sec.get("id") == "auction" and sec.get("items"):
            return False
    return True


def _intraday_section_empty(data: dict) -> bool:
    if data.get("intraday"):
        return False
    for sec in data.get("indicatorSections") or []:
        if sec.get("id") == "intraday" and sec.get("items"):
            return False
    return True


def _apply_live_fields(
    data: dict,
    ref_d: str,
    advice_d: str,
    is_ready: bool,
    prev_d: Optional[str] = None,
) -> dict:
    """缓存命中时仅刷新时间类展示字段，避免整包重算。"""
    out = copy.deepcopy(data)
    today = date_str(datetime.now())
    ref_metrics = (out.get("metrics") or {}) if out.get("refDate", "").replace("-", "")[:8] == (ref_d or "")[:8] else {}
    advice_metrics = load_advice_metrics(advice_d)
    metas, gauge_label, now_hm = build_section_metas(
        ref_d, advice_d, is_ready, ref_metrics=ref_metrics, advice_metrics=advice_metrics
    )
    out["generatedAt"] = gauge_label
    out["generatedAtLabel"] = gauge_label
    out["generatedAtTime"] = now_hm
    out["adviceDate"] = _fmt_date(advice_d if advice_d else today)
    out["date"] = out["adviceDate"]
    out["isReportReady"] = is_ready
    sections = out.get("indicatorSections") or []

    if _auction_section_empty(out):
        fresh_auc = load_auction_snapshot(
            advice_d,
            ref_d,
            prev_d,
            out.get("metrics") or {},
            out.get("prevMetrics") or {},
            is_ready=is_ready,
        )
        if fresh_auc:
            out["auction"] = fresh_auc
            patched = False
            for sec in sections:
                if sec.get("id") == "auction":
                    sec["items"] = fresh_auc
                    patched = True
                    break
            if not patched:
                sections.append({
                    "id": "auction",
                    "title": "今日竞价情绪",
                    "meta": metas.get("auction") or "",
                    "layout": "grid3",
                    "cols": 3,
                    "items": fresh_auc,
                })

    if _intraday_section_empty(out):
        intraday_payload = build_intraday_payload(
            out.get("metrics") or {},
            ref_d=ref_d,
            auction=out.get("auction") or [],
        )
        if intraday_payload.get("items"):
            out["intraday"] = intraday_payload["items"]
            patched = False
            for sec in sections:
                if sec.get("id") == "intraday":
                    sec["items"] = intraday_payload["items"]
                    sec["pending"] = not intraday_payload.get("active")
                    patched = True
                    break
            if not patched:
                sections.append({
                    "id": "intraday",
                    "title": "盘中实时情绪",
                    "meta": metas.get("intraday") or "",
                    "layout": "grid3",
                    "cols": 3,
                    "items": intraday_payload["items"],
                    "pending": not intraday_payload.get("active"),
                })

    meta_map = {
        "yesterday": metas.get("yesterday"),
        "peripheral": metas.get("peripheral"),
        "auction": metas.get("auction"),
        "intraday": metas.get("intraday"),
    }
    for sec in sections:
        sec_id = sec.get("id")
        if sec_id in meta_map and meta_map[sec_id]:
            sec["meta"] = meta_map[sec_id]
    out["indicatorSections"] = order_indicator_sections(sections)
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _is_production() and not CRON_SECRET:
        log.error("生产环境未配置 CRON_SECRET，管理类接口将拒绝访问")
    elif not CRON_SECRET:
        log.warning("CRON_SECRET 未配置，管理类接口在开发环境处于开放状态")
    start_background_refresh(_build_home_for_cache)
    log.info("home sentiment cache warmup started")

    async def _daily_push_coro():
        await _run_daily_subscribe_push()

    start_internal_cron(
        warm_fn=lambda: build_and_store(_build_home_for_cache),
        sync_fn=lambda: sync_history_days(SYNC_HISTORY_DAYS),
        daily_push_fn=lambda: run_async_coro(_daily_push_coro),
        snapshot_1505_fn=_run_snapshot_1505,
        snapshot_1800_fn=_run_snapshot_1800,
        peripheral_0900_fn=_run_peripheral_0900,
        peripheral_10m_fn=_refresh_peripheral_live,
        auction_0926_fn=_run_auction_0926,
        auction_0935_fn=_run_auction_0935,
        intraday_2m_fn=_refresh_intraday_live,
    )
    yield
    stop_internal_cron()
    stop_background_refresh()


async def _run_daily_subscribe_push() -> dict:
    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    metrics = build_day_metrics(ref_d, prev_d)
    sentiment = calc_sentiment(metrics)
    daily = await broadcast_daily_sentiment(
        sentiment, metrics["date"], _fmt_date(advice_d), only_empty=False
    )
    empty_result = None
    if sentiment.get("emptyWarning"):
        empty_result = await broadcast_daily_sentiment(
            sentiment, metrics["date"], _fmt_date(advice_d), only_empty=True
        )
    return {
        "isReportReady": is_ready,
        "refDate": metrics["date"],
        "adviceDate": _fmt_date(advice_d),
        "daily": daily,
        "emptyAlert": empty_result,
    }


app = FastAPI(title="明日当空 API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "明日当空", "status": "ok", "version": "1.0.0"}


@app.get("/api/health")
def health(detail: int = 0, x_cron_secret: str = Header(default="")):
    payload = {"status": "ok", "time": datetime.now().isoformat()}
    if detail:
        err = _cron_auth_error(x_cron_secret)
        if err:
            return err
        payload["users"] = users_status()
    return payload


@app.get("/api/sentiment/today")
def sentiment_today(force: int = 0):
    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    if not ref_d:
        return {"code": 1, "message": "无法获取交易日"}

    if force:
        build_and_store(_build_home_for_cache)

    ensure_memory_loaded()
    snap = get_snapshot()
    if not snap and not force:
        trigger_async_build(_build_home_for_cache)
        return {"code": 2, "message": "缓存预热中，请稍后重试", "retryAfterSec": 5}

    if snap:
        ctx = snap.get("context") or {}
        if (
            ctx.get("ref_d") != ref_d
            or ctx.get("advice_d") != advice_d
            or ctx.get("is_ready") != is_ready
            or ctx.get("calendar_d") != date_str(datetime.now())
        ) and is_stale(60):
            threading.Thread(
                target=lambda: build_and_store(_build_home_for_cache),
                daemon=True,
            ).start()
        data = _apply_live_fields(snap["payload"], ref_d, advice_d, is_ready, prev_d)
        return {
            "code": 0,
            "data": data,
            "cache": {
                "fromCache": True,
                "ageSec": round(snap["age_sec"], 1),
                "building": snap.get("building"),
            },
        }

    trigger_async_build(_build_home_for_cache)
    return {"code": 2, "message": "缓存预热中，请稍后重试", "retryAfterSec": 5}


@app.get("/api/cache/home-status")
def home_cache_status():
    from history_sync import sync_job_status

    data = cache_status()
    data["historySync"] = sync_job_status()
    return {"code": 0, "data": data}


@app.post("/api/cache/warm-home")
def warm_home_cache(x_cron_secret: str = Header(default="")):
    """定时触发或手动预热首页缓存（建议 6:00 / 8:50 各调一次）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    ok = build_and_store(_build_home_for_cache)
    return {"code": 0 if ok else 1, "data": cache_status()}


@app.post("/api/cache/snapshot-daily")
def snapshot_daily_cache(
    phase: str = "1800",
    x_cron_secret: str = Header(default=""),
):
    """
    分板块定时快照（内置 cron 或控制台触发）：
    - 1505 / 1800：昨日情绪（收盘）
    - 0900：外围情绪入库
    - 0926 / 0935：今日竞价初更 / 固化
    """
    if err := _cron_auth_error(x_cron_secret):
        return err

    phase = (phase or "").strip()
    handlers = {
        "1505": lambda: persist_trading_day_snapshot(freeze=False),
        "1800": lambda: persist_trading_day_snapshot(freeze=True),
        "0900": persist_peripheral_db_0900,
        "0926": lambda: persist_auction_snapshot(freeze=False),
        "0935": lambda: persist_auction_snapshot(freeze=True),
    }
    fn = handlers.get(phase)
    if not fn:
        return {"code": 1, "message": f"unknown phase: {phase}"}

    result = fn()
    if result.get("ok"):
        if phase == "0900":
            _refresh_peripheral_live()
        elif phase in ("1505", "1800", "0926", "0935"):
            build_and_store(_build_home_for_cache)
    return {"code": 0 if result.get("ok") else 1, "data": result}


@app.get("/api/sentiment/advice")
def sentiment_advice():
    ref_d, prev_d, advice_d, _ = resolve_advice_dates()
    metrics = build_day_metrics(ref_d, prev_d)
    sentiment = calc_sentiment(metrics)
    percent = sentiment["positionPercent"]
    rule = "盘面接力结构偏弱，情绪数据供复盘参考"
    if sentiment["score"] >= 55:
        rule = "情绪偏强，盘面活跃度较高，数据仅供复盘"
    elif sentiment["emptyWarning"]:
        rule = "个人龙空信号触发，作者本人计划休息（非操作建议）"

    return {
        "code": 0,
        "data": {
            "adviceDate": _fmt_date(advice_d),
            "refDate": metrics["date"],
            "generatedAt": "09:15",
            "percent": percent,
            "label": sentiment["positionLabel"],
            "rule": rule,
            "score": sentiment["score"],
            "reminders": [
                "竞价偏弱，盘面分歧加大",
                "连板高度下降，注意情绪退潮",
                "炸板率升高，短线分歧加剧",
                "晋级率偏低，情绪结构偏弱",
            ],
            "strategies": [
                {"range": "0-20", "name": "冰点", "color": "#1890FF", "action": "情绪冰点区间 · 盘面偏冷"},
                {"range": "21-40", "name": "谨慎", "color": "#FA8C16", "action": "情绪谨慎区间 · 结构一般"},
                {"range": "41-60", "name": "活跃", "color": "#FF4D4F", "action": "情绪活跃区间 · 结构尚可"},
                {"range": "61-100", "name": "亢奋", "color": "#CF1322", "action": "情绪亢奋区间 · 注意分歧"},
            ],
        },
    }


@app.get("/api/sentiment/history")
def sentiment_history(days: int = 30, tab: str = "day"):
    days = max(1, min(days, 90))
    cached = fetch_history_list(days)
    if cached:
        return {
            "code": 0,
            "data": {
                "list": cached[:days],
                "tab": tab,
                "fromCache": True,
                "partial": len(cached) < days,
            },
        }

    threading.Thread(
        target=lambda: trigger_sync_history_days(min(days, 60)),
        daemon=True,
        name="history-sync-async",
    ).start()
    return {
        "code": 0,
        "data": {
            "list": [],
            "tab": tab,
            "fromCache": False,
            "warming": True,
            "message": "历史数据同步中，请稍后下拉刷新",
        },
    }


@app.get("/api/sentiment/day")
def sentiment_day(date: str = ""):
    """查询某日归档：metrics + 9/3/6/18 指标块"""
    ref_d, _, advice_d, _ = resolve_advice_dates()
    trade_d = (date or advice_d or ref_d).replace("-", "")[:8]
    detail = fetch_daily_detail(trade_d)
    if not detail:
        return {"code": 1, "message": "未找到该交易日归档", "data": {"tradeDate": trade_d}}
    return {"code": 0, "data": detail}


@app.post("/api/cache/sync-history")
def sync_history_cache(
    days: int = 60,
    x_cron_secret: str = Header(default=""),
):
    """回填历史情绪与指标到 MySQL（后台执行，接口秒回）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    info = trigger_sync_history_days(days)
    return {"code": 0, "data": info}


@app.post("/api/cache/stop-sync-history")
def stop_sync_history_cache(x_cron_secret: str = Header(default="")):
    """停止当前后台历史同步"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    info = request_stop_sync()
    return {"code": 0, "data": info}


@app.get("/api/wxacode/share")
async def share_wxacode():
    """分享海报用小程序码 PNG"""
    from wxacode import get_share_wxacode_bytes

    try:
        data = await get_share_wxacode_bytes()
        return Response(content=data, media_type="image/png")
    except Exception:
        log.exception("wxacode share failed")
        return Response(content=b"", status_code=503, media_type="image/png")


@app.get("/api/wxacode/share-b64")
async def share_wxacode_b64():
    """分享海报用小程序码（Base64，便于云调用拉取）"""
    import base64

    from wxacode import get_share_wxacode_bytes

    try:
        data = await get_share_wxacode_bytes()
        return {"code": 0, "data": {"base64": base64.b64encode(data).decode("ascii")}}
    except Exception as exc:
        log.exception("wxacode share-b64 failed")
        return {"code": 1, "message": str(exc)}


@app.post("/api/ocr/position")
async def ocr_position(file: UploadFile = File(...)):
    if file.content_type and not file.content_type.startswith("image/"):
        return {"code": 1, "message": "仅支持图片文件", "data": {"success": False}}
    content = await file.read()
    if len(content) > MAX_OCR_BYTES:
        return {"code": 1, "message": "图片过大（最大 5MB）", "data": {"success": False}}
    if not content:
        return {"code": 1, "message": "空文件", "data": {"success": False}}
    try:
        result = ocr_image(content)
    except Exception as e:
        result = {"success": False, "message": str(e), "total": None, "stock": None, "cash": None, "rawText": ""}
    return {"code": 0 if result.get("success") else 1, "data": result}


@app.get("/api/config/subscribe")
def subscribe_config(preview: int = 0):
    data = {
        "templates": SUBSCRIBE_TEMPLATES,
        "fieldKeys": SUBSCRIBE_FIELD_KEYS,
    }
    if preview:
        ref_d, prev_d, advice_d, _ = resolve_advice_dates()
        metrics = build_day_metrics(ref_d, prev_d)
        sentiment = calc_sentiment(metrics)
        msg = build_subscribe_message(
            sentiment,
            ref_date=metrics["date"],
            advice_date=_fmt_date(advice_d),
        )
        data["preview"] = msg
        data["sentiment"] = {
            "score": sentiment["score"],
            "level": sentiment["level"],
            "positionPercent": sentiment["positionPercent"],
            "emptyWarning": sentiment["emptyWarning"],
        }
    return {"code": 0, "data": data}


class SubscribeRegisterBody(BaseModel):
    code: str
    type: str = "sentiment_daily"


class UserLoginBody(BaseModel):
    code: str
    nickName: str = ""
    avatarUrl: str = ""
    uiTheme: str = ""
    pushSentiment: bool = False


@app.post("/api/user/login")
async def user_login(body: UserLoginBody):
    """微信登录：code 换 openid 并写入用户表"""
    try:
        session = await code_to_session(body.code)
        openid = session.get("openid") or ""
        if not openid:
            return {"code": 1, "message": "无法获取 openid"}
        user = upsert_user_login(
            openid,
            unionid=session.get("unionid"),
            nick_name=body.nickName,
            avatar_url=body.avatarUrl,
            ui_theme=body.uiTheme or None,
            push_sentiment=body.pushSentiment,
        )
        if not user:
            return {"code": 1, "message": "用户同步失败，请稍后重试"}
        return {"code": 0, "data": user}
    except Exception as e:
        log.exception("user login failed")
        return {"code": 1, "message": str(e)}


@app.post("/api/subscribe/register")
async def subscribe_register(body: SubscribeRegisterBody):
    """用户授权订阅后，用 wx.login 的 code 登记 openid"""
    try:
        openid = await code_to_openid(body.code)
        register_subscriber(openid, body.type)
        return {"code": 0, "data": {"registered": True, "type": body.type}}
    except Exception as e:
        return {"code": 1, "message": str(e)}


@app.get("/api/subscribe/preview")
def subscribe_preview(kind: str = "sentiment_daily"):
    """预览今日将推送的订阅消息（按昨日情绪动态生成，非写死）"""
    ref_d, prev_d, advice_d, _ = resolve_advice_dates()
    metrics = build_day_metrics(ref_d, prev_d)
    sentiment = calc_sentiment(metrics)
    msg = build_subscribe_message(
        sentiment,
        ref_date=metrics["date"],
        advice_date=_fmt_date(advice_d),
        push_kind=kind,
    )
    return {
        "code": 0,
        "data": {
            "refDate": metrics["date"],
            "adviceDate": _fmt_date(advice_d),
            "sentiment": {
                "score": sentiment["score"],
                "level": sentiment["level"],
                "positionPercent": sentiment["positionPercent"],
                "positionLabel": sentiment["positionLabel"],
                "emptyWarning": sentiment["emptyWarning"],
            },
            "message": msg,
        },
    }


class SubscribeSendBody(BaseModel):
    code: str
    kind: str = "sentiment_daily"


@app.post("/api/subscribe/send-test")
async def subscribe_send_test(
    body: SubscribeSendBody,
    x_cron_secret: str = Header(default=""),
):
    """开发测试：向当前用户发送一条动态订阅消息（需 CRON_SECRET）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    ref_d, prev_d, advice_d, _ = resolve_advice_dates()
    metrics = build_day_metrics(ref_d, prev_d)
    sentiment = calc_sentiment(metrics)
    msg = build_subscribe_message(
        sentiment,
        ref_date=metrics["date"],
        advice_date=_fmt_date(advice_d),
        push_kind=body.kind,
    )
    try:
        openid = await code_to_openid(body.code)
        res = await send_subscribe_message(openid, msg["wxData"])
        if res.get("errcode") == 0:
            return {"code": 0, "data": {"sent": True, "message": msg}}
        return {"code": 1, "message": res.get("errmsg", "发送失败"), "data": {"message": msg, "wx": res}}
    except Exception as e:
        return {"code": 1, "message": str(e), "data": {"message": msg}}


@app.post("/api/subscribe/cron-daily")
async def subscribe_cron_daily(x_cron_secret: str = Header(default="")):
    """每日 09:15 定时触发：向已订阅用户推送（内容随情绪变化）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    data = await _run_daily_subscribe_push()
    return {"code": 0, "data": data}


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)
