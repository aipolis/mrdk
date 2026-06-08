# -*- coding: utf-8 -*-
"""订阅消息：按当日情绪动态生成内容并发送"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from config import bj_now

import httpx

from wechat_http import wechat_http_client

from config import (
    SUBSCRIBE_FIELD_KEYS,
    SUBSCRIBE_PAGE,
    SUBSCRIBE_TEMPLATES,
    WX_APPID,
    WX_SECRET,
)

log = logging.getLogger("mingri.subscribe")

SUBSCRIBERS_FILE = Path(__file__).resolve().parent / "data" / "subscribers.json"
_token_cache: dict = {"token": "", "expires": 0}

# thing5 温馨提示最多 20 字
_TIPS_MAX = 20


def _clip_tips(text: str) -> str:
    s = (text or "").strip()
    return s if len(s) <= _TIPS_MAX else s[:_TIPS_MAX - 1] + "…"


def _weather_label(score: int, empty: bool) -> tuple[str, str]:
    """返回 (天气词, 温馨提示)"""
    if empty or score < 30:
        return "雨天", "雨天宜休息，等晴天再出门"
    if score > 70:
        return "晴天", "天气不错，可积极行动"
    if score >= 50:
        return "多云", "多云天气，带好伞再出门"
    return "阴天", "天气一般，谨慎出行"


def _fmt_advice_date(advice_date: str) -> str:
    """YYYY-MM-DD → YYYY年M月D日"""
    try:
        parts = advice_date.split("-")
        if len(parts) == 3:
            return f"{parts[0]}年{int(parts[1])}月{int(parts[2])}日"
    except Exception:
        pass
    return advice_date


def build_subscribe_message(
    sentiment: dict,
    *,
    ref_date: str,
    advice_date: str,
    push_kind: str = "sentiment_daily",
) -> dict:
    score = int(sentiment.get("displayScore") or sentiment.get("score") or 0)
    empty = bool(sentiment.get("emptyWarning"))
    weather, tip = _weather_label(score, empty)

    date_val = _fmt_advice_date(advice_date)
    tips = _clip_tips(tip)

    fk = SUBSCRIBE_FIELD_KEYS
    wx_data = {
        fk["date"]:    {"value": date_val},
        fk["weather"]: {"value": weather},
        fk["score"]:   {"value": str(score)},
        fk["tips"]:    {"value": tips},
    }

    return {
        "date": date_val,
        "weather": weather,
        "keyData": f"舒适度{score}",
        "tips": tips,
        "wxData": wx_data,
        "score": score,
        "level": weather,
        "emptyWarning": empty,
    }


def _load_subscribers_json() -> dict:
    if not SUBSCRIBERS_FILE.exists():
        return {"users": []}
    try:
        return json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"users": []}


def _save_subscribers_json(data: dict) -> None:
    SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIBERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _subscribe_type(only_empty: bool) -> str:
    return "empty_alert" if only_empty else "sentiment_daily"


def _load_push_openids(*, only_empty: bool) -> tuple[list[str], str]:
    """
    推送名单：优先 MySQL（持久），JSON 文件兜底。
    返回 (openid 列表, 来源 mysql|json|merged)
    """
    sub_type = _subscribe_type(only_empty)
    mysql_ids: list[str] = []
    try:
        from user_store import list_push_subscribers

        mysql_ids = list_push_subscribers(sub_type)
    except Exception:
        log.exception("load push openids from mysql failed")

    json_ids: list[str] = []
    for u in _load_subscribers_json().get("users", []):
        openid = u.get("openid")
        types = u.get("types") or []
        if not openid:
            continue
        if sub_type in types:
            json_ids.append(openid)

    if mysql_ids and json_ids:
        merged = list(dict.fromkeys(mysql_ids + json_ids))
        return merged, "merged"
    if mysql_ids:
        return mysql_ids, "mysql"
    if json_ids:
        return json_ids, "json"
    return [], "none"


def _purge_expired_subscribers(expired_openids: set[str], subscribe_type: str) -> None:
    if not expired_openids:
        return
    data = _load_subscribers_json()
    users = data.get("users", [])
    for u in users:
        if u.get("openid") in expired_openids:
            u["types"] = [t for t in (u.get("types") or []) if t != subscribe_type]
    data["users"] = [u for u in users if u.get("types")]
    _save_subscribers_json(data)
    try:
        from user_store import unregister_user_push

        for openid in expired_openids:
            unregister_user_push(openid, subscribe_type)
    except Exception:
        log.exception("purge expired subscribers in mysql failed")
    log.info("removed %d expired subscribers type=%s", len(expired_openids), subscribe_type)


def register_subscriber(openid: str, subscribe_type: str = "sentiment_daily") -> None:
    if not openid:
        return
    try:
        from user_store import register_user_push

        register_user_push(openid, subscribe_type)
    except Exception:
        log.exception("register user push in mysql failed")
    data = _load_subscribers_json()
    users = data.get("users", [])
    found = next((u for u in users if u.get("openid") == openid), None)
    now = bj_now().isoformat()
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
    _save_subscribers_json(data)


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
    async with wechat_http_client(15) as client:
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
    async with wechat_http_client(15) as client:
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
    page: Optional[str] = None,
) -> dict:
    tmpl = template_id or SUBSCRIBE_TEMPLATES.get("sentiment_daily")
    if not tmpl:
        raise RuntimeError("未配置订阅消息模板 ID")

    token = await get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={token}"
    payload = {
        "touser": openid,
        "template_id": tmpl,
        "page": page or SUBSCRIBE_PAGE,
        "data": wx_data,
        "miniprogram_state": "formal",
    }
    async with wechat_http_client(15) as client:
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
    sub_type = _subscribe_type(only_empty)
    openids, source = _load_push_openids(only_empty=only_empty)
    results = {
        "ok": 0,
        "fail": 0,
        "skipped": 0,
        "total": len(openids),
        "source": source,
        "details": [],
    }

    expired_openids: set[str] = set()
    for openid in openids:
        if not openid:
            continue
        try:
            res = await send_subscribe_message(openid, msg["wxData"])
            errcode = res.get("errcode")
            if errcode == 0:
                results["ok"] += 1
            elif errcode == 43101:
                expired_openids.add(openid)
                results["skipped"] += 1
            else:
                results["fail"] += 1
                results["details"].append({"openid": openid[:8] + "…", "err": res})
        except Exception as e:
            results["fail"] += 1
            results["details"].append({"openid": openid[:8] + "…", "err": str(e)})

    _purge_expired_subscribers(expired_openids, sub_type)

    results["preview"] = {
        "date": msg["date"],
        "weather": msg["weather"],
        "keyData": msg["keyData"],
        "tips": msg["tips"],
    }
    return results
