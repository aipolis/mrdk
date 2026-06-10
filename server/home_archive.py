# -*- coding: utf-8 -*-
"""从 daily_market 组装首页 payload（无东财/akshare 实时抓取）。"""
from __future__ import annotations

import logging
from typing import Optional

from fetcher import (
    build_home_trend,
    build_indicators,
    build_section_metas,
    build_yesterday_sentiment,
    display_level_class,
    display_level_label,
    fetch_intraday_board_stats,
    load_auction_snapshot,
    load_longkong_risk_cached,
)
from history_store import fetch_daily_detail, fetch_intraday_snapshot_at_or_before
from intraday import order_indicator_sections
from sentiment import (
    apply_display_longkong,
    calc_sentiment,
    longkong_state,
    position_desc,
    strategy_note_for_home,
)
from subscribe_msg import build_subscribe_message

log = logging.getLogger("mingri.home_archive")


def _fmt_date(d: str) -> str:
    d = str(d or "").replace("-", "")[:8]
    if len(d) != 8:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _section_items(sections: list, sid: str) -> list:
    for sec in sections or []:
        if sec.get("id") == sid:
            return sec.get("items") or []
    return []


def _detail_metrics(detail: Optional[dict]) -> dict:
    return (detail or {}).get("metrics") or {}


def _detail_sentiment(detail: Optional[dict]) -> dict:
    return (detail or {}).get("sentiment") or {}


