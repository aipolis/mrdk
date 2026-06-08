# -*- coding: utf-8 -*-
"""小程序码生成（分享海报用）"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from wechat_http import wechat_post

from config import WX_APPID
from subscribe_msg import get_access_token

log = logging.getLogger("mingri.wxacode")

_CACHE_PATH = Path(__file__).resolve().parent / "data" / "wxacode_share.png"
_CACHE_TTL = 86400 * 7


def _read_cache() -> bytes | None:
    if not _CACHE_PATH.is_file():
        return None
    if time.time() - _CACHE_PATH.stat().st_mtime > _CACHE_TTL:
        return None
    try:
        return _CACHE_PATH.read_bytes()
    except Exception:
        return None


def _write_cache(data: bytes) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_bytes(data)
    except Exception:
        log.exception("write wxacode cache failed")


async def get_share_wxacode_bytes() -> bytes:
    cached = _read_cache()
    if cached:
        return cached

    token = await get_access_token()
    url = f"https://api.weixin.qq.com/wxa/getwxacodeunlimit?access_token={token}"
    payload = {
        "page": "pages/index/index",
        "scene": "share",
        "width": 430,
        "check_path": False,
        "env_version": "release",
    }
    r = await wechat_post(url, json_body=payload, timeout=20)
    body = r.content
    ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code != 200 or "json" in ctype:
        try:
            err = r.json()
        except Exception:
            err = {"errmsg": r.text[:200]}
        raise RuntimeError(err.get("errmsg") or "生成小程序码失败")
    if not body or len(body) < 128:
        raise RuntimeError("小程序码数据无效")
    _write_cache(body)
    log.info("wxacode share generated appid=%s bytes=%s", WX_APPID, len(body))
    return body
