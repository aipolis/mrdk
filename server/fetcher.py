# -*- coding: utf-8 -*-
"""akshare / 新浪 数据抓取层"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import akshare as ak
import pandas as pd
import requests

_cache: dict = {}

# 东财涨停/跌停/炸板股池可回溯约 30 个自然日；更早仅读 MySQL 归档
EM_POOL_MAX_AGE_DAYS = 30

# 盘中 2 分钟刷新周期（略小于 IntervalTrigger 120s，避免命中旧缓存）
INTRADAY_CACHE_TTL = 100


def _cache_get(key: str, ttl: int = 300):
    item = _cache.get(key)
    if item and time.time() - item["ts"] < ttl:
        return item["data"]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"ts": time.time(), "data": data}


def invalidate_intraday_caches(today: Optional[str] = None) -> None:
    """盘中定时刷新前清缓存，保证 high10 / top10 / 晋级率 等与 2 分钟任务同步。"""
    today = (today or date_str(datetime.now()))[:8]
    for key in (
        "high10_stats_v1",
        "intraday_board_stats_v1",
        f"zt_{today}",
        f"zb_{today}",
    ):
        _cache.pop(key, None)


def date_str(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def parse_date(s: str) -> datetime:
    s = s.replace("-", "")
    return datetime.strptime(s[:8], "%Y%m%d")


def get_recent_trade_dates(count: int = 35) -> list[str]:
    key = f"trade_dates_{count}"
    cached = _cache_get(key, 86400)
    if cached:
        return cached
    try:
        df = ak.tool_trade_date_hist_sina()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        today = datetime.now()
        dates = df[df["trade_date"] <= today]["trade_date"].dt.strftime("%Y%m%d").tolist()
        result = dates[-count:]
        _cache_set(key, result)
        return result
    except Exception:
        result = []
        d = datetime.now()
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
        return (datetime.now() - d).days <= EM_POOL_MAX_AGE_DAYS
    except Exception:
        return False


def fetch_limit_up(d: str, *, ttl: Optional[int] = None) -> pd.DataFrame:
    d = (d or "")[:8]
    key = f"zt_{d}"
    if ttl is None:
        ttl = INTRADAY_CACHE_TTL if d == date_str(datetime.now()) else 300
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
        ttl = INTRADAY_CACHE_TTL if d == date_str(datetime.now()) else 300
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


def _spot_market_amount_yi(spot_df: Optional[pd.DataFrame] = None) -> tuple[str, float]:
    """A 股实时总成交额（亿）；优先腾讯指数汇总，东财全 A 兜底"""
    amt, raw = _fetch_market_amount_tencent(date_str(datetime.now()))
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
    return (int(adv or 0) + int(dec or 0)) >= 50


def _one_word_count(df_up: pd.DataFrame) -> int:
    """收盘一字板：竞价即封死（首末封板时间相同且 ≤09:30）"""
    if df_up is None or df_up.empty:
        return 0
    if "首次封板时间" in df_up.columns and "最后封板时间" in df_up.columns:
        first = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
        last = df_up["最后封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
        mask = (first == last) & (first <= "093000") & (first >= "092500")
        return int(mask.sum())
    # 旧版 akshare 字段名；不可用「炸板次数==0」（会把全天未开板算进去，数量偏大）
    if "开板次数" in df_up.columns:
        try:
            open_cnt = pd.to_numeric(df_up["开板次数"], errors="coerce").fillna(99)
            first_ok = pd.Series([True] * len(df_up), index=df_up.index)
            if "首次封板时间" in df_up.columns:
                first_t = df_up["首次封板时间"].astype(str).str.replace(":", "", regex=False).str.zfill(6)
                first_ok = first_t <= "093000"
            return int(((open_cnt == 0) & first_ok).sum())
        except Exception:
            pass
    return 0


def _auction_one_word_count(trade_d: str, spot_df: Optional[pd.DataFrame] = None) -> Optional[int]:
    """竞价一字板：开盘即涨停且最低价未破开盘价；当日拉取失败返回 None"""
    today = date_str(datetime.now())
    trade_d = (trade_d or "")[:8]
    if trade_d == today:
        try:
            df = spot_df if spot_df is not None else ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return None
            open_p = pd.to_numeric(df.get("今开"), errors="coerce")
            high = pd.to_numeric(df.get("最高"), errors="coerce")
            low = pd.to_numeric(df.get("最低"), errors="coerce")
            pre = pd.to_numeric(df.get("昨收"), errors="coerce").replace(0, pd.NA)
            open_pct = (open_p - pre) / pre * 100
            mask = (
                (open_pct >= 9.8)
                & (open_p > 0)
                & (high > 0)
                & (open_p >= high * 0.998)
                & (low >= open_p * 0.998)
            )
            return int(mask.sum())
        except Exception:
            return None
    # 历史日：用当日涨停池早盘封板口径
    return _one_word_count(fetch_limit_up(trade_d))


PERIPHERAL_CACHE_TTL = 600  # 外围情绪 10 分钟刷新


def invalidate_peripheral_cache() -> None:
    _cache.pop("peripheral_sent", None)


def fetch_peripheral_sentiment() -> list[dict]:
    """外围情绪及指数（3项）：富时A50、标普500、离岸人民币"""
    key = "peripheral_sent"
    cached = _cache_get(key, PERIPHERAL_CACHE_TTL)
    if cached:
        return cached
    result: list[dict] = []

    def _append_index(label: str, price, chg: float):
        price_s = _display_text(price)
        chg_f = _safe_float(chg)
        has_price = price_s != "--"
        chg_text = f"{chg_f:+.2f}%" if has_price and chg_f is not None else "--"
        result.append({
            "key": label,
            "name": label,
            "label": label,
            "price": price_s,
            "value": price_s,
            "chg": chg_f if chg_f is not None else None,
            "chgText": chg_text,
            "up": chg_f >= 0 if chg_f is not None else False,
            "trend": "up" if (chg_f is not None and chg_f >= 0) else "down" if chg_f is not None else "flat",
        })

    def _append_fx(label: str, price, chg: float = 0.0):
        price_s = _display_text(price)
        chg_f = _safe_float(chg)
        has_price = price_s != "--"
        chg_text = f"{chg_f:+.2f}%" if has_price and chg_f is not None and chg_f != 0 else "--"
        result.append({
            "key": label,
            "name": label,
            "label": label,
            "price": price_s,
            "value": price_s,
            "chg": chg_f if chg_f is not None else None,
            "chgText": chg_text,
            "up": chg_f >= 0 if chg_f is not None else False,
            "trend": "up" if (chg_f is not None and chg_f >= 0) else "down" if chg_f is not None else "flat",
        })

    a50_done = False
    try:
        df = ak.index_global_spot_em()
        if df is not None and not df.empty:
            name_col = "名称" if "名称" in df.columns else df.columns[0]
            for kw in ("富时中国A50", "富时A50", "A50"):
                row = df[df[name_col].astype(str).str.contains(kw, na=False)]
                if not row.empty:
                    r0 = row.iloc[0]
                    chg = _safe_float(r0.get("涨跌幅", 0), 0.0) or 0.0
                    price = _display_text(r0.get("最新价", r0.get("当前价")))
                    if price != "--":
                        _append_index("富时A50指数", price, chg)
                        a50_done = True
                        break
    except Exception:
        pass
    if not a50_done:
        try:
            df = ak.stock_hk_index_spot_em()
            row = df[df["名称"].astype(str).str.contains("富时中国A50|富时A50", na=False)]
            if not row.empty:
                r0 = row.iloc[0]
                chg = _safe_float(r0.get("涨跌幅", 0), 0.0) or 0.0
                price = _display_text(r0.get("最新价", r0.get("当前价")))
                if price != "--":
                    _append_index("富时A50指数", price, chg)
                    a50_done = True
        except Exception:
            pass
    if not a50_done:
        _append_index("富时A50指数", "--", 0.0)

    sp_done = False
    try:
        df_us = ak.index_us_stock_sina()
        if df_us is not None and not df_us.empty:
            sp = df_us[df_us["名称"].astype(str).str.contains("标普500", na=False)]
            if not sp.empty:
                r0 = sp.iloc[0]
                chg = _safe_float(r0.get("涨跌幅", 0), 0.0) or 0.0
                price = _display_text(r0.get("最新价", r0.get("当前价")))
                if price != "--":
                    _append_index("标普500", price, chg)
                    sp_done = True
    except Exception:
        pass
    if not sp_done:
        _append_index("标普500", "--", 0.0)

    fx_done = False
    try:
        df_fx = ak.fx_spot_quote()
        if df_fx is not None and not df_fx.empty:
            usd = df_fx[df_fx["货币对"].astype(str).str.contains("USD/CNH", na=False)]
            if usd.empty:
                usd = df_fx.head(1)
            if not usd.empty:
                r0 = usd.iloc[0]
                price = _display_text(r0.get("最新价", r0.iloc[-1] if len(r0) else None))
                chg = _safe_float(r0.get("涨跌幅", 0))
                if price != "--":
                    _append_fx("离岸人民币", price, chg if chg is not None else 0.0)
                    fx_done = True
    except Exception:
        pass
    if not fx_done:
        _append_fx("离岸人民币", "--", 0.0)

    _cache_set(key, result[:3])
    return result[:3]


def fetch_overview_spot() -> list[dict]:
    """兼容旧字段：等同外围情绪三项"""
    return fetch_peripheral_sentiment()


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
# 两市成交额 ≈ 上证 + 深证综指（与常见行情口径一致）
_MARKET_AMOUNT_QT_CODES = ("sh000001", "sz399106")
_MARKET_AMOUNT_BS_CODES = ("sh.000001", "sz.399106")


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


def _fetch_market_amount_tencent(trade_d: str) -> tuple[str, float]:
    """腾讯财经：当日实时两市成交额（历史日请用 Baostock）"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(datetime.now()):
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
    """指定交易日 A 股两市成交额（亿）；优先腾讯 / Baostock，akshare 兜底"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return "--", 0.0
    key = f"market_amt_{trade_d}"
    ttl = 90 if trade_d == date_str(datetime.now()) else 86400
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached

    today = date_str(datetime.now())
    if trade_d == today:
        chain = (
            _fetch_market_amount_tencent,
            _fetch_market_amount_baostock,
            _fetch_market_amount_akshare_em,
        )
    else:
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
    now = now or datetime.now()
    minute = now.minute - (now.minute % 2)
    return f"{now.hour:02d}{minute:02d}"


def _in_trading_minute_window(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
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
    now = now or datetime.now()
    if not _in_trading_minute_window(now):
        return
    hhmm = _intraday_snap_hhmm(now)
    key = f"vol_intraday_map_{trade_d}"
    snap_map = dict(_cache_get(key, 86400 * 10) or {})
    snap_map[hhmm] = round(float(amount_raw), 1)
    _cache_set(key, snap_map)


def _lookup_volume_snapshot(ref_d: str, hhmm: str) -> Optional[float]:
    snap_map = _cache_get(f"vol_intraday_map_{ref_d}", 86400 * 10) or {}
    if not snap_map:
        return None
    if hhmm in snap_map:
        return float(snap_map[hhmm])
    prior = sorted(k for k in snap_map.keys() if k <= hhmm)
    if prior:
        return float(snap_map[prior[-1]])
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
    now = now or datetime.now()
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
    now = now or datetime.now()
    if _in_trading_minute_window(now):
        same = fetch_ref_volume_at_same_time(ref_d, now)
        if same and same > 0:
            return f"{round(float(same))}亿", float(same)
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


def _fetch_sse_chg_tencent(trade_d: str) -> Optional[float]:
    """腾讯财经：当日实时上证涨跌幅 %"""
    trade_d = (trade_d or "")[:8]
    if trade_d != date_str(datetime.now()):
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

    today = date_str(datetime.now())
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
    now = now or datetime.now()
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
        if adv or dec:
            return adv, dec, stat_d
    except Exception:
        pass
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


def get_market_breadth(trade_d: str) -> tuple[int, int]:
    """
    指定交易日全市场上涨/下跌家数。
    优先读缓存 / MySQL 归档；乐股按统计日期匹配；历史日兜底 Baostock。
    """
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return 0, 0

    key = f"market_breadth_{trade_d}"
    cached = _cache_get(key, 86400 * 30)
    if cached is not None:
        adv = int(cached.get("advance", 0))
        dec = int(cached.get("decline", 0))
        if _breadth_valid(adv, dec):
            return adv, dec

    adv, dec = _breadth_from_daily_market(trade_d)
    if _breadth_valid(adv, dec):
        _cache_set(key, {"advance": adv, "decline": dec})
        return adv, dec

    today = date_str(datetime.now())
    adv, dec, stat_d = _fetch_market_breadth_live()
    if stat_d == trade_d and _breadth_valid(adv, dec):
        _cache_set(key, {"advance": adv, "decline": dec})
        return adv, dec

    if trade_d == today and _breadth_valid(adv, dec):
        if _after_market_close():
            _cache_set(key, {"advance": adv, "decline": dec})
        return adv, dec

    adv, dec = _fetch_market_breadth_baostock(trade_d)
    if _breadth_valid(adv, dec):
        _cache_set(key, {"advance": adv, "decline": dec})
    return adv, dec


def _fill_metrics_breadth(metrics: dict, trade_d: str) -> dict:
    """补齐 metrics 中的上涨/下跌家数（避免 0 误写入前日对比）"""
    trade_d = (trade_d or "")[:8]
    adv = int(metrics.get("advance_count") or 0)
    dec = int(metrics.get("decline_count") or 0)
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
    """昨日情绪概览 9 项"""
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

    return [
        {"key": "height", "label": "连板高度", "value": f"{metrics['max_board']}板", "yesterday": f"{_y('max_board')}板", "trend": _trend(metrics["max_board"], prev.get("max_board"))},
        {"key": "limitUp", "label": "涨停家数", "value": str(metrics["limit_up_count"]), "yesterday": str(_y("limit_up_count")), "trend": _trend(metrics["limit_up_count"], prev.get("limit_up_count"))},
        {"key": "seal", "label": "封板率", "value": f"{metrics['seal_rate']:.0f}%", "yesterday": f"{_y('seal_rate')}%", "trend": _trend(metrics["seal_rate"], prev.get("seal_rate"))},
        {"key": "promote", "label": "晋级率", "value": f"{metrics['promote_rate']:.0f}%", "yesterday": f"{_y('promote_rate')}%", "trend": _trend(metrics["promote_rate"], prev.get("promote_rate"))},
        {"key": "limitDown", "label": "跌停家数", "value": str(metrics["limit_down_count"]), "yesterday": str(_y("limit_down_count")), "trend": _trend(metrics["limit_down_count"], prev.get("limit_down_count"), inverse=True)},
        {"key": "break", "label": "炸板率", "value": f"{metrics['break_rate']:.0f}%", "yesterday": f"{_y('break_rate')}%", "trend": _trend(metrics["break_rate"], prev.get("break_rate"), inverse=True)},
        {"key": "oneWord", "label": "一字板", "value": str(metrics.get("one_word_count", 0)), "yesterday": str(_y("one_word_count")), "trend": _trend(metrics.get("one_word_count", 0), prev.get("one_word_count"))},
        {"key": "volume", "label": "市场量能", "value": str(vol), "yesterday": str(vol_prev), "trend": _trend(metrics.get("volume_raw", 0), prev.get("volume_raw")) if prev.get("volume_raw") else "flat"},
        {
            "key": "advance",
            "label": "上涨家数",
            "value": str(adv) if _breadth_valid(adv, dec) else str(adv or "--"),
            "yesterday": prev_adv_s,
            "advance_up": adv,
            "prev_advance_up": prev_adv_cmp if prev_adv_cmp not in (None, "-") else prev_adv_s,
            "trend": _trend(adv, prev_adv_cmp),
        },
    ]


def build_grid_nine(metrics: dict, prev_metrics: Optional[dict] = None) -> list:
    return build_yesterday_sentiment(metrics, prev_metrics)


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
    if f is None or abs(f) < 1e-9:
        return "--"
    return f"{f:+.2f}%"


def sanitize_auction_items(items: list) -> list:
    """竞价块展示清洗：未获取到的 0 / 0% 统一为 --"""
    if not items:
        return items
    vol_item = next((it for it in items if it.get("key") == "auctionVolume"), None)
    vol_missing = _display_text((vol_item or {}).get("value")) == "--"
    pct_keys = frozenset(
        {"yesterdayFirst", "yesterdayMulti", "recentMulti", "top10AuctionChg"}
    )
    out = []
    for it in items:
        row = dict(it)
        key = row.get("key")
        val = _display_text(row.get("value"))
        if key in pct_keys and _auction_zero_placeholder(val):
            val = "--"
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
    """是否已过当日 9:25 竞价撮合"""
    now = now or datetime.now()
    return now.hour > 9 or (now.hour == 9 and now.minute >= 25)


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
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    )
    fields_try = ("f629", "f618", "f619", "f531", "f532", "f617")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    }
    for field in fields_try:
        for url in urls:
            try:
                params = {**base, "fields": f"f12,{field}", "pn": "1"}
                r = requests.get(url, params=params, headers=headers, timeout=25)
                j = r.json()
                data = j.get("data") or {}
                diff = data.get("diff") or []
                if not diff:
                    continue
                per = len(diff)
                pages = math.ceil(int(data.get("total") or per) / max(per, 1))
                subtotal = 0.0
                hits = 0
                for pn in range(1, min(pages + 1, 80)):
                    params = {**base, "fields": f"f12,{field}", "pn": str(pn)}
                    r = requests.get(url, params=params, headers=headers, timeout=25)
                    chunk = (r.json().get("data") or {}).get("diff") or []
                    for row in chunk:
                        v = pd.to_numeric(row.get(field), errors="coerce")
                        if v is not None and float(v) > 0:
                            subtotal += float(v)
                            hits += 1
                    if pn < pages:
                        time.sleep(0.12)
                yi = _yuan_total_to_yi(subtotal)
                if yi and hits >= 200 and 50 <= yi <= 2000:
                    return float(yi)
            except Exception:
                continue
    return None


def get_market_auction_volume_yi(trade_d: str) -> Optional[float]:
    """
    指定交易日 9:25 全市场竞价成交额（亿）。
    当日 9:25 后首次抓取并缓存，当日不再更新。
    """
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return None
    key = f"auction_vol_yi_{trade_d}"
    cached = _cache_get(key, 86400 * 30)
    if cached is not None:
        return float(cached)

    today = date_str(datetime.now())
    if trade_d > today:
        return None
    if trade_d == today and not _after_auction_925():
        return None

    yi = _compute_market_auction_volume_yi()
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

    df_ref = fetch_limit_up(ref_d)
    first_codes = _pool_codes_by_board(df_ref, False)
    multi_codes = _pool_codes_by_board(df_ref, True)
    max_board_codes = _pool_codes_by_max_board(df_ref)

    auction_one_word: Optional[int] = None
    top10_avg: Optional[float] = None
    spot_df = None
    spot_ok = False
    try:
        spot_df = ak.stock_zh_a_spot_em()
        spot_ok = spot_df is not None and not spot_df.empty
    except Exception:
        spot_df = None

    advice_d = (advice_d or date_str(datetime.now()))[:8]
    today = date_str(datetime.now())
    live_auction = advice_d == today and _after_auction_925()
    live_ready = live_auction and spot_ok

    if spot_ok and spot_df is not None:
        try:
            if "成交额" in spot_df.columns:
                top10 = spot_df.nlargest(10, "成交额")
                if "今开" in top10.columns and "昨收" in top10.columns:
                    o = pd.to_numeric(top10["今开"], errors="coerce")
                    p = pd.to_numeric(top10["昨收"], errors="coerce").replace(0, pd.NA)
                    avg = ((o - p) / p * 100).mean(skipna=True)
                    if not pd.isna(avg):
                        v = round(float(avg), 2)
                        if abs(v) > 1e-9:
                            top10_avg = v
                elif "涨跌幅" in top10.columns:
                    avg = pd.to_numeric(top10["涨跌幅"], errors="coerce").mean(skipna=True)
                    if not pd.isna(avg) and float(avg) != 0.0:
                        top10_avg = round(float(avg), 2)
        except Exception:
            pass

    auction_one_word = _auction_one_word_count(advice_d, spot_df)
    if live_auction and not live_ready:
        auction_one_word = None
        top10_avg = None

    first_board_chg = _avg_auction_chg_from_spot(first_codes, spot_df) if live_ready or advice_d != today else None
    multi_board_chg = _avg_auction_chg_from_spot(multi_codes, spot_df) if live_ready or advice_d != today else None
    recent_multi_chg = _avg_auction_chg_from_spot(max_board_codes, spot_df) if live_ready or advice_d != today else None
    if live_auction and not live_ready:
        first_board_chg = multi_board_chg = recent_multi_chg = None

    auction_yi = get_market_auction_volume_yi(advice_d)
    if auction_yi is None:
        stored = metrics.get("auction_volume_yi")
        if advice_d == ref_d and stored:
            auction_yi = float(stored)
    prev_yi = get_market_auction_volume_yi(ref_d)
    if prev_yi is None:
        stored_prev = metrics.get("auction_volume_yi")
        if stored_prev:
            prev_yi = float(stored_prev)
    auction_volume = _yi_display(auction_yi)
    prev_volume = _auction_ref_prev_display(
        ref_d, "auctionVolume", _yi_display(get_market_auction_volume_yi(ref_d)), prev_d=prev_d
    )

    prev_one_word = _auction_ref_prev_display(
        ref_d, "auctionOneWord", metrics.get("one_word_count"), prev_d=prev_d
    )
    if prev_one_word == "--":
        ow = _auction_one_word_count(ref_d)
        prev_one_word = str(ow) if ow is not None else "--"

    prev_top10 = metrics.get("auction_median")
    prev_top10_s = _auction_ref_prev_display(ref_d, "top10AuctionChg", prev_d=prev_d)
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

    prev_first_s = _auction_ref_prev_display(ref_d, "yesterdayFirst", prev_d=prev_d)
    prev_first_chg = None
    if prev_first_s not in ("", "--"):
        try:
            prev_first_chg = float(str(prev_first_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_first_chg = None
    elif prev_d:
        prev_first_chg = _avg_board_auction_chg_historical(prev_d, False, ref_d)

    prev_multi_s = _auction_ref_prev_display(ref_d, "yesterdayMulti", prev_d=prev_d)
    prev_multi_chg = None
    if prev_multi_s not in ("", "--"):
        try:
            prev_multi_chg = float(str(prev_multi_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_multi_chg = None
    elif prev_d:
        prev_multi_chg = _avg_board_auction_chg_historical(prev_d, True, ref_d)

    prev_recent_s = _auction_ref_prev_display(ref_d, "recentMulti", prev_d=prev_d)
    prev_recent_chg = None
    if prev_recent_s not in ("", "--"):
        try:
            prev_recent_chg = float(str(prev_recent_s).replace("%", "").replace("+", ""))
        except Exception:
            prev_recent_chg = None
    elif prev_d:
        prev_recent_chg = _avg_max_board_auction_chg_historical(prev_d, ref_d)

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
    if auction_volume == "--" and (auction_one_word is None or auction_one_word == 0):
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
) -> str:
    """昨：ref 日竞价归档同 key 主值；缺则试 prev_d 归档"""
    for d in ((ref_d or "")[:8], (prev_d or "")[:8]):
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
) -> list:
    """将竞价块对比列统一为 ref / prev 日 DB 归档值"""
    ref_d = (ref_d or "")[:8]
    if not auction or not ref_d:
        return auction
    out = []
    for it in auction:
        key = it.get("key")
        row = dict(it)
        if key:
            prev_s = _auction_ref_prev_display(ref_d, key, prev_d=prev_d)
            if prev_s != "--":
                prev_s = _auction_prev_display(prev_s)
                row["yesterday"] = prev_s
                row["prev"] = prev_s
        out.append(row)
    return out


def _relative_day_label(trade_d: str, today: str) -> str:
    """相对今天：昨天 / 前天 / MM-DD"""
    trade_d = (trade_d or "")[:8]
    today = (today or "")[:8]
    if not trade_d:
        return "--"
    if trade_d == today:
        return "今天"
    dates = get_recent_trade_dates(15)
    try:
        ti = dates.index(today) if today in dates else len(dates)
        di = dates.index(trade_d) if trade_d in dates else -1
        if di >= 0:
            gap = ti - di
            if gap == 1:
                return "昨天"
            if gap == 2:
                return "前天"
    except ValueError:
        pass
    return f"{trade_d[4:6]}-{trade_d[6:8]}"


def build_section_metas(
    ref_d: str,
    advice_d: str,
    is_ready: bool,
    ref_metrics: Optional[dict] = None,
    advice_metrics: Optional[dict] = None,
) -> tuple[dict, str, str]:
    """各板块 meta 与仪表盘综合更新时间"""
    now = datetime.now()
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

    if advice_d == today:
        peripheral_meta = f"{adv_label} {now_hm} 更新"
    elif adv_m.get("peripheral_db_phase") == "0900":
        peripheral_meta = f"{adv_label} 09:00 入库"
    else:
        peripheral_meta = f"{adv_label} 09:00 更新"

    if adv_m.get("auction_frozen") or adv_m.get("auction_phase") == "0935":
        auction_meta = f"{adv_label} 09:35 固化"
    elif adv_m.get("auction_phase") == "0926":
        auction_meta = f"{adv_label} 09:26 更新"
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
            else:
                intraday_meta = f"{adv_label} 9:30 起更新"
        except Exception:
            intraday_meta = f"{adv_label} 盘中更新"
    else:
        intraday_meta = f"{adv_label} 15:00 更新"

    metas = {
        "yesterday": yesterday_meta,
        "peripheral": peripheral_meta,
        "auction": auction_meta,
        "intraday": intraday_meta,
    }

    gauge_label = f"{ref_label} {gauge_hm} 更新"
    if ref_m.get("snapshot_frozen") or ref_m.get("snapshot_phase") == "1800":
        gauge_label = f"{ref_label} {gauge_hm} 固化"

    return metas, gauge_label, gauge_hm


def build_indicator_sections(
    ref_d: str,
    prev_d: Optional[str],
    metrics: dict,
    prev_metrics: Optional[dict] = None,
    *,
    advice_d: str = "",
    is_ready: bool = True,
) -> list[dict]:
    """三大类共 18 项指标"""
    if not advice_d:
        advice_d = ref_d
    metas, _, _ = build_section_metas(ref_d, advice_d, is_ready, ref_metrics=metrics)
    ref_label = _relative_day_label(ref_d, date_str(datetime.now()))
    adv_label = _relative_day_label(advice_d, date_str(datetime.now()))
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
            "id": "peripheral",
            "title": f"{adv_label}外围情绪及指数",
            "meta": metas["peripheral"],
            "layout": "row3",
            "cols": 3,
            "items": fetch_peripheral_sentiment(),
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
            peripheral = (detail or {}).get("peripheral")
            auction = (detail or {}).get("auction")
            grid9 = (detail or {}).get("grid9")
            score = calc_sentiment(
                m,
                peripheral=peripheral,
                auction=auction,
                grid9=grid9,
            ).get("score")
        trend.append({"date": f"{d[4:6]}-{d[6:8]}", "score": int(score or 0)})
    return trend


def display_level_label(score: int) -> str:
    if score >= 90:
        return "狂热"
    if score >= 80:
        return "高潮"
    if score >= 60:
        return "偏乐观"
    if score >= 40:
        return "中性"
    if score >= 20:
        return "偏谨慎"
    return "冰点"


def display_level_class(score: int) -> str:
    if score >= 90:
        return "frenzy"
    if score >= 80:
        return "climax"
    if score >= 60:
        return "optimistic"
    if score >= 40:
        return "neutral"
    if score >= 20:
        return "caution"
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


_EM_CLIST_URLS = (
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://79.push2.eastmoney.com/api/qt/clist/get",
)
_HIGH10_FS_CANDIDATES = (
    "b:MK0105",
    "b:MK0110",
    "b:MK0104",
    "b:MK0103",
    "b:MK0106",
    "b:MK0107",
)


def _fetch_em_board_total(fs: str) -> int:
    """东财特色板块列表 total（如创10日新高）"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    params = {
        "pn": "1",
        "pz": "1",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": fs,
        "fields": "f12",
    }
    for url in _EM_CLIST_URLS:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12)
            j = r.json()
            total = int((j.get("data") or {}).get("total") or 0)
            if total > 0:
                return total
        except Exception:
            continue
    return 0


