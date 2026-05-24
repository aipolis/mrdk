# -*- coding: utf-8 -*-
"""订阅消息：按当日情绪动态生成内容并发送"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from config import (
    SUBSCRIBE_FIELD_KEYS,
    SUBSCRIBE_TEMPLATES,
    WX_APPID,
    WX_SECRET,
)
from fetcher import display_level_label

log = logging.getLogger("mingri.subscribe")

SUBSCRIBERS_FILE = Path(__file__).resolve().parent / "data" / "subscribers.json"
_token_cache: dict = {"token": "", "expires": 0}

# 微信模板字段长度限制（thing 约 20 字）
_MAX = {"thing7": 20, "character_string2": 32, "thing12": 20}


def _clip(text: str, key: str) -> str:
    n = _MAX.get(key, 20)
    s = (text or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _tips_from_sentiment(score: int, empty: bool, reasons: list) -> str:
    if empty and reasons:
        return _clip("；".join(reasons[:2]), "thing12")
    if empty or score <= 14:
        return _clip("昨日情绪极弱，盘面偏冷", "thing12")
    if score >= 61:
        return _clip("昨日情绪偏强，注意分歧", "thing12")
    if score >= 41:
        return _clip("昨日情绪偏暖，结构尚可", "thing12")
    if score >= 21:
        return _clip("昨日情绪偏谨慎", "thing12")
    return _clip("昨日情绪偏弱", "thing12")


def build_subscribe_message(
    sentiment: dict,
    *,
    ref_date: str,
    advice_date: str,
    push_kind: str = "sentiment_daily",
) -> dict:
    """根据情绪结果生成订阅消息 data（非写死）"""
    score = int(sentiment.get("displayScore") or sentiment.get("score") or 0)
    ui_level = display_level_label(score)
    empty = bool(sentiment.get("emptyWarning"))
    reasons = sentiment.get("emptyReasons") or []

    if push_kind == "empty_alert" and empty:
        strategy = _clip("龙空龙·个人信号", "thing7")
    elif empty:
        strategy = _clip("龙空龙·个人信号", "thing7")
    else:
        strategy = _clip(f"市场情绪·{ui_level}", "thing7")

    key_data = _clip(f"情绪{score}分·{ui_level}", "character_string2")
    tips = _tips_from_sentiment(score, empty, reasons)

    time_val = f"{advice_date} 09:15"

    fk = SUBSCRIBE_FIELD_KEYS
    wx_data = {
        fk["strategy"]: {"value": strategy},
        fk["key_data"]: {"value": key_data},
        fk["time"]: {"value": time_val},
        fk["tips"]: {"value": tips},
    }

    return {
        "strategy": strategy,
        "keyData": key_data,
        "time": time_val,
        "tips": tips,
        "wxData": wx_data,
        "score": score,
        "level": ui_level,
        "positionPercent": int(sentiment.get("positionPercent", 0)),
        "emptyWarning": empty,
    }


def _load_subscribers() -> dict:
    if not SUBSCRIBERS_FILE.exists():
        return {"users": []}
    try:
        return json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"users": []}


def _save_subscribers(data: dict) -> None:
    SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIBERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_subscriber(openid: str, subscribe_type: str = "sentiment_daily") -> None:
    if not openid:
        return
    try:
        from user_store import register_user_push

        register_user_push(openid, subscribe_type)
    except Exception:
        log.exception("register user push in mysql failed")
    data = _load_subscribers()
    users = data.get("users", [])
    found = next((u for u in users if u.get("openid") == openid), None)
    now = datetime.now().isoformat()
    if found:
        types = set(found.get("types", []))
        types.add(subscribe_type)
        found["types"] = list(types)
        found["updatedAt"] = now
    else:
        users.append({
            "openid": openid,
            "types": [subscribe_type],
            "createdAt": now,
            "updatedAt": now,
        })
    data["users"] = users
    _save_subscribers(data)


async def get_access_token() -> str:
    if not WX_APPID or not WX_SECRET:
        raise RuntimeError("未配置 WX_APPID / WX_SECRET，无法发送订阅消息")
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now + 60:
        return _token_cache["token"]

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": WX_APPID,
        "secret": WX_SECRET,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        body = r.json()
    if body.get("errcode"):
        raise RuntimeError(body.get("errmsg", "获取 access_token 失败"))
    _token_cache["token"] = body["access_token"]
    _token_cache["expires"] = now + int(body.get("expires_in", 7200))
    return _token_cache["token"]


async def code_to_session(js_code: str) -> dict:
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": WX_APPID,
        "secret": WX_SECRET,
        "js_code": js_code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        body = r.json()
    if body.get("errcode"):
        raise RuntimeError(body.get("errmsg", "code2session 失败"))
    return {
        "openid": body.get("openid", ""),
        "unionid": body.get("unionid") or None,
        "session_key": body.get("session_key"),
    }


async def code_to_openid(js_code: str) -> str:
    session = await code_to_session(js_code)
    return session.get("openid", "")


async def send_subscribe_message(
    openid: str,
    wx_data: dict,
    *,
    template_id: Optional[str] = None,
    page: str = "pages/index/index",
) -> dict:
    tmpl = template_id or SUBSCRIBE_TEMPLATES.get("sentiment_daily")
    if not tmpl:
        raise RuntimeError("未配置订阅消息模板 ID")

    token = await get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={token}"
    payload = {
        "touser": openid,
        "template_id": tmpl,
        "page": page,
        "data": wx_data,
        "miniprogram_state": "formal",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload)
        body = r.json()
    return body


async def broadcast_daily_sentiment(
    sentiment: dict,
    ref_date: str,
    advice_date: str,
    *,
    only_empty: bool = False,
) -> dict:
    """向已注册用户推送（内容按情绪动态生成）"""
    msg = build_subscribe_message(
        sentiment,
        ref_date=ref_date,
        advice_date=advice_date,
        push_kind="empty_alert" if only_empty else "sentiment_daily",
    )
    data = _load_subscribers()
    users = data.get("users", [])
    results = {"ok": 0, "fail": 0, "skipped": 0, "details": []}

    for u in users:
        openid = u.get("openid")
        types = u.get("types", [])
        if not openid:
            continue
        if only_empty and "empty_alert" not in types:
            results["skipped"] += 1
            continue
        if not only_empty and "sentiment_daily" not in types:
            results["skipped"] += 1
            continue
        try:
            res = await send_subscribe_message(openid, msg["wxData"])
            if res.get("errcode") == 0:
                results["ok"] += 1
            else:
                results["fail"] += 1
                results["details"].append({"openid": openid[:8] + "…", "err": res})
        except Exception as e:
            results["fail"] += 1
            results["details"].append({"openid": openid[:8] + "…", "err": str(e)})

    results["preview"] = {
        "strategy": msg["strategy"],
        "keyData": msg["keyData"],
        "time": msg["time"],
        "tips": msg["tips"],
    }
    return results
