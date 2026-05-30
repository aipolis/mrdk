# -*- coding: utf-8 -*-
"""历史交易日数据回填（写入 MySQL）"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from config import bj_now

from daily_sections import build_daily_sections
from fetcher import (
    _fill_metrics_breadth,
    build_day_metrics,
    build_indicators,
    build_ref_day_metrics,
    build_yesterday_sentiment,
    date_str,
    display_level_class,
    display_level_label,
    em_pool_available,
    fetch_sse_index_change,
    get_recent_trade_dates,
)
from history_store import build_history_item, fetch_daily_detail, history_db_status, list_stored_trade_dates, save_daily_record
from sentiment import calc_sentiment

log = logging.getLogger("mingri.history_sync")

_sync_lock = threading.Lock()
_sync_cancel = threading.Event()
_sync_state: dict = {
    "running": False,
    "stopRequested": False,
    "startedAt": None,
    "requestedDays": 0,
    "lastResult": None,
    "lastError": None,
    "finishedAt": None,
}


def _load_or_build_ref_metrics(trade_d: str, prev_d: Optional[str], *, force: bool = False) -> dict:
    """近 30 日从东财计算；更早仅读 MySQL，避免空池覆盖归档。"""
    trade_d = (trade_d or "")[:8]
    if force or em_pool_available(trade_d):
        metrics = _fill_metrics_breadth(build_ref_day_metrics(trade_d, prev_d), trade_d)
    else:
        detail = fetch_daily_detail(trade_d)
        if detail and detail.get("metrics"):
            metrics = detail["metrics"]
        else:
            metrics = _fill_metrics_breadth(build_ref_day_metrics(trade_d, prev_d), trade_d)
    if metrics.get("index_chg") is None:
        metrics = dict(metrics)
        metrics["index_chg"] = fetch_sse_index_change(trade_d)
    return metrics


def _resolve_today_prev() -> tuple[Optional[str], Optional[str]]:
    today = date_str(bj_now())
    dates = get_recent_trade_dates(5)
    if today not in dates:
        return None, None
    idx = dates.index(today)
    prev_d = dates[idx - 1] if idx > 0 else None
    return today, prev_d


def _patch_indicator_sections(
    sections: Optional[list],
    *,
    grid9: Optional[list] = None,
    peripheral: Optional[list] = None,
    auction: Optional[list] = None,
) -> list:
    out = [dict(s) for s in (sections or [])]
    for sec in out:
        sid = sec.get("id")
        if sid == "yesterday" and grid9 is not None:
            sec["items"] = grid9
        if sid == "peripheral" and peripheral is not None:
            sec["items"] = peripheral
        if sid == "auction" and auction is not None:
            sec["items"] = auction
    return out


def _merge_save_daily(
    trade_d: str,
    prev_d: Optional[str],
    *,
    metrics: dict,
    grid9: Optional[list] = None,
    peripheral: Optional[list] = None,
    auction: Optional[list] = None,
    indicator_sections: Optional[list] = None,
    rebuild_sentiment: bool = True,
) -> bool:
    """合并写入 daily_market，保留未传入的板块。"""
    trade_d = (trade_d or "")[:8]
    existing = fetch_daily_detail(trade_d) or {}
    ex_metrics = existing.get("metrics") or {}
    merged_metrics = {**ex_metrics, **metrics}

    grid9_out = grid9 if grid9 is not None else existing.get("grid9")
    peripheral_out = peripheral if peripheral is not None else existing.get("peripheral")
    auction_out = auction if auction is not None else existing.get("auction")
    sections_out = indicator_sections
    if sections_out is None and existing.get("indicatorSections"):
        sections_out = _patch_indicator_sections(
            existing.get("indicatorSections"),
            grid9=grid9,
            peripheral=peripheral,
            auction=auction,
        )

    if rebuild_sentiment or not existing.get("sentiment"):
        sentiment = calc_sentiment(
            merged_metrics,
            peripheral=peripheral_out,
            auction=auction_out,
            grid9=grid9_out,
        )
        ui_level = display_level_label(sentiment["score"])
        level_class = display_level_class(sentiment["score"])
        history_item = build_history_item(
            merged_metrics, sentiment, ui_level=ui_level, level_class=level_class
        )
        indicators = build_indicators(merged_metrics, None)
    else:
        sentiment = existing.get("sentiment") or calc_sentiment(merged_metrics)
        history_item = existing.get("history") or build_history_item(
            merged_metrics,
            sentiment,
            ui_level=display_level_label(sentiment.get("score") or 0),
            level_class=display_level_class(sentiment.get("score") or 0),
        )
        indicators = existing.get("indicators") or build_indicators(merged_metrics, None)

    if sections_out is None:
        prev_metrics = None
        if prev_d:
            prev_detail = fetch_daily_detail(prev_d)
            if prev_detail:
                prev_metrics = prev_detail.get("metrics")
        sections = build_daily_sections(
            trade_d,
            prev_d,
            merged_metrics,
            prev_metrics,
            advice_d=trade_d,
            is_ready=True,
            include_live_peripheral=True,
        )
        sections_out = sections.get("indicatorSections")
        if grid9 is None:
            grid9_out = sections.get("grid9")
        if peripheral is None:
            peripheral_out = sections.get("peripheral")
        if auction is None:
            auction_out = sections.get("auction")

    return save_daily_record(
        trade_d,
        prev_d,
        merged_metrics,
        sentiment,
        history_item=history_item,
        indicators=indicators,
        grid9=grid9_out,
        peripheral=peripheral_out,
        auction=auction_out,
        indicator_sections=sections_out,
    )


def persist_trading_day_snapshot(*, freeze: bool = False) -> dict:
    """
    交易日收盘快照：15:05 初更 / 18:00 固化并写入 MySQL。
    写入 trade_d=当日（次日首页 ref_d 即读此归档）；保留当日外围/竞价归档。
    """
    today, prev_d = _resolve_today_prev()
    if not today:
        return {"ok": False, "skipped": True, "reason": "not_trading_day"}

    prev_metrics = _load_or_build_ref_metrics(prev_d, None, force=True) if prev_d else None
    metrics = _load_or_build_ref_metrics(today, prev_d, force=True)
    phase = "1800" if freeze else "1505"
    metrics = dict(metrics)
    metrics["snapshot_phase"] = phase
    metrics["snapshot_frozen"] = freeze
    metrics["snapshot_at"] = bj_now().isoformat(timespec="seconds")
    grid9 = build_yesterday_sentiment(metrics, prev_metrics)

    existing = fetch_daily_detail(today) or {}
    sections = _patch_indicator_sections(
        existing.get("indicatorSections"),
        grid9=grid9,
    ) if existing.get("indicatorSections") else None

    ok = _merge_save_daily(
        today,
        prev_d,
        metrics=metrics,
        grid9=grid9,
        indicator_sections=sections,
        rebuild_sentiment=True,
    )
    log.info(
        "trading day snapshot trade_d=%s phase=%s frozen=%s saved=%s",
        today,
        phase,
        freeze,
        ok,
    )
    return {
        "ok": ok,
        "trade_d": today,
        "prev_d": prev_d,
        "phase": phase,
        "frozen": freeze,
    }


def persist_peripheral_db_0900() -> dict:
    """外围情绪：每日 9:00 快照写入 MySQL（展示仍每 10 分钟刷新）。"""
    from fetcher import fetch_peripheral_sentiment, invalidate_peripheral_cache

    today, prev_d = _resolve_today_prev()
    if not today:
        return {"ok": False, "skipped": True, "reason": "not_trading_day"}

    invalidate_peripheral_cache()
    peripheral = fetch_peripheral_sentiment()
    metrics = {
        "date": f"{today[:4]}-{today[4:6]}-{today[6:8]}",
        "peripheral_db_phase": "0900",
        "peripheral_db_at": bj_now().isoformat(timespec="seconds"),
    }
    existing = fetch_daily_detail(today) or {}
    sections = _patch_indicator_sections(
        existing.get("indicatorSections"),
        peripheral=peripheral,
    ) if existing.get("indicatorSections") else None

    ok = _merge_save_daily(
        today,
        prev_d,
        metrics=metrics,
        peripheral=peripheral,
        indicator_sections=sections,
        rebuild_sentiment=False,
    )
    log.info("peripheral db 0900 trade_d=%s saved=%s", today, ok)
    return {"ok": ok, "trade_d": today, "phase": "0900"}


def persist_auction_snapshot(*, freeze: bool = False) -> dict:
    """今日竞价情绪：09:26 初更 / 09:35 固化（类比昨日情绪 15:05/18:00）。"""
    from fetcher import _after_auction_925, build_auction_sentiment, load_ref_day_snapshot

    today, prev_d = _resolve_today_prev()
    if not today:
        return {"ok": False, "skipped": True, "reason": "not_trading_day"}
    if not _after_auction_925():
        return {"ok": False, "skipped": True, "reason": "before_auction_925"}

    existing = fetch_daily_detail(today) or {}
    from fetcher import auction_items_incomplete

    if not freeze and ((existing.get("metrics") or {}).get("auction_frozen")):
        if not auction_items_incomplete(existing.get("auction") or []):
            return {"ok": True, "skipped": True, "reason": "already_frozen", "trade_d": today}

    dates = get_recent_trade_dates(5)
    idx = dates.index(today)
    ref_d = prev_d
    ref_prev = dates[idx - 2] if idx > 1 else None
    ref_metrics, ref_prev_metrics, _ = load_ref_day_snapshot(ref_d, ref_prev) if ref_d else ({}, None, [])
    auction = build_auction_sentiment(
        ref_d or today,
        ref_metrics,
        ref_prev_metrics,
        ref_prev,
        advice_d=today,
    )
    phase = "0935" if freeze else "0926"
    metrics = {
        "date": f"{today[:4]}-{today[4:6]}-{today[6:8]}",
        "auction_phase": phase,
        "auction_frozen": freeze,
        "auction_at": bj_now().isoformat(timespec="seconds"),
    }
    for it in auction or []:
        key = it.get("key")
        val = it.get("value")
        if not key or val in (None, "", "--"):
            continue
        try:
            if key == "yesterdayFirst":
                metrics["first_board_auction_chg"] = float(str(val).replace("%", "").replace("+", ""))
            elif key == "yesterdayMulti":
                metrics["multi_board_auction_chg"] = float(str(val).replace("%", "").replace("+", ""))
            elif key == "recentMulti":
                metrics["max_board_auction_chg"] = float(str(val).replace("%", "").replace("+", ""))
            elif key == "top10AuctionChg":
                metrics["auction_median"] = float(str(val).replace("%", "").replace("+", ""))
            elif key == "auctionVolume" and str(val).endswith("亿"):
                metrics["auction_volume_yi"] = float(str(val).replace("亿", ""))
            elif key == "auctionOneWord":
                metrics["auction_one_word_count"] = int(str(val))
        except (TypeError, ValueError):
            pass
    sections = _patch_indicator_sections(
        existing.get("indicatorSections"),
        auction=auction,
    ) if existing.get("indicatorSections") else None

    ok = _merge_save_daily(
        today,
        prev_d,
        metrics=metrics,
        auction=auction,
        indicator_sections=sections,
        rebuild_sentiment=False,
    )
    log.info(
        "auction snapshot trade_d=%s phase=%s frozen=%s saved=%s",
        today,
        phase,
        freeze,
        ok,
    )
    return {"ok": ok, "trade_d": today, "phase": phase, "frozen": freeze}


def persist_day(
    trade_d: str,
    prev_d: Optional[str],
    *,
    advice_d: str = "",
    is_ready: bool = True,
    sections: Optional[dict] = None,
    force: bool = False,
    freeze: bool = False,
    phase: str = "",
) -> bool:
    """计算并写入单日：metrics + 情绪 + 8项 + 9/3/6/18 指标块。"""
    trade_d = (trade_d or "")[:8]
    if not force:
        existing = fetch_daily_detail(trade_d)
        frozen = bool(((existing or {}).get("metrics") or {}).get("snapshot_frozen"))
        if frozen:
            return True

    metrics = _load_or_build_ref_metrics(trade_d, prev_d, force=force)
    if phase or freeze:
        metrics = dict(metrics)
        metrics["snapshot_phase"] = phase or ("1800" if freeze else "1505")
        metrics["snapshot_frozen"] = freeze
        metrics["snapshot_at"] = bj_now().isoformat(timespec="seconds")
    prev_metrics = _load_or_build_ref_metrics(prev_d, None, force=force) if prev_d else None
    if sections is None:
        today = date_str(bj_now())
        sections = build_daily_sections(
            trade_d,
            prev_d,
            metrics,
            prev_metrics,
            advice_d=advice_d or trade_d,
            is_ready=is_ready,
            include_live_peripheral=(trade_d == today or (advice_d or trade_d) == today),
        )
    sentiment = calc_sentiment(
        metrics,
        peripheral=sections.get("peripheral"),
        auction=sections.get("auction"),
        grid9=sections.get("grid9"),
    )
    indicators = build_indicators(metrics, prev_metrics)
    ui_level = display_level_label(sentiment["score"])
    level_class = display_level_class(sentiment["score"])
    history_item = build_history_item(
        metrics, sentiment, ui_level=ui_level, level_class=level_class
    )
    return save_daily_record(
        trade_d,
        prev_d,
        metrics,
        sentiment,
        history_item=history_item,
        indicators=indicators,
        grid9=sections.get("grid9"),
        peripheral=sections.get("peripheral"),
        auction=sections.get("auction"),
        indicator_sections=sections.get("indicatorSections"),
    )


def persist_from_home(
    trade_d: str,
    prev_d: Optional[str],
    home_data: dict,
    *,
    advice_d: str = "",
) -> bool:
    """从首页整包写入（含实时外围/竞价/18项）。"""
    metrics = home_data.get("metrics") or {}
    sentiment = {
        "score": home_data.get("score"),
        "levelColor": home_data.get("levelColor"),
        "positionPercent": home_data.get("positionPercent"),
        "emptyWarning": home_data.get("emptyWarning"),
        "emptyReasons": home_data.get("emptyReasons"),
    }
    ui_level = home_data.get("levelLabel") or display_level_label(sentiment.get("score") or 0)
    level_class = home_data.get("levelClass") or display_level_class(sentiment.get("score") or 0)
    history_item = build_history_item(
        metrics, sentiment, ui_level=ui_level, level_class=level_class
    )
    sections = {
        "grid9": home_data.get("grid9") or [],
        "peripheral": home_data.get("peripheral") or home_data.get("overview") or [],
        "auction": home_data.get("auction") or [],
        "indicatorSections": home_data.get("indicatorSections") or [],
    }
    return save_daily_record(
        trade_d,
        prev_d,
        metrics,
        sentiment,
        history_item=history_item,
        indicators=home_data.get("indicators"),
        grid9=sections["grid9"],
        peripheral=sections["peripheral"],
        auction=sections["auction"],
        indicator_sections=sections["indicatorSections"],
    )


def sync_history_days(days: int = 60) -> dict:
    """回填最近 N 个交易日；已存在则更新。"""
    days = max(1, min(days, 120))
    dates = get_recent_trade_dates(days + 1)
    stored_before = set(list_stored_trade_dates(days + 5))
    ok, fail, skipped = 0, 0, 0
    today = date_str(bj_now())
    for i in range(1, len(dates)):
        if _sync_cancel.is_set():
            skipped = max(0, len(dates) - i)
            log.info("history sync cancelled before %s, skipped=%s", dates[i] if i < len(dates) else "-", skipped)
            break
        d, p = dates[i], dates[i - 1]
        try:
            if persist_day(
                d,
                p,
                advice_d=d,
                is_ready=(d != today or bj_now().hour > 9 or (bj_now().hour == 9 and bj_now().minute >= 15)),
            ):
                ok += 1
            else:
                fail += 1
        except Exception:
            log.exception("persist_day failed %s", d)
            fail += 1
    stored_after = list_stored_trade_dates(3)
    return {
        "requestedDays": days,
        "tradeDates": len(dates) - 1,
        "saved": ok,
        "failed": fail,
        "skipped": skipped,
        "cancelled": _sync_cancel.is_set(),
        "hadBefore": len(stored_before),
        "latestStored": stored_after[0] if stored_after else None,
    }


def sync_job_status() -> dict:
    with _sync_lock:
        out = dict(_sync_state)
        out["stopRequested"] = _sync_cancel.is_set()
    if out.get("startedAt"):
        out["runningSec"] = round(time.time() - out["startedAt"], 1) if out.get("running") else None
    out["history"] = history_db_status()
    return out


def request_stop_sync() -> dict:
    """请求停止当前后台同步（当前日处理完后退出）。"""
    with _sync_lock:
        if not _sync_state["running"]:
            _sync_cancel.clear()
            return {"accepted": False, "running": False, "message": "当前没有进行中的同步任务"}
        _sync_cancel.set()
        _sync_state["stopRequested"] = True
        return {
            "accepted": True,
            "running": True,
            "message": "已请求停止，将在当前交易日处理完成后退出",
            "requestedDays": _sync_state.get("requestedDays") or 0,
        }


def trigger_sync_history_days(days: int = 60) -> dict:
    """后台启动历史回填；若已在跑则直接返回状态。"""
    days = max(1, min(days, 120))
    with _sync_lock:
        if _sync_state["running"]:
            return {
                "accepted": False,
                "alreadyRunning": True,
                "message": "历史同步进行中，请稍后查询 home-status",
                "requestedDays": _sync_state.get("requestedDays") or days,
            }
        _sync_cancel.clear()
        _sync_state["running"] = True
        _sync_state["stopRequested"] = False
        _sync_state["startedAt"] = time.time()
        _sync_state["requestedDays"] = days
        _sync_state["lastError"] = None
        _sync_state["finishedAt"] = None

    def _run() -> None:
        try:
            result = sync_history_days(days)
            with _sync_lock:
                _sync_state["lastResult"] = result
        except Exception as exc:
            log.exception("sync_history_days failed")
            with _sync_lock:
                _sync_state["lastError"] = str(exc)
        finally:
            with _sync_lock:
                _sync_state["running"] = False
                _sync_state["stopRequested"] = False
                _sync_state["finishedAt"] = time.time()
            _sync_cancel.clear()

    threading.Thread(target=_run, daemon=True, name="sync-history").start()
    return {
        "accepted": True,
        "alreadyRunning": False,
        "message": "历史同步已在后台启动，约需数分钟，请轮询 home-status",
        "requestedDays": days,
    }