def _legu_high_low_row(trade_d: str) -> Optional[dict]:
    """乐股创新高统计：指定交易日一行"""
    trade_d = (trade_d or "")[:8]
    if not trade_d:
        return None
    key = "legu_high_low_all"
    df = _cache_get(key, 3600)
    if df is None:
        try:
            df = ak.stock_a_high_low_statistics(symbol="all")
            _cache_set(key, df)
        except Exception:
            return None
    if df is None or df.empty:
        return None
    target = datetime.strptime(trade_d, "%Y%m%d").date()
    for _, row in df.iterrows():
        d = row.get("date")
        if d == target:
            return row.to_dict()
    return None


def fetch_high10_stats(ref_metrics: Optional[dict] = None, *, live: bool = False) -> dict:
    """
    10日新高个股数及相对昨日增减。
    live=True：盘中实时，仅东财板块 total，不走乐股日终 fallback。
    """
    ref_metrics = ref_metrics or {}
    cache_ttl = INTRADAY_CACHE_TTL if live else 120
    cached = _cache_get("high10_stats_v1", cache_ttl)
    if cached:
        return cached

    today_d = date_str(datetime.now())
    prev_d = None
    dates = get_recent_trade_dates(5)
    if today_d in dates:
        idx = dates.index(today_d)
        if idx > 0:
            prev_d = dates[idx - 1]
    elif len(dates) >= 2:
        prev_d = dates[-2]

    today_count = 0
    # ref_metrics = 昨日收盘归档，作为 10日新高对比基准
    prev_count = int(ref_metrics.get("high10_count") or 0)

    fs_hit = _cache_get("high10_fs", 86400 * 7)
    candidates = ([fs_hit] if fs_hit else []) + list(_HIGH10_FS_CANDIDATES)
    for fs in candidates:
        if not fs:
            continue
        n = _fetch_em_board_total(fs)
        if n >= 15:
            today_count = n
            _cache_set("high10_fs", fs)
            break

    if not today_count and not live:
        row = _legu_high_low_row(today_d)
        if row:
            today_count = int(row.get("high20") or 0)

    if prev_d:
        prev_row = _legu_high_low_row(prev_d)
        if prev_row:
            prev_count = int(prev_row.get("high20") or prev_count)
    elif not prev_count:
        try:
            df = ak.stock_a_high_low_statistics(symbol="all")
            if df is not None and len(df) >= 2:
                prev_count = int(df.iloc[-2].get("high20") or 0)
        except Exception:
            pass

    chg_pct = None
    if today_count and prev_count:
        chg_pct = round((today_count - prev_count) / prev_count * 100, 1)

    out = {
        "high10": today_count,
        "prev_high10": prev_count,
        "high10_chg_pct": chg_pct,
    }
    _cache_set("high10_stats_v1", out)
    return out


