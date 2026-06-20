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
import tc_image_ocr
import tc_llm

log = logging.getLogger(__name__)

tradecheck_router = APIRouter(prefix="/api/tradecheck", tags=["tradecheck"])


class BuildMarketReq(BaseModel):
    names: list[str]       # 与 raw_codes 一一对应的中文名
    raw_codes: list[str]   # 交割单里原始代码(拼音简称或 6 位数字)
    start_date: str        # YYYY-MM-DD
    end_date: str          # YYYY-MM-DD


class ExtractCsvReq(BaseModel):
    images: list[str]      # data:image/...;base64,xxx 数组(一张拍不全可多张)
    broker: str = ""       # 可选,如 "同花顺"、"东财"、"通达信",用于辅助 prompt


class OcrReq(BaseModel):
    images: list[str]      # 单次最多 4 张,前端分批调用以绕开网关超时
    start_index: int = 1   # 全局图片序号(1-based),用于 ---- 图片 N ---- 分隔符
    broker: str = ""       # 预留,当前 OCR 阶段不使用


class ParseCsvReq(BaseModel):
    lines: list[str]       # 所有批次 OCR 行片段汇总(含 ---- 图片 N ---- 分隔符)
    broker: str = ""


_OCR_MAX_IMAGES = 4


_EXTRACT_CSV_SYS = (
    "你是 A 股券商交割单截图解析助手。用户上传了 OCR 提取出的成交记录文字片段"
    "(原表格被 OCR 按 Y 坐标拆碎,可能一行被拆成 2~3 个 OCR 片段;若有多张图,"
    "用 ---- 图片 N ---- 分隔)。\n"
    "请把它们重组成标准 CSV,严格按以下表头与规则输出:\n"
    "\n"
    "成交日期,证券代码,证券名称,操作,成交价格,成交数量,成交金额,佣金,印花税,过户费\n"
    "\n"
    "规则:\n"
    "1) 操作:只填\"买入\"或\"卖出\";数量一律取正数(原始可能带负号)。\n"
    "2) 成交日期格式 YYYY-MM-DD HH:MM:SS;若 OCR 缺秒则填 :00;若两位年缺前缀 20 自行补。\n"
    "3) 证券代码:若原文没有标准 6 位代码,用证券名称的拼音首字母大写填(例如\"高乐股份\"→\"GLGF\");\n"
    "4) 价格、金额:保留原始小数,不带千分位,不要带其他符号;\n"
    "5) 佣金/印花税/过户费:OCR 中没有就一律填 0;\n"
    "6) **跳过非成交行**:申购配号、菜单(首页/行情/自选/交易/资讯)、表头、状态栏、"
    "页面标题、筛选条件(默认/按股票/按做 T)、日期范围等都不要输出;\n"
    "7) 一行对应一笔交易,**不要拼接或合并多笔**;\n"
    "8) 顺序按\"成交日期 升序\";\n"
    "9) **只输出 CSV 文本本身**,首行表头,不要任何解释、不要 markdown 包裹。"
)


def _build_extract_user_prompt(lines: list[str], broker: str) -> str:
    head = "以下是 OCR 行片段(按 Y 上→下、X 左→右排序):\n\n"
    if broker:
        head = f"券商/APP:{broker}\n" + head
    body = "\n".join(lines)
    return head + body


