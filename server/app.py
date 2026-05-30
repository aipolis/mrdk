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

from config import APP_ENV, CRON_SECRET, SUBSCRIBE_FIELD_KEYS, SUBSCRIBE_TEMPLATES, SYNC_HISTORY_DAYS, bj_now
from intraday import (
    build_intraday_payload,
    calc_display_score,
    get_intraday_payload_cached,
    intraday_session_phase,
    order_indicator_sections,
)
from fetcher import (
    build_auction_sentiment,
    build_day_metrics,
    build_home_trend,
    calc_regime,
    calc_sector_concentration,
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
    load_peripheral_snapshot,
    load_peripheral_best_available,
    fetch_sse_index_change,
    get_longkong_risk_payload_cached,
    get_recent_trade_dates,
    invalidate_intraday_caches,
    invalidate_peripheral_cache,
    load_advice_metrics,
    load_auction_snapshot,
    load_ref_day_snapshot,
    patch_grid9_live_breadth,
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
from home_archive import assemble_home_from_archive
from update_schedule import (
    HomeRefreshMode,
    resolve_home_refresh_mode,
    should_live_fetch_section,
    should_live_intraday,
    should_use_archive_only,
)
from history_store import fetch_daily_detail, fetch_history_list, fetch_intraday_series, build_history_item, dedupe_daily_market_records, save_intraday_snapshot
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
    longkong_state,
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


def _date_key(d: str) -> str:
    return str(d or "").replace("-", "")[:8]


def _attach_longkong_state(
    p: dict,
    *,
    intraday_sub_scores: Optional[dict] = None,
) -> dict:
    """补齐龙空龙状态灯字段（龙/修复/空/退潮）。"""
    display_score = int(p.get("displayScore") or p.get("score") or 0)
    if intraday_sub_scores is None:
        intraday_sub_scores = p.get("intradaySubScores") or {}
    p["longkongState"] = longkong_state(
        display_score,
        empty_warning=bool(p.get("emptyWarning")),
        risk_level=p.get("riskLevel") or "none",
        sub_scores=p.get("subScores") or {},
        intraday_sub_scores=intraday_sub_scores,
    )
    return p


def _home_context_matches(ctx: dict, ref_d: str, advice_d: str, is_ready: bool) -> bool:
    return (
        _date_key(ctx.get("ref_d")) == _date_key(ref_d)
        and _date_key(ctx.get("advice_d")) == _date_key(advice_d)
        and ctx.get("is_ready") == is_ready
        and _date_key(ctx.get("calendar_d")) == date_str(bj_now())
    )


def resolve_advice_dates() -> tuple[str, Optional[str], str, bool]:
    """返回参考数据日、对比日、建议适用日、是否已过当日09:15"""
    dates = get_recent_trade_dates(15)
    now = bj_now()
    today = date_str(now)

    if not dates:
        return today, None, today, False

    if today in dates:
        advice_d = today
        idx = dates.index(today)
        # 收盘后(15:00+)用今日作为参考日，否则用前一个交易日
        if now.hour >= 15:
            ref_d = today
        else:
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


def _build_fallback_home_payload(ref_d: str, prev_d: Optional[str], advice_d: str, is_ready: bool = True) -> dict:
    """缓存预热期间提供一份稳定的基础展示数据，避免首页一直空白。"""
    now = bj_now()
    fallback_grid9 = [
        {"key": "height", "label": "连板高度", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "limitUp", "label": "涨停家数", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "seal", "label": "封板率", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "promote", "label": "晋级率", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "limitDown", "label": "跌停家数", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "break", "label": "炸板率", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "oneWord", "label": "一字板", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "volume", "label": "市场量能", "value": "--", "prev": "--", "trend": "flat"},
        {"key": "advance", "label": "上涨家数", "value": "--", "prev": "--", "trend": "flat"},
    ]
    fallback_peripheral = [
        {"key": "ftseA50", "label": "富时A50指数", "price": "--", "value": "--", "chgText": "--", "up": False, "trend": "flat"},
        {"key": "sp500", "label": "标普500", "price": "--", "value": "--", "chgText": "--", "up": False, "trend": "flat"},
        {"key": "cnh", "label": "离岸人民币", "price": "--", "value": "--", "chgText": "--", "up": False, "trend": "flat"},
    ]
    fallback_auction = [
        {"key": "auctionOneWord", "label": "竞价一字板", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "auctionVolume", "label": "竞价量能", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "yesterdayFirst", "label": "昨日首板竞价涨幅", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "yesterdayMulti", "label": "昨日连板竞价涨幅", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "recentMulti", "label": "最近多板竞价涨幅", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "top10AuctionChg", "label": "昨日成交额前10平均竞价涨幅", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
    ]
    fallback_intraday = [
        {"key": "sseIndex", "label": "上证涨跌", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "upRatio", "label": "上涨占比", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "limitUpLive", "label": "实时涨停", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "limitDownLive", "label": "实时跌停", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "marketVolumeLive", "label": "全市量能", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "high10Live", "label": "10日新高", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "top10AvgChgLive", "label": "T-1成交额前10平均涨幅", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "promoteLive", "label": "昨日涨停股今日晋级率", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "breakLive", "label": "实时炸板率", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
    ]
    fallback_longkong_risk = [
        {"key": "highBreakFeedback", "label": "高标断板负反馈", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "limitUpPremium", "label": "昨日涨停溢价", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "multiFailRate", "label": "连板晋级失败率", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "resealRate", "label": "炸板后回封率", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "limitDownRisk", "label": "跌停家数", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
        {"key": "bigLossCount", "label": "大面家数", "value": "--", "prev": "--", "yesterday": "--", "trend": "flat"},
    ]
    fallback_sections = [
        {"id": "yesterday", "title": "昨日情绪概览", "meta": "基础参考", "layout": "grid3", "cols": 3, "items": fallback_grid9},
        {"id": "peripheral", "title": "今天外围情绪及指数", "meta": "基础参考", "layout": "row3", "cols": 3, "items": fallback_peripheral},
        {"id": "auction", "title": "今天竞价情绪", "meta": "基础参考", "layout": "grid3", "cols": 3, "items": fallback_auction},
        {"id": "longkongRisk", "title": "龙空龙专属风控", "meta": "基础参考", "layout": "grid3", "cols": 3, "items": fallback_longkong_risk},
        {"id": "intraday", "title": "盘中实时情绪", "meta": "基础参考", "layout": "grid3", "cols": 3, "items": fallback_intraday},
    ]
    return {
        "adviceDate": _fmt_date(advice_d),
        "refDate": _fmt_date(ref_d),
        "date": _fmt_date(advice_d),
        "generatedAt": "基础参考",
        "generatedAtLabel": "基础参考",
        "generatedAtTime": now.strftime("%H:%M"),
        "dailyQuote": "缓存预热中，先显示基础参考值",
        "overview": [],
        "foreignCards": [],
        "grid9": fallback_grid9,
        "peripheral": fallback_peripheral,
        "auction": fallback_auction,
        "intraday": fallback_intraday,
        "longkongRisk": fallback_longkong_risk,
        "indicatorSections": fallback_sections,
        "subscribePreview": {"strategy": "数据预热中", "keyData": [], "time": now.strftime("%H:%M"), "tips": ["缓存预热中，先显示基础参考值"]},
        "score": 58,
        "baselineScore": 58,
        "liveScore": None,
        "displayScore": 58,
        "scoreMode": "baseline",
        "useLiveScore": False,
        "levelLabel": "中性",
        "displayLevel": "中性",
        "levelClass": "neutral",
        "levelColor": "#8b95a9",
        "longkongSignal": False,
        "longkongState": longkong_state(58, empty_warning=False),
        "positionPercent": 0,
        "positionLabel": "中性",
        "positionDesc": "缓存预热中，当前先展示基础参考值。",
        "emptyWarning": False,
        "emptyReasons": [],
        "strategyNote": "缓存尚未完成，首页将先回退到基础参考值。",
        "subScores": {},
        "intradaySubScores": {},
        "baselineEmptyWarning": False,
        "baselineEmptyReasons": [],
        "baselinePositionPercent": 0,
        "baselinePositionLabel": "中性",
        "indicators": [],
        "trend": [],
        "metrics": {"date": ref_d},
        "prevMetrics": {},
        "isReportReady": is_ready,
        "cacheWarmup": True,
    }


def _build_home_payload(ref_d: str, prev_d: Optional[str], advice_d: str, is_ready: bool = True) -> dict:
    mode = resolve_home_refresh_mode()
    if should_use_archive_only(mode):
        archived = assemble_home_from_archive(ref_d, prev_d, advice_d, is_ready=is_ready)
        if archived:
            archived["foreignCards"] = fetch_foreign_sentiment()
            if not archived.get("sectorConcentration"):
                archived["sectorConcentration"] = calc_sector_concentration(ref_d)
            if not archived.get("regime"):
                r = calc_regime(ref_d)
                archived.setdefault("regimeScore", r.get("regimeScore"))
                archived.setdefault("regimeLabel", r.get("regimeLabel"))
                archived.setdefault("regime", r.get("regime", "neutral"))
            return archived

    metrics, prev_metrics, grid9 = load_ref_day_snapshot(ref_d, prev_d)
    grid9 = patch_grid9_live_breadth(grid9, metrics, ref_d=ref_d, advice_d=advice_d)
    advice_metrics = load_advice_metrics(advice_d)
    # 板块集中度：注入 metrics 供 calc_sentiment 评分
    # total 在非交易时段可能为 0，用 hotConceptCount 兜底
    sector_conc = calc_sector_concentration(ref_d)
    if sector_conc.get("total", 0) > 0 or sector_conc.get("hotConceptCount", 0) > 0:
        metrics = {**metrics, "sector_concentration": sector_conc}
    # 外围：始终显示最近有效数据（不因 archive-only 模式返回空）
    peripheral = load_peripheral_best_available(advice_d, ref_d)
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
    regime = calc_regime(ref_d)

    intraday_payload = {"items": [], "intradayScore": None, "active": False}
    if should_live_intraday(mode):
        intraday_payload = build_intraday_payload(
            metrics, ref_d=ref_d, auction=auction, prev_metrics=prev_metrics
        )
    elif not should_use_archive_only(mode):
        stored = assemble_home_from_archive(ref_d, prev_d, advice_d, is_ready=is_ready)
        if stored and stored.get("intraday"):
            intraday_payload = {
                "items": stored.get("intraday") or [],
                "intradayScore": stored.get("liveScore"),
                "active": False,
            }
    baseline_score = int(sentiment["score"])
    intraday_score = intraday_payload.get("intradayScore")
    prev_baseline = int(calc_sentiment(prev_metrics)["score"]) if prev_metrics else None
    display_score, score_mode = calc_display_score(
        baseline_score, intraday_score, prev_baseline=prev_baseline
    )
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
        ref_d,
        prev_d,
        metrics,
        prev_metrics,
        advice_d=advice_d,
        is_ready=is_ready,
        live_longkong=should_live_fetch_section("longkongRisk", mode),
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
    longkong_risk = []
    for sec in indicator_sections:
        if sec.get("id") == "longkongRisk":
            longkong_risk = sec.get("items") or []
            break

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
        "longkongRisk": longkong_risk,
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
        "useLiveScore": True,
        "levelLabel": ui_level,
        "displayLevel": ui_level,
        "levelClass": ui_level_class,
        "levelColor": sentiment["levelColor"],
        "longkongSignal": longkong["longkongSignal"],
        "longkongState": longkong_state(
            display_score,
            empty_warning=longkong["emptyWarning"],
            risk_level=longkong.get("riskLevel", "none"),
            sub_scores=sentiment.get("subScores") or {},
            intraday_sub_scores=intraday_payload.get("intradaySubScores") or {},
        ),
        "positionPercent": longkong["positionPercent"],
        "positionLabel": longkong["positionLabel"],
        "positionDesc": position_desc(display_score, longkong["emptyWarning"], longkong.get("riskLevel", "none")),
        "emptyWarning": longkong["emptyWarning"],
        "emptyReasons": longkong["emptyReasons"],
        "strategyNote": strategy_note,
        "subScores": sentiment.get("subScores") or {},
        "intradaySubScores": intraday_payload.get("intradaySubScores") or {},
        "baselineEmptyWarning": sentiment["emptyWarning"],
        "baselineRiskLevel": sentiment.get("riskLevel", "none"),
        "baselineEmptyReasons": sentiment["emptyReasons"],
        "baselinePositionPercent": sentiment["positionPercent"],
        "baselinePositionLabel": sentiment["positionLabel"],
        "indicators": [
            {**ind, "yesterday": ind["yesterday"].replace("前日 ", "") if str(ind["yesterday"]).startswith("前日") else ind["yesterday"]}
            for ind in indicators
        ],
        "trend": trend,
        "regimeScore": regime.get("regimeScore"),
        "regimeLabel": regime.get("regimeLabel"),
        "regime": regime.get("regime", "neutral"),
        "sectorConcentration": sector_conc,
        "metrics": metrics,
        "prevMetrics": prev_metrics,
    }


def _build_home_for_cache() -> tuple[dict, dict]:
    ref_d, prev_d, advice_d, is_ready = resolve_advice_dates()
    data = _build_home_payload(ref_d, prev_d, advice_d, is_ready)
    data["isReportReady"] = is_ready
    data["quality"] = _payload_quality(data)
    context = {
        "ref_d": ref_d,
        "prev_d": prev_d,
        "advice_d": advice_d,
        "is_ready": is_ready,
        "calendar_d": date_str(bj_now()),
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
    now = bj_now()
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
        metas, gauge_label, gauge_hm = build_section_metas(
            ref_d,
            advice_d,
            is_ready,
            ref_metrics=metrics,
            advice_metrics=advice_metrics,
        )
        return _sync_intraday_display_fields(
            p,
            ref_d,
            advice_d,
            is_ready,
            prev_d=prev_d,
            metas=metas,
            gauge_label=gauge_label,
            gauge_hm=gauge_hm,
            advice_metrics=advice_metrics,
            persist_snapshot=True,
            force_intraday=True,
        )

    if not patch_home_cache(patch):
        build_and_store(_build_home_for_cache)


def _patch_longkong_risk_live(
    p: dict,
    ref_d: str,
    prev_d: Optional[str],
    advice_d: str,
    metas: dict,
    *,
    force: bool = False,
) -> dict:
    """盘中刷新龙空龙专属风控 6 项（与盘中情绪同频节流）。"""
    mode = resolve_home_refresh_mode()
    if not force and not should_live_fetch_section("longkongRisk", mode):
        return p
    metrics = p.get("metrics") or {}
    prev_metrics = p.get("prevMetrics") or {}
    items = get_longkong_risk_payload_cached(
        ref_d,
        prev_d,
        metrics,
        prev_metrics,
        advice_d=advice_d,
        force=force,
    )
    p["longkongRisk"] = items
    lk_sec = {
        "id": "longkongRisk",
        "title": "龙空龙专属风控",
        "meta": metas.get("intraday") or p.get("generatedAtLabel") or "",
        "layout": "grid3",
        "cols": 3,
        "items": items,
    }
    sections = list(p.get("indicatorSections") or [])
    replaced = False
    for i, sec in enumerate(sections):
        if sec.get("id") == "longkongRisk":
            sections[i] = {**sec, **lk_sec}
            replaced = True
            break
    if not replaced:
        sections.append(lk_sec)
    p["indicatorSections"] = order_indicator_sections(sections)
    return p


def _sync_intraday_display_fields(
    p: dict,
    ref_d: str,
    advice_d: str,
    is_ready: bool,
    *,
    prev_d: Optional[str] = None,
    metas: dict,
    gauge_label: str,
    gauge_hm: str,
    advice_metrics: Optional[dict] = None,
    persist_snapshot: bool = False,
    force_intraday: bool = False,
) -> dict:
    """重算展示分，并将 generatedAt 对齐为展示分最后一次形成时间。"""
    metrics = p.get("metrics") or {}
    if advice_metrics is None:
        advice_metrics = load_advice_metrics(advice_d)
    intraday_payload = get_intraday_payload_cached(
        metrics,
        ref_d=ref_d,
        auction=p.get("auction"),
        prev_metrics=p.get("prevMetrics") or {},
        force=force_intraday,
    )
    live_raw = intraday_payload.get("intradayScore")
    if intraday_payload.get("items"):
        p["intraday"] = intraday_payload["items"]
        sections = list(p.get("indicatorSections") or [])
        intraday_sec = {
            "id": "intraday",
            "title": "盘中实时情绪",
            "meta": metas.get("intraday") or gauge_label,
            "layout": "grid3",
            "cols": 3,
            "items": intraday_payload["items"],
            "pending": not intraday_payload.get("active"),
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
    if live_raw is None:
        p["generatedAt"] = gauge_label
        p["generatedAtLabel"] = gauge_label
        p["generatedAtTime"] = gauge_hm
        p["quality"] = _payload_quality(p)
        p = _attach_longkong_state(
            p,
            intraday_sub_scores=intraday_payload.get("intradaySubScores") or {},
        )
        return _patch_longkong_risk_live(
            p, ref_d, prev_d, advice_d, metas, force=force_intraday
        )

    baseline = int(p.get("baselineScore") or p.get("score") or 0)
    prev_baseline_2 = int(calc_sentiment(p.get("prevMetrics") or {})["score"]) if p.get("prevMetrics") else None
    display_score, score_mode = calc_display_score(baseline, live_raw, prev_baseline=prev_baseline_2)
    baseline_sentiment = {
        "emptyWarning": bool(p.get("baselineEmptyWarning")),
        "riskLevel": p.get("baselineRiskLevel") or "none",
        "emptyReasons": list(p.get("baselineEmptyReasons") or []),
        "positionPercent": p.get("baselinePositionPercent"),
        "positionLabel": p.get("baselinePositionLabel") or "",
    }
    longkong = apply_display_longkong(
        baseline_sentiment, display_score, score_mode=score_mode
    )
    updated = intraday_payload.get("updatedAt") or gauge_hm
    p["liveScore"] = live_raw
    p["displayScore"] = display_score
    p["scoreMode"] = score_mode
    p["useLiveScore"] = True
    if score_mode == "live" and intraday_payload.get("updatedAt"):
        p["generatedAt"] = f"盘中 {updated} 更新"
    elif score_mode == "live":
        p["generatedAt"] = f"竞价 {updated} 更新"
    else:
        p["generatedAt"] = gauge_label
    p["generatedAtLabel"] = p["generatedAt"]
    p["generatedAtTime"] = updated if score_mode == "live" else gauge_hm
    p["levelLabel"] = display_level_label(display_score)
    p["displayLevel"] = p["levelLabel"]
    p["levelClass"] = display_level_class(display_score)
    p["longkongSignal"] = longkong["longkongSignal"]
    p["emptyWarning"] = longkong["emptyWarning"]
    p["riskLevel"] = longkong.get("riskLevel", "none")
    p["emptyReasons"] = longkong["emptyReasons"]
    p["positionPercent"] = longkong["positionPercent"]
    p["positionLabel"] = longkong["positionLabel"]
    p["positionDesc"] = position_desc(display_score, longkong["emptyWarning"], longkong.get("riskLevel", "none"))
    p = _attach_longkong_state(
        p,
        intraday_sub_scores=intraday_payload.get("intradaySubScores") or {},
    )
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

    intraday_sec = {
        "id": "intraday",
        "title": "盘中实时情绪",
        "meta": metas.get("intraday") or p["generatedAt"],
        "layout": "grid3",
        "cols": 3,
        "items": intraday_payload["items"],
        "pending": not intraday_payload.get("active"),
    }
    sections = list(p.get("indicatorSections") or [])
    replaced = False
    for i, sec in enumerate(sections):
        if sec.get("id") == "intraday":
            sections[i] = intraday_sec
            replaced = True
            break
    if not replaced:
        sections.append(intraday_sec)
    p["indicatorSections"] = order_indicator_sections(sections)
    p["quality"] = _payload_quality(p)
    if persist_snapshot:
        save_intraday_snapshot(
            advice_d,
            updated,
            ref_d=ref_d,
            advice_d=advice_d,
            baseline_score=baseline,
            intraday_score=live_raw,
            display_score=display_score,
            score_mode=score_mode,
            longkong_signal=longkong["longkongSignal"],
            empty_warning=longkong["emptyWarning"],
            items=intraday_payload.get("items") or [],
            snap=intraday_payload.get("snap") or {},
            sub_scores=intraday_payload.get("intradaySubScores") or {},
            source_status=p.get("quality") or {},
        )
    return _patch_longkong_risk_live(
        p, ref_d, prev_d, advice_d, metas, force=force_intraday
    )


def _auction_items_from_data(data: dict) -> list:
    items = data.get("auction") or []
    if items:
        return items
    for sec in data.get("indicatorSections") or []:
        if sec.get("id") == "auction":
            return sec.get("items") or []
    return []


def _auction_section_empty(data: dict) -> bool:
    from fetcher import auction_items_incomplete

    items = _auction_items_from_data(data)
    if not items:
        return True
    return auction_items_incomplete(items)


def _intraday_section_empty(data: dict) -> bool:
    if data.get("intraday"):
        return False
    for sec in data.get("indicatorSections") or []:
        if sec.get("id") == "intraday" and sec.get("items"):
            return False
    return True


def _missing_item_keys(items: list, required: Optional[list[str]] = None) -> list[str]:
    by_key = {it.get("key"): it for it in (items or []) if it and it.get("key")}
    keys = required or list(by_key.keys())
    missing = []
    for key in keys:
        val = str((by_key.get(key) or {}).get("value") or (by_key.get(key) or {}).get("displayValue") or "").strip()
        if not val or val in ("--", "-", "None", "null"):
            missing.append(key)
    return missing


def _payload_quality(data: dict) -> dict:
    sections = {s.get("id"): s for s in (data.get("indicatorSections") or []) if s}
    auction_required = [
        "auctionOneWord",
        "auctionVolume",
        "yesterdayFirst",
        "yesterdayMulti",
        "recentMulti",
        "top10AuctionChg",
    ]
    intraday_required = [
        "sseIndex",
        "upRatio",
        "limitUpLive",
        "limitDownLive",
        "marketVolumeLive",
        "high10Live",
        "top10AvgChgLive",
        "promoteLive",
        "breakLive",
    ]
    grid_missing = _missing_item_keys(data.get("grid9") or (sections.get("yesterday") or {}).get("items") or [])
    auction_missing = _missing_item_keys(data.get("auction") or (sections.get("auction") or {}).get("items") or [], auction_required)
    intraday_missing = _missing_item_keys(data.get("intraday") or (sections.get("intraday") or {}).get("items") or [], intraday_required)
    peripheral_items = data.get("peripheral") or data.get("overview") or (sections.get("peripheral") or {}).get("items") or []
    peripheral_missing = _missing_item_keys(peripheral_items)
    missing = {
        "yesterday": grid_missing,
        "peripheral": peripheral_missing,
        "auction": auction_missing,
        "intraday": intraday_missing,
    }
    return {
        "complete": not any(missing.values()),
        "missing": missing,
        "counts": {
            "yesterday": len(data.get("grid9") or (sections.get("yesterday") or {}).get("items") or []),
            "peripheral": len(peripheral_items),
            "auction": len(data.get("auction") or (sections.get("auction") or {}).get("items") or []),
            "intraday": len(data.get("intraday") or (sections.get("intraday") or {}).get("items") or []),
        },
    }


def _patch_section_metas(sections: list, metas: dict) -> list:
    meta_map = {
        "yesterday": metas.get("yesterday"),
        "peripheral": metas.get("peripheral"),
        "auction": metas.get("auction"),
        "intraday": metas.get("intraday"),
        "longkongRisk": metas.get("intraday"),
    }
    for sec in sections:
        sec_id = sec.get("id")
        if sec_id in meta_map and meta_map[sec_id]:
            sec["meta"] = meta_map[sec_id]
    return order_indicator_sections(sections)


def _cached_home_payload_usable(data: Optional[dict]) -> bool:
    if not data:
        return False
    if data.get("displayScore") is None and data.get("score") is None:
        return False
    sections = data.get("indicatorSections") or []
    return len(sections) >= 2


def _apply_live_light_fields(
    out: dict,
    *,
    advice_d: str,
    is_ready: bool,
    metas: dict,
    gauge_label: str,
    gauge_hm: str,
) -> dict:
    """非盘中：只更新 meta / 日期，不重拉行情（Web 秒开）。"""
    out["adviceDate"] = _fmt_date(advice_d)
    out["date"] = out["adviceDate"]
    out["isReportReady"] = is_ready
    sections = list(out.get("indicatorSections") or [])
    out["indicatorSections"] = _patch_section_metas(sections, metas)
    if not out.get("generatedAtLabel"):
        out["generatedAt"] = gauge_label
        out["generatedAtLabel"] = gauge_label
        out["generatedAtTime"] = gauge_hm
    out = _attach_longkong_state(out)
    out["quality"] = _payload_quality(out)
    return out


def _apply_live_fields(
    data: dict,
    ref_d: str,
    advice_d: str,
    is_ready: bool,
    prev_d: Optional[str] = None,
) -> dict:
    """缓存命中时按更新时段刷新：收盘后只改 meta，盘中仅节流刷新 intraday。"""
    mode = resolve_home_refresh_mode()

    if should_use_archive_only(mode):
        if _cached_home_payload_usable(data):
            today = date_str(bj_now())
            effective_advice_d = (advice_d or ref_d or today)[:8]
            advice_metrics = load_advice_metrics(effective_advice_d)
            metas, gauge_label, gauge_hm = build_section_metas(
                ref_d,
                advice_d,
                is_ready,
                ref_metrics=data.get("metrics") or {},
                advice_metrics=advice_metrics,
            )
            out = copy.deepcopy(data)
            return _apply_live_light_fields(
                out,
                advice_d=effective_advice_d,
                is_ready=is_ready,
                metas=metas,
                gauge_label=gauge_label,
                gauge_hm=gauge_hm,
            )

        archived = assemble_home_from_archive(ref_d, prev_d, advice_d, is_ready=is_ready)
        if archived:
            archived["foreignCards"] = data.get("foreignCards") or fetch_foreign_sentiment()
            today = date_str(bj_now())
            effective_advice_d = (advice_d or ref_d or today)[:8]
            advice_metrics = load_advice_metrics(effective_advice_d)
            metas, gauge_label, gauge_hm = build_section_metas(
                ref_d,
                advice_d,
                is_ready,
                ref_metrics=archived.get("metrics") or {},
                advice_metrics=advice_metrics,
            )
            archived["adviceDate"] = _fmt_date(advice_d)
            archived["date"] = archived["adviceDate"]
            archived["isReportReady"] = is_ready
            archived["indicatorSections"] = _patch_section_metas(
                list(archived.get("indicatorSections") or []),
                metas,
            )
            if not archived.get("generatedAtLabel"):
                archived["generatedAt"] = gauge_label
                archived["generatedAtLabel"] = gauge_label
                archived["generatedAtTime"] = gauge_hm
            archived["quality"] = _payload_quality(archived)
            return archived

    out = copy.deepcopy(data)
    today = date_str(bj_now())
    payload_ref_d = _date_key(out.get("refDate"))
    effective_ref_d = ref_d if payload_ref_d == _date_key(ref_d) else (payload_ref_d or ref_d)
    effective_advice_d = advice_d if payload_ref_d == _date_key(ref_d) else _date_key(out.get("adviceDate") or advice_d)
    ref_metrics = (out.get("metrics") or {}) if payload_ref_d == _date_key(effective_ref_d) else {}
    advice_metrics = load_advice_metrics(effective_advice_d)
    metas, gauge_label, gauge_hm = build_section_metas(
        effective_ref_d, effective_advice_d, is_ready, ref_metrics=ref_metrics, advice_metrics=advice_metrics
    )
    out["adviceDate"] = _fmt_date(effective_advice_d if effective_advice_d else today)
    out["date"] = out["adviceDate"]
    out["isReportReady"] = is_ready
    sections = out.get("indicatorSections") or []

    if _auction_section_empty(out) and should_live_fetch_section("auction", mode):
        fresh_auc = load_auction_snapshot(
            effective_advice_d,
            effective_ref_d,
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

    if not should_live_intraday(mode):
        return _apply_live_light_fields(
            out,
            advice_d=effective_advice_d if effective_advice_d else today,
            is_ready=is_ready,
            metas=metas,
            gauge_label=gauge_label,
            gauge_hm=gauge_hm,
        )

    if _intraday_section_empty(out) and should_live_fetch_section("intraday", mode):
        intraday_payload = build_intraday_payload(
            out.get("metrics") or {},
            ref_d=effective_ref_d,
            auction=out.get("auction") or [],
            prev_metrics=out.get("prevMetrics") or {},
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

    out["indicatorSections"] = _patch_section_metas(list(out.get("indicatorSections") or []), metas)
    out = _sync_intraday_display_fields(
        out,
        effective_ref_d,
        effective_advice_d,
        is_ready,
        prev_d=prev_d,
        metas=metas,
        gauge_label=gauge_label,
        gauge_hm=gauge_hm,
        advice_metrics=advice_metrics,
        persist_snapshot=False,
        force_intraday=False,
    )
    out["quality"] = _payload_quality(out)
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
    payload = {"status": "ok", "time": bj_now().isoformat()}
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
        data = _build_fallback_home_payload(ref_d, prev_d, advice_d, is_ready)
        data["quality"] = _payload_quality(data)
        return {
            "code": 0,
            "data": data,
            "cache": {
                "fromCache": False,
                "updating": True,
                "building": True,
                "retryAfterSec": 5,
                "warmup": True,
            },
        }

    if snap:
        ctx = snap.get("context") or {}
        if not _home_context_matches(ctx, ref_d, advice_d, is_ready):
            rebuilt = build_and_store(_build_home_for_cache)
            ensure_memory_loaded()
            snap = get_snapshot()
            ctx = (snap or {}).get("context") or {}
            if not snap or not _home_context_matches(ctx, ref_d, advice_d, is_ready):
                trigger_async_build(_build_home_for_cache)
                if snap and snap.get("payload"):
                    data = _apply_live_fields(snap["payload"], ref_d, advice_d, is_ready, prev_d)
                    return {
                        "code": 0,
                        "data": data,
                        "cache": {
                            "fromCache": True,
                            "updating": True,
                            "syncBuildAttempted": rebuilt,
                            "ageSec": round(snap["age_sec"], 1),
                            "building": snap.get("building"),
                            "lastError": snap.get("last_error"),
                            "staleContext": {
                                "cached": ctx,
                                "expected": {
                                    "ref_d": ref_d,
                                    "advice_d": advice_d,
                                    "is_ready": is_ready,
                                    "calendar_d": date_str(bj_now()),
                                },
                            },
                        },
                    }
                return {
                    "code": 2,
                    "message": "缓存更新中，请稍后重试",
                    "retryAfterSec": 5,
                    "staleContext": {
                        "cached": ctx,
                        "expected": {
                            "ref_d": ref_d,
                            "advice_d": advice_d,
                            "is_ready": is_ready,
                            "calendar_d": date_str(bj_now()),
                        },
                    },
                }
        elif is_stale(60):
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


def _build_advice_payload_from_home(data: dict, advice_d: str) -> Optional[dict]:
    """仓位建议优先复用首页缓存，避免接口临时重算重数据源。"""
    if not data:
        return None
    score = data.get("baselineScore")
    if score is None:
        score = data.get("score")
    if score is None:
        score = data.get("displayScore")
    if score is None:
        return None

    empty = bool(data.get("baselineEmptyWarning", data.get("emptyWarning")))
    reasons = list(data.get("baselineEmptyReasons") or data.get("emptyReasons") or [])
    percent = data.get("baselinePositionPercent")
    if percent is None:
        percent = data.get("positionPercent", 0)
    label = data.get("baselinePositionLabel")
    if label is None:
        label = data.get("positionLabel", "")

    rule = "盘面接力结构偏弱，情绪数据供复盘参考"
    if int(score) >= 60:
        rule = "情绪偏强，盘面活跃度较高，数据仅供复盘"
    elif empty:
        rule = "个人龙空信号触发，作者本人计划休息（非操作建议）"

    reminders = reasons[:4] or [
        "竞价偏弱，盘面分歧加大",
        "连板高度下降，注意情绪退潮",
        "炸板率升高，短线分歧加剧",
        "晋级率偏低，情绪结构偏弱",
    ]
    metrics = data.get("metrics") or {}
    return {
        "adviceDate": _fmt_date(advice_d),
        "refDate": metrics.get("date") or data.get("refDate") or data.get("date"),
        "generatedAt": "09:15",
        "percent": percent,
        "label": label,
        "rule": rule,
        "score": int(score),
        "reminders": reminders,
        "strategies": [
            {"range": "0-29", "name": "冰点", "color": "#1890FF", "action": "情绪冰点区间 · 盘面偏冷"},
            {"range": "30-39", "name": "偏冷", "color": "#38BDF8", "action": "情绪偏冷区间 · 等待修复"},
            {"range": "40-49", "name": "偏谨慎", "color": "#FA8C16", "action": "情绪谨慎区间 · 结构一般"},
            {"range": "50-59", "name": "中性", "color": "#FAAD14", "action": "情绪中性区间 · 注意分化"},
            {"range": "60-79", "name": "偏乐观", "color": "#FF4D4F", "action": "情绪乐观区间 · 结构尚可"},
            {"range": "80-89", "name": "高潮", "color": "#FF4D4F", "action": "情绪高潮区间 · 注意一致"},
            {"range": "90-100", "name": "狂热", "color": "#CF1322", "action": "情绪狂热区间 · 注意分歧"},
        ],
    }


@app.post("/api/cache/warm-home")
def warm_home_cache(x_cron_secret: str = Header(default="")):
    """定时触发或手动预热首页缓存（建议 6:00 / 8:50 各调一次）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    ok = build_and_store(_build_home_for_cache)
    return {"code": 0 if ok else 1, "data": cache_status()}


@app.post("/api/cache/rebuild-auction")
def rebuild_auction_cache(x_cron_secret: str = Header(default="")):
    """补跑今日竞价 6 项并刷新首页缓存（收盘后数据不全时手动触发）"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    invalidate_intraday_caches()
    snap = persist_auction_snapshot(freeze=True)
    ok = build_and_store(_build_home_for_cache) if snap.get("ok") else False
    return {
        "code": 0 if ok else 1,
        "data": {"auction": snap, "cache": cache_status()},
    }


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
    ensure_memory_loaded()
    snap = get_snapshot()
    if snap and snap.get("payload"):
        cached = _build_advice_payload_from_home(snap["payload"], advice_d)
        if cached:
            return {"code": 0, "data": cached}

    metrics = build_day_metrics(ref_d, prev_d)
    sentiment = calc_sentiment(metrics)
    percent = sentiment["positionPercent"]
    rule = "盘面接力结构偏弱，情绪数据供复盘参考"
    if sentiment["score"] >= 60:
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
                {"range": "0-29", "name": "冰点", "color": "#1890FF", "action": "情绪冰点区间 · 盘面偏冷"},
                {"range": "30-39", "name": "偏冷", "color": "#38BDF8", "action": "情绪偏冷区间 · 等待修复"},
                {"range": "40-49", "name": "偏谨慎", "color": "#FA8C16", "action": "情绪谨慎区间 · 结构一般"},
                {"range": "50-59", "name": "中性", "color": "#FAAD14", "action": "情绪中性区间 · 注意分化"},
                {"range": "60-79", "name": "偏乐观", "color": "#FF4D4F", "action": "情绪乐观区间 · 结构尚可"},
                {"range": "80-89", "name": "高潮", "color": "#FF4D4F", "action": "情绪高潮区间 · 注意一致"},
                {"range": "90-100", "name": "狂热", "color": "#CF1322", "action": "情绪狂热区间 · 注意分歧"},
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


@app.get("/api/sentiment/intraday-series")
def sentiment_intraday_series(date: str = ""):
    """返回某交易日盘中情绪分时序列（每 2 分钟一个快照）"""
    ref_d, _, advice_d, _ = resolve_advice_dates()
    trade_d = (date or advice_d or ref_d).replace("-", "")[:8]
    series = fetch_intraday_series(trade_d)
    return {"code": 0, "data": {"tradeDate": trade_d, "series": series}}


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


@app.post("/api/cache/dedupe-history")
def dedupe_history_cache(x_cron_secret: str = Header(default="")):
    """删除 daily_market 中展示日期重复的行"""
    if err := _cron_auth_error(x_cron_secret):
        return err
    info = dedupe_daily_market_records()
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
