# -*- coding: utf-8 -*-
"""akshare / 新浪 数据抓取层"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from config import BJT, bj_now, timedelta
from functools import lru_cache
from typing import Optional

import akshare as ak
import pandas as pd
import requests

_cache: dict = {}
log = logging.getLogger(__name__)

# 东财涨停/跌停/炸板股池可回溯约 30 个自然日；更早仅读 MySQL 归档
EM_POOL_MAX_AGE_DAYS = 30

# 盘中 2 分钟刷新周期（略小于 IntervalTrigger 120s，避免命中旧缓存）
INTRADAY_CACHE_TTL = 100

_EM_CLIST_URLS = (
    "https://91.push2.eastmoney.com/api/qt/clist/get",
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://29.push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://48.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
def _cache_get(key: str, ttl: int = 300):
    item = _cache.get(key)
    if item and time.time() - item["ts"] < ttl:
        return item["data"]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"ts": time.time(), "data": data}


def invalidate_sector_concentration_cache(trade_d: Optional[str] = None) -> None:
    """清除概念涨停强度相关进程内缓存。"""
    today = (trade_d or date_str(bj_now()))[:8]
    keys = [f"sector_conc_{today}"]
    dates = get_recent_trade_dates(5)
    if dates:
        keys.append(f"sector_conc_{dates[-1]}")
    for key in keys:
        _cache.pop(key, None)


def invalidate_intraday_caches(today: Optional[str] = None) -> None:
    """盘中定时刷新前清缓存，保证 top10 / 晋级率 等与 2 分钟任务同步。"""
    today = (today or date_str(bj_now()))[:8]
    for key in (
        "intraday_board_stats_v1",
        f"zt_{today}",
        f"zb_{today}",
    ):
        _cache.pop(key, None)
    invalidate_sector_concentration_cache(today)
    invalidate_market_breadth_cache(today)
    _cache.pop(f"em_a_share_snapshot_{today}", None)
    try:
        from intraday import invalidate_intraday_read_cache

        invalidate_intraday_read_cache()
    except Exception:
        pass
    invalidate_longkong_read_cache()


def date_str(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def parse_date(s: str) -> datetime:
    s = s.replace("-", "")
    return datetime.strptime(s[:8], "%Y%m%d").replace(tzinfo=BJT)


def get_recent_trade_dates(count: int = 35) -> list[str]:
    key = f"trade_dates_{count}"
    cached = _cache_get(key, 86400)
    if cached:
        return cached
    try:
        df = ak.tool_trade_date_hist_sina()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        today = bj_now()
        dates = df[df["trade_date"] <= today]["trade_date"].dt.strftime("%Y%m%d").tolist()
        result = dates[-count:]
        _cache_set(key, result)
        return result
    except Exception:
        result = []
        d = bj_now()
        while len(result) < count:
            if d.weekday() < 5:
                result.insert(0, date_str(d))
            d -= timedelta(days=1)
        return result


def em_pool_available(trade_d: str) -> bool:
    """东财股池是否仍在可拉取窗口内（约 30 日）。"""
    trade_d = (trade_d or "")[:8]
    if len(trade_d) != 8:
        return False
    try:
        d = parse_date(trade_d)
        return (bj_now() - d).days <= EM_POOL_MAX_AGE_DAYS
    except Exception:
        return False


def fetch_limit_up(d: str, *, ttl: Optional[int] = None) -> pd.DataFrame:
    d = (d or "")[:8]
    key = f"zt_{d}"
    if ttl is None:
        ttl = INTRADAY_CACHE_TTL if d == date_str(bj_now()) else 300
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached
    if not em_pool_available(d):
        return pd.DataFrame()
    try:
        df = ak.stock_zt_pool_em(date=d)
        _cache_set(key, df)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_limit_down(d: str) -> pd.DataFrame:
    key = f"dt_{d}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not em_pool_available(d):
        return pd.DataFrame()
    try:
        df = ak.stock_zt_pool_dtgc_em(date=d)
        _cache_set(key, df)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_broken_board(d: str, *, ttl: Optional[int] = None) -> pd.DataFrame:
    d = (d or "")[:8]
    key = f"zb_{d}"
    if ttl is None:
        ttl = INTRADAY_CACHE_TTL if d == date_str(bj_now()) else 300
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached
    if not em_pool_available(d):
        return pd.DataFrame()
    try:
        df = ak.stock_zt_pool_zbgc_em(date=d)
        _cache_set(key, df)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_index_spot() -> list[dict]:
    key = "index_spot"
    cached = _cache_get(key, 60)
    if cached:
        return cached
    names = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
    result = []
    try:
        df = ak.stock_zh_index_spot_em()
        for code, name in names.items():
            row = df[df["代码"] == code]
            if row.empty:
                continue
            chg = float(row.iloc[0].get("涨跌幅", 0) or 0)
            result.append({"name": name, "value": f"{chg:+.2f}%", "up": chg >= 0})
    except Exception:
        for name in names.values():
            result.append({"name": name, "value": "--", "up": False})
    _cache_set(key, result)
    return result


def _looks_like_datetime(val) -> bool:
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", str(val or "")))


def _parse_market_activity_df(df: pd.DataFrame) -> dict:
    """解析乐股网市场活跃度（item/value 或旧版宽表）"""
    result = {"advance": 0, "decline": 0, "amount": "--", "amount_raw": 0}
    if df is None or df.empty:
        return result
    if "item" in df.columns and "value" in df.columns:
        for _, row in df.iterrows():
            item = str(row.get("item", "")).strip()
            val = row.get("value")
            if item == "上涨":
                result["advance"] = int(pd.to_numeric(val, errors="coerce") or 0)
            elif item == "下跌":
                result["decline"] = int(pd.to_numeric(val, errors="coerce") or 0)
            elif "成交额" in item and not _looks_like_datetime(val):
                result["amount"] = str(val)
                try:
                    result["amount_raw"] = float(
                        str(val).replace("亿", "").replace(",", "").strip()
                    )
                except Exception:
                    pass
        return result
    row = df.iloc[-1]
    for c in df.columns:
        cs = str(c)
        if "上涨" in cs or cs == "涨":
            result["advance"] = int(pd.to_numeric(row[c], errors="coerce") or 0)
        if "下跌" in cs or cs == "跌":
            result["decline"] = int(pd.to_numeric(row[c], errors="coerce") or 0)
    amount_raw = str(row.get("成交额", ""))
    if amount_raw and not _looks_like_datetime(amount_raw):
        result["amount"] = amount_raw
        try:
            result["amount_raw"] = float(
                str(amount_raw).replace("亿", "").replace(",", "").strip()
            )
        except Exception:
            pass
    return result


_EM_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_EM_A_SHARE_CLIST_URLS = (
    "https://91.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://29.push2.eastmoney.com/api/qt/clist/get",
    "https://48.push2.eastmoney.com/api/qt/clist/get",
)


def _race_em_clist(params: dict, headers: dict, *, timeout: float = 5) -> tuple[dict, Optional[str]]:
    """Race Eastmoney mirrors so one unavailable host cannot stall a refresh."""
    pool = ThreadPoolExecutor(max_workers=len(_EM_A_SHARE_CLIST_URLS))
    futures = {
        pool.submit(requests.get, url, params=params, headers=headers, timeout=timeout): url
        for url in _EM_A_SHARE_CLIST_URLS
    }
    try:
        for future in as_completed(futures, timeout=timeout + 1):
            try:
                data = (future.result().json().get("data") or {})
                if data.get("diff"):
                    return data, futures[future]
            except Exception:
                continue
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {}, None


_SINA_MARKET_CENTER_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)


def _fetch_sina_market_rank(sort: str, *, asc: bool = False) -> list[dict]:
    """Fetch one Sina Shanghai/Shenzhen A-share ranking page."""
    try:
        response = requests.get(
            _SINA_MARKET_CENTER_URL,
            params={
                "page": "1",
                "num": "100",
                "sort": sort,
                "asc": "1" if asc else "0",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page",
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
            timeout=8,
        )
        rows = response.json()
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _fetch_sina_top_amount_spot_df() -> Optional[pd.DataFrame]:
    rows = _fetch_sina_market_rank("amount")
    records = [
        {
            "代码": str(row.get("code") or "").zfill(6),
            "最新价": row.get("trade"),
            "涨跌幅": row.get("changepercent"),
            "成交额": row.get("amount"),
            "今开": row.get("open"),
            "昨收": row.get("settlement"),
        }
        for row in rows[:10]
        if row.get("code")
    ]
    return pd.DataFrame(records) if len(records) >= 10 else None


def _fetch_sina_big_drop_count(threshold: float = -7.0) -> Optional[int]:
    rows = _fetch_sina_market_rank("changepercent", asc=True)
    if not rows:
        return None
    pct = pd.to_numeric(
        pd.Series([row.get("changepercent") for row in rows]), errors="coerce"
    ).dropna()
    if pct.empty or float(pct.iloc[-1]) <= threshold:
        return None
    return int((pct < threshold).sum())


def _fetch_sina_quotes_df(codes: list[str]) -> Optional[pd.DataFrame]:
    """Fetch current/open/previous-close quotes for an arbitrary A-share code list."""
    normalized = _normalize_code_list(codes)
    if not normalized:
        return None
    records: list[dict] = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
    for start in range(0, len(normalized), 100):
        chunk = normalized[start : start + 100]
        symbols = [f"{'sh' if code.startswith(('5', '6', '9')) else 'sz'}{code}" for code in chunk]
        try:
            response = requests.get(
                "https://hq.sinajs.cn/list=" + ",".join(symbols),
                headers=headers,
                timeout=10,
            )
            for line in response.text.splitlines():
                match = re.search(r'hq_str_(?:sh|sz)(\d{6})="([^"]*)"', line)
                if not match:
                    continue
                parts = match.group(2).split(",")
                if len(parts) < 4:
                    continue
                prev_close = pd.to_numeric(parts[2], errors="coerce")
                open_price = pd.to_numeric(parts[1], errors="coerce")
                current = pd.to_numeric(parts[3], errors="coerce")
                if pd.isna(prev_close) or float(prev_close) <= 0:
                    continue
                records.append({
                    "代码": match.group(1),
                    "昨收": prev_close,
                    "今开": open_price,
                    "最新价": current,
                    "涨跌幅": round((float(current) - float(prev_close)) / float(prev_close) * 100, 3),
                })
        except Exception:
            continue
    return pd.DataFrame(records) if records else None


def _fetch_em_top_amount_spot_df() -> Optional[pd.DataFrame]:
    """东财成交额榜实时明细，作为前10指标的快速兜底。"""
    key = f"em_top_amount_spot_df_{date_str(bj_now())}"
    cached = _cache_get(key, 60)
    if isinstance(cached, list) and cached:
        return pd.DataFrame(cached)

    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base_params = {
        "pn": "1",
        "pz": "50",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f6",
        "fs": _EM_A_SHARE_FS,
        "fields": "f12,f2,f3,f6,f17,f18",
    }
    _, winner = _race_em_clist(base_params, headers)
    if not winner:
        return _fetch_sina_top_amount_spot_df()
    for url in (winner,):
        try:
            rows: list[dict] = []
            params = dict(base_params)
            response = requests.get(url, params=params, headers=headers, timeout=5)
            data = response.json().get("data") or {}
            total = int(data.get("total") or 0)
            diff = data.get("diff") or []
            rows.extend(list(diff.values()) if isinstance(diff, dict) else list(diff))
            if total <= 0 or not rows:
                continue

            records = [
                {
                    "代码": str(row.get("f12") or "").zfill(6),
                    "最新价": row.get("f2"),
                    "涨跌幅": row.get("f3"),
                    "成交额": row.get("f6"),
                    "今开": row.get("f17"),
                    "昨收": row.get("f18"),
                }
                for row in rows
                if row.get("f12")
            ]
            if len(records) >= 10:
                _cache_set(key, records)
                return pd.DataFrame(records)
        except Exception:
            continue
    return _fetch_sina_top_amount_spot_df()


def _fetch_em_big_drop_count(threshold: float = -7.0) -> Optional[int]:
    """东财跌幅榜统计低于阈值的股票数，通常一页即可完成。"""
    key = f"em_big_drop_count_{date_str(bj_now())}_{threshold}"
    cached = _cache_get(key, 60)
    if cached is not None:
        return int(cached)

    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base_params = {
        "pn": "1",
        "pz": "500",
        "po": "0",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": _EM_A_SHARE_FS,
        "fields": "f3",
    }
    _, winner = _race_em_clist(base_params, headers)
    if not winner:
        return _fetch_sina_big_drop_count(threshold)
    for url in (winner,):
        try:
            count = 0
            for page in range(1, 20):
                params = dict(base_params)
                params["pn"] = str(page)
                response = requests.get(url, params=params, headers=headers, timeout=5)
                diff = (response.json().get("data") or {}).get("diff") or []
                rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
                if not rows:
                    break
                pct = pd.to_numeric(pd.Series([row.get("f3") for row in rows]), errors="coerce").dropna()
                page_count = int((pct < threshold).sum())
                count += page_count
                if page_count < len(pct):
                    _cache_set(key, count)
                    return count
            _cache_set(key, count)
            return count
        except Exception:
            continue
    return _fetch_sina_big_drop_count(threshold)


def _fetch_em_a_share_snapshot() -> dict:
    """东财全 A 实时列表聚合：成交额、上涨/下跌家数。"""
    key = f"em_a_share_snapshot_{date_str(bj_now())}"
    cached = _cache_get(key, 60)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base_params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": _EM_A_SHARE_FS,
        "fields": "f3,f6",
    }
    _, winner = _race_em_clist(base_params, headers, timeout=12)
    for url in ((winner,) if winner else ()):
        try:
            params = dict(base_params)
            r = requests.get(url, params=params, headers=headers, timeout=12)
            data = (r.json().get("data") or {})
            total = int(data.get("total") or 0)
            diff = data.get("diff") or []
            rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if total <= 0 or not rows:
                continue

            pages = max(1, math.ceil(total / int(base_params["pz"])))
            for pn in range(2, pages + 1):
                params = dict(base_params)
                params["pn"] = str(pn)
                r = requests.get(url, params=params, headers=headers, timeout=12)
                diff = (r.json().get("data") or {}).get("diff") or []
                rows.extend(list(diff.values()) if isinstance(diff, dict) else list(diff))

            pct = pd.to_numeric(pd.Series([row.get("f3") for row in rows]), errors="coerce")
            amount = pd.to_numeric(pd.Series([row.get("f6") for row in rows]), errors="coerce").sum()
            result = {
                "advance": int((pct > 0).sum()),
                "decline": int((pct < 0).sum()),
                "big_drop_count": int((pct < -7.0).sum()),
                "amount_raw": round(float(amount) / 1e8, 1) if amount > 0 else 0.0,
                "rows": len(rows),
            }
            if result["rows"] >= 1000:
                _cache_set(key, result)
                return result
        except Exception:
            continue

    result = {"advance": 0, "decline": 0, "big_drop_count": None, "amount_raw": 0.0, "rows": 0}
    _cache_set(key, result)
    return result


def _spot_market_amount_yi(spot_df: Optional[pd.DataFrame] = None) -> tuple[str, float]:
    """A 股实时总成交额（亿）；优先交易所口径，再东财全 A 聚合/指数兜底。"""
    today = date_str(bj_now())
    amt, raw = _fetch_market_amount_exchange(today)
    if raw > 0:
        return amt, raw

    snap = _fetch_em_a_share_snapshot()
    raw = float(snap.get("amount_raw") or 0)
    if raw > 0:
        return f"{round(raw)}亿", raw

    amt, raw = _fetch_market_amount_tencent(today)
    if raw > 0:
        return amt, raw
    try:
        df = spot_df if spot_df is not None else ak.stock_zh_a_spot_em()
        if df is not None and not df.empty and "成交额" in df.columns:
            total = float(pd.to_numeric(df["成交额"], errors="coerce").sum())
            if total > 0:
                yi = total / 1e8
                return f"{round(yi)}亿", yi
    except Exception:
        pass
    return "--", 0.0


def fetch_market_activity() -> dict:
    """涨跌家数、成交额等"""
    key = "market_activity"
    cached = _cache_get(key, 120)
    if cached:
        return cached
    result = {"advance": 0, "decline": 0, "amount": "--", "amount_raw": 0}
    try:
        df = ak.stock_market_activity_legu()
        result = _parse_market_activity_df(df)
        if result["amount"] in ("--", "") or _looks_like_datetime(result["amount"]):
            amt, raw = _spot_market_amount_yi()
            if raw > 0:
                result["amount"] = amt
                result["amount_raw"] = raw
    except Exception:
        pass
    _cache_set(key, result)
    return result


def _normalize_stock_codes(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "代码" not in df.columns:
        return set()
    return set(
        df["代码"]
        .astype(str)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(6)
        .tolist()
    )


def _breadth_valid(adv: int, dec: int) -> bool:
    adv_i, dec_i = int(adv or 0), int(dec or 0)
    return adv_i > 0 and dec_i > 0 and (adv_i + dec_i) >= 500


def _fetch_market_breadth_spot() -> tuple[int, int]:
    """全 A 实时涨跌家数兜底。只在乐股/归档不完整时使用。"""
    snap = _fetch_em_a_share_snapshot()
    adv = int(snap.get("advance") or 0)
    dec = int(snap.get("decline") or 0)
    if _breadth_valid(adv, dec):
        return adv, dec

    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty or "涨跌幅" not in df.columns:
            return 0, 0
        pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
        adv = int((pct > 0).sum())
        dec = int((pct < 0).sum())
        return adv, dec
    except Exception:
        return 0, 0


def _one_word_count(df_up: pd.DataFrame) -> int:
    """收盘一字板：竞价即封死（首末封板时间相同且 ≤09:30）"""
    sub = _zt_df_one_word_subset(df_up)
    return len(sub) if sub is not None else 0


def _zt_df_one_word_subset(df_up: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df_up is None or df_up.empty:
        return None
    if "首次封板时间" in df_up.columns and "最后封板时间" in df_up.columns:
        first = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
        last = df_up["最后封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
        # 东财涨停池的竞价撮合时间常记录为 09:25:01~09:25:xx。
        mask = (first == last) & (first <= "092559")
        return df_up.loc[mask]
    if "开板次数" in df_up.columns:
        try:
            open_cnt = pd.to_numeric(df_up["开板次数"], errors="coerce").fillna(99)
            first_ok = pd.Series([True] * len(df_up), index=df_up.index)
            if "首次封板时间" in df_up.columns:
                first_t = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
                first_ok = first_t <= "093000"
            return df_up.loc[(open_cnt == 0) & first_ok]
        except Exception:
            pass
    return None


_EM_ONE_WORD_CLIST_FIELDS = "f12,f14,f3,f17,f15,f16,f18,f100"
# 9:15–9:26 竞价 live 刷新间隔；9:26 起按日冻结
AUCTION_LIVE_REFRESH_SEC = 20
_AUCTION_ONE_WORD_FROZEN_TTL = 86400 * 8


def _em_row_auction_one_word_open_pct(row: dict, min_open_pct: float = 9.8) -> Optional[float]:
    """EM clist 行：开盘涨停且最低未破开 → 返回开盘涨幅，否则 None。"""
    pre = pd.to_numeric(row.get("f18"), errors="coerce")
    open_p = pd.to_numeric(row.get("f17"), errors="coerce")
    high = pd.to_numeric(row.get("f15"), errors="coerce")
    low = pd.to_numeric(row.get("f16"), errors="coerce")
    if pre is None or pd.isna(pre) or float(pre) <= 0:
        return None
    if any(v is None or pd.isna(v) or float(v) <= 0 for v in (open_p, high, low)):
        return None
    open_pct = (float(open_p) - float(pre)) / float(pre) * 100
    if open_pct < min_open_pct:
        return None
    if float(open_p) < float(high) * 0.998:
        return None
    if float(low) < float(open_p) * 0.998:
        return None
    return open_pct


def _fetch_em_high_chg_stock_rows(
    *,
    page_size: int = 500,
    max_pages: int = 2,
    stop_f3: float = 8.0,
) -> list[dict]:
    """东财 clist 按涨幅降序拉取，页内最低 f3 低于 stop_f3 即停（通常 1 页够覆盖全部涨停候选）。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": _EM_A_SHARE_FS,
        "fields": _EM_ONE_WORD_CLIST_FIELDS,
        "pz": str(page_size),
    }
    for url in _EM_A_SHARE_CLIST_URLS:
        rows: list[dict] = []
        try:
            for pn in range(1, max_pages + 1):
                r = requests.get(url, params={**base, "pn": str(pn)}, headers=headers, timeout=12)
                diff = (r.json().get("data") or {}).get("diff") or []
                chunk = list(diff.values()) if isinstance(diff, dict) else list(diff)
                if not chunk:
                    break
                rows.extend(chunk)
                f3_vals = pd.to_numeric(pd.Series([x.get("f3") for x in chunk]), errors="coerce")
                if f3_vals.notna().any() and float(f3_vals.min()) < stop_f3:
                    break
            if rows:
                return rows
        except Exception:
            continue
    return []