def fetch_high10_count_for_date(trade_d: str) -> int:
    """归档用：某日 10日新高家数"""
    trade_d = (trade_d or "")[:8]
    row = _legu_high_low_row(trade_d)
    if row:
        return int(row.get("high20") or 0)
    return 0


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
    if trade_d == date_str(datetime.now()):
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
    today = date_str(datetime.now())

    cache_ttl = INTRADAY_CACHE_TTL if live else 90
    cached = _cache_get("intraday_board_stats_v1", cache_ttl)
    if cached:
        return cached

    spot_df = None
    try:
        spot_df = ak.stock_zh_a_spot_em()
    except Exception:
        pass

    ref_codes = ref_metrics.get("top10_codes") or []
    if isinstance(ref_codes, str):
        ref_codes = [c.strip() for c in ref_codes.split(",") if c.strip()]
    if not ref_codes:
        ref_codes = _load_top10_codes_for_date(ref_d)
    top10_live = _avg_pct_chg(spot_df, ref_codes if ref_codes else None)
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
    br = _break_rate(d)
    return round(100 - br, 1) if br else 0.0


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
    promote = _promote_rate(prev_d, trade_d) if prev_d else 0.0
    break_r = _break_rate(trade_d)
    seal_r = _seal_rate(trade_d)
    one_word = _one_word_count(df_up)
    index_chg = fetch_sse_index_change(trade_d)
    volume_amount, volume_raw = _fetch_daily_market_amount_with_raw(trade_d)
    advance_count, decline_count = get_market_breadth(trade_d)
    high10_count = fetch_high10_count_for_date(trade_d)

    top10_codes: list[str] = []
    top10_avg_chg = None
    if trade_d == date_str(datetime.now()):
        try:
            spot_df = ak.stock_zh_a_spot_em()
            top10_codes = _snapshot_top10_codes(spot_df)
            top10_avg_chg = _avg_pct_chg(spot_df, top10_codes)
            if top10_codes:
                _cache_set(f"top10_codes_{trade_d}", top10_codes)
        except Exception:
            pass
    else:
        cached_codes = _cache_get(f"top10_codes_{trade_d}", 86400 * 30)
        if cached_codes:
            top10_codes = list(cached_codes)

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
        "high10_count": high10_count,
        "top10_codes": top10_codes,
        "top10_avg_chg": top10_avg_chg,
    }


