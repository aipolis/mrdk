# -*- coding: utf-8 -*-
"""TradeCheck 专用路由组 — 让 TradeCheck.html 可以远程获取行情/涨停/情绪数据。

设计原则:
- 交割单 100% 不上传(纯前端处理),后端只接收 标的名/原始代码/日期范围;
- 返回 engine.js 可直接 parseMarket 的 CSV 文本;
- 复用 mrdk 已有的 akshare/MySQL/涨停股池/情绪指数。
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import tc_code_resolver
import tc_kline_fetcher

log = logging.getLogger(__name__)

tradecheck_router = APIRouter(prefix="/api/tradecheck", tags=["tradecheck"])


class BuildMarketReq(BaseModel):
    names: list[str]       # 与 raw_codes 一一对应的中文名
    raw_codes: list[str]   # 交割单里原始代码(拼音简称或 6 位数字)
    start_date: str        # YYYY-MM-DD
    end_date: str          # YYYY-MM-DD


def _safe_fetch_limit_up(date_yyyymmdd: str):
    """惰性 import + 异常吞掉,避免 fetcher 模块某依赖异常拖垮整个路由。"""
    try:
        from fetcher import fetch_limit_up
        return fetch_limit_up(date_yyyymmdd)
    except Exception as e:
        log.warning("[tradecheck] fetch_limit_up(%s) 失败: %s", date_yyyymmdd, e)
        return None


def _safe_fetch_daily_detail(date_yyyymmdd: str) -> dict:
    try:
        from history_store import fetch_daily_detail
        return fetch_daily_detail(date_yyyymmdd) or {}
    except Exception as e:
        log.warning("[tradecheck] fetch_daily_detail(%s) 失败: %s", date_yyyymmdd, e)
        return {}


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


@tradecheck_router.get("/health")
def tc_health():
    """前端探测 TradeCheck 子系统是否就绪"""
    return {"ok": True, "feature": "tradecheck", "version": "0.1.0"}


@tradecheck_router.post("/resolve_codes")
def resolve_codes(payload: dict):
    """单纯做代码反查,便于前端调试"""
    items = payload.get("items", [])
    out = []
    for it in items:
        std = tc_code_resolver.resolve(symbol=it.get("symbol"), name=it.get("name"))
        out.append({"input": it, "code": std})
    return {"items": out}


@tradecheck_router.post("/build_market_csv")
def build_market_csv(req: BuildMarketReq):
    if len(req.names) != len(req.raw_codes):
        raise HTTPException(400, "names 与 raw_codes 长度不一致")
    if not req.names:
        return {"csv": "", "n_rows": 0, "unresolved": []}

    try:
        start_dt = _parse_ymd(req.start_date)
        end_dt = _parse_ymd(req.end_date)
    except ValueError:
        raise HTTPException(400, "日期格式必须为 YYYY-MM-DD")
    if end_dt < start_dt:
        raise HTTPException(400, "end_date 早于 start_date")

    # 1. 解析每个标的的标准代码
    mapping: dict[str, str] = {}  # raw_code → standard
    name_map: dict[str, str] = {}  # raw_code → 中文名(用于报表)
    unresolved: list[dict] = []
    seen: set[str] = set()
    for raw, name in zip(req.raw_codes, req.names):
        key = (raw or "") + "|" + (name or "")
        if key in seen:
            continue
        seen.add(key)
        std = tc_code_resolver.resolve(symbol=raw, name=name)
        if std:
            mapping[raw] = std
            name_map[raw] = name
        else:
            unresolved.append({"raw": raw, "name": name})

    # 2. 拉每只票 K 线
    market: dict[tuple[str, str], dict] = {}
    for raw, std in mapping.items():
        klines = tc_kline_fetcher.fetch_one(std, req.start_date, req.end_date)
        for k in klines:
            market[(raw, k["date"])] = {
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "limit_price": k["limit_price"],
                "prev_close": k["prev_close"],
                "board": 0,
                "is_limit": False,
                "senti": None,
            }

    # 3. 用涨停股池覆盖连板数 + 情绪分
    cur_dt = start_dt
    while cur_dt <= end_dt:
        if cur_dt.weekday() < 5:  # 跳过周末
            d8 = cur_dt.strftime("%Y%m%d")
            d_iso = cur_dt.strftime("%Y-%m-%d")

            df = _safe_fetch_limit_up(d8)
            if df is not None and not df.empty:
                code_to_board = {}
                for _, row in df.iterrows():
                    code_std = str(row.get("代码", "")).zfill(6)
                    if not code_std:
                        continue
                    code_to_board[code_std] = int(row.get("连板数", 1) or 1)
                for raw, std in mapping.items():
                    if std in code_to_board:
                        key = (raw, d_iso)
                        if key in market:
                            market[key]["board"] = code_to_board[std]
                            market[key]["is_limit"] = True

            detail = _safe_fetch_daily_detail(d8)
            senti = detail.get("sentiment_score") or detail.get("score")
            if senti is not None:
                try:
                    senti_int = int(senti)
                except (TypeError, ValueError):
                    senti_int = None
                if senti_int is not None:
                    for raw in mapping:
                        key = (raw, d_iso)
                        if key in market:
                            market[key]["senti"] = senti_int
        cur_dt += timedelta(days=1)

    # 4. 输出符合 engine.js parseMarket 期望的 CSV
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["代码", "日期", "开盘", "最高", "最低", "收盘",
                "涨停价", "连板数", "市场情绪", "是否涨停"])
    for code, date in sorted(market.keys()):
        m = market[(code, date)]
        w.writerow([
            code, date, m["open"], m["high"], m["low"], m["close"],
            m["limit_price"], m["board"],
            m["senti"] if m["senti"] is not None else "",
            "是" if m["is_limit"] else "否",
        ])

    return {
        "csv": buf.getvalue(),
        "n_rows": len(market),
        "n_resolved": len(mapping),
        "unresolved": unresolved,
    }