def _parse_seal_amount_raw(val) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").strip()
        n = float(s.replace("万", "").replace("亿", ""))
        if "亿" in str(val):
            n *= 1e8
        elif "万" in str(val):
            n *= 1e4
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _one_word_items_from_zt_df(df_up: pd.DataFrame) -> list[dict]:
    """从东财涨停池筛竞价一字（首封=末封且 09:25–09:30）。"""
    sub = _zt_df_one_word_subset(df_up)
    if sub is None or sub.empty:
        return []
    code_col = _df_col(sub, "代码")
    name_col = _df_col(sub, "名称")
    if not code_col:
        return []
    chg_col = next((c for c in ("涨跌幅", "今日涨跌幅") if c in sub.columns), None)
    items: list[dict] = []
    for _, row in sub.iterrows():
        code = str(row.get(code_col) or "").zfill(6)
        pct = pd.to_numeric(row.get(chg_col), errors="coerce") if chg_col else None
        row_d = row.to_dict()
        sector = "--"
        for key in ("涨停原因类别", "涨停原因", "所属行业", "行业"):
            val = row_d.get(key)
            if val is not None and str(val).strip() not in ("", "--", "nan"):
                sector = str(val).split("+")[0].strip() or str(val).strip()
                break
        seal = _parse_seal_amount_raw(row_d.get("封板资金") or row_d.get("封板金额"))
        items.append({
            "code": code,
            "name": str(row.get(name_col) or code).strip() if name_col else code,
            "openPct": round(float(pct), 2) if pct is not None and pd.notna(pct) else None,
            "sector": sector,
            "sealAmount": seal,
        })
    items.sort(key=lambda x: (-(x.get("sealAmount") or 0), -(x.get("openPct") or 0)))
    return items


def _one_word_items_from_clist() -> list[dict]:
    """
    9:25 竞价快照：当前价 >= 涨停价 → 视为竞价一字板。
    直接用 f3（涨跌幅）判断，不依赖 high/low（竞价阶段 low=昨收，检查无意义）。
    """
    items: list[dict] = []
    for row in _fetch_em_high_chg_stock_rows():
        chg = pd.to_numeric(row.get("f3"), errors="coerce")
        pre = pd.to_numeric(row.get("f18"), errors="coerce")
        if chg is None or pd.isna(chg) or pre is None or pd.isna(pre) or float(pre) <= 0:
            continue
        code = str(row.get("f12") or "").zfill(6)
        # 科创板(688)/创业板(300) 20% 涨停，其余 10%
        min_pct = 19.5 if code[:3] in ("688", "300") else 9.5
        if float(chg) < min_pct:
            continue
        open_pct = (float(pd.to_numeric(row.get("f17"), errors="coerce") or 0) - float(pre)) / float(pre) * 100
        sector = str(row.get("f100") or "").strip()
        items.append({
            "code": code,
            "name": str(row.get("f14") or code).strip(),
            "openPct": round(float(chg), 2),
            "sector": sector if sector not in ("", "--", "nan") else "--",
            "sealAmount": None,
        })
    items.sort(key=lambda x: (-(x.get("openPct") or 0),))
    return items


def _stock_limit_ratio(code: str, name: str = "") -> float:
    """按板块/ST 名称返回涨停比例。"""
    code = str(code or "").zfill(6)
    name = str(name or "").upper()
    if "ST" in name:
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("4", "8", "92")):
        return 0.30
    return 0.10


def _is_limit_open(code: str, name: str, open_price, prev_close) -> bool:
    """竞价开盘价是否达到按分币四舍五入后的涨停价。"""
    try:
        from decimal import Decimal, ROUND_HALF_UP

        open_d = Decimal(str(open_price))
        prev_d = Decimal(str(prev_close))
        if open_d <= 0 or prev_d <= 0:
            return False
        ratio = Decimal(str(_stock_limit_ratio(code, name)))
        limit_price = (prev_d * (Decimal("1") + ratio)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return open_d >= limit_price
    except Exception:
        return False


def _one_word_items_from_open_snapshot() -> list[dict]:
    """全 A 开盘快照：竞价以涨停价开盘即计入，不要求盘中继续封板。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base_params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f17",
        "fs": _EM_A_SHARE_FS,
        "fields": "f12,f14,f17,f18,f100,f3",
    }

    def _fetch_page(page: int) -> tuple[int, list[dict]]:
        for url in _EM_A_SHARE_CLIST_URLS:
            try:
                params = {**base_params, "pn": str(page)}
                response = requests.get(url, params=params, headers=headers, timeout=6)
                data = response.json().get("data") or {}
                diff = data.get("diff") or []
                rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
                if rows:
                    return int(data.get("total") or 0), rows
            except Exception:
                continue
        return 0, []

    total, first_rows = _fetch_page(1)
    if not first_rows:
        return []
    pages = max(1, math.ceil(total / int(base_params["pz"])))
    rows = list(first_rows)
    if pages > 1:
        with ThreadPoolExecutor(max_workers=min(6, pages - 1)) as pool:
            futures = [pool.submit(_fetch_page, page) for page in range(2, pages + 1)]
            for future in as_completed(futures):
                _, chunk = future.result()
                rows.extend(chunk)

    items = []
    for row in rows:
        code = str(row.get("f12") or "").zfill(6)
        name = str(row.get("f14") or code).strip()
        open_price = pd.to_numeric(row.get("f17"), errors="coerce")
        prev_close = pd.to_numeric(row.get("f18"), errors="coerce")
        if not _is_limit_open(code, name, open_price, prev_close):
            continue
        open_pct = (float(open_price) - float(prev_close)) / float(prev_close) * 100
        sector = str(row.get("f100") or "").strip()
        items.append({
            "code": code,
            "name": name,
            "openPct": round(open_pct, 2),
            "sector": sector if sector not in ("", "--", "nan") else "--",
            "sealAmount": None,
        })
    return items


def _merge_one_word_items(*groups: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in groups:
        for item in group or []:
            code = str(item.get("code") or "").zfill(6)
            if not code:
                continue
            if code in merged:
                current = merged[code]
                for key in ("name", "sector", "sealAmount", "openPct"):
                    if current.get(key) in (None, "", "--") and item.get(key) not in (None, "", "--"):
                        current[key] = item[key]
            else:
                merged[code] = dict(item)
    items = list(merged.values())
    items.sort(key=lambda x: (-(x.get("sealAmount") or 0), -(x.get("openPct") or 0)))
    return items


def fetch_auction_one_word_stocks(trade_d: str = "") -> list[dict]:
    """
    竞价一字板列表。9:25 后数据定格，按交易日缓存、日内不再刷新。

    优先东财盘中涨停池 getTopicZTPool（ak.stock_zt_pool_em）；
    9:25–9:30 池未就绪时 fallback clist 涨幅榜。
    """
    trade_d = (trade_d or date_str(bj_now()))[:8]
    today = date_str(bj_now())
    if trade_d > today:
        return []
    if trade_d == today and not _auction_data_ready():
        return []

    cache_key = f"auction_one_word_{trade_d}"
    ttl = _auction_cache_ttl() if trade_d == today else _AUCTION_ONE_WORD_FROZEN_TTL
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return list(cached)

    pool_items = _one_word_items_from_zt_df(fetch_limit_up(trade_d))
    if trade_d == today:
        in_open_capture_window = _auction_hm() <= 9 * 60 + 30
        open_items = _one_word_items_from_open_snapshot() if in_open_capture_window else []
        high_chg_items = _one_word_items_from_clist() if in_open_capture_window or not pool_items else []
        items = _merge_one_word_items(pool_items, open_items, high_chg_items)
        log.info(
            "auction one-word merged pool=%s open=%s high_chg=%s total=%s",
            len(pool_items),
            len(open_items),
            len(high_chg_items),
            len(items),
        )
    else:
        items = pool_items

    _cache_set(cache_key, items)
    log.info("auction one-word frozen %s n=%s", trade_d, len(items))
    return items


# 兼容旧名
fetch_em_auction_one_word_stocks = fetch_auction_one_word_stocks


def _auction_one_word_count(trade_d: str, spot_df: Optional[pd.DataFrame] = None) -> Optional[int]:
    """竞价一字板：9:15–9:26 live 刷新，9:26 起日级冻结。"""
    trade_d = (trade_d or "")[:8]
    today = date_str(bj_now())
    if trade_d == today and not _auction_data_ready():
        return None
    try:
        return len(fetch_auction_one_word_stocks(trade_d))
    except Exception:
        return None


def fetch_foreign_sentiment() -> list[dict]:
    """外盘情绪小卡（6项）"""
    key = "foreign_sent"
    cached = _cache_get(key, 300)
    if cached:
        return cached
    cards = []
    try:
        df = ak.stock_hk_index_spot_em()
        names = ["恒生指数", "恒生科技", "国企指数"]
        for n in names:
            row = df[df["名称"] == n]
            if row.empty:
                continue
            chg = float(row.iloc[0].get("涨跌幅", 0) or 0)
            cards.append({"name": n, "value": f"{chg:+.2f}%", "up": chg >= 0})
    except Exception:
        pass
    try:
        df_us = ak.index_us_stock_sina()
        if df_us is not None:
            for n in ("纳斯达克", "道琼斯", "标普500"):
                row = df_us[df_us["名称"].astype(str).str.contains(n, na=False)]
                if not row.empty:
                    chg = float(row.iloc[0].get("涨跌幅", 0) or 0)
                    cards.append({"name": n, "value": f"{chg:+.2f}%", "up": chg >= 0})
    except Exception:
        pass
    while len(cards) < 6:
        cards.append({"name": f"外盘{len(cards)+1}", "value": "--", "up": False})
    _cache_set(key, cards[:6])
    return cards[:6]


def _normalize_amount(raw) -> str:
    if raw is None or raw in ("--", "-", ""):
        return "--"
    s = str(raw).replace(",", "").strip()
    if "亿" in s:
        return s
    try:
        v = float(s)
        if v >= 10000:
            return f"{round(v / 1e8)}亿"
        return f"{round(v)}亿"
    except Exception:
        return s


_TENCENT_HEADERS = {"User-Agent": "Mozilla/5.0"}
# 指数成交额兜底：上证 + 深成指（与同花顺「两市」更接近，非深证综指 399106）。
_MARKET_AMOUNT_QT_CODES = ("sh000001", "sz399001")
_MARKET_AMOUNT_BS_CODES = ("sh.000001", "sz.399001")
_EM_BJ_FS = "m:0+t:81"


def _parse_tencent_qt_amount_yuan(text: str, symbol: str) -> float:
    """解析 qt.gtimg.cn 返回的指数成交额（元）"""
    m = re.search(rf'v_{re.escape(symbol)}="([^"]+)"', text)
    if not m:
        return 0.0
    for part in m.group(1).split("~"):
        if "/" in part and part.count("/") == 2:
            try:
                return float(part.split("/")[2])
            except Exception:
                pass
    parts = m.group(1).split("~")
    if len(parts) > 37:
        try:
            return float(parts[37]) * 1e4
        except Exception:
            pass
    return 0.0


def _amount_yuan_to_yi(total: float) -> tuple[str, float]:
    if total <= 1e10:
        return "--", 0.0
    yi = float(round(total / 1e8))
    return f"{int(yi)}亿", yi


def _parse_sse_deal_stock_amount_yi(df: Optional[pd.DataFrame]) -> float:
    """上交所每日概况：股票类成交金额（亿元）。"""
    if df is None or df.empty:
        return 0.0
    label_col = df.columns[0]
    stock_col = df.columns[1] if len(df.columns) > 1 else None
    for _, row in df.iterrows():
        label = str(row.get(label_col, row.iloc[0]))
        if "成交金额" not in label:
            continue
        if stock_col is not None:
            v = pd.to_numeric(row.get(stock_col, row.iloc[1]), errors="coerce")
        else:
            v = pd.to_numeric(row.iloc[1], errors="coerce")
        if pd.notna(v) and float(v) > 0:
            return float(v)
    return 0.0


def _parse_szse_stock_amount_yi(df: Optional[pd.DataFrame]) -> float:
    """深交所每日概况：证券类别=股票 的成交金额（元→亿）。"""
    if df is None or df.empty:
        return 0.0
    cat_col = df.columns[0]
    amt_col = "成交金额" if "成交金额" in df.columns else df.columns[2]
    for _, row in df.iterrows():
        if str(row.get(cat_col, row.iloc[0])).strip() != "股票":
            continue
        v = pd.to_numeric(row.get(amt_col, row.iloc[2]), errors="coerce")
        if pd.notna(v) and float(v) > 0:
            return float(v) / 1e8
    return 0.0


def _bj_stock_codes() -> list[str]:
    """北交所股票代码（当日缓存）。"""
    key = f"bj_codes_{date_str(bj_now())}"
    cached = _cache_get(key, 86400)
    if cached is not None:
        return list(cached)
    codes: list[str] = []
    try:
        df = ak.stock_info_bj_name_code()
        codes = df["证券代码"].astype(str).str.zfill(6).tolist()
    except Exception:
        pass
    _cache_set(key, codes)
    return codes


def _fetch_bj_market_amount_em_clist() -> float:
    """东财北交所列表分页汇总成交额（亿）。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": _EM_BJ_FS,
        "fields": "f6",
    }
    total_yuan = 0.0
    for url in _EM_A_SHARE_CLIST_URLS:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12)
            data = r.json().get("data") or {}
            total = int(data.get("total") or 0)
            diff = data.get("diff") or []
            rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if total <= 0 or not rows:
                continue
            amount = pd.to_numeric(pd.Series([row.get("f6") for row in rows]), errors="coerce")
            total_yuan = float(amount.sum())
            pages = max(1, math.ceil(total / int(params["pz"])))
            for pn in range(2, pages + 1):
                p = dict(params)
                p["pn"] = str(pn)
                r = requests.get(url, params=p, headers=headers, timeout=12)
                diff = (r.json().get("data") or {}).get("diff") or []
                rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
                if rows:
                    amount = pd.to_numeric(pd.Series([row.get("f6") for row in rows]), errors="coerce")
                    total_yuan += float(amount.sum())
            if total_yuan > 0:
                return round(total_yuan / 1e8, 1)
        except Exception:
            continue
    return 0.0


def _fetch_bj_market_amount_ulist() -> float:
    """东财 ulist 按北交所代码批量汇总成交额（亿）。"""
    codes = _bj_stock_codes()
    if not codes:
        return 0.0
    headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    total_yuan = 0.0
    for i in range(0, len(codes), 50):
        secids = ",".join(f"0.{c}" for c in codes[i : i + 50])
        try:
            r = requests.get(
                url,
                params={
                    "fltt": "2",
                    "fields": "f6",
                    "secids": secids,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                },
                headers=headers,
                timeout=20,
            )
            diff = (r.json().get("data") or {}).get("diff") or []
            total_yuan += sum(float(x.get("f6") or 0) for x in diff)
        except Exception:
            continue
    if total_yuan > 0:
        return round(total_yuan / 1e8, 1)
    return 0.0


def _fetch_bj_market_amount_yi(trade_d: str) -> float:
    """北交所 A 股当日成交额（亿）；仅当日。"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(bj_now()):
        return 0.0
    key = f"bj_amt_{trade_d}"
    cached = _cache_get(key, 120)
    if cached is not None:
        return float(cached)

    yi = _fetch_bj_market_amount_em_clist()
    if yi < 50:
        yi = _fetch_bj_market_amount_ulist()
    _cache_set(key, yi)
    return yi


def _fetch_market_amount_exchange(trade_d: str) -> tuple[str, float]:
    """沪深（+当日北交所）交易所股票成交额，口径贴近同花顺「市场量能」。"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return "--", 0.0
    total_yi = 0.0
    try:
        sse_df = ak.stock_sse_deal_daily(date=trade_d)
        total_yi += _parse_sse_deal_stock_amount_yi(sse_df)
    except Exception:
        pass
    try:
        sz_df = ak.stock_szse_summary(trade_d)
        total_yi += _parse_szse_stock_amount_yi(sz_df)
    except Exception:
        pass
    try:
        bj_yi = _fetch_bj_market_amount_yi(trade_d)
        if bj_yi > 0:
            total_yi += bj_yi
    except Exception:
        pass
    if total_yi >= 3000:
        yi = float(round(total_yi))
        return f"{int(yi)}亿", yi
    return "--", 0.0


