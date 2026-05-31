# -*- coding: utf-8 -*-
"""竞价情绪下钻：一字个股、板块涨幅 Top10、竞价量能异动"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pandas as pd
import requests

from config import bj_now
from db_store import load_auction_vol_snapshot, save_auction_vol_snapshot
from fetcher import (
    _EM_A_SHARE_FS,
    _EM_CLIST_URLS,
    _after_auction_frozen,
    _auction_cache_ttl,
    _auction_data_ready,
    _cache_get,
    _cache_set,
    _df_col,
    date_str,
    fetch_auction_one_word_stocks,
    get_recent_trade_dates,
)

log = logging.getLogger(__name__)

# 竞价金额（元）：用于排序与 ≥1000 万筛选
_AUCTION_AMOUNT_FIELDS = ("f629", "f618", "f531", "f532")
# 竞价成交量：用于今/昨量比（与金额字段分离）
_AUCTION_VOL_QTY_FIELDS = ("f617", "f619", "f618", "f629")
_AUCTION_AMOUNT_MIN_YUAN = 10_000_000  # 1000 万
_CONCEPT_FS = "m:90+t:3+f:!50"
_DETAIL_CACHE_TTL = 120
_ALL_SECTIONS = ("oneWord", "topSectors", "volumeSurge")
_AUCTION_SECTION_FROZEN_TTL = 86400 * 8
# 量能异动：9:20 起每 30s，9:26 固化
_VOLUME_SURGE_REFRESH_SEC = 30
_AUCTION_VOL_LIGHT_PAGES = 2
_AUCTION_VOL_LIGHT_PAGE_SIZE = 500
_AUCTION_VOL_LIGHT_MIN = 15


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
            r = requests.get(url, params={**base, "pn": "1"}, headers=headers, timeout=12)
            data = (r.json().get("data") or {})
            diff = data.get("diff") or []
            chunk = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if not chunk:
                continue
            rows.extend(chunk)
            total = int(data.get("total") or len(chunk))
            pages = min(max_pages, max(1, math.ceil(total / page_size)))
            for pn in range(2, pages + 1):
                r = requests.get(url, params={**base, "pn": str(pn)}, headers=headers, timeout=12)
                diff = (r.json().get("data") or {}).get("diff") or []
                rows.extend(list(diff.values()) if isinstance(diff, dict) else list(diff))
            if rows:
                return rows
        except Exception:
            continue
    return rows


def _em_auction_amount_yuan(val) -> float:
    """东财 clist 竞价额 → 元（小数值按万元处理）"""
    v = pd.to_numeric(val, errors="coerce")
    if v is None or pd.isna(v) or float(v) <= 0:
        return 0.0
    n = float(v)
    if n < 100_000:
        return n * 1e4
    return n


def _em_auction_volume(val) -> float:
    """东财 clist 竞价成交量"""
    v = pd.to_numeric(val, errors="coerce")
    if v is None or pd.isna(v) or float(v) <= 0:
        return 0.0
    return float(v)


def _fetch_clist_one_page(
    fs: str,
    fields: str,
    *,
    fid: str,
    pn: int,
    page_size: int,
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
        "pn": str(pn),
    }
    for url in _EM_CLIST_URLS:
        try:
            r = requests.get(url, params=base, headers=headers, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            chunk = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if chunk:
                return chunk
        except Exception:
            continue
    return []


def _live_section_cache_ttl(trade_d: str) -> int:
    """板块 Top10 / 竞价一字：9:15–9:26 每 20s；9:26 起按日冻结"""
    trade_d = (trade_d or "")[:8]
    today = date_str(bj_now())
    if trade_d != today:
        return _AUCTION_SECTION_FROZEN_TTL
    if not _auction_data_ready():
        return 0
    return _auction_cache_ttl()


def _after_volume_surge_start(now=None) -> bool:
    now = now or bj_now()
    return now.hour * 60 + now.minute >= 9 * 60 + 20


def _volume_surge_cache_ttl(trade_d: str) -> int:
    """量能异动：9:20–9:26 每 30s；9:26 起按日冻结"""
    trade_d = (trade_d or "")[:8]
    today = date_str(bj_now())
    if trade_d != today:
        return _AUCTION_SECTION_FROZEN_TTL
    if not _after_volume_surge_start():
        return 0
    if _after_auction_frozen():
        return _AUCTION_SECTION_FROZEN_TTL
    return _VOLUME_SURGE_REFRESH_SEC


def _fetch_auction_vol_map_light(trade_d: str) -> tuple[dict[str, float], dict[str, dict]]:
    """
    轻量竞价数据：按竞价金额降序，仅保留金额≥1000万；vol_map 存竞价成交量供量比。
    同时缓存 scanned 页内全量成交量，供昨日对比 lookup。
    """
    trade_d = (trade_d or "")[:8]
    vol_key = f"auction_stock_vol_{trade_d}"
    vol_all_key = f"auction_stock_vol_all_{trade_d}"
    meta_key = f"auction_vol_meta_{trade_d}"
    ttl = _volume_surge_cache_ttl(trade_d)
    if ttl:
        cached_vol = _cache_get(vol_key, ttl)
        cached_meta = _cache_get(meta_key, ttl)
        if cached_vol is not None and cached_meta is not None:
            return dict(cached_vol), dict(cached_meta)

    today = date_str(bj_now())
    if trade_d == today and not _after_volume_surge_start():
        return {}, {}

    vol_map: dict[str, float] = {}
    vol_all: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for amt_f in _AUCTION_AMOUNT_FIELDS:
        for vol_f in _AUCTION_VOL_QTY_FIELDS:
            if vol_f == amt_f:
                continue
            tmp: dict[str, float] = {}
            tmp_meta: dict[str, dict] = {}
            tmp_all: dict[str, float] = {}
            for pn in range(1, _AUCTION_VOL_LIGHT_PAGES + 1):
                rows = _fetch_clist_one_page(
                    _EM_A_SHARE_FS,
                    f"f12,f14,f100,{amt_f},{vol_f}",
                    fid=amt_f,
                    pn=pn,
                    page_size=_AUCTION_VOL_LIGHT_PAGE_SIZE,
                )
                if not rows:
                    break
                page_min_amount = None
                for row in rows:
                    code = str(row.get("f12") or "").zfill(6)
                    if not code:
                        continue
                    volume = _em_auction_volume(row.get(vol_f))
                    if volume > 0:
                        tmp_all[code] = volume
                    amount = _em_auction_amount_yuan(row.get(amt_f))
                    if amount < _AUCTION_AMOUNT_MIN_YUAN:
                        if amount > 0 and (page_min_amount is None or amount < page_min_amount):
                            page_min_amount = amount
                        continue
                    if volume <= 0:
                        continue
                    tmp[code] = volume
                    sector = str(row.get("f100") or "").strip()
                    tmp_meta[code] = {
                        "name": str(row.get("f14") or code).strip(),
                        "sector": sector if sector not in ("", "--", "nan") else "--",
                        "auctionAmount": amount,
                    }
                if page_min_amount is not None and page_min_amount < _AUCTION_AMOUNT_MIN_YUAN:
                    break
            if len(tmp) >= _AUCTION_VOL_LIGHT_MIN:
                vol_map = tmp
                vol_all = tmp_all
                meta = tmp_meta
                break
        if vol_map:
            break

    store_ttl = ttl or _AUCTION_SECTION_FROZEN_TTL
    if vol_map:
        _cache_set(vol_key, vol_map)
        _cache_set(meta_key, meta)
        if vol_all:
            _cache_set(vol_all_key, vol_all)
            save_auction_vol_snapshot(trade_d, vol_all)
        log.info(
            "auction vol light cached %s n=%s vol (amount>=%sw)",
            trade_d,
            len(vol_map),
            int(_AUCTION_AMOUNT_MIN_YUAN / 1e4),
        )
    return vol_map, meta


def _prev_auction_vol_map(prev_d: str, codes: Optional[set[str]] = None) -> dict[str, float]:
    """昨日竞价成交量：优先全量扫描缓存，按 codes 取交集供量比"""
    prev_d = (prev_d or "")[:8]
    if not prev_d:
        return {}
    all_key = f"auction_stock_vol_all_{prev_d}"
    filtered_key = f"auction_stock_vol_{prev_d}"
    cached_all = _cache_get(all_key, _AUCTION_SECTION_FROZEN_TTL)
    if cached_all is None:
        cached_filtered = _cache_get(filtered_key, _AUCTION_SECTION_FROZEN_TTL)
        if cached_filtered is not None:
            cached_all = dict(cached_filtered)
        else:
            _fetch_auction_vol_map_light(prev_d)
            cached_all = _cache_get(all_key, _AUCTION_SECTION_FROZEN_TTL) or _cache_get(
                filtered_key, _AUCTION_SECTION_FROZEN_TTL
            )
            if not cached_all:
                db_data = load_auction_vol_snapshot(prev_d)
                if db_data:
                    cached_all = db_data
                    _cache_set(all_key, db_data)
                    log.info("auction vol prev_d=%s loaded from db snapshot n=%s", prev_d, len(db_data))
    if not cached_all:
        return {}
    src = dict(cached_all)
    if codes:
        return {c: src[c] for c in codes if c in src and src[c] > 0}
    return src


def _fetch_stock_auction_vol_map(trade_d: str) -> dict[str, float]:
    """兼容 history_sync 预热：走轻量竞价量接口"""
    vol_map, _ = _fetch_auction_vol_map_light(trade_d)
    return vol_map


def _list_auction_one_word_stocks(trade_d: str, spot_df: Optional[pd.DataFrame] = None) -> list[dict]:
    """竞价一字：涨停池 / clist 兜底，结果按交易日冻结缓存。"""
    items: list[dict] = []
    for row in fetch_auction_one_word_stocks(trade_d):
        pct = row.get("openPct")
        seal = row.get("sealAmount")
        items.append({
            "code": row.get("code") or "",
            "name": row.get("name") or row.get("code") or "",
            "openPct": pct,
            "openPctText": _fmt_pct(pct),
            "sealAmount": seal,
            "sealAmountText": _fmt_amount(seal),
            "sector": row.get("sector") or "--",
        })
    return items


def _fetch_top_sector_boards_raw(limit: int = 10) -> list[dict]:
    rows = _fetch_clist_pages(_CONCEPT_FS, "f12,f14,f3,f6,f104,f105,f106", fid="f3", page_size=limit, max_pages=1)
    items = []
    for row in rows[:limit]:
        chg = pd.to_numeric(row.get("f3"), errors="coerce")
        if chg is None or pd.isna(chg):
            continue
        amt_raw = pd.to_numeric(row.get("f6"), errors="coerce")
        amt = float(amt_raw) if amt_raw is not None and not pd.isna(amt_raw) and float(amt_raw) > 0 else None
        items.append({
            "code": str(row.get("f12") or ""),
            "name": str(row.get("f14") or "").strip(),
            "chg": round(float(chg), 2),
            "chgText": _fmt_pct(float(chg)),
            "upCount": int(pd.to_numeric(row.get("f104"), errors="coerce") or 0),
            "downCount": int(pd.to_numeric(row.get("f105"), errors="coerce") or 0),
            "auctionAmountText": _fmt_amount(amt),
        })
    items.sort(key=lambda x: -(x.get("chg") or 0))
    return items


def _fetch_top_sector_boards(limit: int = 10, trade_d: str = "") -> list[dict]:
    """板块 Top10：与竞价一字相同，9:15–9:26 每 20s，9:26 后固化"""
    trade_d = (trade_d or date_str(bj_now()))[:8]
    if trade_d == date_str(bj_now()) and not _auction_data_ready():
        return []

    cache_key = f"auction_top_sectors_{trade_d}"
    ttl = _live_section_cache_ttl(trade_d)
    if ttl:
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            return list(cached)

    items = _fetch_top_sector_boards_raw(limit)
    store_ttl = ttl or _AUCTION_SECTION_FROZEN_TTL
    _cache_set(cache_key, items)
    return items


def _build_volume_surge_stocks(
    today_map: dict[str, float],
    prev_map: dict[str, float],
    meta: dict[str, dict],
    min_ratio: float = 1.15,
) -> list[dict]:
    items: list[dict] = []
    for code, today_vol in today_map.items():
        prev_vol = prev_map.get(code)
        if not prev_vol or prev_vol <= 0:
            continue
        ratio = today_vol / prev_vol
        if ratio < min_ratio:
            continue
        m = meta.get(code) or {}
        items.append({
            "code": code,
            "name": m.get("name") or code,
            "sector": m.get("sector") or "--",
            "auctionVol": today_vol,
            "prevAuctionVol": prev_vol,
            "auctionAmount": m.get("auctionAmount"),
            "auctionAmountText": _fmt_amount(m.get("auctionAmount")),
            "volRatio": round(ratio, 3),
            "volRatioText": f"+{(ratio - 1) * 100:.1f}%",
        })
    items.sort(key=lambda x: (-x["volRatio"], -x["auctionVol"]))
    return items[:100]


def _fetch_volume_surge_bundle(
    trade_d: str,
    prev_d: Optional[str],
) -> dict:
    """量能异动：9:20 起每 30s 更新，9:26 固化"""
    trade_d = (trade_d or "")[:8]
    empty = {"volumeSurgeStocks": [], "volumeSurgeSectors": []}
    if trade_d == date_str(bj_now()) and not _after_volume_surge_start():
        return empty

    cache_key = f"auction_volume_surge_{trade_d}"
    ttl = _volume_surge_cache_ttl(trade_d)
    if ttl:
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            return dict(cached)

    prev_d8 = (prev_d or "")[:8] if prev_d else ""
    if not prev_d8:
        return empty

    today_map, meta = _fetch_auction_vol_map_light(trade_d)
    prev_map = _prev_auction_vol_map(prev_d8, set(today_map.keys()))
    if not today_map or not prev_map:
        return empty

    stocks = _build_volume_surge_stocks(today_map, prev_map, meta)
    bundle = {
        "volumeSurgeStocks": stocks,
        "volumeSurgeSectors": _aggregate_volume_sectors(stocks),
    }
    store_ttl = ttl or _AUCTION_SECTION_FROZEN_TTL
    _cache_set(cache_key, bundle)
    return bundle


def _aggregate_volume_sectors(stocks: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for s in stocks:
        sec = s.get("sector") or "未知"
        if sec not in buckets:
            buckets[sec] = {"sector": sec, "count": 0, "avgRatio": 0.0, "maxRatio": 0.0, "totalAmount": 0.0}
        buckets[sec]["count"] += 1
        buckets[sec]["avgRatio"] += float(s.get("volRatio") or 0)
        buckets[sec]["maxRatio"] = max(buckets[sec]["maxRatio"], float(s.get("volRatio") or 0))
        buckets[sec]["totalAmount"] += float(s.get("auctionAmount") or 0)
    out = []
    for sec, data in buckets.items():
        if data["count"] <= 0:
            continue
        data["avgRatio"] = round(data["avgRatio"] / data["count"], 3)
        data["avgRatioText"] = f"+{(data['avgRatio'] - 1) * 100:.1f}%"
        data["maxRatioText"] = f"+{(data['maxRatio'] - 1) * 100:.1f}%"
        data["totalAmountText"] = _fmt_amount(data["totalAmount"]) if data["totalAmount"] > 0 else "--"
        out.append(data)
    out.sort(key=lambda x: (-x["count"], -x["avgRatio"]))
    return out


def _parse_sections(sections: Optional[str]) -> tuple[str, ...]:
    if not sections or sections.strip().lower() in ("all", "*"):
        return _ALL_SECTIONS
    out = []
    for part in sections.replace(" ", "").split(","):
        key = part.strip()
        if key in _ALL_SECTIONS and key not in out:
            out.append(key)
    return tuple(out) if out else _ALL_SECTIONS


def _section_live_done(trade_d: str) -> bool:
    """9:26 后或历史日视为该 section 已定格"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(bj_now()):
        return True
    return _after_auction_frozen()


