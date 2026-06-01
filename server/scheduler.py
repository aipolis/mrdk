# -*- coding: utf-8 -*-
"""内置交易日定时任务（无需云托管控制台再配 cron）"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger("mingri.scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def internal_cron_enabled() -> bool:
    return os.getenv("INTERNAL_CRON", "true").lower() not in ("0", "false", "no")


def start_internal_cron(
    warm_fn: Callable[[], None],
    sync_fn: Callable[[], None],
    daily_push_fn: Callable[[], None],
    snapshot_1505_fn: Callable[[], None],
    snapshot_1800_fn: Callable[[], None],
    auction_0926_fn: Callable[[], None],
    auction_0935_fn: Callable[[], None],
    auction_live_fn: Callable[[], None],
    intraday_2m_fn: Callable[[], None],
) -> Optional[BackgroundScheduler]:
    global _scheduler
    if not internal_cron_enabled():
        log.info("INTERNAL_CRON disabled, skip built-in scheduler")
        return None
    if _scheduler and _scheduler.running:
        return _scheduler

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    weekday = "mon-fri"

    def _is_trading_day() -> bool:
        try:
            from config import bj_now
            from fetcher import date_str, get_recent_trade_dates

            return date_str(bj_now()) in get_recent_trade_dates(10)
        except Exception:
            log.exception("internal cron trading-day check failed")
            return False

    def _safe(name: str, fn: Callable[[], None]) -> None:
        if not _is_trading_day():
            log.info("internal cron skip non-trading day: %s", name)
            return
        log.info("internal cron start: %s", name)
        try:
            fn()
            log.info("internal cron done: %s", name)
        except Exception:
            log.exception("internal cron failed: %s", name)

    sched.add_job(
        lambda: _safe("warm-home-0600", warm_fn),
        CronTrigger(day_of_week=weekday, hour=6, minute=0),
        id="warm-home-0600",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("warm-home-0855", warm_fn),
        CronTrigger(day_of_week=weekday, hour=8, minute=55),
        id="warm-home-0855",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("auction-0926", auction_0926_fn),
        CronTrigger(day_of_week=weekday, hour=9, minute=26),
        id="auction-0926",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("auction-live-20s", auction_live_fn),
        IntervalTrigger(seconds=20),
        id="auction-live-20s",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("auction-0935", auction_0935_fn),
        CronTrigger(day_of_week=weekday, hour=9, minute=35),
        id="auction-0935",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("subscribe-daily-0910", daily_push_fn),
        CronTrigger(day_of_week=weekday, hour=9, minute=10),
        id="subscribe-daily-0910",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("intraday-2m", intraday_2m_fn),
        IntervalTrigger(minutes=2),
        id="intraday-2m",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("snapshot-1505", snapshot_1505_fn),
        CronTrigger(day_of_week=weekday, hour=15, minute=5),
        id="snapshot-1505",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("snapshot-1800", snapshot_1800_fn),
        CronTrigger(day_of_week=weekday, hour=18, minute=0),
        id="snapshot-1800",
        replace_existing=True,
    )
    sched.add_job(
        lambda: _safe("sync-history-1805", sync_fn),
        CronTrigger(day_of_week=weekday, hour=18, minute=5),
        id="sync-history-1805",
        replace_existing=True,
    )

    def _cleanup_auction_vol():
        try:
            from db_store import cleanup_auction_vol_snapshots
            cleanup_auction_vol_snapshots(keep_days=90)
        except Exception:
            log.exception("cleanup auction vol snapshots failed in scheduler")

    sched.add_job(
        _cleanup_auction_vol,
        CronTrigger(day_of_week=weekday, hour=18, minute=10),
        id="cleanup-auction-vol-1810",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    log.info("internal cron started (Asia/Shanghai, mon-fri)")
    return sched


def stop_internal_cron() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("internal cron stopped")
    _scheduler = None


def run_async_coro(coro_fn: Callable):
    """APScheduler 线程内跑 async 协程。"""
    asyncio.run(coro_fn())
