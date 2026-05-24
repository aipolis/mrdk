# -*- coding: utf-8 -*-
"""持仓截图 OCR 识别"""
from __future__ import annotations

import io
import re
from typing import Optional

POSITION_KEYWORDS = ["总仓位", "股票仓位", "持仓比例", "仓位", "可用", "总资产", "市值"]

PERCENT_PATTERNS = [
    re.compile(r"(?:总仓位|股票仓位|持仓|仓位)[^\d]{0,8}(\d{1,3}(?:\.\d+)?)\s*%", re.I),
    re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:仓|持仓|股票)", re.I),
    re.compile(r"仓位\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%"),
]


def _extract_percents(text: str) -> list[float]:
    found = []
    for pat in PERCENT_PATTERNS:
        for m in pat.finditer(text):
            v = float(m.group(1))
            if 0 <= v <= 100:
                found.append(v)
    generic = re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    for g in generic:
        v = float(g)
        if 0 <= v <= 100:
            found.append(v)
    return found


def ocr_image(image_bytes: bytes) -> dict:
    text = ""
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, _ = engine(image_bytes)
        if result:
            text = "\n".join([line[1] for line in result if len(line) > 1])
    except Exception as e:
        return {
            "success": False,
            "message": f"OCR引擎不可用: {e}",
            "total": None, "stock": None, "cash": None, "rawText": "",
        }

    percents = _extract_percents(text)
    total = stock = cash = None

    for kw in ["总仓位", "股票仓位", "仓位"]:
        m = re.search(rf"{kw}[^\d]{{0,6}}(\d{{1,3}}(?:\.\d+)?)\s*%", text)
        if m:
            val = float(m.group(1))
            if kw == "总仓位":
                total = val
            else:
                stock = val

    if total is None and percents:
        total = percents[0]
    if stock is None and total is not None:
        stock = total
    if total is not None:
        cash = round(max(0, 100 - total), 1)

    return {
        "success": total is not None,
        "message": "识别成功" if total is not None else "未能识别仓位，请手动输入",
        "total": total,
        "stock": stock,
        "cash": cash,
        "rawText": text[:500],
    }
