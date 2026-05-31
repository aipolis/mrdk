# -*- coding: utf-8 -*-
"""竞价情绪下钻：一字个股、板块涨幅 Top10、竞价量能异动"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import akshare as ak
import pandas as pd
import requests

from config import bj_now
from fetcher import (
    _EM_A_SHARE_FS,
    _EM_CLIST_URLS,
    _after_auction_925,
    _cache_get,
    _cache_set,
    _df_col,
    date_str,
    fetch_limit_up,
    get_recent_trade_dates,
)

log = logging.getLogger(__name__)

_AUCTION_VOL_FIELDS = ("f629", "f618", "f619", "f617")
_CONCEPT_FS = "m:90+t:3+f:!50"
_DETAIL_CACHE_TTL = 90


def _fmt_amount(v: Optional[float]) -> str:
    if v is None:
        return "--"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "--"
    if n <= 0:
        return "--"
    if n >= 1e8:
        return f"{n / 1e8:.2f}亿"
    if n >= 1e4:
        return f"{n / 1e4:.0f}万"
    return f"{int(n)}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "--"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "--"
    return f"{n:+.2f}%"


def _pick_sector(row: dict, df_row=None) -> str:
    for src in (row, df_row or {}):
        if not src:
            continue
        for key in ("sector", "所属行业", "行业", "涨停原因类别", "涨停原因"):
            val = src.get(key)
            if val is not None and str(val).strip() not in ("", "--", "nan"):
                s = str(val).strip()
                return s.split("+")[0].strip() or s
    return "--"


def _pick_seal_amount(row: dict, df_row=None) -> Optional[float]:
    for src in (row, df_row or {}):
        if not src:
            continue
        for key in ("sealAmount", "封板资金", "封板金额", "封单额", "封单金额"):
            val = src.get(key)
            if val is None:
                continue
            try:
                s = str(val).replace(",", "").replace("万", "").replace("亿", "").strip()
                n = float(s)
                if "亿" in str(val):
                    n *= 1e8
                elif "万" in str(val):
                    n *= 1e4
                if n > 0:
                    return n
            except (TypeError, ValueError):
                continue
    return None


def _fetch_clist_pages(
    fs: str,
    fields: str,
    *,
    fid: str = "f3",
    page_size: int = 500,
    max_pages: int = 80,
) -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": fs,
        "fields": fields,
        "pz": str(page_size),
    }
    rows: list[dict] = []
    for url in _EM_CLIST_URLS:
        try:
            r = requests.get(url, params={**base, "pn": "1"}, headers=headers, timeout=20)
            data = (r.json().get("data") or {})
            diff = data.get("diff") or []
            chunk = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if not chunk:
                continue
            rows.extend(chunk)
            total = int(data.get("total") or len(chunk))
            pages = min(max_pages, max(1, math.ceil(total / page_size)))
            for pn in range(2, pages + 1):
                r = requests.get(url, params={**base, "pn": str(pn)}, headers=headers, timeout=20)
                diff = (r.json().get("data") or {}).get("diff") or []
                rows.extend(list(diff.values()) if isinstance(diff, dict) else list(diff))
                if pn < pages:
                    time.sleep(0.08)
            if rows:
                return rows
        except Exception:
            continue
    return rows


def _fetch_stock_auction_vol_map(trade_d: str) -> dict[str, float]:
    trade_d = (trade_d or "")[:8]
    cache_key = f"auction_stock_vol_{trade_d}"
    cached = _cache_get(cache_key, 86400 * 40)
    if cached is not None:
        return dict(cached)

    today = date_str(bj_now())
    if trade_d != today or not _after_auction_925():
        return {}

    field = None
    vol_map: dict[str, float] = {}
    for f in _AUCTION_VOL_FIELDS:
        rows = _fetch_clist_pages(_EM_A_SHARE_FS, f"f12,f14,{f}")
        if len(rows) < 500:
            continue
        tmp: dict[str, float] = {}
        for row in rows:
            code = str(row.get("f12") or "").zfill(6)
            v = pd.to_numeric(row.get(f), errors="coerce")
            if code and v is not None and float(v) > 0:
                tmp[code] = float(v)
        if len(tmp) >= 500:
            vol_map = tmp
            field = f
            break
    if vol_map:
        _cache_set(cache_key, vol_map)
        log.info("auction stock vol cached %s field=%s n=%s", trade_d, field, len(vol_map))
    return vol_map


def _build_code_meta_maps(spot_df: Optional[pd.DataFrame]) -> tuple[dict[str, str], dict[str, str], dict[str, float]]:
    names: dict[str, str] = {}
    sectors: dict[str, str] = {}
    seals: dict[str, float] = {}
    if spot_df is None or spot_df.empty:
        return names, sectors, seals
    code_col = _df_col(spot_df, "代码")
    name_col = _df_col(spot_df, "名称")
    if not code_col:
        return names, sectors, seals
    for _, row in spot_df.iterrows():
        code = str(row.get(code_col) or "").zfill(6)
        if not code:
            continue
        if name_col:
            names[code] = str(row.get(name_col) or "").strip()
        sectors[code] = _pick_sector({}, row.to_dict())
        seal = _pick_seal_amount({}, row.to_dict())
        if seal:
            seals[code] = seal
    return names, sectors, seals


def _list_auction_one_word_stocks(trade_d: str, spot_df: Optional[pd.DataFrame]) -> list[dict]:
    trade_d = (trade_d or "")[:8]
    today = date_str(bj_now())
    names, sectors, seals = _build_code_meta_maps(spot_df)
    clist_rows = _fetch_clist_pages(_EM_A_SHARE_FS, "f12,f14,f3,f629,f615,f616,f617,f618,f619")
    clist_by_code = {str(r.get("f12") or "").zfill(6): r for r in clist_rows if r.get("f12")}

    items: list[dict] = []

    if trade_d == today and spot_df is not None and not spot_df.empty and _after_auction_925():
        code_col = _df_col(spot_df, "代码")
        if not code_col:
            return items
        open_p = pd.to_numeric(spot_df.get("今开"), errors="coerce")
        high = pd.to_numeric(spot_df.get("最高"), errors="coerce")
        low = pd.to_numeric(spot_df.get("最低"), errors="coerce")
        pre = pd.to_numeric(spot_df.get("昨收"), errors="coerce").replace(0, pd.NA)
        open_pct = (open_p - pre) / pre * 100
        mask = (
            (open_pct >= 9.8)
            & (open_p > 0)
            & (high > 0)
            & (open_p >= high * 0.998)
            & (low >= open_p * 0.998)
        )
        sub = spot_df.loc[mask].copy()
        for _, row in sub.iterrows():
            code = str(row.get(code_col) or "").zfill(6)
            pct = float(open_pct.loc[row.name]) if row.name in open_pct.index and pd.notna(open_pct.loc[row.name]) else None
            em = clist_by_code.get(code) or {}
            seal = seals.get(code)
            if seal is None:
                for f in ("f615", "f616", "f617", "f618", "f619", "f629"):
                    v = pd.to_numeric(em.get(f), errors="coerce")
                    if v is not None and float(v) > 0:
                        seal = float(v)
                        break
            items.append({
                "code": code,
                "name": names.get(code) or str(row.get(_df_col(spot_df, "名称") or "") or code),
                "openPct": round(pct, 2) if pct is not None else None,
                "openPctText": _fmt_pct(pct),
                "sealAmount": seal,
                "sealAmountText": _fmt_amount(seal),
                "sector": sectors.get(code) or _pick_sector({}, row.to_dict()),
            })
    else:
        df_up = fetch_limit_up(trade_d)
        if df_up is None or df_up.empty:
            return items
        code_col = _df_col(df_up, "代码")
        if not code_col:
            return items
        mask = None
        if "首次封板时间" in df_up.columns and "最后封板时间" in df_up.columns:
            first = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
            last = df_up["最后封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
            mask = (first == last) & (first <= "093000") & (first >= "092500")
        elif "开板次数" in df_up.columns:
            open_cnt = pd.to_numeric(df_up["开板次数"], errors="coerce").fillna(99)
            first_ok = pd.Series([True] * len(df_up), index=df_up.index)
            if "首次封板时间" in df_up.columns:
                first_t = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
                first_ok = first_t <= "093000"
            mask = (open_cnt == 0) & first_ok
        if mask is None:
            return items
        sub = df_up.loc[mask]
        chg_col = next((c for c in ("涨跌幅", "今日涨跌幅") if c in sub.columns), None)
        for _, row in sub.iterrows():
            code = str(row.get(code_col) or "").zfill(6)
            pct = pd.to_numeric(row.get(chg_col), errors="coerce") if chg_col else None
            seal = _pick_seal_amount({}, row.to_dict())
            items.append({
                "code": code,
                "name": str(row.get(_df_col(df_up, "名称") or "") or code).strip(),
                "openPct": round(float(pct), 2) if pct is not None and pd.notna(pct) else None,
                "openPctText": _fmt_pct(float(pct)) if pct is not None and pd.notna(pct) else "--",
                "sealAmount": seal,
                "sealAmountText": _fmt_amount(seal),
                "sector": _pick_sector({}, row.to_dict()),
            })

    items.sort(key=lambda x: (-(x.get("sealAmount") or 0), -(x.get("openPct") or 0)))
    return items


def _fetch_top_sector_boards(limit: int = 10) -> list[dict]:
    cache_key = f"auction_top_sectors_{date_str(bj_now())}"
    cached = _cache_get(cache_key, _DETAIL_CACHE_TTL)
    if cached is not None:
        return cached

    rows = _fetch_clist_pages(_CONCEPT_FS, "f12,f14,f3,f104,f105,f106", fid="f3", page_size=limit, max_pages=1)
    items = []
    for row in rows[:limit]:
        chg = pd.to_numeric(row.get("f3"), errors="coerce")
        if chg is None or pd.isna(chg):
            continue
        items.append({
            "code": str(row.get("f12") or ""),
            "name": str(row.get("f14") or "").strip(),
            "chg": round(float(chg), 2),
            "chgText": _fmt_pct(float(chg)),
            "upCount": int(pd.to_numeric(row.get("f104"), errors="coerce") or 0),
            "downCount": int(pd.to_numeric(row.get("f105"), errors="coerce") or 0),
        })
    items.sort(key=lambda x: -(x.get("chg") or 0))
    _cache_set(cache_key, items)
    return items


def _list_volume_surge_stocks(trade_d: str, prev_d: Optional[str], min_ratio: float = 1.15) -> list[dict]:
    trade_d = (trade_d or "")[:8]
    prev_d = (prev_d or "")[:8] if prev_d else ""
    if not prev_d:
        return []
    today_map = _fetch_stock_auction_vol_map(trade_d)
    prev_map = _fetch_stock_auction_vol_map(prev_d)
    if not today_map or not prev_map:
        return []

    spot_df = None
    try:
        spot_df = ak.stock_zh_a_spot_em()
    except Exception:
        pass
    names, sectors, _ = _build_code_meta_maps(spot_df)

    items: list[dict] = []
    for code, today_vol in today_map.items():
        prev_vol = prev_map.get(code)
        if not prev_vol or prev_vol <= 0:
            continue
        ratio = today_vol / prev_vol
        if ratio < min_ratio:
            continue
        items.append({
            "code": code,
            "name": names.get(code) or code,
            "sector": sectors.get(code) or "--",
            "auctionVol": today_vol,
            "prevAuctionVol": prev_vol,
            "volRatio": round(ratio, 3),
            "volRatioText": f"+{(ratio - 1) * 100:.1f}%",
        })
    items.sort(key=lambda x: (-x["volRatio"], -x["auctionVol"]))
    return items[:100]


def _aggregate_volume_sectors(stocks: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for s in stocks:
        sec = s.get("sector") or "未知"
        if sec not in buckets:
            buckets[sec] = {"sector": sec, "count": 0, "avgRatio": 0.0, "maxRatio": 0.0}
        buckets[sec]["count"] += 1
        buckets[sec]["avgRatio"] += float(s.get("volRatio") or 0)
        buckets[sec]["maxRatio"] = max(buckets[sec]["maxRatio"], float(s.get("volRatio") or 0))
    out = []
    for sec, data in buckets.items():
        if data["count"] <= 0:
            continue
        data["avgRatio"] = round(data["avgRatio"] / data["count"], 3)
        data["avgRatioText"] = f"+{(data['avgRatio'] - 1) * 100:.1f}%"
        data["maxRatioText"] = f"+{(data['maxRatio'] - 1) * 100:.1f}%"
        out.append(data)
    out.sort(key=lambda x: (-x["count"], -x["avgRatio"]))
    return out


def build_auction_detail_payload(
    trade_d: str = "",
    prev_d: Optional[str] = None,
) -> dict:
    trade_d = (trade_d or date_str(bj_now()))[:8]
    today = date_str(bj_now())
    if not prev_d:
        dates = get_recent_trade_dates(10)
        if trade_d in dates:
            idx = dates.index(trade_d)
            prev_d = dates[idx - 1] if idx > 0 else None
        else:
            prev_d = dates[-2] if len(dates) >= 2 else None

    ready = trade_d < today or (trade_d == today and _after_auction_925())
    cache_key = f"auction_detail_{trade_d}_{prev_d or ''}"
    if ready:
        cached = _cache_get(cache_key, _DETAIL_CACHE_TTL)
        if cached is not None:
            return cached

    spot_df = None
    if ready:
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            spot_df = None

    one_word = _list_auction_one_word_stocks(trade_d, spot_df) if ready else []
    top_sectors = _fetch_top_sector_boards(10) if ready else []
    surge_stocks = _list_volume_surge_stocks(trade_d, prev_d) if ready else []
    surge_sectors = _aggregate_volume_sectors(surge_stocks)

    now = bj_now()
    payload = {
        "tradeDate": trade_d,
        "prevDate": prev_d or "",
        "ready": ready,
        "updatedAt": now.strftime("%H:%M") if ready else "",
        "oneWordStocks": one_word,
        "topSectors": top_sectors,
        "volumeSurgeStocks": surge_stocks,
        "volumeSurgeSectors": surge_sectors,
        "sourceNote": "板块数据来自东财概念板块，非万得",
    }
    if ready:
        _cache_set(cache_key, payload)
    return payload
