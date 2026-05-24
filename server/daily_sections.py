# -*- coding: utf-8 -*-
"""构建单日 9+3+6 指标块（用于按日落库）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fetcher import (
    build_auction_sentiment,
    build_indicator_sections,
    build_yesterday_sentiment,
    date_str,
    fetch_peripheral_sentiment,
)


def build_daily_sections(
    trade_d: str,
    prev_d: Optional[str],
    metrics: dict,
    prev_metrics: Optional[dict],
    *,
    advice_d: str = "",
    is_ready: bool = True,
    include_live_peripheral: bool = False,
) -> dict:
    """返回 grid9 / peripheral / auction / indicatorSections 四块。"""
    trade_d = (trade_d or "")[:8]
    advice_d = (advice_d or trade_d)[:8]
    prev_metrics = prev_metrics or {}

    grid9 = build_yesterday_sentiment(metrics, prev_metrics)
    auction = build_auction_sentiment(
        trade_d, metrics, prev_metrics, prev_d, advice_d=advice_d
    )
    indicator_sections = build_indicator_sections(
        trade_d,
        prev_d,
        metrics,
        prev_metrics,
        advice_d=advice_d,
        is_ready=is_ready,
    )
    today = date_str(datetime.now())
    peripheral = (
        fetch_peripheral_sentiment()
        if include_live_peripheral or trade_d == today or advice_d == today
        else []
    )
    return {
        "grid9": grid9,
        "peripheral": peripheral,
        "auction": auction,
        "indicatorSections": indicator_sections,
    }