def assemble_home_from_archive(
    ref_d: str,
    prev_d: Optional[str],
    advice_d: str,
    *,
    is_ready: bool = True,
) -> Optional[dict]:
    """收盘后/非交易时段：优先从 MySQL 组装整包，避免实时行情请求。"""
    ref_d = (ref_d or "")[:8]
    advice_d = (advice_d or ref_d)[:8]
    if len(ref_d) != 8:
        return None

    ref_detail = fetch_daily_detail(ref_d)
    if not ref_detail or not _detail_metrics(ref_detail):
        log.info("archive miss ref_d=%s", ref_d)
        return None

    advice_detail = fetch_daily_detail(advice_d) if advice_d != ref_d else ref_detail
    if not advice_detail:
        advice_detail = ref_detail

    metrics = _detail_metrics(ref_detail)
    prev_metrics = None
    if prev_d:
        prev_detail = fetch_daily_detail(prev_d)
        if prev_detail:
            prev_metrics = _detail_metrics(prev_detail)

    grid9 = ref_detail.get("grid9") or []
    if not grid9:
        grid9 = build_yesterday_sentiment(metrics, prev_metrics)

    auction = load_auction_snapshot(
        advice_d,
        ref_d,
        prev_d,
        metrics,
        prev_metrics,
        is_ready=is_ready,
    )
    if not auction:
        auction = advice_detail.get("auction") or []

    indicator_sections = list(
        advice_detail.get("indicatorSections")
        or ref_detail.get("indicatorSections")
        or []
    )
    longkong_risk = load_longkong_risk_cached(
        ref_d, prev_d, metrics, prev_metrics, advice_d=advice_d
    )

    intraday = (
        advice_detail.get("intraday")
        if isinstance(advice_detail.get("intraday"), list)
        else _section_items(indicator_sections, "intraday")
    )
    intraday_snapshot = fetch_intraday_snapshot_at_or_before(advice_d, "15:00")
    if intraday_snapshot and intraday_snapshot.get("items"):
        intraday = intraday_snapshot["items"]
    if intraday and advice_d == ref_d:
        board = fetch_intraday_board_stats(ref_d, metrics, live=False)
        board_values = {
            "highBoardChgLive": (
                board.get("high_board_chg_live"),
                board.get("prev_high_board_chg"),
                "pct",
            ),
            "promoteLive": (
                board.get("promote_live"),
                board.get("prev_promote"),
                "rate",
            ),
        }
        corrected = []
        for item in intraday:
            cell = dict(item)
            current, previous, value_type = board_values.get(cell.get("key"), (None, None, ""))
            if current is not None:
                digits = 2 if value_type == "pct" else 0
                cell["value"] = f"{float(current):+.{digits}f}%" if value_type == "pct" else f"{float(current):.{digits}f}%"
                cell["yesterday"] = (
                    f"{float(previous):+.{digits}f}%" if value_type == "pct"
                    else f"{float(previous):.{digits}f}%"
                ) if previous is not None else "--"
                cell["prev"] = cell["yesterday"]
                cell["trend"] = "up" if previous is not None and current > previous else "down" if previous is not None and current < previous else "flat"
            corrected.append(cell)
        intraday = corrected

    sentiment = calc_sentiment(
        metrics,
        auction=auction,
        grid9=grid9,
    )
    stored = _detail_sentiment(advice_detail) or _detail_sentiment(ref_detail)
    if (
        stored.get("score") is not None
        and stored.get("scoreVersion") == sentiment.get("scoreVersion")
    ):
        sentiment["score"] = int(stored["score"])

    baseline_score = int(sentiment["score"])
    display_score = baseline_score
    score_mode = "baseline"
    intraday_score = None

    # 若库里有盘中归档分，保留展示（收盘后仍可见最后盘中分）
    adv_m = _detail_metrics(advice_detail)
    if adv_m.get("display_score") is not None:
        display_score = int(adv_m["display_score"])
    if adv_m.get("intraday_score") is not None:
        intraday_score = int(adv_m["intraday_score"])
    if adv_m.get("score_mode"):
        score_mode = str(adv_m["score_mode"])

    longkong = apply_display_longkong(sentiment, display_score, score_mode=score_mode)
    advice_metrics = _detail_metrics(advice_detail)
    metas, gauge_label, now_hm = build_section_metas(
        ref_d, advice_d, is_ready, ref_metrics=metrics, advice_metrics=advice_metrics
    )

    if indicator_sections:
        for sec in indicator_sections:
            sid = sec.get("id")
            if sid == "yesterday":
                sec["items"] = grid9
                sec["meta"] = metas.get("yesterday", sec.get("meta"))
            elif sid == "auction":
                sec["items"] = auction
                sec["meta"] = metas.get("auction", sec.get("meta"))
            elif sid == "longkongRisk":
                sec["items"] = longkong_risk
                sec["meta"] = metas.get("intraday", sec.get("meta"))
            elif sid == "intraday" and intraday:
                sec["items"] = intraday
                sec["meta"] = metas.get("intraday", sec.get("meta"))
                sec["pending"] = False
        # Filter out any legacy peripheral sections from DB
        indicator_sections = [sec for sec in indicator_sections if sec.get("id") != "peripheral"]
        if intraday and not any(sec.get("id") == "intraday" for sec in indicator_sections):
            indicator_sections.append({
                "id": "intraday",
                "title": "盘中实时情绪",
                "meta": metas.get("intraday") or "",
                "layout": "grid3",
                "cols": 3,
                "items": intraday,
                "pending": False,
            })
        indicator_sections = order_indicator_sections(indicator_sections)
    else:
        from fetcher import build_indicator_sections

        indicator_sections = build_indicator_sections(
            ref_d, prev_d, metrics, prev_metrics, advice_d=advice_d, is_ready=is_ready
        )
        for sec in indicator_sections:
            sid = sec.get("id")
            if sid == "yesterday":
                sec["items"] = grid9
            elif sid == "auction":
                sec["items"] = auction
            elif sid == "longkongRisk":
                sec["items"] = longkong_risk

    ui_level = display_level_label(display_score)
    ui_level_class = display_level_class(display_score)
    subscribe_preview = build_subscribe_message(
        {**sentiment, **longkong, "displayScore": display_score},
        ref_date=metrics.get("date") or ref_d,
        advice_date=_fmt_date(advice_d),
    )

    return {
        "adviceDate": _fmt_date(advice_d),
        "refDate": _fmt_date(metrics.get("date") or ref_d),
        "date": _fmt_date(advice_d),
        "generatedAt": gauge_label,
        "generatedAtLabel": gauge_label,
        "generatedAtTime": now_hm,
        "dailyQuote": "买在分歧，卖在一致",
        "overview": [],
        "foreignCards": [],
        "grid9": grid9,
        "auction": auction,
        "intraday": intraday or [],
        "longkongRisk": longkong_risk,
        "indicatorSections": indicator_sections,
        "subscribePreview": {
            "date": subscribe_preview["date"],
            "weather": subscribe_preview["weather"],
            "keyData": subscribe_preview["keyData"],
            "tips": subscribe_preview["tips"],
        },
        "score": baseline_score,
        "scoreVersion": sentiment.get("scoreVersion"),
        "baselineScore": baseline_score,
        "liveScore": intraday_score,
        "displayScore": display_score,
        "scoreMode": score_mode,
        "useLiveScore": score_mode == "live",
        "levelLabel": ui_level,
        "displayLevel": ui_level,
        "levelClass": ui_level_class,
        "levelColor": sentiment.get("levelColor"),
        "longkongSignal": longkong["longkongSignal"],
        "longkongState": longkong_state(
            display_score,
            empty_warning=longkong["emptyWarning"],
            risk_level=longkong.get("riskLevel", "none"),
            sub_scores=sentiment.get("subScores") or {},
            intraday_sub_scores={},
        ),
        "positionPercent": longkong["positionPercent"],
        "positionLabel": longkong["positionLabel"],
        "positionDesc": position_desc(
            display_score, longkong["emptyWarning"], longkong.get("riskLevel", "none")
        ),
        "emptyWarning": longkong["emptyWarning"],
        "riskLevel": longkong.get("riskLevel", "none"),
        "emptyReasons": longkong["emptyReasons"],
        "strategyNote": strategy_note_for_home(
            sentiment, display_score, score_mode=score_mode, longkong=longkong
        ),
        "subScores": sentiment.get("subScores") or {},
        "scoreContributions": (sentiment.get("subScores") or {}).get("contributions") or {},
        "scoreDataQuality": (sentiment.get("subScores") or {}).get("dataQuality") or {},
        "intradaySubScores": {},
        "baselineEmptyWarning": sentiment.get("emptyWarning"),
        "baselineRiskLevel": sentiment.get("riskLevel", "none"),
        "baselineEmptyReasons": sentiment.get("emptyReasons") or [],
        "baselinePositionPercent": sentiment.get("positionPercent"),
        "baselinePositionLabel": sentiment.get("positionLabel"),
        "indicators": advice_detail.get("indicators") or build_indicators(metrics, prev_metrics),
        "trend": build_home_trend(ref_d),
        "metrics": metrics,
        "prevMetrics": prev_metrics or {},
        "isReportReady": is_ready,
        "fromArchive": True,
    }
