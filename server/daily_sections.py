# -*- coding: utf-8 -*-
"""构建单日 9+6 指标块（用于按日落库）"""
from __future__ import annotations

from typing import Optional

from fetcher import (
    build_auction_sentiment,
    build_indicator_sections,
    build_longkong_risk_items,
    build_yesterday_sentiment,
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
    """返回 grid9 / auction / indicatorSections 三块。"""
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
    return {
        "grid9": grid9,
        "peripheral": [],
        "auction": auction,
        "longkongRisk": build_longkong_risk_items(
            trade_d, prev_d, metrics, prev_metrics, advice_d=advice_d
        ),
        "indicatorSections": indicator_sections,
    }