def _parse_lines_to_csv(lines: list[str], broker: str = "") -> dict:
    """OCR 行片段 → LLM → 标准交割单 CSV(供 parse_csv 与 extract_csv 复用)。"""
    if not lines:
        raise HTTPException(422, "OCR 行片段为空,无法解析")
    if not tc_llm.available()["ok"]:
        raise HTTPException(503, "LLM 未配置:管理员需在环境变量加 DEEPSEEK_API_KEY 或 ZHIPU_API_KEY")

    try:
        user = _build_extract_user_prompt(lines, broker or "")
        csv_text = tc_llm.chat(
            [{"role": "user", "content": user}],
            system=_EXTRACT_CSV_SYS,
            max_tokens=8192,
            temperature=0.0,
        )
    except Exception as e:
        log.exception("[tradecheck] parse_csv LLM 调用失败")
        raise HTTPException(500, f"LLM 调用失败: {e}")

    csv_text = (csv_text or "").strip()
    first_line = csv_text.split("\n", 1)[0] if csv_text else ""
    if "成交日期" not in first_line:
        log.warning("[tradecheck] LLM 输出可能不规范: %r", csv_text[:200])

    n_rows = max(0, len([l for l in csv_text.splitlines() if l.strip()]) - 1)
    return {
        "csv": csv_text,
        "n_rows": n_rows,
        "ocr_lines": len(lines),
        "llm": tc_llm.available(),
    }


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
    llm = tc_llm.available()
    ocr_ok = tc_image_ocr.ocr_available()
    return {
        "ok": True,
        "feature": "tradecheck",
        "version": "0.3.0",
        "capabilities": {
            "market_csv": True,
            "ocr": ocr_ok,
            "parse_csv": llm["ok"],
            "extract_csv": llm["ok"] and ocr_ok,  # 旧版一体接口,保留兼容
        },
        "llm": llm,
        "ocr_batch_max": _OCR_MAX_IMAGES,
    }


@tradecheck_router.post("/ocr")
def ocr_images(req: OcrReq):
    """轻量 OCR:单次最多 4 张图,仅返回行文本(不含 LLM)。前端分批调用后汇总 lines。"""
    if not req.images:
        raise HTTPException(400, "未收到图片")
    if len(req.images) > _OCR_MAX_IMAGES:
        raise HTTPException(
            400,
            f"单次 OCR 最多 {_OCR_MAX_IMAGES} 张图,请前端分批调用 /ocr",
        )
    if not tc_image_ocr.ocr_available():
        raise HTTPException(503, "RapidOCR 未安装或加载失败")

    start = max(1, req.start_index)
    lines, sizes = tc_image_ocr.extract_multi_images(req.images, start_index=start)
    if not lines:
        raise HTTPException(422, "OCR 未提取到任何文字,可能图片模糊或内容非交割单")

    return {
        "lines": lines,
        "n_images": len(req.images),
        "ocr_lines": len(lines),
        "ocr_per_image": sizes,
        "start_index": start,
    }


@tradecheck_router.post("/parse_csv")
def parse_csv(req: ParseCsvReq):
    """OCR 行片段(可来自多批 /ocr) → 单次 LLM 调用 → 标准交割单 CSV"""
    out = _parse_lines_to_csv(req.lines, req.broker or "")
    return out


@tradecheck_router.post("/extract_csv")
def extract_csv(req: ExtractCsvReq):
    """图片(单张/多张)→ OCR → LLM 解析 → 标准交割单 CSV(旧版一体接口,保留兼容)"""
    if not req.images:
        raise HTTPException(400, "未收到图片")
    if not tc_image_ocr.ocr_available():
        raise HTTPException(503, "RapidOCR 未安装或加载失败")

    lines, sizes = tc_image_ocr.extract_multi_images(req.images)
    if not lines:
        raise HTTPException(422, "OCR 未提取到任何文字,可能图片模糊或 RapidOCR 未安装")

    out = _parse_lines_to_csv(lines, req.broker or "")
    out["n_images"] = len(req.images)
    out["ocr_per_image"] = sizes
    return out


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


# ---------- 用户聚合数据 + 反馈(opt-in) ----------

try:
    import tc_analytics_store
except Exception as _e:  # noqa
    tc_analytics_store = None  # type: ignore


@tradecheck_router.post("/log_metrics")
def log_metrics(payload: dict):
    """前端在用户勾选「允许匿名分享聚合统计」时上报报告指标。
    口径:不存股票代码/日期/精确金额,只存比率与万元分桶。"""
    if not tc_analytics_store:
        return {"ok": False, "reason": "analytics_unavailable"}
    ok = tc_analytics_store.save_metrics(payload or {})
    return {"ok": bool(ok)}


@tradecheck_router.post("/feedback")
def submit_feedback(payload: dict):
    """前端反馈卡片:1-5 星评分 + 可选文字。"""
    if not tc_analytics_store:
        return {"ok": False, "reason": "analytics_unavailable"}
    ok = tc_analytics_store.save_feedback(payload or {})
    return {"ok": bool(ok)}