def _empty_payload(trade_d: str, prev_d: Optional[str], ready: bool) -> dict:
    now = bj_now()
    return {
        "tradeDate": trade_d,
        "prevDate": prev_d or "",
        "ready": ready,
        "updatedAt": now.strftime("%H:%M") if ready else "",
        "oneWordStocks": [],
        "topSectors": [],
        "volumeSurgeStocks": [],
        "volumeSurgeSectors": [],
        "topSectorsReady": False,
        "volumeSurgeReady": False,
        "sourceNote": "板块数据来自东财概念板块；量能异动为竞价金额≥1000万且竞价量较昨日+15%以上",
    }


def build_auction_detail_payload(
    trade_d: str = "",
    prev_d: Optional[str] = None,
    *,
    sections: Optional[str] = None,
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

    want = _parse_sections(sections)
    ready = trade_d < today or (trade_d == today and _auction_data_ready())
    top_ready = trade_d < today or (trade_d == today and _auction_data_ready())
    vol_ready = trade_d < today or (trade_d == today and _after_volume_surge_start())

    cache_key = f"auction_detail_{trade_d}_{prev_d or ''}_{','.join(want)}"
    if want == ("volumeSurge",):
        detail_ttl = _volume_surge_cache_ttl(trade_d)
    elif trade_d == today:
        detail_ttl = _auction_cache_ttl()
    else:
        detail_ttl = 86400
    if ready and detail_ttl:
        cached = _cache_get(cache_key, detail_ttl)
        if cached is not None:
            return cached

    payload = _empty_payload(trade_d, prev_d, ready)
    if not ready:
        return payload

    futures = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if "oneWord" in want:
            futures["oneWord"] = pool.submit(_list_auction_one_word_stocks, trade_d)
        if "topSectors" in want and top_ready:
            futures["topSectors"] = pool.submit(_fetch_top_sector_boards, 10, trade_d)
        if "volumeSurge" in want and vol_ready:
            futures["volumeSurge"] = pool.submit(_fetch_volume_surge_bundle, trade_d, prev_d)

        for key, fut in futures.items():
            try:
                result = fut.result(timeout=90)
                if key == "oneWord":
                    payload["oneWordStocks"] = result
                elif key == "topSectors":
                    payload["topSectors"] = result
                elif key == "volumeSurge":
                    payload["volumeSurgeStocks"] = result.get("volumeSurgeStocks") or []
                    payload["volumeSurgeSectors"] = result.get("volumeSurgeSectors") or []
            except Exception:
                log.exception("auction detail section failed: %s", key)

    if ready:
        payload["updatedAt"] = bj_now().strftime("%H:%M")
        if "topSectors" in want:
            payload["topSectorsReady"] = _section_live_done(trade_d) or bool(payload["topSectors"])
        if "volumeSurge" in want:
            surge_cached = _cache_get(f"auction_volume_surge_{trade_d}", _AUCTION_SECTION_FROZEN_TTL)
            payload["volumeSurgeReady"] = _section_live_done(trade_d) or surge_cached is not None

    if detail_ttl or trade_d != today:
        _cache_set(cache_key, payload)
    return payload