def _fetch_market_amount_tencent(trade_d: str) -> tuple[str, float]:
    """腾讯财经：当日实时两市成交额（历史日请用 Baostock）"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(bj_now()):
        return "--", 0.0
    try:
        r = requests.get(
            "https://qt.gtimg.cn/q=" + ",".join(_MARKET_AMOUNT_QT_CODES),
            headers=_TENCENT_HEADERS,
            timeout=15,
        )
        total = sum(_parse_tencent_qt_amount_yuan(r.text, sym) for sym in _MARKET_AMOUNT_QT_CODES)
        return _amount_yuan_to_yi(total)
    except Exception:
        pass
    return "--", 0.0


def _fetch_market_amount_baostock(trade_d: str) -> tuple[str, float]:
    """Baostock：历史日成交额（盘后稳定）"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return "--", 0.0
    try:
        import baostock as bs
    except ImportError:
        return "--", 0.0
    d = f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}"
    total = 0.0
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return "--", 0.0
        for code in _MARKET_AMOUNT_BS_CODES:
            rs = bs.query_history_k_data_plus(
                code, "date,amount", start_date=d, end_date=d, frequency="d"
            )
            if rs.error_code != "0":
                continue
            while rs.next():
                row = rs.get_row_data()
                if row and len(row) > 1:
                    total += float(row[1] or 0)
    except Exception:
        pass
    finally:
        try:
            import baostock as bs

            bs.logout()
        except Exception:
            pass
    return _amount_yuan_to_yi(total)


def _fetch_market_amount_akshare_em(trade_d: str) -> tuple[str, float]:
    """东财指数日线（akshare 兜底，网络不稳时可能失败）"""
    trade_d = (trade_d or "")[:8]
    try:
        d = f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}"
        total = 0.0
        for sym in _MARKET_AMOUNT_QT_CODES:
            df = ak.stock_zh_index_daily_em(symbol=sym)
            if df is None or df.empty:
                continue
            date_col = "date" if "date" in df.columns else df.columns[0]
            amt_col = "amount" if "amount" in df.columns else None
            if not amt_col:
                for c in df.columns:
                    if "成交额" in str(c) or c == "amount":
                        amt_col = c
                        break
            if not amt_col:
                continue
            row = df[df[date_col].astype(str).str[:10] == d]
            if not row.empty:
                total += float(pd.to_numeric(row.iloc[0][amt_col], errors="coerce") or 0)
        return _amount_yuan_to_yi(total)
    except Exception:
        pass
    return "--", 0.0


def _fetch_daily_market_amount_with_raw(trade_d: str) -> tuple[str, float]:
    """指定交易日 A 股成交额（亿）；优先交易所沪深京股票口径，再东财聚合/指数兜底。"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return "--", 0.0
    key = f"market_amt_{trade_d}"
    ttl = 90 if trade_d == date_str(bj_now()) else 86400
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached

    today = date_str(bj_now())
    if trade_d == today:
        amt, raw = _fetch_market_amount_exchange(trade_d)
        if raw > 0:
            result = (amt, raw)
            _cache_set(key, result)
            return result
        snap = _fetch_em_a_share_snapshot()
        raw = float(snap.get("amount_raw") or 0)
        if raw > 0:
            result = (f"{round(raw)}亿", raw)
            _cache_set(key, result)
            return result
        chain = (
            _fetch_market_amount_tencent,
            _fetch_market_amount_baostock,
            _fetch_market_amount_akshare_em,
        )
    else:
        amt, raw = _fetch_market_amount_exchange(trade_d)
        if raw > 0:
            result = (amt, raw)
            _cache_set(key, result)
            return result
        chain = (_fetch_market_amount_baostock, _fetch_market_amount_akshare_em)

    for fn in chain:
        amt, raw = fn(trade_d)
        if raw > 0:
            result = (amt, raw)
            _cache_set(key, result)
            return result

    result = ("--", 0.0)
    _cache_set(key, result)
    return result


def _fetch_daily_market_amount(trade_d: str) -> str:
    amt, _ = _fetch_daily_market_amount_with_raw(trade_d)
    return _normalize_amount(amt)


def _intraday_snap_hhmm(now: Optional[datetime] = None) -> str:
    """对齐 2 分钟刷新网格"""
    now = now or bj_now()
    minute = now.minute - (now.minute % 2)
    return f"{now.hour:02d}{minute:02d}"


def _in_trading_minute_window(now: Optional[datetime] = None) -> bool:
    now = now or bj_now()
    hm = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= hm <= 11 * 60 + 30) or (13 * 60 <= hm <= 15 * 60)


def record_intraday_volume_snapshot(
    trade_d: str,
    amount_raw: float,
    now: Optional[datetime] = None,
) -> None:
    """盘中记录两市累计成交额（亿），供次日同时刻对比"""
    trade_d = (trade_d or "")[:8]
    if not trade_d or amount_raw <= 0:
        return
    now = now or bj_now()
    if not _in_trading_minute_window(now):
        return
    hhmm = _intraday_snap_hhmm(now)
    key = f"vol_intraday_map_{trade_d}"
    snap_map = dict(_cache_get(key, 86400 * 10) or {})
    snap_map[hhmm] = round(float(amount_raw), 1)
    _cache_set(key, snap_map)


def _lookup_volume_snapshot(ref_d: str, hhmm: str) -> Optional[float]:
    snap_map = _cache_get(f"vol_intraday_map_{ref_d}", 86400 * 10) or {}
    if snap_map:
        if hhmm in snap_map:
            return float(snap_map[hhmm])
        prior = sorted(k for k in snap_map.keys() if k <= hhmm)
        if prior:
            return float(snap_map[prior[-1]])
    try:
        from history_store import fetch_intraday_volume_at_or_before

        snap_time = f"{hhmm[:2]}:{hhmm[2:4]}"
        persisted = fetch_intraday_volume_at_or_before(ref_d, snap_time)
        if persisted and persisted > 0:
            return float(persisted)
    except Exception:
        pass
    return None


def _fetch_market_amount_through_time_baostock(
    trade_d: str,
    hour: int,
    minute: int,
) -> Optional[float]:
    """Baostock 5 分钟线：累计至指定时刻的两市成交额（亿）"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return None
    hm = hour * 60 + minute
    if hm < 9 * 60 + 30:
        return None
    if hm > 15 * 60:
        hour, minute = 15, 0
    d = f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}"
    end_ts = datetime.strptime(f"{d} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")

    def _in_session(dt: datetime) -> bool:
        t = dt.hour * 60 + dt.minute
        return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60)

    cache_key = f"vol_through_{trade_d}_{hour:02d}{minute:02d}"
    cached = _cache_get(cache_key, 86400 * 30)
    if cached is not None:
        return float(cached)

    total = 0.0
    try:
        import baostock as bs
    except ImportError:
        return None

    try:
        lg = bs.login()
        if lg.error_code != "0":
            return None
        for code in _MARKET_AMOUNT_BS_CODES:
            rs = bs.query_history_k_data_plus(
                code,
                "date,time,amount",
                start_date=d,
                end_date=d,
                frequency="5",
                adjustflag="3",
            )
            if rs.error_code != "0":
                continue
            while rs.next():
                row = rs.get_row_data()
                if not row or len(row) < 3:
                    continue
                try:
                    dt = datetime.strptime(str(row[1])[:19], "%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError):
                    continue
                if not _in_session(dt) or dt > end_ts:
                    continue
                total += float(row[2] or 0)
    except Exception:
        return None
    finally:
        try:
            import baostock as bs

            bs.logout()
        except Exception:
            pass

    if total <= 0:
        return None
    _, yi = _amount_yuan_to_yi(total)
    if yi <= 0:
        return None
    _cache_set(cache_key, yi)
    return float(yi)


def fetch_ref_volume_at_same_time(
    ref_d: str,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """
    昨日（ref 日）同一时刻累计两市成交额（亿）。
    优先读盘中快照；无快照时用 Baostock 5 分钟线回溯。
    """
    ref_d = (ref_d or "")[:8]
    if not ref_d:
        return None
    now = now or bj_now()
    if not _in_trading_minute_window(now):
        return None
    hhmm = _intraday_snap_hhmm(now)
    snap = _lookup_volume_snapshot(ref_d, hhmm)
    if snap and snap > 0:
        return snap
    return _fetch_market_amount_through_time_baostock(ref_d, now.hour, now.minute)


def fetch_ref_volume_prev_label(
    ref_metrics: Optional[dict],
    ref_d: str = "",
    now: Optional[datetime] = None,
) -> tuple[str, Optional[float]]:
    """
    全市量能「昨」：盘中为 ref 日同时刻；休市/盘前为 ref 日收盘量能。
    """
    ref_metrics = ref_metrics or {}
    ref_d = (ref_d or ref_metrics.get("date") or "").replace("-", "")[:8]
    now = now or bj_now()
    if _in_trading_minute_window(now):
        same = fetch_ref_volume_at_same_time(ref_d, now)
        if same and same > 0:
            return f"{round(float(same))}亿", float(same)
        return "--", None
    raw = ref_metrics.get("volume_raw")
    if raw is not None:
        try:
            yi = float(raw)
            if yi > 0:
                return f"{round(yi)}亿", yi
        except (TypeError, ValueError):
            pass
    return "--", None


_SSE_INDEX_QT = "s_sh000001"
_SSE_INDEX_BS = "sh.000001"


def fetch_prev_zt_avg_chg(ref_d: str) -> Optional[float]:
    """
    昨日涨停指数：ref_d 涨停股在次日（advice_d）的平均涨跌幅。
    直接从 stock_zt_pool_previous_em 接口获取，无需自行对码计算。
    含义：
      均涨幅 ≈ +10% → 大部分续板，接力结构强
      均涨幅 ≈ 0%   → 续板少，结构一般
      均涨幅 < 0%   → 高位大面，情绪转弱信号
    """
    ref_d = (ref_d or "")[:8]
    if not ref_d:
        return None
    key = f"prev_zt_avg_{ref_d}"
    cached = _cache_get(key, 7200)
    if cached is not None:
        return float(cached)
    try:
        df = ak.stock_zt_pool_previous_em(date=ref_d)
        if df is None or df.empty or "涨跌幅" not in df.columns:
            return None
        import pandas as pd
        chgs = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
        if chgs.empty:
            return None
        avg = round(float(chgs.mean()), 2)
        _cache_set(key, avg)
        return avg
    except Exception:
        return None


def _fetch_sse_chg_tencent(trade_d: str) -> Optional[float]:
    """腾讯财经：当日实时上证涨跌幅 %"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(bj_now()):
        return None
    try:
        r = requests.get(
            f"https://qt.gtimg.cn/q={_SSE_INDEX_QT}",
            headers=_TENCENT_HEADERS,
            timeout=15,
        )
        m = re.search(r'v_s_sh000001="([^"]+)"', r.text)
        if not m:
            return None
        parts = m.group(1).split("~")
        if len(parts) > 5:
            return round(float(parts[5]), 2)
    except Exception:
        pass
    return None


def _fetch_sse_chg_baostock(trade_d: str) -> Optional[float]:
    """Baostock：历史/当日上证涨跌幅 %"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return None
    try:
        import baostock as bs
    except ImportError:
        return None
    d = f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}"
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return None
        rs = bs.query_history_k_data_plus(
            _SSE_INDEX_BS, "date,pctChg", start_date=d, end_date=d, frequency="d"
        )
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if row and len(row) > 1 and row[1] not in (None, ""):
                return round(float(row[1]), 2)
    except Exception:
        pass
    finally:
        try:
            import baostock as bs

            bs.logout()
        except Exception:
            pass
    return None


def _fetch_sse_chg_sina(trade_d: str) -> Optional[float]:
    """新浪 K 线：历史上证涨跌幅 %"""
    trade_d = (trade_d or "")[:8]
    try:
        r = requests.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": "sh000001", "scale": 240, "ma": "no", "datalen": 30},
            timeout=15,
        )
        rows = r.json()
        for i, row in enumerate(rows):
            if str(row.get("day", "")).replace("-", "")[:8] != trade_d:
                continue
            if i <= 0:
                return None
            prev_close = float(rows[i - 1]["close"])
            cur_close = float(row["close"])
            if prev_close:
                return round((cur_close - prev_close) / prev_close * 100, 2)
    except Exception:
        pass
    return None


def _fetch_sse_chg_akshare(trade_d: str) -> Optional[float]:
    """akshare 新浪日线（兜底）"""
    trade_d = (trade_d or "")[:8]
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return None
        df = df.copy()
        col_date = "date" if "date" in df.columns else df.columns[0]
        df["_d"] = pd.to_datetime(df[col_date]).dt.strftime("%Y%m%d")
        idx = df[df["_d"] == trade_d[:8]]
        if idx.empty:
            return None
        row = idx.iloc[-1]
        pos = df[df["_d"] == trade_d[:8]].index[0]
        if pos <= 0 or "close" not in df.columns:
            return None
        prev_close = float(df.iloc[pos - 1]["close"])
        cur_close = float(row["close"])
        if prev_close:
            return round((cur_close - prev_close) / prev_close * 100, 2)
    except Exception:
        pass
    return None


def fetch_sse_index_change(trade_d: str) -> float:
    """指定交易日上证指数涨跌幅 %；优先腾讯/Baostock，新浪/akshare 兜底"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return 0.0
    key = f"sse_chg_{trade_d}"
    cached = _cache_get(key, 86400)
    if cached is not None:
        return float(cached)

    today = date_str(bj_now())
    if trade_d == today:
        chain = (
            _fetch_sse_chg_tencent,
            _fetch_sse_chg_baostock,
            _fetch_sse_chg_sina,
            _fetch_sse_chg_akshare,
        )
    else:
        chain = (
            _fetch_sse_chg_baostock,
            _fetch_sse_chg_sina,
            _fetch_sse_chg_akshare,
            _fetch_sse_chg_tencent,
        )

    for fn in chain:
        chg = fn(trade_d)
        if chg is not None:
            _cache_set(key, chg)
            return float(chg)
    return 0.0


def _after_market_close(now: Optional[datetime] = None) -> bool:
    """A 股收盘后（15:00 及以后）"""
    now = now or bj_now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 0)


def _parse_legu_stat_date(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    if "item" in df.columns and "value" in df.columns:
        for _, row in df.iterrows():
            item = str(row.get("item", "")).strip()
            if "统计日期" in item:
                raw = str(row.get("value", "")).strip()
                return raw[:10].replace("-", "")
    return ""


def _fetch_market_breadth_live() -> tuple[int, int, str]:
    """乐股：全 A 上涨/下跌家数（返回统计日期 YYYYMMDD）"""
    try:
        df = ak.stock_market_activity_legu()
        parsed = _parse_market_activity_df(df)
        adv = int(parsed.get("advance") or 0)
        dec = int(parsed.get("decline") or 0)
        stat_d = _parse_legu_stat_date(df)
        if _breadth_valid(adv, dec):
            return adv, dec, stat_d
    except Exception:
        pass
    adv, dec = _fetch_market_breadth_spot()
    if _breadth_valid(adv, dec):
        return adv, dec, date_str(bj_now())
    return 0, 0, ""


def _breadth_from_daily_market(trade_d: str) -> tuple[int, int]:
    try:
        from history_store import fetch_daily_detail

        detail = fetch_daily_detail((trade_d or "")[:8])
        if not detail:
            return 0, 0
        for item in detail.get("grid9") or []:
            if item.get("key") != "advance":
                continue
            adv = item.get("advance_up")
            if adv is None:
                adv = item.get("advanceUp")
            dec = item.get("decline_down")
            if dec is None:
                dec = item.get("declineDown")
            if adv is not None:
                adv_i, dec_i = int(adv or 0), int(dec or 0)
                if _breadth_valid(adv_i, dec_i):
                    return adv_i, dec_i
        metrics = detail.get("metrics") or {}
        adv = int(metrics.get("advance_count") or 0)
        dec = int(metrics.get("decline_count") or 0)
        if _breadth_valid(adv, dec):
            return adv, dec
    except Exception:
        pass
    return 0, 0


def _fetch_market_breadth_baostock(trade_d: str) -> tuple[int, int]:
    """历史日上涨/下跌家数（Baostock 逐股统计，结果长期缓存）"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return 0, 0
    key = f"market_breadth_bs_{trade_d}"
    cached = _cache_get(key, 86400 * 90)
    if cached is not None:
        return int(cached.get("advance", 0)), int(cached.get("decline", 0))
    try:
        import baostock as bs
    except ImportError:
        return 0, 0
    fmt = f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}"
    adv = dec = 0
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return 0, 0
        codes: list[str] = []
        rs = bs.query_all_stock(day=fmt)
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if len(row) > 1 and row[1] == "1":
                codes.append(row[0])
        for code in codes:
            rs2 = bs.query_history_k_data_plus(
                code,
                "date,pctChg",
                start_date=fmt,
                end_date=fmt,
                frequency="d",
                adjustflag="3",
            )
            if rs2.error_code != "0":
                continue
            rows = []
            while rs2.error_code == "0" and rs2.next():
                rows.append(rs2.get_row_data())
            if not rows:
                continue
            try:
                pct = float(rows[0][1])
            except (TypeError, ValueError, IndexError):
                continue
            if pct > 0:
                adv += 1
            elif pct < 0:
                dec += 1
        bs.logout()
    except Exception:
        return 0, 0
    if adv or dec:
        _cache_set(key, {"advance": adv, "decline": dec})
    return adv, dec


def invalidate_market_breadth_cache(trade_d: Optional[str] = None) -> None:
    """清涨跌家数内存缓存（warm-home / 日终快照前调用）。"""
    if trade_d:
        d = (trade_d or "")[:8]
        _cache.pop(f"market_breadth_{d}", None)
        _cache.pop(f"market_breadth_bs_{d}", None)
        return
    for key in list(_cache.keys()):
        if key.startswith("market_breadth_"):
            _cache.pop(key, None)


