# -*- coding: utf-8 -*-
"""小程序用户账号（openid 体系）"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from config import bj_now
from db_store import MYSQL_CHARSET, MYSQL_COLLATE, ensure_schema, mysql_enabled, with_retry

log = logging.getLogger("mingri.user")

TABLE_USERS = "mini_users"
_users_ready = False


def mask_openid(openid: str) -> str:
    s = (openid or "").strip()
    if len(s) <= 8:
        return s[:2] + "…" if s else ""
    return f"{s[:4]}…{s[-4:]}"


def _safe_avatar(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("https://") or u.startswith("http://"):
        return u[:512]
    return ""


def ensure_users_table() -> bool:
    global _users_ready
    if _users_ready:
        return True
    if not mysql_enabled() or not ensure_schema():
        return False

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_USERS}` (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    openid VARCHAR(64) NOT NULL,
                    unionid VARCHAR(64) NULL,
                    nick_name VARCHAR(64) NOT NULL DEFAULT '',
                    avatar_url VARCHAR(512) NOT NULL DEFAULT '',
                    ui_theme VARCHAR(16) NULL,
                    push_sentiment TINYINT NOT NULL DEFAULT 0,
                    push_empty TINYINT NOT NULL DEFAULT 0,
                    last_login_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_openid (openid),
                    KEY idx_unionid (unionid),
                    KEY idx_last_login (last_login_at)
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
        conn.commit()

    try:
        with_retry(_run)
        _users_ready = True
        log.info("users table ready table=%s", TABLE_USERS)
        return True
    except Exception:
        log.exception("users table init failed")
        return False


def _row_to_public(row: dict, *, is_new: bool = False) -> dict[str, Any]:
    return {
        "userId": int(row["id"]),
        "openidHint": mask_openid(row.get("openid") or ""),
        "nickName": row.get("nick_name") or "",
        "avatarUrl": row.get("avatar_url") or "",
        "uiTheme": row.get("ui_theme") or "",
        "pushSentiment": bool(row.get("push_sentiment")),
        "pushEmpty": bool(row.get("push_empty")),
        "lastLoginAt": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
        "isNew": is_new,
    }


def upsert_user_login(
    openid: str,
    *,
    unionid: Optional[str] = None,
    nick_name: str = "",
    avatar_url: str = "",
    ui_theme: Optional[str] = None,
    push_sentiment: Optional[bool] = None,
    push_empty: Optional[bool] = None,
) -> Optional[dict[str, Any]]:
    if not openid or not ensure_users_table():
        return None

    nick = (nick_name or "").strip()[:64]
    avatar = _safe_avatar(avatar_url)
    now = bj_now()
    theme = (ui_theme or "").strip()[:16] or None
    ps = int(bool(push_sentiment)) if push_sentiment is not None else None
    pe = int(bool(push_empty)) if push_empty is not None else None

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, openid, nick_name, avatar_url FROM `{TABLE_USERS}` WHERE openid=%s LIMIT 1",
                (openid,),
            )
            existing = cur.fetchone()
            is_new = not existing

            if existing:
                sets = ["last_login_at=%s"]
                params: list[Any] = [now]
                if nick:
                    sets.append("nick_name=%s")
                    params.append(nick)
                if avatar:
                    sets.append("avatar_url=%s")
                    params.append(avatar)
                if unionid:
                    sets.append("unionid=%s")
                    params.append(unionid)
                if theme is not None:
                    sets.append("ui_theme=%s")
                    params.append(theme)
                if ps is not None:
                    sets.append("push_sentiment=%s")
                    params.append(ps)
                if pe is not None:
                    sets.append("push_empty=%s")
                    params.append(pe)
                params.append(openid)
                cur.execute(
                    f"UPDATE `{TABLE_USERS}` SET {', '.join(sets)} WHERE openid=%s",
                    params,
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO `{TABLE_USERS}` (
                        openid, unionid, nick_name, avatar_url, ui_theme,
                        push_sentiment, push_empty, last_login_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        openid,
                        unionid or None,
                        nick or "微信用户",
                        avatar,
                        theme,
                        ps if ps is not None else 0,
                        pe if pe is not None else 0,
                        now,
                    ),
                )

            cur.execute(
                f"""
                SELECT id, openid, unionid, nick_name, avatar_url, ui_theme,
                       push_sentiment, push_empty, last_login_at
                FROM `{TABLE_USERS}` WHERE openid=%s LIMIT 1
                """,
                (openid,),
            )
            row = cur.fetchone()
        conn.commit()
        return row, is_new

    try:
        row, is_new = with_retry(_run)
        if not row:
            return None
        return _row_to_public(row, is_new=is_new)
    except Exception:
        log.exception("upsert user login failed openid=%s", mask_openid(openid))
        return None


def register_user_push(openid: str, subscribe_type: str) -> None:
    if not openid or not ensure_users_table():
        return
    col = "push_sentiment" if subscribe_type == "sentiment_daily" else "push_empty"
    if col not in ("push_sentiment", "push_empty"):
        return

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_USERS}` (openid, nick_name, {col}, last_login_at)
                VALUES (%s, %s, 1, %s)
                ON DUPLICATE KEY UPDATE {col}=1, last_login_at=VALUES(last_login_at)
                """,
                (openid, "微信用户", bj_now()),
            )
        conn.commit()

    try:
        with_retry(_run)
    except Exception:
        log.exception("register user push failed openid=%s type=%s", mask_openid(openid), subscribe_type)


def users_status() -> dict:
    if not mysql_enabled():
        return {"enabled": False, "ready": False}
    ready = ensure_users_table()
    if not ready:
        return {"enabled": True, "ready": False}

    def _count(conn):
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM `{TABLE_USERS}`")
            return int((cur.fetchone() or {}).get("c") or 0)

    try:
        total = with_retry(_count)
        return {"enabled": True, "ready": True, "table": TABLE_USERS, "userCount": total}
    except Exception:
        log.exception("users status failed")
        return {"enabled": True, "ready": False}
