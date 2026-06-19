# -*- coding: utf-8 -*-
"""TradeCheck 通用图像 OCR + 行重组

封装 RapidOCR(开箱本地推理,无 API 成本),输出按 Y 坐标聚合后的"行文本"列表,
供下游 LLM 解析成结构化 CSV。
"""
from __future__ import annotations

import base64
import io
import logging
from functools import lru_cache
from typing import Optional

log = logging.getLogger(__name__)

_engine_loaded = False
_engine = None


def _get_engine():
    """惰性加载 RapidOCR,避免冷启动时 onnxruntime 一并拖慢启动。"""
    global _engine_loaded, _engine
    if _engine_loaded:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    except Exception as e:
        log.warning("[tc_image_ocr] RapidOCR 不可用: %s", e)
        _engine = None
    _engine_loaded = True
    return _engine


def extract_text_lines(image_bytes: bytes,
                       row_gap_px: int = 25) -> list[str]:
    """从单张图片提取 OCR 行文本(按 Y 坐标聚合,同 Y 内按 X 排序)。

    返回类似:
      [
        "高乐股份 | 11.320 | -1200 | 卖出",
        "卖2026061814:06:28 | 13584.000",
        ...
      ]
    用 " | " 分隔同一行内不同 OCR 片段,方便 LLM 理解列关系。
    """
    engine = _get_engine()
    if engine is None:
        return []
    try:
        result, _ = engine(image_bytes)
    except Exception as e:
        log.warning("[tc_image_ocr] OCR 执行失败: %s", e)
        return []
    if not result:
        return []

    items: list[tuple[float, float, str]] = []
    for entry in result:
        if not entry or len(entry) < 2:
            continue
        box, text = entry[0], entry[1]
        if not text or not box:
            continue
        try:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            items.append((min(ys), min(xs), str(text).strip()))
        except Exception:
            continue

    items.sort(key=lambda t: (t[0], t[1]))

    grouped: list[list[tuple[float, str]]] = []
    cur: list[tuple[float, str]] = []
    last_y: Optional[float] = None
    for y, x, t in items:
        if last_y is None or abs(y - last_y) < row_gap_px:
            cur.append((x, t))
        else:
            cur.sort()
            grouped.append(cur)
            cur = [(x, t)]
        last_y = y
    if cur:
        cur.sort()
        grouped.append(cur)

    return [" | ".join(t for _, t in row) for row in grouped]


def extract_text_from_data_url(data_url: str) -> list[str]:
    """从 data:image/...;base64,xxx 中解码并 OCR,返回行文本列表。"""
    if not data_url.startswith("data:"):
        return []
    try:
        _, payload = data_url.split(",", 1)
        raw = base64.b64decode(payload)
    except Exception as e:
        log.warning("[tc_image_ocr] data URL 解码失败: %s", e)
        return []
    return extract_text_lines(raw)


def extract_multi_images(data_urls: list[str]) -> tuple[list[str], list[int]]:
    """处理多张图(用户截屏一张拍不全要拼接),返回:
      lines: 所有图的行文本顺序拼接(图与图之间插入分隔符)
      sizes: 每张图的行数,便于排错
    """
    all_lines: list[str] = []
    sizes: list[int] = []
    for i, url in enumerate(data_urls):
        lines = extract_text_from_data_url(url)
        sizes.append(len(lines))
        if not lines:
            continue
        all_lines.append(f"---- 图片 {i + 1} ----")
        all_lines.extend(lines)
    return all_lines, sizes
