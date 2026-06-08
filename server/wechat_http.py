# -*- coding: utf-8 -*-
"""调用微信开放接口的 HTTP 客户端（解决云托管 SSL/CA 问题）"""
from __future__ import annotations

import os

import httpx

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore


def wechat_http_verify():
    """默认用 certifi CA 包；环境变量 WECHAT_HTTP_VERIFY=false 可关闭校验（仅排查用）"""
    flag = os.getenv("WECHAT_HTTP_VERIFY", "true").lower()
    if flag in ("0", "false", "no"):
        return False
    if certifi is not None:
        return certifi.where()
    return True


def wechat_http_client(timeout: float = 15) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, verify=wechat_http_verify())
