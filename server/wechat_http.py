# -*- coding: utf-8 -*-
"""调用微信开放接口（api.weixin.qq.com）；云托管容器 CA 不全时自动跳过 SSL 校验"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore

log = logging.getLogger("mingri.wechat_http")


def _is_ssl_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "certificate" in msg or "ssl" in msg:
        return True
    cause = getattr(exc, "__cause__", None)
    return bool(cause and _is_ssl_error(cause))


def _verify_candidates() -> list[Any]:
    """
    校验策略：
    - WECHAT_HTTP_VERIFY=true  → 仅 certifi/系统 CA
    - WECHAT_HTTP_VERIFY=false → 不校验（云托管推荐）
    - 默认 auto：先 certifi，SSL 失败再降级不校验
    """
    flag = os.getenv("WECHAT_HTTP_VERIFY", "auto").lower()
    if flag in ("0", "false", "no"):
        return [False]
    if flag in ("1", "true", "yes"):
        return [certifi.where() if certifi else True]
    strict = certifi.where() if certifi else True
    return [strict, False]


async def _request(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: float = 15,
) -> httpx.Response:
    last_exc: Optional[BaseException] = None
    for verify in _verify_candidates():
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
                if method == "GET":
                    return await client.get(url, params=params or {})
                return await client.post(url, json=json_body or {})
        except Exception as exc:
            last_exc = exc
            if verify is not False and _is_ssl_error(exc):
                log.warning("wechat http ssl error verify=%s, will retry: %s", verify, exc)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("wechat http request failed")


async def wechat_get(url: str, *, params: Optional[dict] = None, timeout: float = 15) -> dict:
    r = await _request("GET", url, params=params, timeout=timeout)
    return r.json()


async def wechat_post(url: str, *, json_body: Optional[dict] = None, timeout: float = 15) -> httpx.Response:
    return await _request("POST", url, json_body=json_body, timeout=timeout)