def get_market_breadth(trade_d: str) -> tuple[int, int]:
    """
    指定交易日全市场上涨/下跌家数。
    当日优先乐股/东财实时；历史日读归档或 Baostock。
    """
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return 0, 0

    today = date_str(bj_now())
    key = f"market_breadth_{trade_d}"
    cache_ttl = 90 if trade_d == today else 86400 * 30
    cached = _cache_get(key, cache_ttl)
    if cached is not None and trade_d != today:
        adv = int(cached.get("advance", 0))
        dec = int(cached.get("decline", 0))
        if _breadth_valid(adv, dec):
            return adv, dec

    if trade_d == today:
        adv, dec, stat_d = _fetch_market_breadth_live()
        if stat_d == trade_d and _breadth_valid(adv, dec):
            _cache_set(key, {"advance": adv, "decline": dec})
            return adv, dec
        adv, dec = _fetch_market_breadth_spot()
        if _breadth_valid(adv, dec):
            _cache_set(key, {"advance": adv, "decline": dec})
            return adv, dec
        if cached is not None:
            adv = int(cached.get("advance", 0))
            dec = int(cached.get("decline", 0))
            if _breadth_valid(adv, dec):
                return adv, dec

    adv, dec = _breadth_from_daily_market(trade_d)
    if _breadth_valid(adv, dec):
        _cache_set(key, {"advance": adv, "decline": dec})
        return adv, dec

    if trade_d != today:
        adv, dec, stat_d = _fetch_market_breadth_live()
        if stat_d == trade_d and _breadth_valid(adv, dec):
            _cache_set(key, {"advance": adv, "decline": dec})
            return adv, dec

    adv, dec = _fetch_market_breadth_baostock(trade_d)
    if _breadth_valid(adv, dec):
        _cache_set(key, {"advance": adv, "decline": dec})
    return adv, dec


def _fill_metrics_breadth(metrics: dict, trade_d: str) -> dict:
    """补齐 metrics 中的上涨/下跌家数（避免 0 误写入前日对比）"""
    trade_d = (trade_d or "")[:8]
    today = date_str(bj_now())
    adv = int(metrics.get("advance_count") or 0)
    dec = int(metrics.get("decline_count") or 0)
    # 当日必须用实时涨跌家数，不能用 MySQL 里未刷新的归档值
    if trade_d == today:
        adv2, dec2 = get_market_breadth(trade_d)
        if _breadth_valid(adv2, dec2):
            metrics = dict(metrics)
            metrics["advance_count"] = adv2
            metrics["decline_count"] = dec2
        return metrics
    if _breadth_valid(adv, dec):
        return metrics
    adv2, dec2 = get_market_breadth(trade_d)
    if _breadth_valid(adv2, dec2):
        metrics = dict(metrics)
        metrics["advance_count"] = adv2
        metrics["decline_count"] = dec2
    return metrics


def _fmt_prev_breadth(val, dec=None) -> str:
    if val is None or val in ("-", "--", ""):
        return "--"
    try:
        n = int(val)
    except (TypeError, ValueError):
        return str(val)
    dec_n = 0
    if dec not in (None, "-", "--", ""):
        try:
            dec_n = int(dec)
        except (TypeError, ValueError):
            dec_n = 0
    if n == 0 and dec_n == 0:
        return "--"
    return str(n)


def _fmt_adv_decline(metrics: dict) -> str:
    adv = metrics.get("advance_count", 0)
    dec = metrics.get("decline_count", 0)
    if adv or dec:
        return f"涨{adv}/跌{dec}"
    return str(adv) if adv else "--"


def build_yesterday_sentiment(metrics: dict, prev_metrics: Optional[dict] = None) -> list:
    """昨日情绪概览 10 项（含连板占比）"""
    prev = prev_metrics or {}

    def _y(key, suffix=""):
        v = prev.get(key, "-")
        if suffix and v != "-":
            return f"{v}{suffix}"
        return str(v)

    vol = _normalize_amount(metrics.get("volume_amount", "--"))
    vol_prev = _normalize_amount(prev.get("volume_amount", "--"))
    adv = metrics.get("advance_count", 0)
    dec = metrics.get("decline_count", 0)
    prev_adv = prev.get("advance_count", "-")
    prev_dec = prev.get("decline_count", "-")
    prev_adv_s = _fmt_prev_breadth(prev_adv, prev_dec)
    prev_adv_cmp = None if prev_adv_s == "--" else prev_adv

    # multi_board_count 必须是真实数据（非 None），否则不显示连板占比
    mb_raw = metrics.get("multi_board_count")
    lu = int(metrics.get("limit_up_count") or 0)
    mb = int(mb_raw) if mb_raw is not None else None
    mb_prev_raw = prev.get("multi_board_count")
    lu_prev = int(prev.get("limit_up_count") or 0)
    mb_prev = int(mb_prev_raw) if mb_prev_raw is not None else None
    cont_ratio = mb / lu * 100 if mb is not None and lu else None
    cont_ratio_prev = mb_prev / lu_prev * 100 if mb_prev is not None and lu_prev else None
    cont_val = f"{cont_ratio:.1f}%" if cont_ratio is not None else "--"
    cont_prev = f"{cont_ratio_prev:.1f}%" if cont_ratio_prev is not None else "--"

    rows = [
        {"key": "height", "label": "连板高度", "value": f"{metrics['max_board']}板", "yesterday": f"{_y('max_board')}板", "trend": _trend(metrics["max_board"], prev.get("max_board"))},
        {"key": "limitUp", "label": "涨停家数", "value": str(metrics["limit_up_count"]), "yesterday": str(_y("limit_up_count")), "trend": _trend(metrics["limit_up_count"], prev.get("limit_up_count"))},
        {"key": "seal", "label": "封板率", "value": f"{metrics['seal_rate']:.0f}%", "yesterday": f"{_y('seal_rate')}%", "trend": _trend(metrics["seal_rate"], prev.get("seal_rate"))},
        {"key": "promote", "label": "晋级率", "value": f"{metrics['promote_rate']:.0f}%", "yesterday": f"{_y('promote_rate')}%", "trend": _trend(metrics["promote_rate"], prev.get("promote_rate"))},
        {"key": "limitDown", "label": "跌停家数", "value": str(metrics["limit_down_count"]), "yesterday": str(_y("limit_down_count")), "trend": _trend(metrics["limit_down_count"], prev.get("limit_down_count"))},
        {"key": "break", "label": "炸板率", "value": f"{metrics['break_rate']:.0f}%", "yesterday": f"{_y('break_rate')}%", "trend": _trend(metrics["break_rate"], prev.get("break_rate"))},
        {"key": "oneWord", "label": "一字板", "value": str(metrics.get("one_word_count", 0)), "yesterday": str(_y("one_word_count")), "trend": _trend(metrics.get("one_word_count", 0), prev.get("one_word_count"))},
        {"key": "volume", "label": "市场量能", "value": str(vol), "yesterday": str(vol_prev), "trend": _trend(metrics.get("volume_raw", 0), prev.get("volume_raw")) if prev.get("volume_raw") else "flat"},
        {
            "key": "advance",
            "label": "上涨家数",
            "value": str(adv) if _breadth_valid(adv, dec) else "--",
            "yesterday": prev_adv_s,
            "advance_up": adv,
            "prev_advance_up": prev_adv_cmp if prev_adv_cmp not in (None, "-") else prev_adv_s,
            "trend": _trend(adv, prev_adv_cmp),
        },
    ]
    if mb is not None and lu:  # 只有真实数据才显示，None 时不显示
        rows.append({
            "key": "continuationDepth",
            "label": "连板占比",
            "value": cont_val,
            "yesterday": cont_prev,
            "multi_board_count": mb,
            "limit_up_count": lu,
            "trend": _trend(mb / lu if lu else 0, mb_prev / lu_prev if mb_prev is not None and lu_prev else None),
        })

    # 成交额前10均涨幅（可选）
    top10_chg = metrics.get("top10_avg_chg")
    if top10_chg is not None:
        top10_chg_f = _safe_float(top10_chg)
        top10_prev = prev.get("top10_avg_chg")
        top10_prev_f = _safe_float(top10_prev)
        rows.append({
            "key": "top10AvgChg",
            "label": "成交额前10平均涨幅",
            "value": f"{top10_chg_f:+.2f}%" if top10_chg_f is not None else "--",
            "yesterday": f"{top10_prev_f:+.2f}%" if top10_prev_f is not None else "--",
            "trend": _trend(top10_chg_f, top10_prev_f),
        })
    # 高位板晋级率（≥3连板）：高位股开始大面时情绪转弱的前瞻信号
    hb_cont = metrics.get("high_board_promote_continued")
    hb_total = metrics.get("high_board_promote_total")
    hb_cont_prev = prev.get("high_board_promote_continued")
    hb_total_prev = prev.get("high_board_promote_total")
    if hb_total is not None and hb_total > 0:
        hb_rate = round(hb_cont / hb_total * 100, 1) if hb_cont is not None else 0.0
        hb_val = f"{hb_cont}/{hb_total}"
        hb_prev_rate = round(hb_cont_prev / hb_total_prev * 100, 1) if hb_cont_prev is not None and hb_total_prev else None
        hb_prev_val = f"{hb_cont_prev}/{hb_total_prev}" if hb_cont_prev is not None and hb_total_prev else "--"
        rows.append({
            "key": "highBoardPromote",
            "label": "高位板晋级",
            "value": hb_val,
            "yesterday": hb_prev_val,
            "high_board_promote_rate": hb_rate,
            "trend": _trend(hb_rate, hb_prev_rate),
        })

    # 板块集中度（如 metrics 中有数据）
    sc = metrics.get("sector_concentration") or {}
    if sc.get("total", 0) >= 10:
        top3r = sc.get("top3Ratio", 0)
        top_name = sc.get("topSector", "")
        sc_prev = (prev_metrics or {}).get("sector_concentration") or {}
        sc_prev_top3r = sc_prev.get("top3Ratio")
        rows.append({
            "key": "sectorConcentration",
            "label": "板块集中度",
            "value": f"{top3r:.0f}%",
            "displaySuffix": top_name,
            "topSectors": sc.get("topSectors", []),
            "yesterday": f"{sc_prev_top3r:.0f}%" if sc_prev_top3r is not None else "--",
            "trend": _trend(top3r, sc_prev_top3r),
        })
    display_order = {
        key: index
        for index, key in enumerate((
            "highBoardPromote", "promote", "break",
            "height", "seal", "limitUp",
            "limitDown", "advance", "volume",
            "oneWord", "continuationDepth", "top10AvgChg",
            "sectorConcentration",
        ))
    }
    return sorted(rows, key=lambda row: display_order.get(row.get("key"), len(display_order)))


def patch_grid9_live_breadth(
    grid9: list,
    metrics: dict,
    *,
    ref_d: str,
    advice_d: str,
) -> list:
    """
    盘中 ref 日仍为上一交易日时，仅「上涨家数」展示当日乐股/东财实时，昨=ref 日收盘。
    """
    ref_d = (ref_d or "")[:8]
    advice_d = (advice_d or "")[:8]
    today = date_str(bj_now())
    if advice_d != today or ref_d == today or not grid9:
        return grid9

    adv, dec, stat_d = _fetch_market_breadth_live()
    if stat_d != today or not _breadth_valid(adv, dec):
        adv, dec = _fetch_market_breadth_spot()
    if not _breadth_valid(adv, dec):
        return grid9

    ref_adv = int(metrics.get("advance_count") or 0)
    ref_dec = int(metrics.get("decline_count") or 0)
    prev_adv_s = _fmt_prev_breadth(ref_adv, ref_dec)
    prev_cmp = None if prev_adv_s == "--" else ref_adv

    out = []
    for item in grid9:
        cell = dict(item)
        if cell.get("key") == "advance":
            cell["value"] = str(adv)
            cell["yesterday"] = prev_adv_s
            cell["advance_up"] = adv
            cell["prev_advance_up"] = prev_cmp if prev_cmp is not None else prev_adv_s
            cell["trend"] = _trend(adv, prev_cmp)
        out.append(cell)
    return out


def build_grid_nine(metrics: dict, prev_metrics: Optional[dict] = None) -> list:
    return build_yesterday_sentiment(metrics, prev_metrics)


