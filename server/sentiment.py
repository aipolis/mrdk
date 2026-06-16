# -*- coding: utf-8 -*-
"""情绪评分引擎 — 基准分：T 日 9:00 前（昨日）；盘中分：9:00 后含竞价 + 9 项实时"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from config import bj_now

# 盘中分内：竞价块权重随时间从 9:30 的 65% 线性降至 15:00 的 15%
LIVE_AUC_W_AT_930 = 0.65
LIVE_AUC_W_AT_1500 = 0.15

# 盘中 9 项权重（展示分融合用，总和 1.0）
W_INTRADAY = {
    "sseIndex": 0.05,
    "upRatio": 0.06,
    "limitUpLive": 0.08,
    "limitDownLive": 0.13,
    "marketVolumeLive": 0.05,
    "top10AvgChgLive": 0.13,
    "promoteLive": 0.18,
    "breakLive": 0.15,
    "highBoardChgLive": 0.17,
}

# 竞价 6 项权重：接力信号（近期溢价/首板涨幅）权重更高
W_AUCTION = {
    "recentMulti":      0.28,
    "yesterdayMulti":   0.23,
    "yesterdayFirst":   0.20,
    "top10AuctionChg":  0.15,
    "auctionVolume":    0.08,
    "auctionOneWord":   0.06,
}

# 龙空龙评分 V2：核心接力与亏钱效应优先，市场热度仅作为承载力。
# sealQuality 合并封板率与炸板率，避免同一信息重复计分。
W_YESTERDAY = {
    "promote":          0.16,
    "sealQuality":      0.16,
    "highBoardPromote": 0.14,
    "height":           0.10,
    "limitUp":          0.10,
    "limitDown":        0.10,
    "advance":          0.08,
    "volume":           0.06,
    "oneWord":          0.03,
}
# 可选项：有数据时纳入权重并归一化
W_YESTERDAY_OPT = {
    "continuationDepth":    0.08,  # 连板占比，接力深度
    "sectorConcentration":  0.05,  # 板块集中度，结构性信号
    "top10AvgChg":          0.04,
}

# 仅昨日 metrics（历史 sync / 趋势图）
W_YESTERDAY_ONLY = 1.0

SCORE_STRONG = 90
SCORE_MID = 55
SCORE_WEAK = 20
SCORE_NEUTRAL = 55
SCORE_VERSION = "longkong-v2"

# 连续评分中判定"信号偏弱"的阈值
_SIGNAL_WEAK = 40          # 一般指标
_SIGNAL_WEAK_PRIMARY = 45  # leading indicators（晋级率/炸板率/封板率）：阈值更高，更早预警

DISPLAY_LONGKONG_THRESHOLD = 50

RISK_MULTIPLIERS = {
    "none": 1.0,
    "caution": 0.9,
    "warning": 0.5,
    "critical": 0.0,
}

POSITION_SCORE_BASE = 30
POSITION_SCORE_SLOPE = 1.3
POSITION_SCORE_CAP = 100
WARNING_MULT_STRUCTURAL = 0.75
WARNING_MULT_WEAK = 0.5
VOLATILITY_MULT_HIGH = 0.85
VOLATILITY_MULT_MID = 0.92


# ── 连续线性评分函数 ───────────────────────────────────────────

def _linear_high(value: float, lo: float, hi: float) -> int:
    """值越高越好：lo → 20，hi → 90，中间线性插值。"""
    if value <= lo:
        return SCORE_WEAK
    if value >= hi:
        return SCORE_STRONG
    return round(SCORE_WEAK + (value - lo) / (hi - lo) * (SCORE_STRONG - SCORE_WEAK))


def _linear_low(value: float, lo: float, hi: float) -> int:
    """值越低越好：lo → 90，hi → 20，中间线性插值。"""
    if value <= lo:
        return SCORE_STRONG
    if value >= hi:
        return SCORE_WEAK
    return round(SCORE_STRONG - (value - lo) / (hi - lo) * (SCORE_STRONG - SCORE_WEAK))


# 保留旧的三档函数供外部兼容调用
def _tier_high(value: float, hi: float, mid: float) -> int:
    lo = 2 * mid - hi
    return _linear_high(value, lo, hi)


def _tier_low(value: float, lo: float, mid: float) -> int:
    hi = 2 * mid - lo
    return _linear_low(value, lo, hi)


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


# ── 昨日情绪 9 项（连续线性评分）─────────────────────────────

def score_height(max_board: int) -> int:
    # lo=0→20  hi=12→90  3板→38(触发) 4板→43(不触发)
    return _linear_high(float(max_board or 0), lo=0, hi=12)


def score_limit_up(count: int) -> int:
    # lo=14 → 20  hi=140 → 90  boundary≈50只→40
    return _linear_high(float(count or 0), lo=14, hi=140)


def score_seal(rate: float) -> int:
    # lo=41% → 20  hi=75% → 90  mid=58% → 55
    return _linear_high(float(rate or 0), lo=41.0, hi=75.0)


def score_promote(rate: float) -> int:
    """
    昨日涨停今日晋级率。低晋级区惩罚加重：约 9%→22，20%→50，35%+→90。
    """
    rate = float(rate or 0)
    if rate <= 0:
        return 10
    if rate >= 35:
        return 90
    if rate <= 15:
        return round(10 + rate / 15.0 * 22)
    return round(32 + (rate - 15) / 20.0 * 58)


def score_limit_down(count: int) -> int:
    # lo=5（偏少）→90  hi=31（偏多）→20  mid=18 → 55
    return _linear_low(float(count or 0), lo=5.0, hi=31.0)


def score_break_rate(rate: float) -> int:
    # lo=18%（健康）→90  hi=46%（危险）→20  mid=32% → 55
    # ≥50% 进入超危险区：凸形惩罚，最低接近 10
    rate = float(rate or 0)
    if rate >= 50.0:
        return max(10, round(20 - (rate - 50.0) * 0.4))
    return _linear_low(rate, lo=18.0, hi=46.0)


def score_sector_concentration(top3_ratio: float, total: int) -> int:
    """
    板块集中度（前三板块涨停占比）：集中 → 接力有利，分散 → 主题扩散难持续。
    total < 10 时数据不够，返回中性。
    lo=30% → 20，hi=80% → 90，mid=55% → 55。
    """
    if total < 10:
        return SCORE_NEUTRAL
    return _linear_high(float(top3_ratio or 0), lo=30.0, hi=80.0)


def score_continuation_depth(multi_board: int, limit_up: int) -> int:
    """
    连板占比 = multi_board / limit_up：接力深度。
    0%→0  15%→20  25%→50  40%→70  60%+→90
    """
    if not limit_up:
        return SCORE_NEUTRAL
    ratio = multi_board / limit_up * 100
    if ratio <= 0:
        return 0
    if ratio >= 60:
        return 90
    if ratio <= 15:
        return round(ratio / 15.0 * 20)
    if ratio <= 25:
        return round(20 + (ratio - 15) / 10.0 * 30)
    if ratio <= 40:
        return round(50 + (ratio - 25) / 15.0 * 20)
    return round(70 + (ratio - 40) / 20.0 * 20)


def score_one_word(count: int) -> int:
    # lo=0 → 20  hi=12 → 90  mid=5 → 49（略低于55，可接受）
    return _linear_high(float(count or 0), lo=0, hi=12)


def score_high_board_promote(continued: int, total: int) -> int:
    """高位板晋级率，小样本向中性分收缩，避免 0/1 或 1/1 过度扰动。"""
    continued, total = int(continued or 0), int(total or 0)
    if total <= 0:
        return SCORE_NEUTRAL
    raw = _linear_high(continued / total * 100, lo=0.0, hi=70.0)
    confidence = min(1.0, total / 5.0)
    return round(SCORE_NEUTRAL * (1 - confidence) + raw * confidence)


def score_volume_yi(yi: float, avg_20d: Optional[float] = None) -> int:
    """
    有 avg_20d（20日均量）时：相对均量百分比评分，-25%→20，+25%→90，0%→55。
    无均量时：绝对阈值兜底（1.5万–3.8万亿≈15000–38000亿，2.7万≈55分）。
    """
    yi = float(yi or 0)
    if avg_20d and avg_20d > 0:
        pct = (yi - avg_20d) / avg_20d * 100
        return _linear_high(pct, lo=-25.0, hi=25.0)
    return _linear_high(yi, lo=15000.0, hi=38000.0)


def score_volume_intraday(amount_raw: float, vol_pct: Optional[float] = None) -> int:
    """盘中量能：优先同时刻同比；无对比时不使用全天阈值压分。"""
    if vol_pct is not None:
        # lo=-10% → 20  hi=15% → 90  mid=2.5% ≈ 55
        return _linear_high(float(vol_pct), lo=-10.0, hi=15.0)
    if float(amount_raw or 0) > 0:
        return SCORE_NEUTRAL
    return SCORE_NEUTRAL


def score_advance_breadth(adv: int, dec: int) -> int:
    adv, dec = int(adv or 0), int(dec or 0)
    total = adv + dec
    if adv <= 0 or dec <= 0 or total < 500:
        return SCORE_NEUTRAL
    ratio = adv / total * 100  # 转为百分比
    # lo=26% → 20  hi=75% → 90  boundary=40%→40
    return _linear_high(ratio, lo=26.0, hi=75.0)


def score_top10_avg_chg(chg: float) -> int:
    # lo=-1.2% → 20  hi=1.2% → 90  mid=0% → 55
    return _linear_high(float(chg or 0), lo=-1.2, hi=1.2)


def score_sse_index(chg: float) -> int:
    # 昨日涨停指数均涨幅：lo=-5%（大面）→20，hi=8%（大部分续板）→90，mid≈2%→55
    return _linear_high(float(chg or 0), lo=-5.0, hi=8.0)


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

    top10_chg = m.get("top10_avg_chg")
    multi_board = m.get("multi_board_count")
    try:
        top10_f = float(top10_chg) if top10_chg is not None else None
    except (TypeError, ValueError):
        top10_f = None

    seal_score = score_seal(float(seal or 0))
    break_score = score_break_rate(float(break_r or 0))
    out: dict[str, int] = {
        "height": score_height(int(max_board or 0)),
        "limitUp": score_limit_up(int(limit_up or 0)),
        "seal": seal_score,
        "promote": score_promote(float(promote or 0)),
        "limitDown": score_limit_down(int(limit_down or 0)),
        "break": break_score,
        "sealQuality": round((seal_score + break_score) / 2),
        "oneWord": score_one_word(int(one_word or 0)),
        "volume": score_volume_yi(float(vol_yi or 0), avg_20d=m.get("volume_20d_avg")),
    }
    if int(adv or 0) > 0 and int(dec or 0) > 0 and int(adv or 0) + int(dec or 0) >= 500:
        out["advance"] = score_advance_breadth(int(adv), int(dec))
    if top10_f is not None:
        out["top10AvgChg"] = score_top10_avg_chg(top10_f)
    if multi_board is not None:
        out["continuationDepth"] = score_continuation_depth(int(multi_board), int(limit_up or 0))
    high_cont = m.get("high_board_promote_continued")
    high_total = m.get("high_board_promote_total")
    if high_cont is not None and high_total is not None and int(high_total or 0) > 0:
        out["highBoardPromote"] = score_high_board_promote(int(high_cont), int(high_total))
    sc = m.get("sector_concentration")
    if sc:
        out["sectorConcentration"] = score_sector_concentration(
            float(sc.get("top3Ratio") or 0), int(sc.get("total") or 0)
        )
    return out


def _weighted_auction_avg(scores: dict[str, int]) -> float:
    """竞价块加权平均：接力信号（溢价/涨幅）权重更高。"""
    weighted = 0.0
    total_w = 0.0
    for key, w in W_AUCTION.items():
        if key in scores:
            weighted += scores[key] * w
            total_w += w
    if total_w <= 0:
        return float(SCORE_NEUTRAL)
    return weighted / total_w


def _weighted_yesterday_avg(scores: dict[str, int]) -> float:
    """昨日块加权平均：leading indicators 权重更高；optional 项有数据时纳入并归一化。"""
    all_weights = {**W_YESTERDAY, **W_YESTERDAY_OPT}
    weighted = 0.0
    total_w = 0.0
    for key, w in all_weights.items():
        if key in scores:
            weighted += scores[key] * w
            total_w += w
    if total_w <= 0:
        return float(SCORE_NEUTRAL)
    return weighted / total_w


def _score_contributions(scores: dict[str, int]) -> dict[str, float]:
    all_weights = {**W_YESTERDAY, **W_YESTERDAY_OPT}
    total_w = sum(w for key, w in all_weights.items() if key in scores)
    if total_w <= 0:
        return {}
    return {
        key: round(scores[key] * weight / total_w, 2)
        for key, weight in all_weights.items()
        if key in scores
    }


def _score_data_quality(scores: dict[str, int]) -> dict:
    all_weights = {**W_YESTERDAY, **W_YESTERDAY_OPT}
    available = sum(weight for key, weight in all_weights.items() if key in scores)
    total = sum(all_weights.values())
    return {
        "availableWeight": round(available, 2),
        "totalWeight": round(total, 2),
        "completeness": round(available / total, 3) if total else 0,
        "missing": [key for key in all_weights if key not in scores],
    }


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
    top10 = snap.get("top10_avg_live")
    promote = snap.get("promote_live")
    break_r = snap.get("break_live")
    high_board_chg = snap.get("high_board_chg_live")

    if ratio is not None:
        # lo=34% → 20  hi=66% → 90
        breadth_s = _linear_high(float(ratio), lo=34.0, hi=66.0)
    elif adv > 0 and dec > 0 and adv + dec >= 500:
        breadth_s = _linear_high(adv / (adv + dec) * 100, lo=34.0, hi=66.0)
    else:
        breadth_s = SCORE_NEUTRAL

    try:
        top10_f = float(top10) if top10 is not None else None
    except (TypeError, ValueError):
        top10_f = None

    out = {
        # lo=0 → 20  hi=70 → 90  mid=35 → 55
        "limitUpLive": _linear_high(float(lu), lo=0, hi=70),
        # lo=8（少）→ 90  hi=42（多）→ 20  mid=25 → 55
        "limitDownLive": _linear_low(float(ld), lo=8.0, hi=42.0),
    }
    if sse is not None:
        out["sseIndex"] = score_sse_index(float(sse))
    if ratio is not None or (adv > 0 and dec > 0 and adv + dec >= 500):
        out["upRatio"] = breadth_s
    if vol_pct is not None:
        out["marketVolumeLive"] = score_volume_intraday(amt, vol_pct)
    if top10_f is not None:
        out["top10AvgChgLive"] = score_top10_avg_chg(top10_f)
    if promote is not None:
        out["promoteLive"] = score_promote(float(promote))
    if break_r is not None:
        out["breakLive"] = score_break_rate(float(break_r))
    if high_board_chg is not None:
        # -5% 及以下为强退潮，+9% 及以上接近续板强度。
        out["highBoardChgLive"] = _linear_high(float(high_board_chg), lo=-5.0, hi=9.0)
    return out


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
    now = now or bj_now()
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
        auc_avg = _weighted_auction_avg(_score_auction_block(auction, metrics))
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

    out: dict[str, int] = {}
    if one_word is not None:
        out["auctionOneWord"] = _linear_high(float(one_word), lo=0, hi=8)
    if vol_yi is not None:
        out["auctionVolume"] = _linear_high(float(vol_yi), lo=190.0, hi=450.0)
    if first_chg is not None:
        out["yesterdayFirst"] = _linear_high(first_chg, lo=-2.0, hi=2.0)
    if multi_chg is not None:
        out["yesterdayMulti"] = _linear_high(multi_chg, lo=-3.0, hi=1.0)
    if recent_chg is not None:
        out["recentMulti"] = _linear_high(recent_chg, lo=-2.5, hi=2.5)
    if top10_chg is not None:
        out["top10AuctionChg"] = _linear_high(top10_chg, lo=-1.2, hi=1.2)
    return out


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


# ── 分级风险系统 ──────────────────────────────────────────────

def _collect_weak_reasons(
    y: dict[str, int],
    metrics: dict,
) -> list[str]:
    """收集偏弱信号原因。Leading indicators 使用更高阈值 _SIGNAL_WEAK_PRIMARY=45。"""
    reasons = []
    high_cont = metrics.get("high_board_promote_continued")
    high_total = metrics.get("high_board_promote_total")
    if (
        high_cont is not None
        and high_total is not None
        and int(high_total or 0) >= 3
        and y.get("highBoardPromote", 99) < _SIGNAL_WEAK_PRIMARY
    ):
        reasons.append(f"高位板晋级仅{int(high_cont)}/{int(high_total)}")
    # ── leading indicators（阈值 45）──────────────────────────
    if y.get("promote", 99) < _SIGNAL_WEAK_PRIMARY:
        reasons.append(f"昨日涨停股今日晋级率仅{metrics.get('promote_rate', 0):.0f}%")
    if y.get("break", 99) < _SIGNAL_WEAK_PRIMARY:
        reasons.append(f"炸板率{metrics.get('break_rate', 0):.0f}%偏高")
    if y.get("seal", 99) < _SIGNAL_WEAK_PRIMARY:
        reasons.append(f"封板率{metrics.get('seal_rate', 0):.0f}%偏低")
    if y.get("continuationDepth", 99) < _SIGNAL_WEAK_PRIMARY:
        mb = int(metrics.get("multi_board_count") or 0)
        lu = int(metrics.get("limit_up_count") or 1)
        reasons.append(f"连板占比仅{mb}/{lu}（接力深度偏弱）")
    sc = (metrics.get("sector_concentration") or {})
    if y.get("sectorConcentration", 99) < _SIGNAL_WEAK_PRIMARY and sc.get("total", 0) >= 10:
        reasons.append(f"板块集中度偏低（前三板块占比{sc.get('top3Ratio', 0):.0f}%）")
    # ── secondary indicators（阈值 40）───────────────────────
    if y.get("limitUp", 99) < _SIGNAL_WEAK:
        reasons.append(f"涨停仅{metrics.get('limit_up_count', 0)}只")
    if y.get("height", 99) < _SIGNAL_WEAK:
        reasons.append(f"最高连板仅{metrics.get('max_board', 0)}板")
    if y.get("advance", 99) < _SIGNAL_WEAK:
        adv = int(metrics.get("advance_count") or 0)
        dec = int(metrics.get("decline_count") or 0)
        if adv + dec >= 50:
            reasons.append(f"上涨家数占比偏低（涨{adv}/跌{dec}）")
    top10 = metrics.get("top10_avg_chg")
    if top10 is not None and y.get("top10AvgChg", 99) < _SIGNAL_WEAK:
        reasons.append(f"成交额前10平均涨幅仅{float(top10):.2f}%")
    return reasons


def _baseline_risk_gate(metrics: dict) -> str:
    """龙空龙硬风控：高位核心集体失败时，不允许总分掩盖风险。"""
    continued = metrics.get("high_board_promote_continued")
    total = metrics.get("high_board_promote_total")
    if continued is None or total is None:
        return "none"
    continued, total = int(continued or 0), int(total or 0)
    if total >= 5 and continued == 0:
        return "critical"
    if total >= 3 and continued == 0:
        return "warning"
    return "none"


def _collect_live_weak_reasons(
    live_scores: dict[str, int],
    auc_scores: dict[str, int],
    metrics: dict,
) -> list[str]:
    """盘中分走弱原因（含竞价 6 项）"""
    reasons = []
    m = metrics or {}
    if auc_scores.get("auctionOneWord", 99) < _SIGNAL_WEAK and auc_scores.get("yesterdayFirst", 99) < _SIGNAL_WEAK:
        reasons.append("竞价接力偏弱")
    if auc_scores.get("recentMulti", 99) < _SIGNAL_WEAK:
        reasons.append("连板竞价溢价不足")
    if live_scores.get("limitDownLive", 99) < _SIGNAL_WEAK:
        reasons.append("实时跌停偏多")
    if live_scores.get("breakLive", 99) < _SIGNAL_WEAK:
        break_rate = m.get("break_live")
        if break_rate is None:
            break_rate = m.get("break_rate", 0)
        reasons.append(f"实时炸板率{float(break_rate or 0):.0f}%偏高")
    return reasons


def _promote_reason_text(rate: float) -> str:
    return f"昨日涨停股今日晋级率仅{float(rate):.0f}%"


def reconcile_live_risk_overrides(
    risk_items: list,
    empty_reasons: list,
    *,
    promote_live: Optional[float] = None,
    break_live: Optional[float] = None,
) -> tuple[list, list, float]:
    """
    盘中用实时晋级率/炸板率刷新仓位主因文案与风险权重。
    基准分仍用昨日收盘口径，但「昨日涨停股今日晋级率」应随盘中更新。
    """
    items = [dict(x) for x in (risk_items or [])]
    reasons = list(empty_reasons or [])
    promote_prefix = "昨日涨停股今日晋级率仅"

    if promote_live is not None:
        rate = float(promote_live)
        promote_score = score_promote(rate)
        new_reason = _promote_reason_text(rate)
        if promote_score >= _SIGNAL_WEAK_PRIMARY:
            items = [x for x in items if x.get("key") != "promote"]
            reasons = [r for r in reasons if promote_prefix not in r]
        else:
            for item in items:
                if item.get("key") == "promote":
                    item["reason"] = new_reason
            reasons = [new_reason if promote_prefix in r else r for r in reasons]

    if break_live is not None:
        rate = float(break_live)
        break_score = score_break_rate(rate)
        break_prefixes = ("实时炸板率", "炸板率")
        new_break_reason = f"实时炸板率{rate:.0f}%偏高"
        if break_score >= _SIGNAL_WEAK_PRIMARY:
            items = [x for x in items if x.get("key") not in ("breakLive", "break")]
            reasons = [r for r in reasons if not any(p in r for p in break_prefixes)]
        else:
            for item in items:
                reason = str(item.get("reason") or "")
                if item.get("key") in ("breakLive", "break") or "炸板率" in reason:
                    item["reason"] = new_break_reason
            reasons = [
                new_break_reason if any(p in r for p in break_prefixes) else r
                for r in reasons
            ]

    risk_score = sum(float(x.get("weight") or 0) for x in items)
    return items, reasons, risk_score


def _risk_items(y: dict[str, int], metrics: dict) -> list[dict]:
    """按独立风险主题加权，避免封板率与炸板率等相关指标重复计量。"""
    items = []

    def add(key: str, weight: float, reason: str) -> None:
        items.append({"key": key, "weight": weight, "reason": reason})

    high_cont = metrics.get("high_board_promote_continued")
    high_total = metrics.get("high_board_promote_total")
    if high_cont is not None and high_total is not None and int(high_total or 0) >= 3:
        if y.get("highBoardPromote", 99) < _SIGNAL_WEAK_PRIMARY:
            add("highBoardFailure", 3.0, f"高位板晋级仅{int(high_cont)}/{int(high_total)}")
    if y.get("promote", 99) < _SIGNAL_WEAK_PRIMARY:
        add("promote", 2.0, f"昨日涨停股今日晋级率仅{metrics.get('promote_rate', 0):.0f}%")
    if y.get("sealQuality", 99) < _SIGNAL_WEAK_PRIMARY:
        add(
            "sealQuality",
            2.0,
            f"封板质量偏弱（封板率{metrics.get('seal_rate', 0):.0f}% / 炸板率{metrics.get('break_rate', 0):.0f}%）",
        )
    if y.get("continuationDepth", 99) < _SIGNAL_WEAK_PRIMARY:
        add(
            "continuationDepth",
            1.0,
            f"连板占比仅{int(metrics.get('multi_board_count') or 0)}/{int(metrics.get('limit_up_count') or 1)}",
        )
    sc = metrics.get("sector_concentration") or {}
    if y.get("sectorConcentration", 99) < _SIGNAL_WEAK_PRIMARY and sc.get("total", 0) >= 10:
        add("sectorConcentration", 0.5, f"前三板块占比仅{sc.get('top3Ratio', 0):.0f}%")
    if y.get("limitUp", 99) < _SIGNAL_WEAK:
        add("limitUp", 1.0, f"涨停仅{metrics.get('limit_up_count', 0)}只")
    if y.get("height", 99) < _SIGNAL_WEAK:
        add("height", 1.0, f"最高连板仅{metrics.get('max_board', 0)}板")
    if y.get("advance", 99) < _SIGNAL_WEAK:
        adv = int(metrics.get("advance_count") or 0)
        dec = int(metrics.get("decline_count") or 0)
        if adv + dec >= 50:
            add("breadth", 1.0, f"上涨家数占比偏低（涨{adv}/跌{dec}）")
    top10 = metrics.get("top10_avg_chg")
    if top10 is not None and y.get("top10AvgChg", 99) < _SIGNAL_WEAK:
        add("top10AvgChg", 1.0, f"成交额前10平均涨幅仅{float(top10):.2f}%")
    return items


def _calc_risk_level(risk_score: float, score: int) -> str:
    """根据加权风险分和情绪分确定最终风险等级。"""
    if score <= 30 or risk_score >= 7:
        return "critical"
    if score <= 40 or risk_score >= 4:
        return "warning"
    if score <= 45 or risk_score >= 1:
        return "caution"
    return "none"


def _risk_multiplier_for_position(risk_level: str, score: int) -> float:
    """warning 分档：展示分≥50 为结构性风险，<50 为综合走弱。"""
    if risk_level == "critical":
        return 0.0
    if risk_level == "warning":
        if int(score or 0) >= DISPLAY_LONGKONG_THRESHOLD:
            return WARNING_MULT_STRUCTURAL
        return WARNING_MULT_WEAK
    return RISK_MULTIPLIERS.get(risk_level, 1.0)


def _apply_risk_to_position(position: int, risk_level: str, score: int = 0) -> int:
    mult = _risk_multiplier_for_position(risk_level, score)
    return _round_position(position * mult)


def _base_position_from_score(score: int) -> int:
    """连续情绪仓位曲线：30 分以下为 0，高分可达 100%。"""
    raw = max(0, (int(score or 0) - POSITION_SCORE_BASE) * POSITION_SCORE_SLOPE)
    return _round_position(max(0, min(POSITION_SCORE_CAP, raw)))


def _final_position_from_components(
    base_position: int,
    risk_level: str,
    score: int,
    volatility_multiplier: float,
) -> int:
    """风险与波动一次 round，避免双重 floor 额外降档。"""
    mult = _risk_multiplier_for_position(risk_level, score)
    return _round_position(base_position * mult * float(volatility_multiplier or 1.0))


def _round_position(value: float) -> int:
    """仓位统一到 10% 档，避免输出缺乏可靠性的个位数建议。"""
    return max(0, min(100, int(float(value) / 10 + 0.5) * 10))


def _floor_position(value: float) -> int:
    """风险调整采用保守向下取整，确保降档确实降低暴露。"""
    return max(0, min(100, int(float(value) // 10) * 10))


def _volatility_proxy(metrics: dict) -> dict:
    """用现有市场压力指标构造波动代理；它不是统计历史波动率。"""
    metrics = metrics or {}
    stress = 0
    reasons = []
    index_chg = metrics.get("index_chg")
    top10 = metrics.get("top10_avg_chg")

    if index_chg is not None and abs(float(index_chg)) >= 3:
        stress += 2
        reasons.append("指数波动较大")
    elif index_chg is not None and abs(float(index_chg)) >= 1.5:
        stress += 1
        reasons.append("指数波动偏大")
    if top10 is not None and abs(float(top10)) >= 4:
        stress += 2
        reasons.append("成交额前10波动较大")
    elif top10 is not None and abs(float(top10)) >= 2:
        stress += 1
        reasons.append("成交额前10波动偏大")

    multiplier = VOLATILITY_MULT_HIGH if stress >= 3 else VOLATILITY_MULT_MID if stress >= 1 else 1.0
    return {"score": stress, "multiplier": multiplier, "reasons": reasons}


def _stabilize_position(
    target: int,
    *,
    previous_position: Optional[int] = None,
    increase_confirmations: int = 0,
    score_mode: str = "baseline",
    critical: bool = False,
) -> tuple[int, int, str]:
    """限制仓位跳变；盘中只降不升，非盘中改善确认两次后再升仓。"""
    target = _round_position(target)
    if previous_position is None:
        return target, 0, "initial"
    previous = _round_position(previous_position)
    if critical:
        return 0, 0, "critical"
    if target < previous:
        return max(target, previous - 10), 0, "reduced"
    if target == previous:
        return previous, 0, "unchanged"
    if score_mode == "live":
        if previous > 0 and target > previous:
            return previous, 0, "live_hold"
        return target, 0, "initial"
    confirmations = int(increase_confirmations or 0) + 1
    if confirmations < 2:
        return previous, confirmations, "confirming"
    return min(target, previous + 10), 0, "increased"


def calc_sentiment(
    metrics: dict,
    *,
    auction: Optional[list] = None,
    grid9: Optional[list] = None,
) -> dict:
    """
    基准情绪分 0–100（T 日 9:00 前口径：昨日，不含竞价）。
    auction 参数保留兼容，不参与基准分；竞价计分见 calc_live_score。
    """
    metrics = metrics or {}
    y_scores = _score_yesterday_block(metrics, grid9)
    y_avg = _weighted_yesterday_avg(y_scores)

    a_scores: dict[str, int] = {}

    if _has_auction_data(auction):
        a_scores = _score_auction_block(auction, metrics)

    score = round(y_avg * W_YESTERDAY_ONLY)
    mode = "yesterday_only"

    score = max(0, min(100, score))

    if score >= 90:
        level, color, signal = "极度亢奋", "#CF1322", "强"
    elif score >= 80:
        level, color, signal = "高潮", "#FF4D4F", "强"
    elif score >= 60:
        level, color, signal = "偏乐观", "#FF4D4F", "强"
    elif score >= 50:
        level, color, signal = "中性", "#FAAD14", "中"
    elif score >= 40:
        level, color, signal = "偏谨慎", "#FA8C16", "弱"
    elif score >= 30:
        level, color, signal = "偏冷", "#38BDF8", "弱"
    else:
        level, color, signal = "冰点", "#1890FF", "极弱"

    risk_items = _risk_items(y_scores, metrics)
    empty_reasons = [item["reason"] for item in risk_items]
    risk_score = sum(float(item["weight"]) for item in risk_items)
    risk_level = _calc_risk_level(risk_score, score)
    gate_level = _baseline_risk_gate(metrics)
    levels = ("none", "caution", "warning", "critical")
    risk_level = levels[max(levels.index(risk_level), levels.index(gate_level))]
    if gate_level == "critical":
        risk_items.insert(0, {"key": "hardGate", "weight": 7.0, "reason": "高位核心集体晋级失败"})
        risk_score = max(risk_score, 7.0)
    elif gate_level == "warning":
        risk_items.insert(0, {"key": "hardGate", "weight": 4.0, "reason": "高位核心晋级失败"})
        risk_score = max(risk_score, 4.0)
    volatility = _volatility_proxy(metrics)
    base_position = _base_position_from_score(score)
    position = _final_position_from_components(
        base_position, risk_level, score, volatility["multiplier"]
    )
    empty_warning = risk_level == "critical"

    return {
        "score": score,
        "scoreVersion": SCORE_VERSION,
        "level": level,
        "levelColor": color,
        "longkongSignal": signal,
        "positionPercent": position,
        "positionTargetPercent": position,
        "basePositionPercent": base_position,
        "riskMultiplier": _risk_multiplier_for_position(risk_level, score),
        "volatilityMultiplier": volatility["multiplier"],
        "volatilityProxy": volatility,
        "positionReasons": [item["reason"] for item in risk_items] + volatility["reasons"],
        "positionConfirmations": 0,
        "positionStability": "baseline",
        "positionLabel": "",
        "emptyWarning": empty_warning,
        "riskLevel": risk_level,
        "riskScore": round(risk_score, 1),
        "riskItems": risk_items,
        "emptyReasons": empty_reasons,
        "scoreMode": mode,
        "subScores": {
            "yesterday": y_scores,
            "auction": a_scores,
            "yesterdayAvg": round(y_avg, 1),
            "auctionAvg": round(_weighted_auction_avg(a_scores), 1) if a_scores else None,
            "contributions": _score_contributions(y_scores),
            "dataQuality": _score_data_quality(y_scores),
        },
    }


def longkong_signal_from_score(score: int) -> str:
    """龙空信号档位（随展示分）"""
    score = int(score or 0)
    if score >= 60:
        return "强"
    if score >= 50:
        return "中"
    if score >= 30:
        return "弱"
    return "极弱"


def longkong_state(
    score: int,
    *,
    empty_warning: bool = False,
    risk_level: str = "none",
    sub_scores: Optional[dict] = None,
    intraday_sub_scores: Optional[dict] = None,
) -> dict:
    """
    龙空龙短线状态：龙>75 / 较强60–75 / 较弱40–60 / 空<40。
    风险等级会压低状态上限：
      critical → 强制为空
      warning  → 最高为较弱（即使分数在较强/龙区间）
      caution  → 最高为较强（即使分数在龙区间）
    """
    del sub_scores, intraday_sub_scores
    score = int(score or 0)

    if empty_warning or risk_level == "critical":
        state, label = "empty", "空"
        desc = "风险偏高，宜控节奏"
    elif score > 75:
        state, label = "dragon", "龙"
        desc = "接力结构较强"
    elif score >= 60:
        state, label = "repair", "较强"
        desc = "有较强迹象，待确认"
    elif score >= 40:
        state, label = "retreat", "较弱"
        desc = "接力偏弱"
    else:
        state, label = "empty", "空"
        desc = "风险偏高，宜控节奏"

    # 风险等级压制：warning 最高较弱，caution 最高较强
    _order = ("empty", "retreat", "repair", "dragon")
    if risk_level == "warning":
        cap = "retreat"
    elif risk_level == "caution":
        cap = "repair"
    else:
        cap = "dragon"
    if _order.index(state) > _order.index(cap):
        state = cap
        if cap == "retreat":
            label, desc = "较弱", "弱信号较多，接力偏弱"
        else:
            label, desc = "较强", "有较强迹象，注意风险"

    return {
        "state": state,
        "label": label,
        "desc": desc,
    }


def apply_display_longkong(
    baseline_sentiment: dict,
    display_score: int,
    *,
    score_mode: str = "baseline",
    previous_position: Optional[int] = None,
    increase_confirmations: int = 0,
    live_snap: Optional[dict] = None,
) -> dict:
    """
    龙空信号 / riskLevel / emptyWarning 随展示分更新。
    展示分 < 50 追加盘中或综合走弱风险提示。
    """
    baseline_sentiment = baseline_sentiment or {}
    baseline_empty = bool(baseline_sentiment.get("emptyWarning"))
    baseline_score = int(baseline_sentiment.get("score") or 0)
    reasons = list(baseline_sentiment.get("emptyReasons") or [])
    risk_items = list(baseline_sentiment.get("riskItems") or [])
    risk_score = float(baseline_sentiment.get("riskScore") or 0)
    live_snap = live_snap or {}
    live_promote = live_snap.get("promote_live")
    live_break = live_snap.get("break_live")
    has_live_risk = (
        score_mode == "live"
        and (live_promote is not None or live_break is not None)
    )
    if has_live_risk:
        risk_items, reasons, risk_score = reconcile_live_risk_overrides(
            risk_items,
            reasons,
            promote_live=live_promote,
            break_live=live_break,
        )
        baseline_risk = _calc_risk_level(risk_score, baseline_score)
    else:
        baseline_risk = baseline_sentiment.get("riskLevel", "none")
    display_score = int(display_score or 0)

    display_risk = display_score < DISPLAY_LONGKONG_THRESHOLD
    if display_risk:
        if score_mode == "live":
            risk_reason = f"盘中情绪分{display_score}，低于{DISPLAY_LONGKONG_THRESHOLD}分"
        else:
            risk_reason = f"综合情绪分{display_score}，低于{DISPLAY_LONGKONG_THRESHOLD}分"
        if risk_reason not in reasons:
            reasons.insert(0, risk_reason)
            display_weight = 2.0 if display_score < 40 else 1.0
            risk_items.insert(0, {"key": "displayScore", "weight": display_weight, "reason": risk_reason})
            risk_score += display_weight

    # 综合展示分重新计算风险等级
    risk_level = _calc_risk_level(risk_score, display_score)
    # 取基准与展示风险的较高档
    _levels = ("none", "caution", "warning", "critical")
    risk_level = _levels[max(_levels.index(baseline_risk), _levels.index(risk_level))]

    empty_warning = baseline_empty or risk_level == "critical" or display_score <= 30

    base_position = _base_position_from_score(baseline_score)
    volatility = baseline_sentiment.get("volatilityProxy") or {"score": 0, "multiplier": 1.0, "reasons": []}
    volatility_multiplier = float(volatility.get("multiplier") or 1.0)
    target_position = _final_position_from_components(
        base_position, risk_level, baseline_score, volatility_multiplier
    )
    if empty_warning:
        target_position = 0
    position, confirmations, stability = _stabilize_position(
        target_position,
        previous_position=previous_position,
        increase_confirmations=increase_confirmations,
        score_mode=score_mode,
        critical=empty_warning,
    )

    return {
        "longkongSignal": longkong_signal_from_score(display_score),
        "emptyWarning": empty_warning,
        "riskLevel": risk_level,
        "riskScore": round(risk_score, 1),
        "riskItems": risk_items,
        "emptyReasons": reasons,
        "positionPercent": position,
        "positionTargetPercent": target_position,
        "basePositionPercent": base_position,
        "riskMultiplier": _risk_multiplier_for_position(risk_level, baseline_score),
        "volatilityMultiplier": volatility_multiplier,
        "volatilityProxy": volatility,
        "positionReasons": [item.get("reason", "") for item in risk_items if item.get("reason")]
        + list(volatility.get("reasons") or []),
        "positionConfirmations": confirmations,
        "positionStability": stability,
        "positionLabel": "",
    }


def strategy_note_for_home(
    baseline_sentiment: dict,
    display_score: int,
    *,
    score_mode: str,
    longkong: dict,
) -> str:
    risk = longkong.get("riskLevel", "none")
    if risk == "none":
        if display_score >= 60:
            return "综合情绪偏强，盘面结构活跃"
        return "综合昨日收盘与外围，更新今日情绪参考"
    if risk == "caution":
        return "情绪出现弱信号，建议轻仓观察"
    if (
        score_mode == "live"
        and display_score < DISPLAY_LONGKONG_THRESHOLD
        and not baseline_sentiment.get("emptyWarning")
    ):
        return "盘中情绪走弱，展示分低于50（龙空风险提示）"
    return "综合情绪偏弱，个人龙空信号触发（作者复盘）"


def position_desc(score: int, empty_warning: bool, risk_level: str = "none") -> str:
    score = int(score or 0)
    if risk_level == "critical" or (empty_warning and score <= 30):
        return "综合情绪极弱，盘面偏冷"
    if empty_warning and score < DISPLAY_LONGKONG_THRESHOLD:
        return "综合情绪走弱，展示分低于50，宜控节奏"
    if risk_level == "warning":
        if score < DISPLAY_LONGKONG_THRESHOLD:
            return "综合情绪走弱，展示分低于50，宜控节奏"
        return "接力结构偏弱，宜控节奏"
    if empty_warning:
        return "综合情绪偏弱，龙空风险提示"
    if risk_level == "caution":
        return "情绪出现弱信号，建议轻仓观察"
    if score >= 60:
        return "综合情绪偏强，接力结构尚可"
    if score >= 50:
        return "综合情绪中性偏暖，注意分化"
    if score >= 40:
        return "综合情绪偏谨慎，短线结构一般"
    if score >= 30:
        return "综合情绪偏冷，耐心等待较强"
    return "综合情绪偏弱，宜控节奏"
