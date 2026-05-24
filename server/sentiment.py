# -*- coding: utf-8 -*-
"""情绪评分引擎 — 基准分：T 日 9:00 前（昨日+外围）；盘中分：9:00 后含竞价 + 9 项实时"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

# 基准分：仅昨日 + 外围（竞价已移入盘中分）
W_YESTERDAY_BASE = 0.80
W_PERIPHERAL_BASE = 0.20

# 盘中分内：竞价块权重随时间从 9:30 的 65% 线性降至 15:00 的 15%
LIVE_AUC_W_AT_930 = 0.65
LIVE_AUC_W_AT_1500 = 0.15

# 盘中 9 项权重（展示分融合用，总和 1.0）
W_INTRADAY = {
    "sseIndex": 0.14,
    "upRatio": 0.14,
    "limitUpLive": 0.11,
    "limitDownLive": 0.09,
    "marketVolumeLive": 0.10,
    "high10Live": 0.10,
    "top10AvgChgLive": 0.12,
    "promoteLive": 0.10,
    "breakLive": 0.10,
}

# 仅昨日 metrics（历史 sync / 趋势图）
W_YESTERDAY_ONLY = 1.0

SCORE_STRONG = 90
SCORE_MID = 55
SCORE_WEAK = 20
SCORE_NEUTRAL = 55


def _tier_high(value: float, hi: float, mid: float) -> int:
    if value >= hi:
        return SCORE_STRONG
    if value >= mid:
        return SCORE_MID
    return SCORE_WEAK


def _tier_low(value: float, lo: float, mid: float) -> int:
    """值越低越好（跌停、炸板等）"""
    if value <= lo:
        return SCORE_STRONG
    if value <= mid:
        return SCORE_MID
    return SCORE_WEAK


def _parse_num(raw) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s in ("", "--", "-"):
        return None
    s = s.replace("板", "").replace("亿", "")
    m = re.search(r"-?\d+\.?\d*", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return None


def _parse_pct(raw) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip().replace("%", "").replace("+", "")
    if s in ("", "--", "-"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return _parse_num(raw)


def _items_by_key(items: Optional[list]) -> dict:
    out = {}
    for it in items or []:
        key = it.get("key") or it.get("name")
        if key:
            out[str(key)] = it
    return out


def _item_pct(item: Optional[dict]) -> Optional[float]:
    if not item:
        return None
    if item.get("chg") is not None:
        try:
            return float(item["chg"])
        except (TypeError, ValueError):
            pass
    return _parse_pct(item.get("chgText") or item.get("value"))


def _item_num(item: Optional[dict]) -> Optional[float]:
    if not item:
        return None
    return _parse_num(item.get("value"))


# ── 昨日情绪 9 项 ─────────────────────────────────────────────


def score_height(max_board: int) -> int:
    return _tier_high(float(max_board or 0), 6, 3)


def score_limit_up(count: int) -> int:
    return _tier_high(float(count or 0), 80, 40)


def score_seal(rate: float) -> int:
    return _tier_high(float(rate or 0), 75, 58)


def score_promote(rate: float) -> int:
    return _tier_high(float(rate or 0), 40, 20)


def score_limit_down(count: int) -> int:
    return _tier_low(float(count or 0), 5, 18)


def score_break_rate(rate: float) -> int:
    return _tier_low(float(rate or 0), 18, 32)


def score_one_word(count: int) -> int:
    return _tier_high(float(count or 0), 12, 5)


def score_volume_yi(yi: float) -> int:
    return _tier_high(float(yi or 0), 9000, 6500)


def score_volume_intraday(amount_raw: float, vol_pct: Optional[float] = None) -> int:
    """盘中量能：优先同时刻同比；无对比时不使用全天阈值压分。"""
    if vol_pct is not None:
        return _tier_high(float(vol_pct), 8.0, -2.0)
    if float(amount_raw or 0) > 0:
        return SCORE_NEUTRAL
    return SCORE_NEUTRAL


def score_advance_breadth(adv: int, dec: int) -> int:
    adv, dec = int(adv or 0), int(dec or 0)
    total = adv + dec
    if total < 50:
        return SCORE_NEUTRAL
    ratio = adv / total
    if ratio >= 0.62:
        return SCORE_STRONG
    if ratio >= 0.48:
        return SCORE_MID
    return SCORE_WEAK


def score_high10(count: int) -> int:
    return _tier_high(float(count or 0), 400, 150)


def score_top10_avg_chg(chg: float) -> int:
    return _tier_high(float(chg or 0), 1.2, 0.0)


def score_sse_index(chg: float) -> int:
    return _tier_high(float(chg or 0), 0.8, 0.0)


def _score_yesterday_block(metrics: dict, grid9: Optional[list] = None) -> dict[str, int]:
    g = _items_by_key(grid9)
    m = metrics or {}

    max_board = _parse_num((g.get("height") or {}).get("value")) or m.get("max_board", 0)
    limit_up = _parse_num((g.get("limitUp") or {}).get("value")) or m.get("limit_up_count", 0)
    seal = _parse_pct((g.get("seal") or {}).get("value")) or m.get("seal_rate", 0)
    promote = _parse_pct((g.get("promote") or {}).get("value")) or m.get("promote_rate", 0)
    limit_down = _parse_num((g.get("limitDown") or {}).get("value")) or m.get("limit_down_count", 0)
    break_r = _parse_pct((g.get("break") or {}).get("value")) or m.get("break_rate", 0)
    one_word = _parse_num((g.get("oneWord") or {}).get("value")) or m.get("one_word_count", 0)
    vol_yi = m.get("volume_raw") or _parse_num((g.get("volume") or {}).get("value"))
    adv_item = g.get("advance") or {}
    adv = adv_item.get("advance_up")
    if adv is None:
        adv = adv_item.get("advanceUp")
    if adv is None:
        adv = m.get("advance_count", 0)
    dec = adv_item.get("decline_down")
    if dec is None:
        dec = adv_item.get("declineDown")
    if dec is None:
        dec = m.get("decline_count", 0)

    high10 = m.get("high10_count")
    top10_chg = m.get("top10_avg_chg")
    try:
        top10_f = float(top10_chg) if top10_chg is not None else None
    except (TypeError, ValueError):
        top10_f = None

    out = {
        "height": score_height(int(max_board or 0)),
        "limitUp": score_limit_up(int(limit_up or 0)),
        "seal": score_seal(float(seal or 0)),
        "promote": score_promote(float(promote or 0)),
        "limitDown": score_limit_down(int(limit_down or 0)),
        "break": score_break_rate(float(break_r or 0)),
        "oneWord": score_one_word(int(one_word or 0)),
        "volume": score_volume_yi(float(vol_yi or 0)),
        "advance": score_advance_breadth(int(adv or 0), int(dec or 0)),
        "high10": score_high10(int(high10 or 0)) if high10 is not None else SCORE_NEUTRAL,
        "top10AvgChg": score_top10_avg_chg(top10_f) if top10_f is not None else SCORE_NEUTRAL,
    }
    return out


# ── 盘中实时 9 项 ─────────────────────────────────────────────


def score_intraday_block(snap: dict) -> dict[str, int]:
    """盘中 9 项单项分（与 UI key 一致）"""
    snap = snap or {}
    sse = snap.get("sse_chg")
    adv = int(snap.get("advance") or 0)
    dec = int(snap.get("decline") or 0)
    lu = int(snap.get("limit_up") or 0)
    ld = int(snap.get("limit_down") or 0)
    ratio = snap.get("up_ratio")
    amt = float(snap.get("amount_raw") or 0)
    prev_vol = snap.get("prev_volume_raw")
    vol_pct = None
    if amt > 0 and prev_vol is not None:
        try:
            pv = float(prev_vol)
            if pv > 0:
                vol_pct = (amt - pv) / pv * 100
        except (TypeError, ValueError):
            pass
    high10 = int(snap.get("high10") or 0)
    top10 = snap.get("top10_avg_live")
    promote = snap.get("promote_live")
    break_r = snap.get("break_live")

    if ratio is not None:
        breadth_s = _tier_high(float(ratio), 62, 48)
    elif adv + dec >= 50:
        breadth_s = _tier_high(adv / (adv + dec) * 100, 62, 48)
    else:
        breadth_s = SCORE_NEUTRAL

    try:
        top10_f = float(top10) if top10 is not None else None
    except (TypeError, ValueError):
        top10_f = None

    return {
        "sseIndex": score_sse_index(float(sse)) if sse is not None else SCORE_NEUTRAL,
        "upRatio": breadth_s,
        "limitUpLive": _tier_high(float(lu), 70, 35),
        "limitDownLive": _tier_low(float(ld), 8, 25),
        "marketVolumeLive": score_volume_intraday(amt, vol_pct),
        "high10Live": score_high10(high10) if high10 else SCORE_NEUTRAL,
        "top10AvgChgLive": score_top10_avg_chg(top10_f) if top10_f is not None else SCORE_NEUTRAL,
        "promoteLive": score_promote(float(promote)) if promote is not None else SCORE_NEUTRAL,
        "breakLive": score_break_rate(float(break_r)) if break_r is not None else SCORE_NEUTRAL,
    }


def _weighted_intraday_avg(scores: dict[str, int]) -> float:
    if not scores:
        return float(SCORE_NEUTRAL)
    weighted = 0.0
    total_w = 0.0
    for key, w in W_INTRADAY.items():
        if key not in scores:
            continue
        weighted += scores[key] * w
        total_w += w
    if total_w <= 0:
        return float(SCORE_NEUTRAL)
    return weighted / total_w


def _has_live_snap(snap: dict) -> bool:
    """9:30 后实时快照是否有效（非空占位）"""
    snap = snap or {}
    if snap.get("sse_chg") is not None:
        return True
    if float(snap.get("amount_raw") or 0) > 0:
        return True
    if int(snap.get("limit_up") or 0) or int(snap.get("limit_down") or 0):
        return True
    adv = int(snap.get("advance") or 0)
    dec = int(snap.get("decline") or 0)
    return adv + dec >= 50


def calc_intraday_score(snap: dict) -> int:
    """盘中实时 9 项加权（不含竞价）"""
    return round(_weighted_intraday_avg(score_intraday_block(snap or {})))


def _auction_block_weight_in_live(now: Optional[datetime] = None) -> float:
    """
    盘中分内竞价块权重：9:00–9:29 仅竞价(100%)；9:30 起随时间降低，15:00 约 15%。
    """
    now = now or datetime.now()
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 30:
        return 1.0
    start, end = 9 * 60 + 30, 15 * 60
    if hm >= end:
        return LIVE_AUC_W_AT_1500
    t = (hm - start) / (end - start)
    return LIVE_AUC_W_AT_930 - t * (LIVE_AUC_W_AT_930 - LIVE_AUC_W_AT_1500)


def calc_live_score(
    snap: Optional[dict] = None,
    *,
    auction: Optional[list] = None,
    metrics: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """
    盘中分：T 日 9:00 后计入竞价；9:30 后与实时 9 项融合，竞价比重随时间降低。
    仅竞价或仅实时时取有数据的一侧。
    """
    snap = snap or {}
    has_live = _has_live_snap(snap)
    has_auc = _has_auction_data(auction)

    auc_avg: Optional[float] = None
    live_avg: Optional[float] = None
    if has_auc:
        auc_avg = _block_avg(_score_auction_block(auction, metrics))
    if has_live:
        live_avg = _weighted_intraday_avg(score_intraday_block(snap))

    if live_avg is not None and auc_avg is not None:
        w_auc = _auction_block_weight_in_live(now)
        return round(live_avg * (1 - w_auc) + auc_avg * w_auc)
    if auc_avg is not None:
        return round(auc_avg)
    if live_avg is not None:
        return round(live_avg)
    return None


# ── 外围 3 项 ───────────────────────────────────────────────


def _match_peripheral(items: list, *keywords: str) -> Optional[dict]:
    for it in items:
        blob = f"{it.get('key', '')} {it.get('label', '')} {it.get('name', '')}"
        if any(kw in blob for kw in keywords):
            return it
    return None


def _score_peripheral_block(peripheral: Optional[list]) -> dict[str, int]:
    items = peripheral or []
    a50 = _match_peripheral(items, "A50", "富时")
    sp = _match_peripheral(items, "标普")
    cnh = _match_peripheral(items, "人民币", "CNH", "离岸")

    a50_chg = _item_pct(a50)
    sp_chg = _item_pct(sp)
    cnh_chg = _item_pct(cnh)

    return {
        "ftseA50": _tier_high(a50_chg if a50_chg is not None else 0, 0.5, -0.3)
        if a50_chg is not None
        else SCORE_NEUTRAL,
        "sp500": _tier_high(sp_chg if sp_chg is not None else 0, 0.3, -0.5)
        if sp_chg is not None
        else SCORE_NEUTRAL,
        # 离岸人民币升（贬值）偏空，取反
        "cnh": _tier_low(cnh_chg if cnh_chg is not None else 0, -0.05, 0.15)
        if cnh_chg is not None
        else SCORE_NEUTRAL,
    }


# ── 竞价 6 项 ───────────────────────────────────────────────


def _score_auction_block(auction: Optional[list], metrics: Optional[dict] = None) -> dict[str, int]:
    a = _items_by_key(auction)
    m = metrics or {}

    one_word = _item_num(a.get("auctionOneWord"))
    if one_word is None:
        one_word = m.get("auction_one_word_count")

    vol_yi = _parse_num((a.get("auctionVolume") or {}).get("value"))
    if vol_yi is None:
        vol_yi = m.get("auction_volume_yi")

    first_chg = _parse_pct((a.get("yesterdayFirst") or {}).get("value"))
    multi_chg = _parse_pct((a.get("yesterdayMulti") or {}).get("value"))
    recent_chg = _parse_pct((a.get("recentMulti") or {}).get("value"))
    top10_chg = _parse_pct((a.get("top10AuctionChg") or {}).get("value"))

    return {
        "auctionOneWord": _tier_high(float(one_word or 0), 8, 3)
        if one_word is not None
        else SCORE_NEUTRAL,
        "auctionVolume": _tier_high(float(vol_yi or 0), 450, 320)
        if vol_yi is not None
        else SCORE_NEUTRAL,
        "yesterdayFirst": _tier_high(first_chg if first_chg is not None else 0, 2.0, 0.0)
        if first_chg is not None
        else SCORE_NEUTRAL,
        "yesterdayMulti": _tier_high(multi_chg if multi_chg is not None else 0, 1.0, -1.0)
        if multi_chg is not None
        else SCORE_NEUTRAL,
        "recentMulti": _tier_high(recent_chg if recent_chg is not None else 0, 2.5, 0.0)
        if recent_chg is not None
        else SCORE_NEUTRAL,
        "top10AuctionChg": _tier_high(top10_chg if top10_chg is not None else 0, 1.2, 0.0)
        if top10_chg is not None
        else SCORE_NEUTRAL,
    }


def _block_avg(scores: dict[str, int]) -> float:
    if not scores:
        return float(SCORE_NEUTRAL)
    return sum(scores.values()) / len(scores)


def _has_auction_data(auction: Optional[list]) -> bool:
    if not auction:
        return False
    for it in auction:
        val = str(it.get("value") or "").strip()
        if val and val not in ("--", "-", "0"):
            return True
    return False


def _collect_weak_reasons(
    y: dict[str, int],
    p: dict[str, int],
    metrics: dict,
) -> list[str]:
    reasons = []
    if y.get("promote", 99) <= SCORE_WEAK:
        reasons.append(f"晋级率仅{metrics.get('promote_rate', 0):.0f}%")
    if y.get("limitUp", 99) <= SCORE_WEAK:
        reasons.append(f"涨停仅{metrics.get('limit_up_count', 0)}只")
    if y.get("height", 99) <= SCORE_WEAK:
        reasons.append(f"最高连板仅{metrics.get('max_board', 0)}板")
    if y.get("advance", 99) <= SCORE_WEAK:
        adv = int(metrics.get("advance_count") or 0)
        dec = int(metrics.get("decline_count") or 0)
        if adv + dec >= 50:
            reasons.append(f"上涨家数占比偏低（涨{adv}/跌{dec}）")
    if y.get("break", 99) <= SCORE_WEAK:
        reasons.append(f"炸板率{metrics.get('break_rate', 0):.0f}%偏高")
    top10 = metrics.get("top10_avg_chg")
    if top10 is not None and y.get("top10AvgChg", 99) <= SCORE_WEAK:
        reasons.append(f"成交额前10平均涨幅仅{float(top10):.2f}%")
    high10 = metrics.get("high10_count")
    if high10 is not None and y.get("high10", 99) <= SCORE_WEAK:
        reasons.append(f"10日新高仅{int(high10)}只")
    if p.get("ftseA50", 99) <= SCORE_WEAK and p.get("sp500", 99) <= SCORE_WEAK:
        reasons.append("外围指数偏弱")
    return reasons


def _collect_live_weak_reasons(
    live_scores: dict[str, int],
    auc_scores: dict[str, int],
    metrics: dict,
) -> list[str]:
    """盘中分走弱原因（含竞价 6 项）"""
    reasons = []
    m = metrics or {}
    if auc_scores.get("auctionOneWord", 99) <= SCORE_WEAK and auc_scores.get("yesterdayFirst", 99) <= SCORE_WEAK:
        reasons.append("竞价接力偏弱")
    if auc_scores.get("recentMulti", 99) <= SCORE_WEAK:
        reasons.append("连板竞价溢价不足")
    if live_scores.get("limitDownLive", 99) <= SCORE_WEAK:
        reasons.append("实时跌停偏多")
    if live_scores.get("breakLive", 99) <= SCORE_WEAK:
        reasons.append(f"实时炸板率{m.get('break_rate', 0):.0f}%偏高")
    return reasons


def calc_sentiment(
    metrics: dict,
    *,
    peripheral: Optional[list] = None,
    auction: Optional[list] = None,
    grid9: Optional[list] = None,
) -> dict:
    """
    基准情绪分 0–100（T 日 9:00 前口径：昨日 + 外围，不含竞价）。
    - 有 peripheral：昨日 × 80% + 外围 × 20%
    - 仅 metrics：历史归档 / 趋势图
    auction 参数保留兼容，不参与基准分；竞价计分见 calc_live_score。
    """
    metrics = metrics or {}
    y_scores = _score_yesterday_block(metrics, grid9)
    y_avg = _block_avg(y_scores)

    has_peripheral = bool(peripheral)

    p_scores: dict[str, int] = {}
    a_scores: dict[str, int] = {}

    if has_peripheral:
        p_scores = _score_peripheral_block(peripheral)
    if _has_auction_data(auction):
        a_scores = _score_auction_block(auction, metrics)

    if has_peripheral:
        p_avg = _block_avg(p_scores)
        score = round(y_avg * W_YESTERDAY_BASE + p_avg * W_PERIPHERAL_BASE)
        mode = "yesterday+peripheral"
    else:
        score = round(y_avg * W_YESTERDAY_ONLY)
        mode = "yesterday_only"

    score = max(0, min(100, score))

    if score >= 75:
        level, color, signal = "极度亢奋", "#CF1322", "强"
        position, pos_label = 70, ""
    elif score >= 55:
        level, color, signal = "强", "#FF4D4F", "强"
        position, pos_label = 50, ""
    elif score >= 35:
        level, color, signal = "中性", "#FAAD14", "中"
        position, pos_label = 30, ""
    elif score >= 15:
        level, color, signal = "偏谨慎", "#FA8C16", "弱"
        position, pos_label = 10, ""
    else:
        level, color, signal = "冰点", "#1890FF", "极弱"
        position, pos_label = 0, ""

    empty_reasons = _collect_weak_reasons(y_scores, p_scores, metrics)
    empty_warning = len(empty_reasons) >= 2 or score <= 14
    if empty_warning:
        position, pos_label = 0, ""

    return {
        "score": score,
        "level": level,
        "levelColor": color,
        "longkongSignal": signal,
        "positionPercent": position,
        "positionLabel": pos_label,
        "emptyWarning": empty_warning,
        "emptyReasons": empty_reasons,
        "scoreMode": mode,
        "subScores": {
            "yesterday": y_scores,
            "peripheral": p_scores,
            "auction": a_scores,
            "yesterdayAvg": round(y_avg, 1),
            "peripheralAvg": round(_block_avg(p_scores), 1) if p_scores else None,
            "auctionAvg": round(_block_avg(a_scores), 1) if a_scores else None,
        },
    }


DISPLAY_LONGKONG_THRESHOLD = 50


def longkong_signal_from_score(score: int) -> str:
    """龙空信号档位（随展示分）"""
    score = int(score or 0)
    if score >= 55:
        return "强"
    if score >= 35:
        return "中"
    if score >= 15:
        return "弱"
    return "极弱"


def apply_display_longkong(
    baseline_sentiment: dict,
    display_score: int,
    *,
    score_mode: str = "baseline",
) -> dict:
    """
    龙空信号 / emptyWarning 随展示分更新。
    展示分 < 50 追加盘中或综合走弱风险提示（与基准龙空取并集）。
    """
    baseline_sentiment = baseline_sentiment or {}
    baseline_empty = bool(baseline_sentiment.get("emptyWarning"))
    reasons = list(baseline_sentiment.get("emptyReasons") or [])
    display_score = int(display_score or 0)

    display_risk = display_score < DISPLAY_LONGKONG_THRESHOLD
    empty_warning = baseline_empty or display_risk or display_score <= 14

    if display_risk:
        if score_mode == "live":
            risk_reason = f"盘中情绪分{display_score}，低于{DISPLAY_LONGKONG_THRESHOLD}分"
        else:
            risk_reason = f"综合情绪分{display_score}，低于{DISPLAY_LONGKONG_THRESHOLD}分"
        if risk_reason not in reasons:
            reasons.insert(0, risk_reason)

    signal = longkong_signal_from_score(display_score)
    position = int(baseline_sentiment.get("positionPercent") or 0)
    pos_label = baseline_sentiment.get("positionLabel") or ""
    if empty_warning:
        position, pos_label = 0, ""

    return {
        "longkongSignal": signal,
        "emptyWarning": empty_warning,
        "emptyReasons": reasons,
        "positionPercent": position,
        "positionLabel": pos_label,
    }


def strategy_note_for_home(
    baseline_sentiment: dict,
    display_score: int,
    *,
    score_mode: str,
    longkong: dict,
) -> str:
    if not longkong.get("emptyWarning"):
        if display_score >= 55:
            return "综合情绪偏强，盘面结构活跃"
        return "综合昨日收盘与外围，更新今日情绪参考"
    if (
        score_mode == "live"
        and display_score < DISPLAY_LONGKONG_THRESHOLD
        and not baseline_sentiment.get("emptyWarning")
    ):
        return "盘中情绪走弱，展示分低于50（龙空风险提示）"
    return "综合情绪偏弱，个人龙空信号触发（作者复盘）"


def position_desc(score: int, empty_warning: bool) -> str:
    score = int(score or 0)
    if empty_warning and score <= 14:
        return "综合情绪极弱，盘面偏冷"
    if empty_warning and score < DISPLAY_LONGKONG_THRESHOLD:
        return "综合情绪走弱，展示分低于50，宜控节奏"
    if empty_warning:
        return "综合情绪偏弱，龙空风险提示"
    if score >= 61:
        return "综合情绪偏强，接力结构尚可"
    if score >= 41:
        return "综合情绪中性偏暖，注意分化"
    if score >= 21:
        return "综合情绪偏谨慎，短线结构一般"
    return "综合情绪偏弱，宜控节奏"