def calc_sector_concentration(trade_d: str) -> dict:
    """
    板块集中度：涨停池标签统计。
    数据来源 akshare 涨停池「涨停原因类别」，按 + 拆分计数，按家数取 Top5。
    """
    key = f"sector_conc_{trade_d}"
    cached = _cache_get(key, 900)
    if cached is not None:
        return cached

    empty = {
        "topSectors": [],
        "top3Ratio": 0.0,
        "hhi": 0.0,
        "total": 0,
        "topSector": "",
        "hotConceptCount": 0,
    }
    try:
        lu_df = fetch_limit_up(trade_d)
        if lu_df is None or lu_df.empty:
            return empty

        total = len(lu_df)
        concept_count: dict[str, int] = {}
        tag_col = next((c for c in ["涨停原因类别", "涨停原因", "所属行业"] if c in lu_df.columns), None)
        if tag_col:
            for tags_raw in lu_df[tag_col].dropna():
                tags = [t.strip() for t in str(tags_raw).split("+") if t.strip()]
                for tag in tags:
                    concept_count[tag] = concept_count.get(tag, 0) + 1

        if not concept_count:
            return empty

        hot = sorted(
            [{"name": k, "count": v, "chg": 0.0, "ratio": v} for k, v in concept_count.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        all_count = sum(h["count"] for h in hot)
        top3_count = sum(h["count"] for h in hot[:3])
        top3_ratio = round(top3_count / all_count * 100, 1) if all_count > 0 else 0.0
        hhi = round(sum((h["count"] / all_count) ** 2 for h in hot) * 100, 1) if all_count > 0 else 0.0

        result = {
            "topSectors": hot[:5],
            "top3Ratio": top3_ratio,
            "hhi": hhi,
            "total": total,
            "topSector": hot[0]["name"] if hot else "",
            "hotConceptCount": len(hot),
        }
        _cache_set(key, result)
        return result
    except Exception:
        import traceback
        traceback.print_exc()
        return empty


def _limit_up_board_stats(trade_d: str) -> tuple[int, int, int]:
    """首板数、连板数、最高连板"""
    df = fetch_limit_up(trade_d)
    if df is None or df.empty:
        return 0, 0, 0
    if "连板数" in df.columns:
        boards = pd.to_numeric(df["连板数"], errors="coerce").fillna(1)
        first_board = int((boards == 1).sum())
        multi_board = int((boards >= 2).sum())
        max_recent = int(boards.max())
        return first_board, multi_board, max_recent
    return len(df), 0, _max_board(df)


def _pool_codes_by_board(df_up: pd.DataFrame, multi: bool) -> list[str]:
    """从涨停池按首板/连板筛选代码"""
    if df_up is None or df_up.empty:
        return []
    code_col = "代码" if "代码" in df_up.columns else None
    if not code_col:
        return []
    codes = df_up[code_col].astype(str).str.zfill(6)
    if "连板数" not in df_up.columns:
        return codes.tolist() if not multi else []
    boards = pd.to_numeric(df_up["连板数"], errors="coerce").fillna(1)
    mask = boards >= 2 if multi else boards == 1
    return codes[mask].tolist()


def _pool_codes_by_max_board(df_up: pd.DataFrame) -> list[str]:
    """最高连板档个股代码"""
    if df_up is None or df_up.empty:
        return []
    code_col = "代码" if "代码" in df_up.columns else None
    if not code_col or "连板数" not in df_up.columns:
        return []
    boards = pd.to_numeric(df_up["连板数"], errors="coerce").fillna(1)
    max_b = int(boards.max())
    if max_b <= 0:
        return []
    return df_up.loc[boards == max_b, code_col].astype(str).str.zfill(6).tolist()


def _avg_auction_chg_from_spot(codes: list[str], spot_df: Optional[pd.DataFrame]) -> Optional[float]:
    """实时行情：今开相对昨收的竞价涨幅均值 %"""
    if not codes or spot_df is None or spot_df.empty:
        return None
    code_set = {c.zfill(6) for c in codes}
    df = spot_df.copy()
    df["_code"] = df["代码"].astype(str).str.zfill(6)
    sub = df[df["_code"].isin(code_set)]
    if sub.empty:
        return None
    o = pd.to_numeric(sub["今开"], errors="coerce")
    p = pd.to_numeric(sub["昨收"], errors="coerce").replace(0, pd.NA)
    chg = ((o - p) / p * 100).dropna()
    if chg.empty:
        return None
    return round(float(chg.mean()), 2)


def _code_open_pct_on_date(code: str, trade_d: str) -> Optional[float]:
    """指定交易日开盘相对前收的涨幅 %"""
    key = f"open_pct_{code}_{trade_d}"
    cached = _cache_get(key, 86400)
    if cached is not None:
        return cached
    try:
        start = (parse_date(trade_d) - timedelta(days=15)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code.zfill(6), period="daily",
            start_date=start, end_date=trade_d[:8], adjust="qfq",
        )
        if df is None or df.empty:
            return None
        df = df.copy()
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        df["_d"] = pd.to_datetime(df[date_col]).dt.strftime("%Y%m%d")
        rows = df[df["_d"] == trade_d[:8]]
        if rows.empty:
            return None
        pos = df.index.get_loc(rows.index[0])
        if pos == 0:
            return None
        open_p = float(rows.iloc[0]["开盘"])
        prev_close = float(df.iloc[pos - 1]["收盘"])
        if prev_close <= 0:
            return None
        chg = round((open_p - prev_close) / prev_close * 100, 2)
        _cache_set(key, chg)
        return chg
    except Exception:
        return None


def _avg_board_auction_chg_historical(pool_d: str, multi: bool, auction_d: str) -> Optional[float]:
    """历史：pool_d 涨停池在 auction_d 日开盘竞价涨幅均值"""
    key = f"board_auction_{pool_d}_{multi}_{auction_d}"
    cached = _cache_get(key, 86400)
    if cached is not None:
        return cached
    codes = _pool_codes_by_board(fetch_limit_up(pool_d), multi)
    if not codes:
        return None
    chgs = []
    for code in codes[:60]:
        c = _code_open_pct_on_date(code, auction_d)
        if c is not None:
            chgs.append(c)
    if not chgs:
        return None
    avg = round(sum(chgs) / len(chgs), 2)
    _cache_set(key, avg)
    return avg


def _avg_max_board_auction_chg_historical(pool_d: str, auction_d: str) -> Optional[float]:
    """历史：pool_d 最高连板档在 auction_d 日开盘竞价涨幅均值"""
    key = f"max_board_auction_{pool_d}_{auction_d}"
    cached = _cache_get(key, 86400)
    if cached is not None:
        return cached
    codes = _pool_codes_by_max_board(fetch_limit_up(pool_d))
    if not codes:
        return None
    chgs = []
    for code in codes[:60]:
        c = _code_open_pct_on_date(code, auction_d)
        if c is not None:
            chgs.append(c)
    if not chgs:
        return None
    avg = round(sum(chgs) / len(chgs), 2)
    _cache_set(key, avg)
    return avg


def _is_missing_value(val) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip().lower()
        return s in ("", "--", "-", "nan", "none", "null")
    try:
        if pd.isna(val):
            return True
    except Exception:
        pass
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return True
    return False


def _display_text(val, *, default: str = "--") -> str:
    if _is_missing_value(val):
        return default
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null"):
        return default
    return s


def _safe_float(val, default: Optional[float] = None) -> Optional[float]:
    if _is_missing_value(val):
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _pct_display(v: Optional[float]) -> str:
    f = _safe_float(v)
    if f is None:
        return "--"
    return f"{f:+.2f}%"


def _count_display(v: Optional[int]) -> str:
    if v is None:
        return "--"
    return str(int(v))


def _auction_zero_placeholder(val) -> bool:
    s = _display_text(val, default="")
    if not s or s == "--":
        return False
    s = s.replace("%", "").replace("+", "").strip()
    try:
        return abs(float(s)) < 1e-9
    except (TypeError, ValueError):
        return s in ("0", "0.0", "0.00")


def _auction_pct_display(v: Optional[float]) -> str:
    f = _safe_float(v)
    if f is None:
        return "--"
    return f"{f:+.2f}%"


_AUCTION_VALUE_KEYS = (
    "auctionVolume",
    "yesterdayFirst",
    "yesterdayMulti",
    "recentMulti",
    "top10AuctionChg",
)


def auction_items_incomplete(items: list) -> bool:
    """竞价 6 项中有效主值过少则视为未归档完整，需重算。"""
    if not items:
        return True
    by_key = {it.get("key"): it for it in items if it and it.get("key")}
    filled = 0
    for key in _AUCTION_VALUE_KEYS:
        val = _display_text((by_key.get(key) or {}).get("value"))
        if val != "--":
            filled += 1
    ow = _display_text((by_key.get("auctionOneWord") or {}).get("value"))
    if ow != "--":
        filled += 1
    return filled < 2


def sanitize_auction_items(items: list) -> list:
    """竞价块展示清洗：仅把真正缺失的值展示为 --，0% 是有效中性值。"""
    if not items:
        return items
    vol_item = next((it for it in items if it.get("key") == "auctionVolume"), None)
    vol_missing = _display_text((vol_item or {}).get("value")) == "--"
    out = []
    for it in items:
        row = dict(it)
        key = row.get("key")
        val = _display_text(row.get("value"))
        if key == "auctionOneWord" and vol_missing and val in ("0", "0.0"):
            val = "--"
        prev = _auction_prev_display(row.get("prev") or row.get("yesterday"))
        row["value"] = val
        row["prev"] = prev
        row["yesterday"] = prev
        row["displayValue"] = val
        if val == "--":
            row["trend"] = "flat"
            row.pop("up", None)
        out.append(row)
    return out


def _auction_prev_display(val) -> str:
    s = _display_text(val)
    if _auction_zero_placeholder(s):
        return "--"
    return s


def _after_auction_925(now: Optional[datetime] = None) -> bool:
    """是否已过 9:25 竞价撮合（一字判定等口径仍用此边界）"""
    now = now or bj_now()
    return now.hour > 9 or (now.hour == 9 and now.minute >= 25)


def _auction_hm(now: Optional[datetime] = None) -> int:
    now = now or bj_now()
    return now.hour * 60 + now.minute


def _auction_data_ready(now: Optional[datetime] = None) -> bool:
    """9:15 起展示/刷新竞价数据"""
    return _auction_hm(now) >= 9 * 60 + 15


def _in_auction_live_window(now: Optional[datetime] = None) -> bool:
    """9:15–9:26 竞价 live 窗口（不含 9:26 整点起）"""
    hm = _auction_hm(now)
    return 9 * 60 + 15 <= hm < 9 * 60 + 26


def _after_auction_frozen(now: Optional[datetime] = None) -> bool:
    """9:26 起竞价数据固化"""
    return _auction_hm(now) >= 9 * 60 + 26


def _in_auction_amount_window(now: Optional[datetime] = None) -> bool:
    """9:25撮合后短窗口，可从两市实时成交额读取集合竞价金额。"""
    hm = _auction_hm(now)
    return 9 * 60 + 25 <= hm < 9 * 60 + 31


def _auction_cache_ttl(now: Optional[datetime] = None) -> int:
    """当日竞价缓存 TTL：live 20s / 固化后按日"""
    if _after_auction_frozen(now):
        return _AUCTION_ONE_WORD_FROZEN_TTL
    if _in_auction_live_window(now):
        return AUCTION_LIVE_REFRESH_SEC
    return 0


def invalidate_auction_day_cache(trade_d: str = "") -> None:
    """9:26 固化前清 live 缓存，确保最终快照重新拉取"""
    trade_d = (trade_d or date_str(bj_now()))[:8]
    exact_keys = (
        f"auction_one_word_{trade_d}",
        f"auction_vol_yi_{trade_d}",
        f"auction_stock_vol_{trade_d}",
        f"auction_stock_vol_all_{trade_d}",
        f"auction_vol_meta_{trade_d}",
        f"auction_top_sectors_{trade_d}",
        f"auction_volume_surge_{trade_d}",
    )
    for key in list(_cache.keys()):
        if key.startswith(f"auction_detail_{trade_d}_") or key in exact_keys:
            _cache.pop(key, None)


def _yi_display(yi: Optional[float]) -> str:
    if yi is None or yi <= 0:
        return "--"
    return f"{round(yi)}亿"


def _yuan_total_to_yi(total: float) -> Optional[float]:
    """将汇总金额转为亿元"""
    if total <= 0:
        return None
    if total >= 1e8:
        return round(total / 1e8)
    if total >= 100:
        return round(total)
    return None


def _compute_market_auction_volume_yi() -> Optional[float]:
    """汇总全 A 股 9:25 竞价成交额（亿），取东财 clist 竞价额字段求和"""
    urls = (
        "https://91.push2.eastmoney.com/api/qt/clist/get",
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    )
    fields_try = ("f629", "f618", "f619", "f531", "f532", "f617")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    }
    def _probe(field: str, url: str) -> Optional[float]:
        try:
            params = {**base, "fields": f"f12,{field}", "pn": "1"}
            response = requests.get(url, params=params, headers=headers, timeout=6)
            diff = (response.json().get("data") or {}).get("diff") or []
            rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
            subtotal = 0.0
            hits = 0
            for row in rows:
                value = pd.to_numeric(row.get(field), errors="coerce")
                if value is not None and not pd.isna(value) and float(value) > 0:
                    subtotal += float(value)
                    hits += 1
            yi = _yuan_total_to_yi(subtotal)
            if yi and hits >= 200 and 50 <= yi <= 2000:
                return float(yi)
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=len(fields_try) * len(urls)) as pool:
        futures = [pool.submit(_probe, field, url) for field in fields_try for url in urls]
        for future in as_completed(futures):
            yi = future.result()
            if yi is not None:
                return yi
    return None


def get_market_auction_volume_yi(trade_d: str) -> Optional[float]:
    """
    指定交易日 9:25 全市场竞价成交额（亿）。
    当日 9:15–9:26 每 20s 刷新，9:26 起固化。
    """
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return None
    key = f"auction_vol_yi_{trade_d}"
    today = date_str(bj_now())
    ttl = _auction_cache_ttl() if trade_d == today else 86400 * 30
    if trade_d == today:
        if not _auction_data_ready():
            return None
        cached = _cache_get(key, ttl or AUCTION_LIVE_REFRESH_SEC)
    else:
        cached = _cache_get(key, ttl)
    if cached is not None:
        return float(cached)

    if trade_d > today:
        return None
    if trade_d == today and not _auction_data_ready():
        return None

    yi = _compute_market_auction_volume_yi()
    if not yi and trade_d == today and _in_auction_amount_window():
        _, yi = _fetch_market_amount_tencent(today)
    if yi and yi > 0:
        _cache_set(key, yi)
        return yi
    return None