def load_ref_day_snapshot(ref_d: str, prev_d: Optional[str] = None) -> tuple[dict, Optional[dict], list]:
    """
    读取 ref 日昨日情绪快照：优先 MySQL 归档，近 30 日无归档时从东财计算一次。
    超过 30 日且 MySQL 无记录时不再调东财。
    """
    ref_d = (ref_d or "")[:8]
    prev_d = (prev_d or "")[:8] if prev_d else None

    try:
        from history_store import fetch_daily_detail
    except Exception:
        fetch_daily_detail = None  # type: ignore

    ref_detail = fetch_daily_detail(ref_d) if fetch_daily_detail else None
    if ref_detail and _snapshot_grid9_complete(ref_detail.get("metrics"), ref_detail.get("grid9")):
        metrics = ref_detail["metrics"]
        grid9 = ref_detail["grid9"]
        prev_metrics = None
        if prev_d and fetch_daily_detail:
            prev_detail = fetch_daily_detail(prev_d)
            if prev_detail and prev_detail.get("metrics"):
                prev_metrics = prev_detail["metrics"]
        return metrics, prev_metrics, grid9

    if em_pool_available(ref_d):
        metrics = _fill_metrics_breadth(build_ref_day_metrics(ref_d, prev_d), ref_d)
        prev_metrics = (
            _fill_metrics_breadth(build_ref_day_metrics(prev_d, None), prev_d)
            if prev_d
            else None
        )
        grid9 = build_yesterday_sentiment(metrics, prev_metrics)
        return metrics, prev_metrics, grid9

    if ref_detail:
        metrics = ref_detail.get("metrics") or build_ref_day_metrics(ref_d, prev_d)
        prev_metrics = None
        if prev_d and fetch_daily_detail:
            prev_detail = fetch_daily_detail(prev_d)
            if prev_detail and prev_detail.get("metrics"):
                prev_metrics = prev_detail["metrics"]
        grid9 = ref_detail.get("grid9") or build_yesterday_sentiment(metrics, prev_metrics)
        return metrics, prev_metrics, grid9

    metrics = _fill_metrics_breadth(build_ref_day_metrics(ref_d, prev_d), ref_d)
    prev_metrics = (
        _fill_metrics_breadth(build_ref_day_metrics(prev_d, None), prev_d)
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
    today = date_str(datetime.now())
    trade_dates = get_recent_trade_dates(15)

    frozen = _try_load_frozen_auction(advice_d, ref_d, prev_d)
    if frozen:
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
            ref_d, metrics, prev_metrics, prev_d, advice_d=advice_d
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

    activity = fetch_market_activity() if trade_d == date_str(datetime.now()) else {}
    volume_amount = base.get("volume_amount", "--")
    volume_raw = float(base.get("volume_raw") or 0)
    if not volume_raw and activity.get("amount_raw"):
        volume_raw = float(activity.get("amount_raw") or 0)
        if volume_raw > 0 and volume_amount in ("--", ""):
            volume_amount = f"{round(volume_raw)}亿"

    auction_up = 0
    if trade_d == date_str(datetime.now()) and datetime.now().hour >= 9:
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
        ("auctionUp", "🚀", "竞价涨停数", str(metrics["auction_up"]), str(prev.get("auction_up", "-")), metrics["auction_up"], trend(metrics["auction_up"], prev.get("auction_up"))),
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
