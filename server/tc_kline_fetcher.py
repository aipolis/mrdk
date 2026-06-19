# -*- coding: utf-8 -*-
"""TradeCheck 个股日 K 线获取(MySQL 缓存)"""
from __future__ import annotations

import logging
from typing import Optional

from db_store import db_connection, mysql_enabled

log = logging.getLogger(__name__)

_mem_cache: dict[str, list[dict]] = {}


def _ensure_table() -> bool:
    if not mysql_enabled():
        return False
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS tc_kline (
                    code VARCHAR(8) NOT NULL,
                    trade_date VARCHAR(10) NOT NULL,
                    open_p DECIMAL(12,3) NOT NULL,
                    high_p DECIMAL(12,3) NOT NULL,
                    low_p DECIMAL(12,3) NOT NULL,
                    close_p DECIMAL(12,3) NOT NULL,
                    volume DECIMAL(20,2) NOT NULL DEFAULT 0,
                    amount DECIMAL(20,2) NOT NULL DEFAULT 0,
                    prev_close DECIMAL(12,3) NOT NULL DEFAULT 0,
                    limit_price DECIMAL(12,3) NOT NULL DEFAULT 0,
                    PRIMARY KEY(code, trade_date)
                ) DEFAULT CHARSET=utf8mb4"""
            )
        conn.commit()
    return True


def _limit_rate(code: str) -> float:
    if code.startswith(("30", "68")):
        return 1.20  # 创业板 / 科创板
    if code.startswith(("8", "4")):
        return 1.30  # 北交所
    return 1.10  # 主板


def _calc_limit_price(code: str, prev_close: float) -> float:
    if not prev_close:
        return 0.0
    return round(prev_close * _limit_rate(code), 2)


def _read_cache(code: str, start: str, end: str) -> list[dict]:
    if mysql_enabled():
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT trade_date, open_p, high_p, low_p, close_p,
                              volume, amount, prev_close, limit_price
                       FROM tc_kline
                       WHERE code=%s AND trade_date BETWEEN %s AND %s
                       ORDER BY trade_date""",
                    (code, start, end),
                )
                rows = cur.fetchall()
        return [
            {
                "date": r[0],
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]) if r[5] else 0,
                "amount": float(r[6]) if r[6] else 0,
                "prev_close": float(r[7]) if r[7] else 0,
                "limit_price": float(r[8]) if r[8] else 0,
            }
            for r in rows
        ]
    mem = _mem_cache.get(code, [])
    return [r for r in mem if start <= r["date"] <= end]


def fetch_one(code: str, start: str, end: str) -> list[dict]:
    """获取单只股票 [start, end] 区间日 K(YYYY-MM-DD)"""
    _ensure_table()
    code = code.zfill(6)
    cached = _read_cache(code, start, end)
    if cached:
        # 简化策略:本地有数据就用,不做"按交易日精确补齐"
        # 后续如需精确,改成判断 cached_dates 是否覆盖所有交易日
        return cached

    try:
        import akshare as ak

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",
        )
    except Exception as e:
        log.warning("[tc_kline] %s 拉取失败: %s", code, e)
        return []

    if df is None or df.empty:
        return []

    rows: list[tuple] = []
    prev_close: Optional[float] = None
    for _, r in df.iterrows():
        d = str(r["日期"])[:10]
        o = float(r["开盘"])
        h = float(r["最高"])
        l = float(r["最低"])
        c = float(r["收盘"])
        vol = float(r.get("成交量", 0) or 0)
        amt = float(r.get("成交额", 0) or 0)
        pc = prev_close if prev_close is not None else c
        lp = _calc_limit_price(code, pc)
        rows.append((code, d, o, h, l, c, vol, amt, pc, lp))
        prev_close = c

    if mysql_enabled() and rows:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT IGNORE INTO tc_kline
                       (code, trade_date, open_p, high_p, low_p, close_p,
                        volume, amount, prev_close, limit_price)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    rows,
                )
            conn.commit()
    else:
        _mem_cache.setdefault(code, []).extend(
            [
                {
                    "date": r[1],
                    "open": r[2],
                    "high": r[3],
                    "low": r[4],
                    "close": r[5],
                    "volume": r[6],
                    "amount": r[7],
                    "prev_close": r[8],
                    "limit_price": r[9],
                }
                for r in rows
            ]
        )

    return _read_cache(code, start, end)