def build_auction_sentiment(
    ref_d: str,
    metrics: Optional[dict] = None,
    prev_metrics: Optional[dict] = None,
    prev_d: Optional[str] = None,
    advice_d: str = "",
) -> list:
    """今日竞价情绪 6 项；yesterday 为 ref 日归档竞价（MySQL）同项主值"""
    metrics = metrics or {}
    prev_metrics = prev_metrics or {}
    advice_d = (advice_d or date_str(bj_now()))[:8]
    today = date_str(bj_now())

    # 收盘后 ref_d 会切到今天，但“今日竞价”的股票池仍应来自昨日涨停池。
    pool_d = prev_d if advice_d == ref_d and prev_d else ref_d
    df_ref = fetch_limit_up(pool_d)
    first_codes = _pool_codes_by_board(df_ref, False)
    multi_codes = _pool_codes_by_board(df_ref, True)
    max_board_codes = _pool_codes_by_max_board(df_ref)

    auction_one_word: Optional[int] = None
    top10_avg: Optional[float] = None
    spot_df = None
    spot_ok = False
    quote_codes = list(dict.fromkeys(first_codes + multi_codes + max_board_codes))
    if advice_d == today and _after_auction_frozen():
        sina_spot = _fetch_sina_quotes_df(quote_codes)
        if sina_spot is not None and not sina_spot.empty:
            spot_df = sina_spot
            spot_ok = True
    if not spot_ok:
        try:
            spot_df = ak.stock_zh_a_spot_em()
            spot_ok = spot_df is not None and not spot_df.empty
        except Exception:
            spot_df = None
    if not spot_ok:
        spot_df = _fetch_em_top_amount_spot_df()
        spot_ok = spot_df is not None and not spot_df.empty

    now = bj_now()
    live_auction = advice_d == today and _auction_data_ready()
    auction_frozen = bool(metrics.get("auction_frozen")) or (advice_d == today and _after_auction_frozen(now))
    # 15:00 后不再依赖盘中 spot；9:26 固化后走归档 metrics
    live_ready = live_auction and not auction_frozen and spot_ok and now.hour < 15

    if spot_ok and spot_df is not None:
        top10_codes = _load_top10_codes_for_date(pool_d)
        if top10_codes:
            top10_avg = _avg_open_pct_for_top_amount(spot_df, top10_codes)

    auction_one_word = _auction_one_word_count(advice_d, spot_df)
    if auction_one_word is None:
        for k in ("auction_one_word_count", "one_word_count", "auction_up"):
            v = metrics.get(k)
            if v is not None:
                try:
                    auction_one_word = int(float(v))
                    break
                except (TypeError, ValueError):
                    pass
    exact_spot_ready = spot_ok and advice_d == today
    first_board_chg = _avg_auction_chg_from_spot(first_codes, spot_df) if exact_spot_ready else None
    multi_board_chg = _avg_auction_chg_from_spot(multi_codes, spot_df) if exact_spot_ready else None
    recent_multi_chg = _avg_auction_chg_from_spot(max_board_codes, spot_df) if exact_spot_ready else None
    if advice_d <= today:
        if first_board_chg is None:
            first_board_chg = _avg_board_auction_chg_historical(pool_d, False, advice_d)
        if multi_board_chg is None:
            multi_board_chg = _avg_board_auction_chg_historical(pool_d, True, advice_d)
        if recent_multi_chg is None:
            recent_multi_chg = _avg_max_board_auction_chg_historical(pool_d, advice_d)
    if first_board_chg is None:
        first_board_chg = _safe_float(metrics.get("first_board_auction_chg"))
    if multi_board_chg is None:
        multi_board_chg = _safe_float(metrics.get("multi_board_auction_chg"))
    if recent_multi_chg is None:
        recent_multi_chg = _safe_float(metrics.get("max_board_auction_chg"))
    prefer_prev_auction = bool(advice_d and ref_d and advice_d <= ref_d)
    auction_yi = get_market_auction_volume_yi(advice_d)
    if auction_yi is None:
        stored = metrics.get("auction_volume_yi")
        if stored:
            try:
                auction_yi = float(stored)
            except (TypeError, ValueError):
                auction_yi = None
    if auction_yi is None and advice_d:
        cached_yi = _cache_get(f"auction_vol_yi_{advice_d}", 86400 * 30)
        if cached_yi is not None:
            auction_yi = float(cached_yi)
    prev_yi = get_market_auction_volume_yi(ref_d)
    if prev_yi is None:
        stored_prev = metrics.get("auction_volume_yi")
        if stored_prev:
            prev_yi = float(stored_prev)
    auction_volume = _yi_display(auction_yi)
    prev_volume = _auction_ref_prev_display(
        ref_d, "auctionVolume", _yi_display(get_market_auction_volume_yi(ref_d)), prev_d=prev_d, prefer_prev=prefer_prev_auction
    )

    prev_one_word = _auction_ref_prev_display(
        ref_d, "auctionOneWord", metrics.get("one_word_count"), prev_d=prev_d, prefer_prev=prefer_prev_auction
    )
    if prev_one_word == "--":
        ow = _auction_one_word_count(prev_d if prefer_prev_auction else ref_d)
        prev_one_word = str(ow) if ow is not None else "--"

    prev_top10 = metrics.get("auction_median")
    prev_top10_s = _auction_ref_prev_display(ref_d, "top10AuctionChg", prev_d=prev_d, prefer_prev=prefer_prev_auction)
    if prev_top10_s == "--":
        archived = _auction_items_by_key(ref_d).get("top10AuctionChg")
        if archived and not _auction_zero_placeholder(archived.get("value")):
            prev_top10_s = _auction_prev_display(archived.get("value"))
        elif prev_top10 is not None:
            try:
                f = float(prev_top10)
                if abs(f) > 1e-9:
                    prev_top10_s = f"{f:+.2f}%"
            except Exception:
                prev_top10_s = "--"
    prev_top10_s = _auction_prev_display(prev_top10_s)
    prev_top10_num = None
    if prev_top10_s not in ("", "--"):
        try:
            prev_top10_num = float(str(prev_top10_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_top10_num = None

    prev_first_s = _auction_ref_prev_display(ref_d, "yesterdayFirst", prev_d=prev_d, prefer_prev=prefer_prev_auction)
    prev_first_chg = None
    if prev_first_s not in ("", "--"):
        try:
            prev_first_chg = float(str(prev_first_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_first_chg = None

    prev_multi_s = _auction_ref_prev_display(ref_d, "yesterdayMulti", prev_d=prev_d, prefer_prev=prefer_prev_auction)
    prev_multi_chg = None
    if prev_multi_s not in ("", "--"):
        try:
            prev_multi_chg = float(str(prev_multi_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_multi_chg = None

    prev_recent_s = _auction_ref_prev_display(ref_d, "recentMulti", prev_d=prev_d, prefer_prev=prefer_prev_auction)
    prev_recent_chg = None
    if prev_recent_s not in ("", "--"):
        try:
            prev_recent_chg = float(str(prev_recent_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_recent_chg = None

    def _item(key, label, value, yesterday, trend=None, up=None):
        val_s = _display_text(value)
        prev_s = _auction_prev_display(yesterday)
        row = {
            "key": key,
            "label": label,
            "value": val_s,
            "yesterday": prev_s,
            "prev": prev_s,
            "trend": trend or "flat",
        }
        if up is not None:
            row["up"] = up
        return row

    one_word_val = _count_display(auction_one_word)
    if auction_volume == "--" and auction_one_word is None:
        one_word_val = "--"
    top10_val = _auction_pct_display(top10_avg)
    top10_num = top10_avg if top10_avg is not None else None
    items = [
        _item(
            "auctionOneWord", "竞价一字板", one_word_val, prev_one_word,
            _trend(auction_one_word, prev_one_word),
        ),
        _item(
            "auctionVolume", "竞价量能", auction_volume, prev_volume,
            _trend(auction_yi, prev_yi),
        ),
        _item(
            "yesterdayFirst", "昨日首板竞价涨幅", _auction_pct_display(first_board_chg),
            prev_first_s if prev_first_s != "--" else _auction_pct_display(prev_first_chg),
            _trend(first_board_chg, prev_first_chg),
            first_board_chg is not None and first_board_chg >= 0,
        ),
        _item(
            "yesterdayMulti", "昨日连板竞价涨幅", _auction_pct_display(multi_board_chg),
            prev_multi_s if prev_multi_s != "--" else _auction_pct_display(prev_multi_chg),
            _trend(multi_board_chg, prev_multi_chg),
            multi_board_chg is not None and multi_board_chg >= 0,
        ),
        _item(
            "recentMulti", "最近多板竞价涨幅", _auction_pct_display(recent_multi_chg),
            prev_recent_s if prev_recent_s != "--" else _auction_pct_display(prev_recent_chg),
            _trend(recent_multi_chg, prev_recent_chg),
            recent_multi_chg is not None and recent_multi_chg >= 0,
        ),
        _item(
            "top10AuctionChg", "昨日成交额前10平均竞价涨幅", top10_val, prev_top10_s,
            _trend(top10_num, prev_top10_num),
            top10_num is not None and top10_num >= 0,
        ),
    ]
    return sanitize_auction_items(_apply_auction_prev_from_ref(items, ref_d, prev_d))


def _auction_items_by_key(trade_d: str) -> dict[str, dict]:
    """读取指定交易日固化竞价块（daily_market.auction_json）"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return {}
    try:
        from history_store import fetch_daily_detail

        detail = fetch_daily_detail(trade_d)
        if detail and detail.get("auction"):
            return {
                str(it.get("key")): it
                for it in detail["auction"]
                if it and it.get("key")
            }
    except Exception:
        pass
    return {}


def _auction_ref_prev_display(
    ref_d: str,
    key: str,
    fallback=None,
    *,
    prev_d: Optional[str] = None,
    prefer_prev: bool = False,
) -> str:
    """昨：根据当前展示日选择 ref 或 prev 日竞价归档同 key 主值。"""
    dates = ((prev_d or "")[:8], (ref_d or "")[:8]) if prefer_prev else ((ref_d or "")[:8], (prev_d or "")[:8])
    for d in dates:
        if not d:
            continue
        item = _auction_items_by_key(d).get(key)
        if item:
            val = item.get("value")
            if val not in (None, "", "--") and not _auction_zero_placeholder(val):
                return str(val)
    if fallback is None or fallback in ("", "--"):
        return "--"
    return str(fallback)


def _apply_auction_prev_from_ref(
    auction: list,
    ref_d: str,
    prev_d: Optional[str] = None,
    prefer_prev: bool = False,
) -> list:
    """将竞价块对比列统一为 ref / prev 日 DB 归档同 key 主值。"""
    ref_d = (ref_d or "")[:8]
    if not auction or not ref_d:
        return auction
    out = []
    for it in auction:
        key = it.get("key")
        row = dict(it)
        if key:
            prev_s = _auction_ref_prev_display(ref_d, key, prev_d=prev_d, prefer_prev=prefer_prev)
            if prev_s != "--":
                prev_s = _auction_prev_display(prev_s)
                row["yesterday"] = prev_s
                row["prev"] = prev_s
        out.append(row)
    return out


def _relative_day_label(trade_d: str, today: str) -> str:
    """日期标签：x月x日（今日则返回今日）"""
    trade_d = (trade_d or "")[:8]
    today = (today or "")[:8]
    if not trade_d or len(trade_d) < 8:
        return "--"
    if trade_d == today:
        return "今日"
    month = int(trade_d[4:6])
    day = int(trade_d[6:8])
    return f"{month}月{day}日"


def build_section_metas(
    ref_d: str,
    advice_d: str,
    is_ready: bool,
    ref_metrics: Optional[dict] = None,
    advice_metrics: Optional[dict] = None,
) -> tuple[dict, str, str]:
    """各板块 meta 与仪表盘综合更新时间"""
    now = bj_now()
    now_hm = now.strftime("%H:%M")
    today = date_str(now)
    ref_d = (ref_d or "")[:8]
    advice_d = (advice_d or today)[:8]

    ref_label = _relative_day_label(ref_d, today)
    adv_label = _relative_day_label(advice_d, today)

    ref_m = ref_metrics or {}
    adv_m = advice_metrics or {}

    if ref_m.get("snapshot_frozen") or ref_m.get("snapshot_phase") == "1800":
        yesterday_meta = f"{ref_label} 18:00 固化"
        gauge_hm = "18:00"
    elif ref_m.get("snapshot_phase") == "1505":
        yesterday_meta = f"{ref_label} 15:05 更新"
        gauge_hm = "15:05"
    else:
        yesterday_meta = f"{ref_label} 15:00 更新"
        gauge_hm = "15:00"

    if adv_m.get("auction_frozen") or adv_m.get("auction_phase") in ("0926", "0935") or _after_auction_frozen():
        auction_meta = f"{adv_label} 09:26 固化"
    elif _in_auction_live_window(now):
        auction_meta = f"{adv_label} {now_hm} 更新"
    elif advice_d == today and is_ready:
        auction_meta = f"{adv_label} {now_hm} 更新"
    else:
        auction_meta = f"{adv_label} 09:15 更新"

    if advice_d == today:
        try:
            from intraday import intraday_session_phase

            phase = intraday_session_phase(now)
            if phase == "live":
                intraday_meta = f"{adv_label} {now_hm} 更新"
            elif phase == "closed":
                intraday_meta = f"{adv_label} 15:00 已收盘"
            elif phase == "night":
                intraday_meta = "下个交易日 9:30 起更新"
            else:
                intraday_meta = f"{adv_label} 9:30 起更新"
        except Exception:
            intraday_meta = f"{adv_label} 盘中更新"
    else:
        intraday_meta = f"{adv_label} 15:00 更新"

    metas = {
        "yesterday": yesterday_meta,
        "auction": auction_meta,
        "intraday": intraday_meta,
    }

    gauge_label = f"{ref_label} {gauge_hm} 更新"
    if ref_m.get("snapshot_frozen") or ref_m.get("snapshot_phase") == "1800":
        gauge_label = f"{ref_label} {gauge_hm} 固化"

    return metas, gauge_label, gauge_hm


def _pool_codes_all(df_up: pd.DataFrame) -> list[str]:
    if df_up is None or df_up.empty:
        return []
    col = _df_col(df_up, "\u4ee3\u7801")
    if not col:
        return []
    return _normalize_code_list(df_up[col].tolist())


def _big_drop_count(spot_df, threshold: float = -7.0) -> Optional[int]:
    """全市场涨跌幅 < threshold 的股票数量（默认 -7%）。"""
    if spot_df is None or spot_df.empty:
        return None
    chg_col = _df_col(spot_df, "涨跌幅")
    if not chg_col:
        return None
    chg = pd.to_numeric(spot_df[chg_col], errors="coerce").dropna()
    return int((chg < threshold).sum())


def _recent_zt_big_drop_count(
    ref_d: str,
    prev_d: Optional[str],
    advice_d: str,
    spot_df=None,
    _fallback_pool_dfs: Optional[list] = None,
) -> Optional[int]:
    """全市场今日涨跌幅 < -7% 的股票数量。"""
    return _big_drop_count(spot_df)


def _recent_zt_big_drop_count_UNUSED(
    ref_d: str,
    prev_d: Optional[str],
    advice_d: str,
    spot_df=None,
    _fallback_pool_dfs: Optional[list] = None,
) -> Optional[int]:
    """（已废弃）近2日触板股从高点回落超10%家数。"""
    advice_d = (advice_d or "")[:8]
    today = date_str(bj_now())
    if advice_d != today:
        try:
            from intraday import is_trading_day
            from datetime import datetime
            dt = datetime.strptime(advice_d, "%Y%m%d")
            if not is_trading_day(dt):
                return None
        except Exception:
            pass

    stock_highs: dict[str, float] = {}
    for d in [ref_d, prev_d]:
        if not d:
            continue
        for df_pool in [fetch_limit_up(d), fetch_broken_board(d)]:
            if df_pool is None or df_pool.empty:
                continue
            code_col = _df_col(df_pool, "代码")
            price_col = (
                _df_col(df_pool, "最高价")
                or _df_col(df_pool, "最新价")
                or _df_col(df_pool, "当前价")
            )
            if not code_col or not price_col:
                continue
            codes_n = (
                df_pool[code_col].astype(str)
                .str.replace(r"\D", "", regex=True)
                .str.zfill(6)
            )
            prices = pd.to_numeric(df_pool[price_col], errors="coerce")
            for code, p in zip(codes_n, prices):
                if not pd.isna(p) and float(p) > 0:
                    if float(p) > stock_highs.get(code, 0):
                        stock_highs[code] = float(p)

    if not stock_highs:
        return 0

    if spot_df is None or spot_df.empty:
        return None

    code_col_s = _df_col(spot_df, "代码")
    price_col_s = _df_col(spot_df, "最新价") or _df_col(spot_df, "当前价")
    if not code_col_s or not price_col_s:
        return None

    codes_s = (
        spot_df[code_col_s].astype(str)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(6)
    )
    prices_s = pd.to_numeric(spot_df[price_col_s], errors="coerce")
    today_prices = dict(zip(codes_s, prices_s))

    # 步骤3：统计回落超10个百分点的股票数
    count = 0
    for code, high in stock_highs.items():
        curr = today_prices.get(code)
        if curr is None or pd.isna(curr) or high <= 0:
            continue
        if (high - float(curr)) / high * 100 >= 10.0:
            count += 1
    return count


def _build_risk_placeholder(metrics: dict, prev_metrics: dict) -> list[dict]:
    """数据准备期（8:00-9:15）占位：全部显示 --，昨列保留对比值。"""
    prev_promote = prev_metrics.get("promote_rate")
    prev_break_rate = prev_metrics.get("break_rate")
    prev_limit_down = prev_metrics.get("limit_down_count")
    prev_max_board = int(prev_metrics.get("max_board") or 0)

    def ph(key, label, yesterday="--", desc=""):
        return {"key": key, "label": label, "value": "--",
                "yesterday": str(yesterday) if yesterday not in (None, "") else "--",
                "trend": "flat", "desc": desc}

    multi_fail_prev = f"{max(0.0, 100.0-float(prev_promote or 0)):.0f}%" if prev_promote is not None else "--"
    reseal_prev = f"{max(0.0, 100.0-float(prev_break_rate or 0)):.0f}%" if prev_break_rate is not None else "--"
    return [
        ph("highBreakFeedback", "连板最高标涨幅", f"{prev_max_board}板" if prev_max_board else "--"),
        ph("limitUpPremium", "昨日涨停溢价", _prev_limit_up_premium(str(prev_metrics.get("date") or "").replace("-", "")[:8]) or "--"),
        ph("multiFailRate", "连板晋级失败率", multi_fail_prev),
        ph("resealRate", "炸板后回封率", reseal_prev),
        ph("limitDownRisk", "跌停家数", str(prev_limit_down) if prev_limit_down is not None else "--"),
        ph("bigLossCount", "跌幅>7%"),
    ]


def _prev_limit_up_premium(prev_d: Optional[str]) -> Optional[str]:
    """从 MySQL 读取 prev_d 当天存储的 limitUpPremium.value，作为昨日对比值。"""
    if not prev_d:
        return None
    try:
        from history_store import fetch_daily_detail
    except Exception:
        return None
    detail = fetch_daily_detail(prev_d)
    if not detail:
        return None
    for sec in (detail.get("indicatorSections") or []):
        if sec.get("id") == "longkongRisk":
            for it in (sec.get("items") or []):
                if it.get("key") == "limitUpPremium":
                    v = str(it.get("value") or "").strip()
                    return v if v and v != "--" else None
    return None


def _prev_longkong_risk_value(trade_d: Optional[str], key: str) -> Optional[str]:
    """从指定交易日归档读取龙空风控指标值。"""
    if not trade_d or not key:
        return None
    try:
        from history_store import fetch_daily_detail
    except Exception:
        return None
    detail = fetch_daily_detail(trade_d)
    if not detail:
        return None
    for sec in (detail.get("indicatorSections") or []):
        if sec.get("id") != "longkongRisk":
            continue
        for item in (sec.get("items") or []):
            if item.get("key") == key:
                value = str(item.get("value") or "").strip()
                return value if value and value != "--" else None
    return None


def build_longkong_risk_items(
    ref_d: str,
    prev_d: Optional[str],
    metrics: Optional[dict] = None,
    prev_metrics: Optional[dict] = None,
    *,
    advice_d: str = "",
) -> list[dict]:
    metrics = metrics or {}
    prev_metrics = prev_metrics or {}
    ref_d = (ref_d or "")[:8]

    # 数据准备期（交易日 8:00–9:15）：本板块全部显示 --，避免旧数据误导
    try:
        from intraday import is_data_prep_window
        if is_data_prep_window():
            return _build_risk_placeholder(metrics, prev_metrics)
    except Exception:
        pass

    df_ref_up = fetch_limit_up(ref_d)
    df_ref_broken = fetch_broken_board(ref_d)
    df_ref_down = fetch_limit_down(ref_d)
    premium_pool_d = prev_d if advice_d and advice_d[:8] == ref_d and prev_d else ref_d
    ref_codes = _pool_codes_all(fetch_limit_up(premium_pool_d))
    spot_df = None
    if ref_codes and advice_d and advice_d[:8] == date_str(bj_now()):
        spot_df = _fetch_sina_quotes_df(ref_codes)
    if spot_df is None or spot_df.empty:
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            spot_df = None

    ref_max_board = int(metrics.get("max_board") or _max_board(df_ref_up) or 0)
    prev_max_board = int(prev_metrics.get("max_board") or 0)
    high_break = max(prev_max_board - ref_max_board, 0) if prev_max_board else 0

    # 竞价涨幅：昨日涨停股今日开盘相对昨收的涨幅均值
    premium = _avg_auction_chg_from_spot(ref_codes, spot_df) if ref_codes else None
    # 盘后兜底：spot_df 不可用时，用历史开盘价接口逐股计算
    if premium is None and ref_codes and advice_d:
        advice_d8 = (advice_d or "")[:8]
        chgs = [c for c in (_code_open_pct_on_date(code, advice_d8) for code in ref_codes[:30]) if c is not None]
        if chgs:
            premium = round(sum(chgs) / len(chgs), 2)
    promote_rate = float(metrics.get("promote_rate") or 0)
    multi_fail_rate = round(max(0.0, 100.0 - promote_rate), 1)

    broken_n = len(df_ref_broken) if df_ref_broken is not None else 0
    fallback_up_n = len(df_ref_up) if df_ref_up is not None else 0
    limit_up_n = int(metrics.get("limit_up_count") or fallback_up_n)
    reseal_rate = round(limit_up_n / (limit_up_n + broken_n) * 100, 1) if limit_up_n + broken_n > 0 else 0.0

    limit_down_n = int(metrics.get("limit_down_count") or (len(df_ref_down) if df_ref_down is not None else 0))

    # \u5927\u9762\u5bb6\u6570\uff1a\u8fd13\u65e5\u66fe\u6da8\u505c\u3001\u4eca\u65e5\u8dcc\u505c\u7684\u80a1\u7968\u6570\u91cf
    # \u6bd4\u300c\u5168\u5e02\u8dcc\u5e45\u2264-7%\u300d\u66f4\u7cbe\u51c6 \u2014\u2014 \u4e13\u6307\u70ed\u94b1\u9ad8\u4f4d\u5d29\u76d8
    big_loss = _recent_zt_big_drop_count(
        ref_d, prev_d, advice_d or ref_d, None,
        _fallback_pool_dfs=[df_ref_up, df_ref_broken],
    )
    if big_loss is None:
        market_snapshot = _fetch_em_a_share_snapshot()
        if int(market_snapshot.get("rows") or 0) >= 1000:
            big_loss = market_snapshot.get("big_drop_count")
    if big_loss is None:
        big_loss = _fetch_em_big_drop_count()
    prev_big_loss = _prev_longkong_risk_value(ref_d, "bigLossCount")

    prev_limit_down = prev_metrics.get("limit_down_count")
    prev_break_rate = prev_metrics.get("break_rate")
    prev_promote = prev_metrics.get("promote_rate")

    def item(key: str, label: str, value, yesterday, trend, desc: str = "") -> dict:
        return {
            "key": key,
            "label": label,
            "value": value,
            "yesterday": yesterday if yesterday not in (None, "") else "--",
            "trend": trend,
            "desc": desc,
        }

    # \u8fde\u677f\u6700\u9ad8\u6807\u4eca\u65e5\u6da8\u5e45\uff08\u66ff\u4ee3\u539f\u9ad8\u6807\u65ad\u677f\u516c\u5f0f\uff09
    top_chg = None
    if prev_d and advice_d and advice_d[:8] == date_str(bj_now()):
        top_codes = _pool_codes_by_max_board(fetch_limit_up(prev_d))
        top_spot = _fetch_sina_quotes_df(top_codes)
        top_chg = _avg_pct_chg(top_spot, top_codes)
    if top_chg is None and prev_d:
        top_chg = _top_board_stock_chg(prev_d, ref_d)
    top_chg_str = f"{top_chg:+.1f}%" if top_chg is not None else "--"
    top_chg_trend = ("up" if top_chg is not None and top_chg >= 9.5
                     else "down" if top_chg is not None and top_chg < 0
                     else "flat")
    return [
        item("highBreakFeedback", "\u8fde\u677f\u6700\u9ad8\u6807\u6da8\u5e45",
             top_chg_str,
             f"{prev_max_board}\u677f" if prev_max_board else "--",
             top_chg_trend,
             "\u6628\u65e5\u6700\u9ad8\u8fde\u677f\u80a1\u4eca\u65e5\u6da8\u5e45\uff1a\u7eed\u677f+10%\u4e3a\u5f3a\uff0c\u8dcc\u7eff\u4e3a\u9ad8\u4f4d\u5927\u9762\u4fe1\u53f7"),
        item("limitUpPremium", "\u6628\u65e5\u6da8\u505c\u6ea2\u4ef7", f"{float(premium):+.2f}%" if premium is not None else "--", _prev_limit_up_premium(prev_d) or "--", "up" if premium is not None and float(premium) >= 0 else "down" if premium is not None else "flat", "\u6628\u65e5\u6da8\u505c\u6c60\u4eca\u65e5\u5e73\u5747\u8868\u73b0"),
        item("multiFailRate", "\u8fde\u677f\u664b\u7ea7\u5931\u8d25\u7387", f"{multi_fail_rate:.0f}%", f"{max(0.0, 100.0 - float(prev_promote or 0)):.0f}%" if prev_promote is not None else "--", _trend(multi_fail_rate, max(0.0, 100.0 - float(prev_promote or 0)) if prev_promote is not None else None, inverse=True), "\u664b\u7ea7\u7387\u7684\u53cd\u5411\u98ce\u9669\u53e3\u5f84"),
        item("resealRate", "\u70b8\u677f\u540e\u56de\u5c01\u7387", f"{reseal_rate:.0f}%", f"{max(0.0, 100.0 - float(prev_break_rate or 0)):.0f}%" if prev_break_rate is not None else "--", _trend(reseal_rate, max(0.0, 100.0 - float(prev_break_rate or 0)) if prev_break_rate is not None else None), "\u6da8\u505c\u5c01\u4f4f\u5360\u6da8\u505c\u52a0\u70b8\u677f\u7684\u6bd4\u4f8b"),
        item("limitDownRisk", "\u8dcc\u505c\u5bb6\u6570", str(limit_down_n), str(prev_limit_down) if prev_limit_down is not None else "--", _trend(limit_down_n, prev_limit_down, inverse=True), "\u6781\u7aef\u4e8f\u94b1\u6548\u5e94\u6e29\u5ea6"),
        item("bigLossCount", "\u8dcc\u5e45>7%",
             str(big_loss) if big_loss is not None else "--",
             prev_big_loss or "--",
             _trend(big_loss, prev_big_loss, inverse=True),
             "\u5168\u5e02\u573a\u4eca\u65e5\u6da8\u8dcc\u5e45\u4f4e\u4e8e-7%\u7684\u80a1\u7968\u6570\u91cf"),
    ]


LONGKONG_RISK_KEYS = (
    "highBreakFeedback",
    "limitUpPremium",
    "multiFailRate",
    "resealRate",
    "limitDownRisk",
    "bigLossCount",
)


def _section_items_complete(items: list, required_keys: tuple[str, ...]) -> bool:
    by_key = {it.get("key"): it for it in (items or []) if it and it.get("key")}
    for key in required_keys:
        val = str((by_key.get(key) or {}).get("value") or (by_key.get(key) or {}).get("displayValue") or "").strip()
        if not val or val in ("--", "-", "None", "null"):
            return False
    return bool(by_key)


_LONGKONG_EXPECTED_LABELS = {
    "bigLossCount": "跌幅>7%",
}


def _longkong_labels_valid(items: list) -> bool:
    """校验关键 label 是否与当前版本一致，避免返回旧缓存的错误标签。"""
    by_key = {it.get("key"): it for it in (items or []) if it and it.get("key")}
    for key, expected in _LONGKONG_EXPECTED_LABELS.items():
        item = by_key.get(key)
        if item and item.get("label") != expected:
            return False
    return True


def _longkong_from_detail(detail: Optional[dict]) -> list:
    if not detail:
        return []
    for sec in detail.get("indicatorSections") or []:
        if sec.get("id") == "longkongRisk":
            items = sec.get("items") or []
            if _section_items_complete(items, LONGKONG_RISK_KEYS) and _longkong_labels_valid(items):
                return items
    return []


_longkong_read_cache: dict = {"key": "", "at": 0.0, "items": None}


def _longkong_read_ttl_sec() -> int:
    return int(os.getenv("LONGKONG_READ_TTL_SEC", os.getenv("INTRADAY_READ_TTL_SEC", "90")))


def invalidate_longkong_read_cache() -> None:
    _longkong_read_cache.update({"key": "", "at": 0.0, "items": None})


def get_longkong_risk_payload_cached(
    ref_d: str,
    prev_d: Optional[str],
    metrics: Optional[dict] = None,
    prev_metrics: Optional[dict] = None,
    *,
    advice_d: str = "",
    force: bool = False,
) -> list[dict]:
    """盘中实时龙空风控：API 读取时节流重算；定时任务 force=True 强制刷新。"""
    key = f"{(ref_d or '')[:8]}:{(advice_d or '')[:8]}:{date_str(bj_now())}"
    now = time.time()
    if not force:
        cached = _longkong_read_cache.get("items")
        if cached and _longkong_read_cache.get("key") == key:
            age = now - float(_longkong_read_cache.get("at") or 0)
            if age < _longkong_read_ttl_sec():
                return cached
    items = build_longkong_risk_items(
        ref_d, prev_d, metrics, prev_metrics, advice_d=advice_d
    )
    _longkong_read_cache.update({"key": key, "at": now, "items": items})
    return items


def load_longkong_risk_cached(
    ref_d: str,
    prev_d: Optional[str],
    metrics: Optional[dict] = None,
    prev_metrics: Optional[dict] = None,
    *,
    advice_d: str = "",
    live: bool = False,
    force: bool = False,
) -> list[dict]:
    """龙空风控：收盘后读 daily_market；盘中 live=True 时实时重算（带节流）。"""
    if live:
        return get_longkong_risk_payload_cached(
            ref_d,
            prev_d,
            metrics,
            prev_metrics,
            advice_d=advice_d,
            force=force,
        )
    try:
        from history_store import fetch_daily_detail
    except Exception:
        fetch_daily_detail = None  # type: ignore

    if fetch_daily_detail:
        for d in dict.fromkeys([(advice_d or "")[:8], (ref_d or "")[:8]]):
            if len(d) != 8:
                continue
            items = _longkong_from_detail(fetch_daily_detail(d))
            if items:
                return items
    return build_longkong_risk_items(
        ref_d, prev_d, metrics, prev_metrics, advice_d=advice_d
    )


def build_indicator_sections(
    ref_d: str,
    prev_d: Optional[str],
    metrics: dict,
    prev_metrics: Optional[dict] = None,
    *,
    advice_d: str = "",
    is_ready: bool = True,
    live_longkong: bool = False,
) -> list[dict]:
    """三大类共 18 项指标"""
    if not advice_d:
        advice_d = ref_d
    metas, _, _ = build_section_metas(ref_d, advice_d, is_ready, ref_metrics=metrics)
    ref_label = _relative_day_label(ref_d, date_str(bj_now()))
    adv_label = _relative_day_label(advice_d, date_str(bj_now()))
    return [
        {
            "id": "yesterday",
            "title": f"{ref_label}情绪概览",
            "meta": metas["yesterday"],
            "layout": "grid3",
            "cols": 3,
            "items": build_yesterday_sentiment(metrics, prev_metrics),
        },
        {
            "id": "auction",
            "title": f"{adv_label}竞价情绪",
            "meta": metas["auction"],
            "layout": "grid3",
            "cols": 3,
            "items": build_auction_sentiment(
                ref_d, metrics, prev_metrics, prev_d, advice_d=advice_d
            ),
        },
        {
            "id": "longkongRisk",
            "title": "\u9f99\u7a7a\u9f99\u4e13\u5c5e\u98ce\u63a7",
            "meta": metas["intraday"],
            "layout": "grid3",
            "cols": 3,
            "items": load_longkong_risk_cached(
                ref_d,
                prev_d,
                metrics,
                prev_metrics,
                advice_d=advice_d,
                live=live_longkong,
            ),
        },
    ]


def _trend(cur, prev, inverse=False):
    if prev is None or prev == "-":
        return "flat"
    try:
        c, p = float(cur), float(prev)
    except Exception:
        return "flat"
    if c > p:
        return "down" if inverse else "up"
    if c < p:
        return "up" if inverse else "down"
    return "flat"


HOME_TREND_DAYS = 10


def build_home_trend(ref_d: str, days: int = HOME_TREND_DAYS) -> list[dict]:
    """近 N 个交易日情绪分趋势（优先 DB 存档，缺则回算）。"""
    from history_store import fetch_daily_detail
    from sentiment import calc_sentiment

    ref_d = (ref_d or "").replace("-", "")[:8]
    dates = get_recent_trade_dates(max(days + 10, 25))
    if not dates:
        return []
    ref_idx = dates.index(ref_d) if ref_d in dates else len(dates) - 1
    start_idx = max(0, ref_idx - (days - 1))
    trend: list[dict] = []
    for i in range(start_idx, ref_idx + 1):
        d = dates[i]
        score = None
        detail = fetch_daily_detail(d)
        if detail:
            score = (detail.get("sentiment") or {}).get("score")
            if score is None:
                score = (detail.get("history") or {}).get("score")
        if score is None:
            p = dates[i - 1] if i > 0 else None
            m = _fill_metrics_breadth(build_ref_day_metrics(d, p), d)
            auction = (detail or {}).get("auction")
            grid9 = (detail or {}).get("grid9")
            score = calc_sentiment(
                m,
                auction=auction,
                grid9=grid9,
            ).get("score")
        trend.append({"date": f"{d[4:6]}-{d[6:8]}", "score": int(score or 0)})
    return trend


def calc_regime(ref_d: str, days: int = 20) -> dict:
    """
    20 日情绪分移动均值，判断当前市场环境档位。
    regime: bull（均值≥60）/ neutral（40–60）/ bear（<40）
    """
    trend = build_home_trend(ref_d, days=days)
    if not trend:
        return {"regimeScore": None, "regimeLabel": "--", "regime": "neutral"}
    scores = [int(t.get("score") or 0) for t in trend if t.get("score") is not None]
    if not scores:
        return {"regimeScore": None, "regimeLabel": "--", "regime": "neutral"}
    avg = round(sum(scores) / len(scores))
    if avg >= 60:
        label, regime = f"偏强（{days}日均分{avg}）", "bull"
    elif avg >= 40:
        label, regime = f"中性（{days}日均分{avg}）", "neutral"
    else:
        label, regime = f"偏弱（{days}日均分{avg}）", "bear"
    return {"regimeScore": avg, "regimeLabel": label, "regime": regime}


def display_level_label(score: int) -> str:
    if score >= 90:
        return "狂热"
    if score >= 80:
        return "高潮"
    if score >= 60:
        return "偏乐观"
    if score >= 50:
        return "中性"
    if score >= 40:
        return "偏谨慎"
    if score >= 30:
        return "偏冷"
    return "冰点"


def display_level_class(score: int) -> str:
    if score >= 90:
        return "frenzy"
    if score >= 80:
        return "climax"
    if score >= 60:
        return "optimistic"
    if score >= 50:
        return "neutral"
    if score >= 40:
        return "caution"
    if score >= 30:
        return "weak"
    return "cold"


def fetch_market_volume() -> dict:
    key = "volume"
    cached = _cache_get(key, 120)
    if cached:
        return cached
    try:
        df = ak.stock_market_activity_legu()
        parsed = _parse_market_activity_df(df)
        amount = parsed.get("amount", "--")
        if amount in ("--", "") or _looks_like_datetime(amount):
            amount, _ = _spot_market_amount_yi()
        result = {"amount": amount, "change": "", "label": "实时"}
        _cache_set(key, result)
        return result
    except Exception:
        pass
    return {"amount": "--", "change": "", "label": ""}


def _max_board(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    col = "连板数" if "连板数" in df.columns else None
    if col:
        return int(pd.to_numeric(df[col], errors="coerce").fillna(1).max())
    return 1


def _promote_rate(prev_d: str, curr_d: str) -> float:
    """昨日涨停股今日继续涨停 / 昨日涨停总数"""
    df_prev = fetch_limit_up(prev_d)
    df_curr = fetch_limit_up(curr_d)
    codes_prev = _normalize_stock_codes(df_prev)
    if not codes_prev:
        return 0.0
    codes_curr = _normalize_stock_codes(df_curr)
    if not codes_curr:
        return 0.0
    return round(len(codes_prev & codes_curr) / len(codes_prev) * 100, 1)


def _top_board_stock_chg(prev_d: str, ref_d: str) -> Optional[float]:
    """
    昨日最高连板股在 ref_d 当天的收益率（%）。
    先查 ref_d 涨停/炸板池快速判断，再回落到日线数据。
    最多对 2 只最高板股取均值。
    """
    df_prev = fetch_limit_up(prev_d)
    if df_prev is None or df_prev.empty or "连板数" not in df_prev.columns:
        return None
    boards = pd.to_numeric(df_prev["连板数"], errors="coerce").fillna(1)
    max_b = int(boards.max())
    if max_b < 2:
        return None
    norm = df_prev["代码"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
    top_codes = set(norm[boards == max_b].tolist())
    if not top_codes:
        return None

    # 快捷路径：还在涨停池 → 取该板块实际涨停幅度
    df_up = fetch_limit_up(ref_d)
    up_codes = _normalize_stock_codes(df_up)
    still_up = top_codes & up_codes
    if still_up:
        # 读收盘涨幅（科创板 20%，主板 10%，创业板 20%）
        # 用 df_up 的「涨跌幅」列（若有），否则近似10%
        if df_up is not None and "涨跌幅" in df_up.columns:
            norm_up = df_up["代码"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
            vals = pd.to_numeric(df_up.loc[norm_up.isin(still_up), "涨跌幅"], errors="coerce").dropna()
            if not vals.empty:
                return round(float(vals.mean()), 2)
        return 10.0  # 主板涨停近似值

    # 回落到日线接口：取当天涨跌幅
    chgs: list[float] = []
    for code in list(top_codes)[:2]:
        key = f"board_chg_{prev_d}_{ref_d}_{code}"
        cached = _cache_get(key, 86400 * 7)
        if cached is not None:
            chgs.append(float(cached))
            continue
        got = False
        try:
            df_h = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=ref_d[:8], end_date=ref_d[:8], adjust="",
            )
            if df_h is not None and not df_h.empty and "涨跌幅" in df_h.columns:
                v = float(pd.to_numeric(df_h.iloc[0]["涨跌幅"], errors="coerce"))
                if not pd.isna(v):
                    _cache_set(key, v)
                    chgs.append(v)
                    got = True
        except Exception:
            pass
        if not got:
            # 兜底：跌停池 → -9.9，炸板池 → 3.0（近似）
            try:
                dn_codes = _normalize_stock_codes(fetch_limit_down(ref_d))
                brk_codes = _normalize_stock_codes(fetch_broken_board(ref_d))
                if code in dn_codes:
                    chgs.append(-9.9)
                elif code in brk_codes:
                    chgs.append(3.0)
            except Exception:
                pass
    return round(sum(chgs) / len(chgs), 2) if chgs else None


def _get_prev_trade_d(d: str) -> Optional[str]:
    """返回 d 的上一个交易日（8位字符串），利用缓存的交易日列表。"""
    d8 = (d or "")[:8]
    if not d8:
        return None
    dates = get_recent_trade_dates(35)
    try:
        idx = dates.index(d8)
        return dates[idx - 1] if idx > 0 else None
    except ValueError:
        return None



def _high_board_promote(prev_d: str, curr_d: str, min_boards: int = 3) -> Optional[tuple[int, int]]:
    """
    高位股（≥min_boards 连板）的晋级情况：返回 (continued, total)。
    当高位股开始大面断板，情绪往往转弱。
    数据不足时返回 None。
    """
    df_prev = fetch_limit_up(prev_d)
    if df_prev is None or df_prev.empty or "连板数" not in df_prev.columns:
        return None
    boards = pd.to_numeric(df_prev["连板数"], errors="coerce").fillna(1)
    df_high = df_prev[boards >= min_boards]
    if df_high.empty:
        return None
    high_codes = set(df_high["代码"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6).tolist())
    df_curr = fetch_limit_up(curr_d)
    curr_codes = _normalize_stock_codes(df_curr)
    return len(high_codes & curr_codes), len(high_codes)


def _break_rate(d: str) -> float:
    df_up = fetch_limit_up(d)
    df_broken = fetch_broken_board(d)
    up_n = len(df_up) if df_up is not None else 0
    broken_n = len(df_broken) if df_broken is not None else 0
    total = up_n + broken_n
    if total == 0:
        return 0.0
    return round(broken_n / total * 100, 1)


def _snapshot_top10_codes(spot_df: Optional[pd.DataFrame] = None) -> list[str]:
    """当日成交额前10代码"""
    try:
        df = spot_df if spot_df is not None else ak.stock_zh_a_spot_em()
        if df is None or df.empty or "成交额" not in df.columns or "代码" not in df.columns:
            return []
        return (
            df.nlargest(10, "成交额")["代码"]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
            .str.zfill(6)
            .tolist()
        )
    except Exception:
        return []


def _avg_pct_chg(spot_df: Optional[pd.DataFrame], codes: Optional[list[str]] = None) -> Optional[float]:
    """指定股票或成交额前10的平均涨跌幅"""
    if spot_df is None or spot_df.empty or "涨跌幅" not in spot_df.columns:
        return None
    df = spot_df
    if codes:
        norm = df["代码"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
        sub = df[norm.isin(codes)]
        if sub.empty:
            return None
        df = sub
    elif "成交额" in df.columns:
        df = df.nlargest(10, "成交额")
    val = pd.to_numeric(df["涨跌幅"], errors="coerce").mean(skipna=True)
    if pd.isna(val):
        return None
    return round(float(val), 2)


def _load_top10_codes_for_date(trade_d: str) -> list[str]:
    """指定交易日成交额前10代码（缓存 / 当日 spot）"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return []
    cached = _cache_get(f"top10_codes_{trade_d}", 86400 * 30)
    if cached:
        return list(cached)
    if trade_d == date_str(bj_now()):
        codes = _snapshot_top10_codes()
        if codes:
            _cache_set(f"top10_codes_{trade_d}", codes)
        return codes
    return []


def _df_col(df: Optional[pd.DataFrame], name: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    if name in df.columns:
        return name
    for col in df.columns:
        if str(col).strip() == name:
            return col
    return None


def _normalize_code_list(codes) -> list[str]:
    if not codes:
        return []
    if isinstance(codes, str):
        codes = re.split(r"[,，\s]+", codes)
    out: list[str] = []
    for code in codes:
        c = re.sub(r"\D", "", str(code or "")).zfill(6)
        if len(c) == 6 and c not in out:
            out.append(c)
    return out


def _snapshot_top10_codes(spot_df: Optional[pd.DataFrame] = None) -> list[str]:
    try:
        df = spot_df if spot_df is not None else ak.stock_zh_a_spot_em()
        amount_col = _df_col(df, "\u6210\u4ea4\u989d")
        code_col = _df_col(df, "\u4ee3\u7801")
        if df is None or df.empty or not amount_col or not code_col:
            return []
        return (
            df.nlargest(10, amount_col)[code_col]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
            .str.zfill(6)
            .tolist()
        )
    except Exception:
        return []


def _avg_pct_chg(spot_df: Optional[pd.DataFrame], codes: Optional[list[str]] = None) -> Optional[float]:
    pct_col = _df_col(spot_df, "\u6da8\u8dcc\u5e45")
    if spot_df is None or spot_df.empty or not pct_col:
        return None
    df = spot_df
    if codes:
        code_col = _df_col(df, "\u4ee3\u7801")
        if not code_col:
            return None
        normalized_codes = _normalize_code_list(codes)
        norm = df[code_col].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
        sub = df[norm.isin(normalized_codes)]
        if sub.empty or len(sub) < len(normalized_codes):
            return None
        df = sub
    else:
        amount_col = _df_col(df, "\u6210\u4ea4\u989d")
        if amount_col:
            df = df.nlargest(10, amount_col)
    val = pd.to_numeric(df[pct_col], errors="coerce").mean(skipna=True)
    if pd.isna(val):
        return None
    return round(float(val), 2)


def _avg_open_pct_for_top_amount(
    spot_df: Optional[pd.DataFrame],
    codes: Optional[list[str]] = None,
) -> Optional[float]:
    open_col = _df_col(spot_df, "\u4eca\u5f00")
    prev_col = _df_col(spot_df, "\u6628\u6536")
    if spot_df is None or spot_df.empty or not open_col or not prev_col:
        return None
    df = spot_df
    if codes:
        code_col = _df_col(df, "\u4ee3\u7801")
        if not code_col:
            return None
        norm = df[code_col].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
        sub = df[norm.isin(_normalize_code_list(codes))]
        if sub.empty:
            return None
        df = sub
    else:
        amount_col = _df_col(df, "\u6210\u4ea4\u989d")
        if amount_col:
            df = df.nlargest(10, amount_col)
    o = pd.to_numeric(df[open_col], errors="coerce")
    p = pd.to_numeric(df[prev_col], errors="coerce").replace(0, pd.NA)
    val = ((o - p) / p * 100).mean(skipna=True)
    if pd.isna(val):
        return None
    return round(float(val), 2)


def _load_top10_codes_from_daily_market(trade_d: str) -> list[str]:
    trade_d = (trade_d or "").replace("-", "")[:8]
    if not trade_d:
        return []
    try:
        from history_store import fetch_daily_detail

        detail = fetch_daily_detail(trade_d)
        codes = ((detail or {}).get("metrics") or {}).get("top10_codes")
        return _normalize_code_list(codes)
    except Exception:
        return []


def _load_top10_codes_for_date(trade_d: str) -> list[str]:
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return []
    cached = _cache_get(f"top10_codes_{trade_d}", 86400 * 30)
    if cached:
        return _normalize_code_list(cached)
    stored = _load_top10_codes_from_daily_market(trade_d)
    if stored:
        _cache_set(f"top10_codes_{trade_d}", stored)
        return stored
    if trade_d == date_str(bj_now()):
        codes = _snapshot_top10_codes()
        if codes:
            _cache_set(f"top10_codes_{trade_d}", codes)
        return codes
    return []


def _resolve_prev_top10_avg(ref_metrics: Optional[dict], ref_d: str = "") -> Optional[float]:
    """T-1 前10 平均涨幅的「昨」：ref 日收盘归档"""
    ref_metrics = ref_metrics or {}
    val = ref_metrics.get("top10_avg_chg")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    ref_d = (ref_d or ref_metrics.get("date") or "").replace("-", "")[:8]
    if not ref_d:
        return None
    key = f"top10_avg_chg_{ref_d}"
    cached = _cache_get(key, 86400 * 7)
    if cached is not None:
        return float(cached)
    if em_pool_available(ref_d):
        try:
            m = build_ref_day_metrics(ref_d, None)
            chg = m.get("top10_avg_chg")
            if chg is not None:
                _cache_set(key, float(chg))
                return float(chg)
        except Exception:
            pass
    return None


def fetch_intraday_board_stats(
    ref_d: str,
    ref_metrics: Optional[dict] = None,
    *,
    live: bool = False,
) -> dict:
    """
    盘中扩展指标：T-1 成交额前10平均涨幅、T-1日涨停晋级率、实时炸板率。
    对比基准均为 ref_metrics（昨日收盘归档）。
    live=True 时按 INTRADAY_CACHE_TTL 刷新（与 2 分钟任务对齐）。
    """
    ref_metrics = ref_metrics or {}
    ref_d = (ref_d or "")[:8]
    today = date_str(bj_now())

    cache_ttl = INTRADAY_CACHE_TTL if live else 90
    cached = _cache_get("intraday_board_stats_v1", cache_ttl)
    if cached:
        return cached

    spot_df = None
    try:
        spot_df = ak.stock_zh_a_spot_em()
    except Exception:
        spot_df = None
    if spot_df is None or spot_df.empty:
        spot_df = _fetch_em_top_amount_spot_df()

    ref_codes = _normalize_code_list(ref_metrics.get("top10_codes") or [])
    if not ref_codes:
        ref_codes = _load_top10_codes_for_date(ref_d)
    top10_live = _avg_pct_chg(spot_df, ref_codes if ref_codes else None)
    if top10_live is None and ref_codes:
        top10_live = _avg_open_pct_for_top_amount(spot_df, ref_codes)
    prev_top10_f = _resolve_prev_top10_avg(ref_metrics, ref_d)

    promote_live = _promote_rate(ref_d, today) if ref_d and ref_d != today else None
    prev_promote = float(ref_metrics.get("promote_rate") or 0)

    break_live = _break_rate(today) if today else 0.0
    prev_break = float(ref_metrics.get("break_rate") or 0)

    out = {
        "top10_avg_live": top10_live,
        "prev_top10_avg": prev_top10_f,
        "promote_live": promote_live,
        "prev_promote": prev_promote,
        "break_live": break_live,
        "prev_break": prev_break,
    }
    _cache_set("intraday_board_stats_v1", out)
    return out


def _seal_rate(d: str) -> float:
    """封板率 = 成功封板数 / (成功封板 + 炸板)。
    直接从两个池计算，避免 break_rate=0 时误判（0.0 falsy → 封板率错误返回 0）。
    """
    df_up = fetch_limit_up(d)
    df_broken = fetch_broken_board(d)
    up_n = len(df_up) if df_up is not None and not df_up.empty else 0
    broken_n = len(df_broken) if df_broken is not None and not df_broken.empty else 0
    total = up_n + broken_n
    if total == 0:
        return 0.0
    return round(up_n / total * 100, 1)


def _auction_up_estimate() -> int:
    """盘中用实时涨停近似竞价涨停；收盘后用涨停池"""
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return 0
        if "涨跌幅" not in df.columns:
            return 0
        return int((pd.to_numeric(df["涨跌幅"], errors="coerce") >= 9.9).sum())
    except Exception:
        return 0


def _snapshot_grid9_complete(metrics: Optional[dict], grid9: Optional[list]) -> bool:
    if not metrics or not grid9:
        return False
    return len(grid9) >= 9 and bool(metrics.get("date"))


def build_ref_day_metrics(trade_d: str, prev_d: Optional[str] = None) -> dict:
    """
    ref 日收盘快照（昨日情绪 9 项数据源）。
    涨停/跌停/炸板以东财股池为准；封板率/晋级率在日终写入时计算一次。
    """
    trade_d = (trade_d or "")[:8]
    prev_d = (prev_d or "")[:8] if prev_d else None

    df_up = fetch_limit_up(trade_d)
    df_down = fetch_limit_down(trade_d)
    limit_up = len(df_up) if df_up is not None and not df_up.empty else 0
    limit_down = len(df_down) if df_down is not None and not df_down.empty else 0
    max_board = _max_board(df_up)
    # 连板分布：首板 / 连板数量（用于连板占比指标）
    first_board_count: Optional[int] = None
    multi_board_count: Optional[int] = None
    if df_up is not None and not df_up.empty and "连板数" in df_up.columns:
        boards = pd.to_numeric(df_up["连板数"], errors="coerce").fillna(1)
        first_board_count = int((boards == 1).sum())
        multi_board_count = int((boards >= 2).sum())
    promote = _promote_rate(prev_d, trade_d) if prev_d else 0.0
    high_board_promote = _high_board_promote(prev_d, trade_d) if prev_d else None  # (continued, total)
    break_r = _break_rate(trade_d)
    seal_r = _seal_rate(trade_d)
    one_word = _one_word_count(df_up)
    index_chg = fetch_sse_index_change(trade_d)
    volume_amount, volume_raw = _fetch_daily_market_amount_with_raw(trade_d)
    advance_count, decline_count = get_market_breadth(trade_d)

    top10_codes: list[str] = []
    top10_avg_chg = None
    if trade_d == date_str(bj_now()):
        spot_df = None
        try:
            spot_df = ak.stock_zh_a_spot_em()
        except Exception:
            pass
        if spot_df is None or spot_df.empty:
            spot_df = _fetch_em_top_amount_spot_df()
        try:
            top10_codes = _snapshot_top10_codes(spot_df)
            top10_avg_chg = _avg_pct_chg(spot_df, top10_codes)
            if top10_codes:
                _cache_set(f"top10_codes_{trade_d}", top10_codes)
        except Exception:
            pass
    else:
        top10_codes = _load_top10_codes_for_date(trade_d)

    return {
        "date": f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}",
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "max_board": max_board,
        "promote_rate": promote,
        "break_rate": break_r,
        "seal_rate": seal_r,
        "one_word_count": one_word,
        "index_chg": index_chg,
        "volume_amount": volume_amount,
        "volume_raw": volume_raw,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "top10_codes": top10_codes,
        "top10_avg_chg": top10_avg_chg,
        "first_board_count": first_board_count,
        "multi_board_count": multi_board_count,
        "high_board_promote_continued": high_board_promote[0] if high_board_promote else None,
        "high_board_promote_total": high_board_promote[1] if high_board_promote else None,
    }


def _enrich_metrics_volume_avg(metrics: dict, ref_d: str) -> dict:
    """注入 volume_20d_avg（20日成交量均值）供动态量能评分使用。失败时静默跳过。"""
    if metrics.get("volume_20d_avg"):
        return metrics
    try:
        from history_store import fetch_avg_volume_yi
        avg = fetch_avg_volume_yi(ref_d, days=20)
        if avg and avg > 0:
            metrics = {**metrics, "volume_20d_avg": avg}
    except Exception:
        pass
    return metrics


def load_ref_day_snapshot(ref_d: str, prev_d: Optional[str] = None) -> tuple[dict, Optional[dict], list]:
    """
    读取 ref 日昨日情绪快照：优先 MySQL 归档，近 30 日无归档时从东财计算一次。
    超过 30 日且 MySQL 无记录时不再调东财。
    """
    ref_d = (ref_d or "")[:8]
    prev_d = (prev_d or "")[:8] if prev_d else None
    prev_prev_d = _get_prev_trade_d(prev_d) if prev_d else None

    try:
        from history_store import fetch_daily_detail
    except Exception:
        fetch_daily_detail = None  # type: ignore

    ref_detail = fetch_daily_detail(ref_d) if fetch_daily_detail else None
    if ref_detail and _snapshot_grid9_complete(ref_detail.get("metrics"), ref_detail.get("grid9")):
        raw_metrics = ref_detail["metrics"]
        prev_metrics = None
        if prev_d and fetch_daily_detail:
            prev_detail = fetch_daily_detail(prev_d)
            if prev_detail and prev_detail.get("metrics"):
                prev_metrics = _fill_metrics_breadth(prev_detail["metrics"], prev_d)
        metrics = _enrich_metrics_volume_avg(_fill_metrics_breadth(raw_metrics, ref_d), ref_d)
        grid9 = build_yesterday_sentiment(metrics, prev_metrics)
        return metrics, prev_metrics, grid9

    if em_pool_available(ref_d):
        metrics = _enrich_metrics_volume_avg(
            _fill_metrics_breadth(build_ref_day_metrics(ref_d, prev_d), ref_d), ref_d
        )
        prev_metrics = (
            _fill_metrics_breadth(build_ref_day_metrics(prev_d, prev_prev_d), prev_d)
            if prev_d
            else None
        )
        grid9 = build_yesterday_sentiment(metrics, prev_metrics)
        return metrics, prev_metrics, grid9

    if ref_detail:
        metrics = _enrich_metrics_volume_avg(
            _fill_metrics_breadth(
                ref_detail.get("metrics") or build_ref_day_metrics(ref_d, prev_d), ref_d
            ),
            ref_d,
        )
        prev_metrics = None
        if prev_d and fetch_daily_detail:
            prev_detail = fetch_daily_detail(prev_d)
            if prev_detail and prev_detail.get("metrics"):
                prev_metrics = _fill_metrics_breadth(prev_detail["metrics"], prev_d)
        grid9 = build_yesterday_sentiment(metrics, prev_metrics)
        return metrics, prev_metrics, grid9

    metrics = _enrich_metrics_volume_avg(
        _fill_metrics_breadth(build_ref_day_metrics(ref_d, prev_d), ref_d), ref_d
    )
    prev_metrics = (
        _fill_metrics_breadth(build_ref_day_metrics(prev_d, prev_prev_d), prev_d)
        if prev_d
        else None
    )
    grid9 = build_yesterday_sentiment(metrics, prev_metrics)
    return metrics, prev_metrics, grid9


def _try_load_frozen_auction(
    trade_d: str,
    ref_d: str,
    prev_d: Optional[str] = None,
) -> Optional[list]:
    """读取 daily_market 中已归档的竞价 6 项。"""
    trade_d = (trade_d or "")[:8]
    ref_d = (ref_d or "")[:8]
    if not trade_d:
        return None
    try:
        from history_store import fetch_daily_detail
    except Exception:
        return None
    detail = fetch_daily_detail(trade_d)
    if not detail:
        return None
    auc = detail.get("auction") or []
    if not auc:
        return None
    m = detail.get("metrics") or {}
    if not (
        m.get("auction_frozen")
        or m.get("auction_phase") in ("0926", "0935")
    ):
        return None
    return sanitize_auction_items(_apply_auction_prev_from_ref(auc, ref_d, prev_d))


def load_auction_snapshot(
    advice_d: str,
    ref_d: str,
    prev_d: Optional[str],
    metrics: dict,
    prev_metrics: Optional[dict],
    *,
    is_ready: bool = True,
) -> list:
    """今日竞价情绪：固化后读 MySQL，否则实时计算。"""
    advice_d = (advice_d or "")[:8]
    ref_d = (ref_d or "")[:8]
    today = date_str(bj_now())
    trade_dates = get_recent_trade_dates(15)
    adv_metrics = load_advice_metrics(advice_d) if advice_d else {}
    merged_metrics = {**dict(metrics or {}), **adv_metrics}

    frozen = _try_load_frozen_auction(advice_d, ref_d, prev_d)
    if frozen and not auction_items_incomplete(frozen):
        return frozen

    # 非交易日：展示最近一个交易日的竞价归档
    if advice_d == today and today not in trade_dates:
        last_td = trade_dates[-1] if trade_dates else ref_d
        if last_td and last_td != advice_d:
            archived = _try_load_frozen_auction(last_td, ref_d, prev_d)
            if archived:
                return archived

    # 9:25 前也返回 6 项占位（--），避免缓存写入空 items 后无法恢复
    return sanitize_auction_items(
        build_auction_sentiment(
            ref_d, merged_metrics, prev_metrics, prev_d, advice_d=advice_d
        )
    )


def load_advice_metrics(advice_d: str) -> dict:
    """读取 advice 日归档 meta（外围/竞价快照阶段）。"""
    advice_d = (advice_d or "")[:8]
    try:
        from history_store import fetch_daily_detail
    except Exception:
        return {}
    detail = fetch_daily_detail(advice_d)
    if not detail:
        return {}
    return detail.get("metrics") or {}


def build_day_metrics(trade_d: str, prev_d: Optional[str] = None) -> dict:
    """完整日指标（含竞价等）；昨日情绪 9 项以 build_ref_day_metrics 为准。"""
    trade_d = (trade_d or "")[:8]
    base = build_ref_day_metrics(trade_d, prev_d)

    df_up = fetch_limit_up(trade_d)
    limit_up = int(base.get("limit_up_count") or 0)

    activity = fetch_market_activity() if trade_d == date_str(bj_now()) else {}
    volume_amount = base.get("volume_amount", "--")
    volume_raw = float(base.get("volume_raw") or 0)
    if not volume_raw and activity.get("amount_raw"):
        volume_raw = float(activity.get("amount_raw") or 0)
        if volume_raw > 0 and volume_amount in ("--", ""):
            volume_amount = f"{round(volume_raw)}亿"

    auction_up = 0
    if trade_d == date_str(bj_now()) and bj_now().hour >= 9:
        auction_up = min(limit_up, _auction_up_estimate()) if limit_up else _auction_up_estimate()
    elif limit_up:
        auction_up = min(limit_up, max(3, limit_up // 3))

    first_board_count = multi_board_count = 0
    if df_up is not None and not df_up.empty and "连板数" in df_up.columns:
        boards = pd.to_numeric(df_up["连板数"], errors="coerce").fillna(1)
        first_board_count = int((boards == 1).sum())
        multi_board_count = int((boards >= 2).sum())

    auction_volume_yi = get_market_auction_volume_yi(trade_d)
    auction_one_word = _auction_one_word_count(trade_d)

    return {
        **base,
        "volume_amount": volume_amount,
        "volume_raw": volume_raw,
        "auction_up": auction_up,
        "auction_one_word_count": auction_one_word,
        "auction_median": 0.0,
        "auction_volume_yi": auction_volume_yi,
        "first_board_count": first_board_count,
        "multi_board_count": multi_board_count,
    }


def build_indicators(metrics: dict, prev_metrics: Optional[dict] = None) -> list:
    def trend(cur, prev):
        if prev is None:
            return "flat"
        return "up" if cur > prev else ("down" if cur < prev else "flat")

    prev = prev_metrics or {}
    items = [
        ("height", "📈", "连板高度", f"{metrics['max_board']}板", f"{prev.get('max_board', '-')}板", metrics["max_board"], trend(metrics["max_board"], prev.get("max_board"))),
        ("promote", "🔄", "晋级率", f"{metrics['promote_rate']:.0f}%", f"{prev.get('promote_rate', 0):.0f}%", metrics["promote_rate"], trend(metrics["promote_rate"], prev.get("promote_rate"))),
        ("limitUp", "🔴", "涨停家数", str(metrics["limit_up_count"]), str(prev.get("limit_up_count", "-")), metrics["limit_up_count"], trend(metrics["limit_up_count"], prev.get("limit_up_count"))),
        ("limitDown", "🟢", "跌停家数", str(metrics["limit_down_count"]), str(prev.get("limit_down_count", "-")), metrics["limit_down_count"], trend(metrics["limit_down_count"], prev.get("limit_down_count"))),
        ("auction", "⏰", "竞价涨幅中位数", f"{metrics.get('auction_median', 0):.2f}%", f"{prev.get('auction_median', 0):.2f}%", 30, "flat"),
        ("auctionUp", "🚀", "竞价涨停数", str(metrics.get("auction_up", 0)), str(prev.get("auction_up", "-")), metrics.get("auction_up", 0), trend(metrics.get("auction_up", 0), prev.get("auction_up"))),
        ("seal", "🔒", "封板率", f"{metrics['seal_rate']:.0f}%", f"{prev.get('seal_rate', 0):.0f}%", metrics["seal_rate"], trend(metrics["seal_rate"], prev.get("seal_rate"))),
        ("break", "💥", "炸板率", f"{metrics['break_rate']:.0f}%", f"{prev.get('break_rate', 0):.0f}%", metrics["break_rate"], trend(metrics["break_rate"], prev.get("break_rate"))),
    ]
    result = []
    for key, icon, title, value, yesterday, bar, tr in items:
        status = "偏强" if tr == "up" and key not in ("limitDown", "break") else ("偏弱" if tr == "down" else "中性")
        if key in ("limitDown", "break"):
            status = "偏强" if tr == "up" else ("偏弱" if tr == "down" else "中性")
        result.append({
            "key": key, "icon": icon, "title": title, "value": value,
            "yesterday": f"前日 {yesterday}" if not str(yesterday).startswith("前") else yesterday,
            "trend": tr, "status": status,
            "barPercent": min(100, int(bar)) if isinstance(bar, (int, float)) else 50,
            "yesterdayBar": min(100, int(bar) + 8) if isinstance(bar, (int, float)) else 50,
        })
    return result
