# -*- coding: utf-8 -*-
"""盘中实时情绪：数据抓取、指标块、盘中分"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from config import bj_now
from fetcher import (
    _fetch_market_breadth_live,
    _fetch_sse_chg_tencent,
    _parse_legu_stat_date,
    _parse_market_activity_df,
    _spot_market_amount_yi,
    _trend,
    date_str,
    fetch_high10_stats,
    fetch_intraday_board_stats,
    fetch_market_activity,
    fetch_ref_volume_at_same_time,
    fetch_ref_volume_prev_label,
    fetch_sse_index_change,
    get_recent_trade_dates,
    record_intraday_volume_snapshot,
)
from sentiment import (
    calc_live_score,
    score_intraday_block,
    _score_auction_block,
    _has_auction_data,
)


def is_trading_day(now: Optional[datetime] = None) -> bool:
    """是否 A 股交易日（不含时段）"""
    now = now or bj_now()
    if now.weekday() >= 5:
        return False
    today = date_str(now)
    dates = get_recent_trade_dates(3)
    return today in dates


def intraday_session_phase(now: Optional[datetime] = None) -> str:
    """off | waiting | live | closed | night"""
    now = now or bj_now()
    if not is_trading_day(now):
        return "off"
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 30:
        return "waiting"
    if hm <= 15 * 60:
        return "live"
    if hm >= 18 * 60:
        return "night"
    return "closed"


def is_intraday_session(now: Optional[datetime] = None) -> bool:
    """交易日 9:30–15:00 盘中时段"""
    return intraday_session_phase(now) == "live"


def is_intraday_pinned_window(now: Optional[datetime] = None) -> bool:
    """盘中板块置顶时段：交易日 9:00–15:30"""
    now = now or bj_now()
    if not is_trading_day(now):
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


# 交易时段完整顺序：盘中 → 龙空风控 → 竞价 → 昨日 → 外围
_TRADING_SECTION_ORDER = (
    "intraday",
    "longkongRisk",
    "auction",
    "yesterday",
    "peripheral",
)


def order_indicator_sections(sections: list, *, now: Optional[datetime] = None) -> list:
    """9:00–15:30 按交易时段顺序排列；非置顶时段仅盘中块沉底。"""
    if not sections:
        return sections
    if is_intraday_pinned_window(now):
        by_id = {sec.get("id"): sec for sec in sections if sec and sec.get("id")}
        ordered = [by_id[sid] for sid in _TRADING_SECTION_ORDER if sid in by_id]
        known = set(_TRADING_SECTION_ORDER)
        for sec in sections:
            sid = sec.get("id")
            if sid and sid not in known:
                ordered.append(sec)
        return ordered if ordered else sections
    intraday = None
    rest = []
    for sec in sections:
        if sec.get("id") == "intraday":
            intraday = sec
        else:
            rest.append(sec)
    if not intraday:
        return sections
    return rest + [intraday]


def _legu_live_counts() -> dict:
    """乐股实时：上涨/下跌/涨停/跌停 + 统计日期"""
    out = {
        "advance": 0,
        "decline": 0,
        "limit_up": 0,
        "limit_down": 0,
        "stat_d": "",
    }
    try:
        import akshare as ak

        df = ak.stock_market_activity_legu()
        parsed = _parse_market_activity_df(df)
        out["advance"] = int(parsed.get("advance") or 0)
        out["decline"] = int(parsed.get("decline") or 0)
        out["stat_d"] = _parse_legu_stat_date(df)
        if "item" in df.columns and "value" in df.columns:
            for _, row in df.iterrows():
                item = str(row.get("item", "")).strip()
                val = row.get("value")
                if item in ("涨停", "真实涨停"):
                    n = int(float(val or 0))
                    if n > out["limit_up"]:
                        out["limit_up"] = n
                if item in ("跌停", "真实跌停"):
                    n = int(float(val or 0))
                    if n > out["limit_down"]:
                        out["limit_down"] = n
    except Exception:
        pass
    if out["limit_up"] == 0 and out["limit_down"] == 0:
        act = fetch_market_activity()
        out["advance"] = out["advance"] or int(act.get("advance") or 0)
        out["decline"] = out["decline"] or int(act.get("decline") or 0)
    return out


def _resolve_prev_sse(ref_metrics: Optional[dict], ref_d: str = "") -> Optional[float]:
    """昨日收盘上证涨跌幅（对比列「昨」）"""
    ref_metrics = ref_metrics or {}
    val = ref_metrics.get("index_chg")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    ref_d = (ref_d or ref_metrics.get("date") or "").replace("-", "")[:8]
    if ref_d:
        return fetch_sse_index_change(ref_d)
    return None


def fetch_intraday_snapshot(ref_metrics: Optional[dict] = None, ref_d: str = "") -> dict:
    """拉取盘中实时快照（不写库）。对比基准均为昨日收盘 ref_metrics。"""
    ref_metrics = ref_metrics or {}
    if not ref_d:
        ref_d = (ref_metrics.get("date") or "").replace("-", "")[:8]
    today = date_str(bj_now())
    legu = _legu_live_counts()
    adv = int(legu.get("advance") or 0)
    dec = int(legu.get("decline") or 0)
    limit_up = int(legu.get("limit_up") or 0)
    limit_down = int(legu.get("limit_down") or 0)

    def _breadth_live_valid(a: int, d: int) -> bool:
        total = int(a or 0) + int(d or 0)
        return total >= 500 and int(a or 0) > 0 and int(d or 0) > 0

    if not _breadth_live_valid(adv, dec):
        adv2, dec2, stat_d = _fetch_market_breadth_live()
        if stat_d == today or _breadth_live_valid(adv2, dec2):
            adv, dec = adv2, dec2

    sse_chg = _fetch_sse_chg_tencent(today)
    amount_str, amount_raw = _spot_market_amount_yi()
    if amount_raw <= 0:
        act = fetch_market_activity()
        amount_str = act.get("amount") or "--"
        try:
            amount_raw = float(act.get("amount_raw") or 0)
        except (TypeError, ValueError):
            amount_raw = 0.0

    up_ratio = round(adv / (adv + dec) * 100, 1) if _breadth_live_valid(adv, dec) else None

    prev_adv = int(ref_metrics.get("advance_count") or 0)
    prev_dec = int(ref_metrics.get("decline_count") or 0)
    prev_limit_up = int(ref_metrics.get("limit_up_count") or 0)
    prev_limit_down = int(ref_metrics.get("limit_down_count") or 0)
    vol_prev_s, prev_vol = fetch_ref_volume_prev_label(ref_metrics, ref_d)
    prev_sse = _resolve_prev_sse(ref_metrics, ref_d)
    high10_info = fetch_high10_stats(ref_metrics, live=True)
    # 副指标「昨」列：优先用 ref 日归档的 high10，避免误取前日
    prev_high10 = int(ref_metrics.get("high10_count") or high10_info.get("prev_high10") or 0)
    board = fetch_intraday_board_stats(ref_d, ref_metrics, live=True)

    if amount_raw > 0:
        record_intraday_volume_snapshot(today, amount_raw)

    return {
        "sse_chg": sse_chg,
        "advance": adv,
        "decline": dec,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "amount": amount_str if amount_str not in ("", "--") else "--",
        "amount_raw": amount_raw,
        "up_ratio": up_ratio,
        "high10": int(high10_info.get("high10") or 0),
        "prev_high10": prev_high10,
        "high10_chg_pct": (
            round((int(high10_info.get("high10") or 0) - prev_high10) / prev_high10 * 100, 1)
            if int(high10_info.get("high10") or 0) and prev_high10
            else high10_info.get("high10_chg_pct")
        ),
        "prev_advance": prev_adv,
        "prev_decline": prev_dec,
        "prev_limit_up": prev_limit_up,
        "prev_limit_down": prev_limit_down,
        "prev_volume_raw": prev_vol if prev_vol and prev_vol > 0 else None,
        "prev_volume_label": vol_prev_s,
        "prev_sse_chg": prev_sse,
        "top10_avg_live": board.get("top10_avg_live"),
        "prev_top10_avg": board.get("prev_top10_avg"),
        "promote_live": board.get("promote_live"),
        "prev_promote": board.get("prev_promote"),
        "break_live": board.get("break_live"),
        "prev_break": board.get("prev_break"),
        "updated_at": bj_now().strftime("%H:%M"),
    }


def _prev_up_ratio(prev_adv, prev_dec) -> Optional[float]:
    if prev_adv is None or prev_dec is None:
        return None
    adv_i, dec_i = int(prev_adv or 0), int(prev_dec or 0)
    total = adv_i + dec_i
    if adv_i <= 0 or dec_i <= 0 or total < 500:
        return None
    return round(adv_i / total * 100, 1)


def _vol_pct(amount_raw: float, prev_vol: float) -> Optional[float]:
    if amount_raw > 0 and prev_vol > 0:
        return round((amount_raw - prev_vol) / prev_vol * 100, 1)
    return None


def _fmt_vol_value(amount_raw: float, prev_vol: float) -> str:
    if amount_raw <= 0:
        return "--"
    yi = round(amount_raw)
    pct = _vol_pct(amount_raw, prev_vol)
    if pct is not None:
        return f"{yi}亿 {pct:+.1f}%"
    return f"{yi}亿"


def _fmt_high10_value(count: int, chg_pct: Optional[float]) -> str:
    if not count:
        return "--"
    if chg_pct is not None:
        return f"{count} {chg_pct:+.1f}%"
    return str(count)


def _fmt_pct_val(val: Optional[float]) -> str:
    if val is None:
        return "--"
    return f"{float(val):+.2f}%"


def _fmt_rate_val(val: Optional[float]) -> str:
    if val is None:
        return "--"
    return f"{float(val):.0f}%"


def build_intraday_items(snap: dict) -> list:
    """盘中实时情绪 9 项（grid3）"""
    prev_lu = snap.get("prev_limit_up")
    prev_ld = snap.get("prev_limit_down")
    prev_vol = snap.get("prev_volume_raw")
    prev_sse = snap.get("prev_sse_chg")
    prev_adv = snap.get("prev_advance")
    prev_dec = snap.get("prev_decline")

    sse = snap.get("sse_chg")
    sse_val = f"{sse:+.2f}%" if sse is not None else "--"
    sse_prev = f"{float(prev_sse):+.2f}%" if prev_sse is not None else "--"

    ratio = snap.get("up_ratio")
    ratio_val = f"{ratio:.1f}%" if ratio is not None else "--"
    prev_ratio = _prev_up_ratio(prev_adv, prev_dec)

    lu = int(snap.get("limit_up") or 0)
    ld = int(snap.get("limit_down") or 0)
    amount_raw = float(snap.get("amount_raw") or 0)
    prev_vol_label = snap.get("prev_volume_label")
    prev_vol = float(snap.get("prev_volume_raw") or 0) if snap.get("prev_volume_raw") else 0.0
    prev_vol_f = prev_vol if prev_vol > 0 else 0.0
    vol_val = _fmt_vol_value(amount_raw, prev_vol_f)
    vol_prev = str(prev_vol_label) if prev_vol_label not in (None, "", "--") else (
        f"{round(prev_vol_f)}亿" if prev_vol_f > 0 else "--"
    )
    vol_pct = _vol_pct(amount_raw, prev_vol_f)

    high10 = int(snap.get("high10") or 0)
    prev_high10 = snap.get("prev_high10")
    high10_chg = snap.get("high10_chg_pct")
    high10_val = _fmt_high10_value(high10, high10_chg)
    high10_prev = str(int(prev_high10)) if prev_high10 is not None else "--"

    top10 = snap.get("top10_avg_live")
    prev_top10 = snap.get("prev_top10_avg")
    top10_val = _fmt_pct_val(top10)
    top10_prev = _fmt_pct_val(prev_top10) if prev_top10 is not None else "--"

    promote = snap.get("promote_live")
    prev_promote = snap.get("prev_promote")
    promote_val = _fmt_rate_val(promote)
    promote_prev = _fmt_rate_val(prev_promote) if prev_promote is not None else "--"

    break_r = snap.get("break_live")
    prev_break = snap.get("prev_break")
    break_val = _fmt_rate_val(break_r)
    break_prev = _fmt_rate_val(prev_break) if prev_break is not None else "--"

    def _item(key, label, value, yesterday, trend=None, up=None, **extra):
        row = {
            "key": key,
            "label": label,
            "value": str(value),
            "yesterday": str(yesterday) if yesterday not in (None, "") else "--",
            "prev": str(yesterday) if yesterday not in (None, "") else "--",
            "trend": trend or "flat",
        }
        if up is not None:
            row["up"] = up
        row.update(extra)
        return row

    return [
        _item(
            "sseIndex",
            "上证涨跌",
            sse_val,
            sse_prev,
            _trend(sse, prev_sse),
            up=(sse or 0) >= 0 if sse is not None else None,
        ),
        _item(
            "upRatio",
            "上涨占比",
            ratio_val,
            f"{prev_ratio:.1f}%" if prev_ratio is not None else "--",
            _trend(ratio, prev_ratio),
        ),
        _item(
            "limitUpLive",
            "实时涨停",
            str(lu) if lu else "--",
            str(prev_lu) if prev_lu is not None else "--",
            _trend(lu, prev_lu),
        ),
        _item(
            "limitDownLive",
            "实时跌停",
            str(ld) if ld else "--",
            str(prev_ld) if prev_ld is not None else "--",
            _trend(ld, prev_ld),
        ),
        _item(
            "marketVolumeLive",
            "全市量能",
            vol_val,
            vol_prev,
            _trend(vol_pct, 0) if vol_pct is not None else _trend(amount_raw, prev_vol_f if prev_vol_f else None),
            up=(vol_pct or 0) >= 0 if vol_pct is not None else None,
            chg_pct=vol_pct,
        ),
        _item(
            "high10Live",
            "10日新高",
            high10_val,
            high10_prev,
            _trend(high10, prev_high10 if prev_high10 else None),
            up=(high10_chg or 0) >= 0 if high10_chg is not None else None,
            chg_pct=high10_chg,
        ),
        _item(
            "top10AvgChgLive",
            "T-1成交额前10平均涨幅",
            top10_val,
            top10_prev,
            _trend(top10, prev_top10),
            up=(top10 or 0) >= 0 if top10 is not None else None,
        ),
        _item(
            "promoteLive",
            "晋级率",
            promote_val,
            promote_prev,
            _trend(promote, prev_promote),
        ),
        _item(
            "breakLive",
            "实时炸板率",
            break_val,
            break_prev,
            _trend(break_r, prev_break),
        ),
    ]


def build_intraday_placeholder_items(ref_metrics: Optional[dict] = None) -> list:
    """非盘中时段占位 9 项（对比昨日收盘）"""
    ref = ref_metrics or {}
    prev_adv = ref.get("advance_count")
    prev_dec = ref.get("decline_count")
    prev_lu = ref.get("limit_up_count")
    prev_ld = ref.get("limit_down_count")
    prev_sse = _resolve_prev_sse(ref, (ref.get("date") or "").replace("-", "")[:8])
    ref_d_s = (ref.get("date") or "").replace("-", "")[:8]
    vol_prev_s, prev_vol = fetch_ref_volume_prev_label(ref, ref_d_s)
    prev_high10 = ref.get("high10_count")
    prev_top10 = ref.get("top10_avg_chg")
    prev_promote = ref.get("promote_rate")
    prev_break = ref.get("break_rate")
    prev_ratio = _prev_up_ratio(prev_adv, prev_dec)

    def _item(key, label, prev_val=None, **extra):
        prev_s = str(prev_val) if prev_val not in (None, "") else "--"
        return {
            "key": key,
            "label": label,
            "value": "--",
            "yesterday": prev_s,
            "prev": prev_s,
            "trend": "flat",
            **extra,
        }

    sse_prev = f"{float(prev_sse):+.2f}%" if prev_sse is not None else "--"
    vol_prev = vol_prev_s if vol_prev_s not in ("", "--") else "--"
    return [
        _item("sseIndex", "上证涨跌", sse_prev),
        _item("upRatio", "上涨占比", f"{prev_ratio:.1f}%" if prev_ratio is not None else "--"),
        _item("limitUpLive", "实时涨停", str(prev_lu) if prev_lu is not None else "--"),
        _item("limitDownLive", "实时跌停", str(prev_ld) if prev_ld is not None else "--"),
        _item("marketVolumeLive", "全市量能", vol_prev),
        _item("high10Live", "10日新高", str(prev_high10) if prev_high10 is not None else "--"),
        _item(
            "top10AvgChgLive",
            "T-1成交额前10平均涨幅",
            _fmt_pct_val(float(prev_top10)) if prev_top10 is not None else "--",
        ),
        _item(
            "promoteLive",
            "晋级率",
            _fmt_rate_val(float(prev_promote)) if prev_promote is not None else "--",
        ),
        _item(
            "breakLive",
            "实时炸板率",
            _fmt_rate_val(float(prev_break)) if prev_break is not None else "--",
        ),
    ]


def build_intraday_closed_items(
    ref_metrics: Optional[dict] = None,
    prev_metrics: Optional[dict] = None,
) -> list:
    """收盘后展示当日最终盘面值，避免盘中块整块变成占位。"""
    ref = ref_metrics or {}
    prev = prev_metrics or {}
    ref_d = (ref.get("date") or "").replace("-", "")[:8]
    prev_d = (prev.get("date") or "").replace("-", "")[:8]
    adv = ref.get("advance_count")
    dec = ref.get("decline_count")
    ratio = _prev_up_ratio(adv, dec)
    sse = _resolve_prev_sse(ref, ref_d)
    if ref_d:
        try:
            today_d = date_str(bj_now())
            if ref_d == today_d:
                live_sse = _fetch_sse_chg_tencent(today_d)
                sse = live_sse if live_sse is not None else fetch_sse_index_change(ref_d)
            else:
                sse = fetch_sse_index_change(ref_d)
        except Exception:
            pass
    vol_label, _ = fetch_ref_volume_prev_label(ref, ref_d)
    prev_adv = prev.get("advance_count")
    prev_dec = prev.get("decline_count")
    prev_ratio = _prev_up_ratio(prev_adv, prev_dec)
    prev_sse = _resolve_prev_sse(prev, prev_d)
    if prev_d:
        try:
            prev_sse = fetch_sse_index_change(prev_d)
        except Exception:
            pass
    prev_vol_label, _ = fetch_ref_volume_prev_label(prev, prev_d)
    board = fetch_intraday_board_stats(ref_d, ref, live=True) if ref_d else {}
    top10_live = board.get("top10_avg_live")
    top10_prev = board.get("prev_top10_avg")
    if top10_prev is None and prev.get("top10_avg_chg") is not None:
        top10_prev = float(prev.get("top10_avg_chg"))

    def _item(key, label, value=None, prev_val="--"):
        value_s = str(value) if value not in (None, "") else "--"
        prev_s = str(prev_val) if prev_val not in (None, "") else "--"
        return {
            "key": key,
            "label": label,
            "value": value_s,
            "yesterday": prev_s,
            "prev": prev_s,
            "trend": "flat",
        }

    return [
        _item(
            "sseIndex",
            "上证涨跌",
            f"{float(sse):+.2f}%" if sse is not None else "--",
            f"{float(prev_sse):+.2f}%" if prev_sse is not None else "--",
        ),
        _item(
            "upRatio",
            "上涨占比",
            f"{ratio:.1f}%" if ratio is not None else "--",
            f"{prev_ratio:.1f}%" if prev_ratio is not None else "--",
        ),
        _item("limitUpLive", "实时涨停", ref.get("limit_up_count"), prev.get("limit_up_count")),
        _item("limitDownLive", "实时跌停", ref.get("limit_down_count"), prev.get("limit_down_count")),
        _item(
            "marketVolumeLive",
            "全市量能",
            vol_label if vol_label not in ("", "--") else ref.get("volume_amount"),
            prev_vol_label if prev_vol_label not in ("", "--") else prev.get("volume_amount"),
        ),
        _item("high10Live", "10日新高", ref.get("high10_count"), prev.get("high10_count")),
        _item(
            "top10AvgChgLive",
            "T-1成交额前10平均涨幅",
            _fmt_pct_val(float(top10_live))
            if top10_live is not None
            else (
                _fmt_pct_val(float(ref.get("top10_avg_chg")))
                if ref.get("top10_avg_chg") is not None
                else "--"
            ),
            _fmt_pct_val(float(top10_prev))
            if top10_prev is not None
            else (
                _fmt_pct_val(float(prev.get("top10_avg_chg")))
                if prev.get("top10_avg_chg") is not None
                else "--"
            ),
        ),
        _item(
            "promoteLive",
            "晋级率",
            _fmt_rate_val(float(ref.get("promote_rate"))) if ref.get("promote_rate") is not None else "--",
            _fmt_rate_val(float(prev.get("promote_rate"))) if prev.get("promote_rate") is not None else "--",
        ),
        _item(
            "breakLive",
            "实时炸板率",
            _fmt_rate_val(float(ref.get("break_rate"))) if ref.get("break_rate") is not None else "--",
            _fmt_rate_val(float(prev.get("break_rate"))) if prev.get("break_rate") is not None else "--",
        ),
    ]


def _live_blend_weight(now: Optional[datetime] = None) -> float:
    """
    盘中分在展示分中的权重。
    9:00–9:29 固定 30%；9:30 起线性升至 15:00 的 85%。
    """
    now = now or bj_now()
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60:
        return 0.0
    if hm > 15 * 60:
        return 0.0
    if hm < 9 * 60 + 30:
        return 0.30
    start, end = 9 * 60 + 30, 15 * 60
    w_start, w_end = 0.30, 0.85
    if hm >= end:
        return w_end
    t = (hm - start) / (end - start)
    return w_start + t * (w_end - w_start)


def is_live_score_window(now: Optional[datetime] = None) -> bool:
    """交易日 9:00–15:00，展示分可融合盘中分"""
    now = now or bj_now()
    if not is_trading_day(now):
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60


def calc_display_score(
    baseline_score: int,
    intraday_score: Optional[int],
    *,
    prev_baseline: Optional[int] = None,
    now: Optional[datetime] = None,
) -> tuple[int, str]:
    """
    返回 (展示分, scoreMode)。
    9:00 起若有盘中分（含竞价）则融合；收盘后回到基准分。
    prev_baseline：前一交易日基准分，用于计算趋势速度修正（±8 分上限）。
    """
    # 速度修正：相较前日基准的方向性加权，±8 分封顶，盘中不叠加（由盘中分承接）
    adjusted_baseline = baseline_score
    if prev_baseline is not None and (intraday_score is None or not is_live_score_window(now)):
        velocity = baseline_score - int(prev_baseline)
        kicker = max(-8, min(8, round(velocity * 0.25)))
        adjusted_baseline = max(0, min(100, baseline_score + kicker))

    if intraday_score is None or not is_live_score_window(now):
        return adjusted_baseline, "baseline"
    w = _live_blend_weight(now)
    if w <= 0:
        return adjusted_baseline, "baseline"
    blended = round(baseline_score * (1 - w) + int(intraday_score) * w)
    return max(0, min(100, blended)), "live"


def build_intraday_payload(
    ref_metrics: Optional[dict] = None,
    ref_d: str = "",
    *,
    auction: Optional[list] = None,
    prev_metrics: Optional[dict] = None,
) -> dict:
    """盘中块：items + intradayScore（含竞价）+ snap；交易日始终返回 items（非盘中为占位）"""
    if not ref_d and ref_metrics:
        ref_d = (ref_metrics.get("date") or "").replace("-", "")[:8]
    phase = intraday_session_phase()
    metrics = ref_metrics or {}
    now = bj_now()
    if phase in ("off", "night"):
        items = build_intraday_placeholder_items(ref_metrics)
        return {
            "items": items,
            "intradayScore": None,
            "snap": {},
            "active": False,
            "phase": phase,
        }
    if phase == "closed":
        items = build_intraday_closed_items(ref_metrics, prev_metrics)
        return {
            "items": items,
            "intradayScore": None,
            "snap": {},
            "active": False,
            "phase": phase,
        }
    auc_scores = _score_auction_block(auction, metrics) if _has_auction_data(auction) else {}
    if phase == "live":
        snap = fetch_intraday_snapshot(ref_metrics, ref_d=ref_d)
        items = build_intraday_items(snap)
        intraday_score = calc_live_score(snap, auction=auction, metrics=metrics, now=now)
        return {
            "items": items,
            "intradayScore": intraday_score,
            "intradaySubScores": {
                "live": score_intraday_block(snap),
                "auction": auc_scores,
            },
            "snap": snap,
            "active": True,
            "phase": phase,
            "updatedAt": snap.get("updated_at"),
        }
    items = build_intraday_placeholder_items(ref_metrics)
    intraday_score = calc_live_score({}, auction=auction, metrics=metrics, now=now)
    return {
        "items": items,
        "intradayScore": intraday_score,
        "intradaySubScores": {
            "live": {},
            "auction": auc_scores,
        },
        "snap": {},
        "active": False,
        "phase": phase,
    }


import os
import time
from typing import Any

_intraday_read_cache: dict[str, Any] = {"key": "", "at": 0.0, "payload": None}


def _intraday_read_ttl_sec() -> int:
    return int(os.getenv("INTRADAY_READ_TTL_SEC", "90"))


def invalidate_intraday_read_cache() -> None:
    _intraday_read_cache.update({"key": "", "at": 0.0, "payload": None})


def get_intraday_payload_cached(
    metrics: dict,
    *,
    ref_d: str,
    auction: Optional[list] = None,
    prev_metrics: Optional[dict] = None,
    force: bool = False,
) -> dict:
    """API 读取时节流盘中重算；定时任务 force=True 强制刷新。"""
    key = f"{(ref_d or '')[:8]}:{date_str(bj_now())}"
    now = time.time()
    if not force:
        cached = _intraday_read_cache.get("payload")
        if cached and _intraday_read_cache.get("key") == key:
            age = now - float(_intraday_read_cache.get("at") or 0)
            if age < _intraday_read_ttl_sec():
                return cached
    payload = build_intraday_payload(
        metrics,
        ref_d=ref_d,
        auction=auction,
        prev_metrics=prev_metrics or {},
    )
    _intraday_read_cache.update({"key": key, "at": now, "payload": payload})
    return payload
