# -*- coding: utf-8 -*-
"""首页各板块更新时段与刷新策略。

时段（北京时间，交易日）：
  06:00 / 08:50  预热首页缓存（全量或归档组装）
  09:00          外围 3 项入库 → 当日盘中不再重算（展示 10 分钟刷新由 cron 写缓存）
  09:15–09:26    竞价 6 项每 20 秒刷新，09:26 固化
  09:30–15:00    盘中 9 项 + 龙空风控 6 项，每 2 分钟（cron 写缓存；API 读缓存节流）
  15:05          收盘快照入库
  18:00          日终固化

盘中不变（读 daily_market / 首页缓存）：
  昨日情绪 9 项、09:00 后外围、09:26 后竞价
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from config import bj_now
from fetcher import date_str, get_recent_trade_dates
from intraday import intraday_session_phase


class HomeRefreshMode(str, Enum):
    """首页数据刷新模式。"""

    ARCHIVED = "archived"  # 收盘后/夜间/非交易日：只读库
    PREOPEN = "preopen"  # 6:00–9:00 预热，可读库+补缺
    AUCTION = "auction"  # 9:15–9:26 竞价窗口
    INTRADAY = "intraday"  # 9:30–15:00 仅盘中块 live


# 各板块在何种模式下允许实时抓取（API 请求路径）
_SECTION_LIVE: dict[str, frozenset[HomeRefreshMode]] = {
    "yesterday": frozenset({HomeRefreshMode.PREOPEN}),
    "auction": frozenset({HomeRefreshMode.PREOPEN, HomeRefreshMode.AUCTION}),
    "longkongRisk": frozenset({HomeRefreshMode.PREOPEN, HomeRefreshMode.INTRADAY}),
    "intraday": frozenset({HomeRefreshMode.INTRADAY}),
}


def resolve_home_refresh_mode(now: Optional[datetime] = None) -> HomeRefreshMode:
    now = now or bj_now()
    today = date_str(now)
    phase = intraday_session_phase(now)

    if phase == "off":
        return HomeRefreshMode.ARCHIVED
    if today not in get_recent_trade_dates(10):
        return HomeRefreshMode.ARCHIVED
    if phase in ("night", "closed"):
        return HomeRefreshMode.ARCHIVED

    hm = now.hour * 60 + now.minute
    if hm < 9 * 60:
        return HomeRefreshMode.PREOPEN
    if phase == "waiting":
        return HomeRefreshMode.AUCTION
    if phase == "live":
        return HomeRefreshMode.INTRADAY
    return HomeRefreshMode.ARCHIVED


def should_use_archive_only(mode: Optional[HomeRefreshMode] = None) -> bool:
    return (mode or resolve_home_refresh_mode()) == HomeRefreshMode.ARCHIVED


def should_live_fetch_section(section_id: str, mode: Optional[HomeRefreshMode] = None) -> bool:
    mode = mode or resolve_home_refresh_mode()
    return mode in _SECTION_LIVE.get(section_id or "", frozenset())


def should_live_intraday(mode: Optional[HomeRefreshMode] = None) -> bool:
    return (mode or resolve_home_refresh_mode()) == HomeRefreshMode.INTRADAY


def cron_interval_minutes(job: str) -> int:
    """文档化各定时任务频率（分钟）。"""
    return {
        "intraday": 2,
        "home_warm": 600,
    }.get(job, 0)
