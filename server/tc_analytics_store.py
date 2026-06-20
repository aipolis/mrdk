# -*- coding: utf-8 -*-
"""TradeCheck 用户数据上报存储 — 聚合指标 + 反馈。

口径:
- 仅在前端用户勾选「允许匿名分享聚合统计」时才会调用
- 不存储股票代码/日期/精确金额,只存指标和万元分桶
- 用户标识用匿名 UUID(localStorage),换浏览器/清缓存即新身份
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pymysql

from db_store import (
    MYSQL_CHARSET, MYSQL_COLLATE, db_connection, mysql_enabled, with_retry,
)
from config import MYSQL_DATABASE

log = logging.getLogger("mingri.tc_analytics")

TABLE_METRICS = "tc_user_metrics"
TABLE_FEEDBACK = "tc_user_feedback"
_schema_ready = False


def _bucket_pnl_wan(total_pnl: float) -> str:
    """把净盈亏聚合到万元分桶,避免存精确金额。"""
    if total_pnl is None:
        return "unknown"
    w = total_pnl / 10000.0
    if w >= 50: return "+50w_up"
    if w >= 20: return "+20w_to_50w"
    if w >= 10: return "+10w_to_20w"
    if w >= 5: return "+5w_to_10w"
    if w >= 1: return "+1w_to_5w"
    if w >= 0: return "0_to_1w"
    if w >= -1: return "-1w_to_0"
    if w >= -5: return "-5w_to_-1w"
    if w >= -10: return "-10w_to_-5w"
    if w >= -20: return "-20w_to_-10w"
    if w >= -50: return "-50w_to_-20w"
    return "-50w_down"


def ensure_schema() -> bool:
    global _schema_ready
    if _schema_ready or not mysql_enabled():
        return _schema_ready

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_METRICS}` (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    user_uuid VARCHAR(40) NOT NULL,
                    score INT NOT NULL,
                    grade VARCHAR(16) NOT NULL DEFAULT '',
                    style VARCHAR(32) NOT NULL DEFAULT '',
                    n_trades INT NOT NULL DEFAULT 0,
                    n_orders INT NOT NULL DEFAULT 0,
                    win_rate DOUBLE NOT NULL DEFAULT 0,
                    profit_loss_ratio DOUBLE NOT NULL DEFAULT 0,
                    profit_factor DOUBLE NOT NULL DEFAULT 0,
                    avg_hold_win DOUBLE NOT NULL DEFAULT 0,
                    avg_hold_loss DOUBLE NOT NULL DEFAULT 0,
                    de_ratio DOUBLE NOT NULL DEFAULT 0,
                    total_return_pct DOUBLE NOT NULL DEFAULT 0,
                    max_drawdown_pct DOUBLE NOT NULL DEFAULT 0,
                    pnl_bucket VARCHAR(16) NOT NULL DEFAULT '',
                    period_start CHAR(10) NULL,
                    period_end CHAR(10) NULL,
                    has_market TINYINT NOT NULL DEFAULT 0,
                    has_dabp TINYINT NOT NULL DEFAULT 0,
                    upload_source VARCHAR(16) NOT NULL DEFAULT 'csv',
                    ua_hash VARCHAR(32) NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_uuid (user_uuid),
                    KEY idx_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_FEEDBACK}` (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    user_uuid VARCHAR(40) NOT NULL,
                    rating TINYINT NOT NULL DEFAULT 0,
                    comment TEXT NULL,
                    report_score INT NULL,
                    report_style VARCHAR(32) NULL,
                    ua_hash VARCHAR(32) NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_uuid (user_uuid),
                    KEY idx_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
        conn.commit()

    try:
        with db_connection() as conn:
            _run(conn)
        _schema_ready = True
        log.info("tc_analytics schema ready")
        return True
    except Exception:
        log.exception("tc_analytics schema init failed")
        return False


def save_metrics(payload: dict) -> bool:
    if not mysql_enabled() or not ensure_schema():
        return False
    m = payload or {}
    uuid = (m.get("user_uuid") or "").strip()[:40]
    if not uuid:
        return False
    pnl_bucket = _bucket_pnl_wan(m.get("total_pnl"))

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_METRICS}` (
                    user_uuid, score, grade, style, n_trades, n_orders,
                    win_rate, profit_loss_ratio, profit_factor,
                    avg_hold_win, avg_hold_loss, de_ratio,
                    total_return_pct, max_drawdown_pct, pnl_bucket,
                    period_start, period_end, has_market, has_dabp,
                    upload_source, ua_hash
                ) VALUES (
                    %(uuid)s, %(score)s, %(grade)s, %(style)s, %(n_trades)s, %(n_orders)s,
                    %(win_rate)s, %(plr)s, %(pf)s,
                    %(ahw)s, %(ahl)s, %(de)s,
                    %(ret)s, %(dd)s, %(pb)s,
                    %(ps)s, %(pe)s, %(hm)s, %(hd)s,
                    %(src)s, %(uah)s
                )
                """,
                {
                    "uuid": uuid,
                    "score": int(m.get("score") or 0),
                    "grade": (m.get("grade") or "")[:16],
                    "style": (m.get("style") or "")[:32],
                    "n_trades": int(m.get("n_trades") or 0),
                    "n_orders": int(m.get("n_orders") or 0),
                    "win_rate": float(m.get("win_rate") or 0),
                    "plr": float(m.get("profit_loss_ratio") or 0),
                    "pf": float(m.get("profit_factor") or 0),
                    "ahw": float(m.get("avg_hold_win") or 0),
                    "ahl": float(m.get("avg_hold_loss") or 0),
                    "de": float(m.get("de_ratio") or 0),
                    "ret": float(m.get("total_return_pct") or 0),
                    "dd": float(m.get("max_drawdown_pct") or 0),
                    "pb": pnl_bucket,
                    "ps": (m.get("period_start") or "")[:10] or None,
                    "pe": (m.get("period_end") or "")[:10] or None,
                    "hm": 1 if m.get("has_market") else 0,
                    "hd": 1 if m.get("has_dabp") else 0,
                    "src": (m.get("upload_source") or "csv")[:16],
                    "uah": (m.get("ua_hash") or "")[:32],
                },
            )
        conn.commit()
        return True

    try:
        return bool(with_retry(_run))
    except Exception:
        log.exception("tc_analytics save_metrics failed")
        return False


def get_overview() -> dict:
    """整体统计:总报告数/总用户数/近7日新增/反馈数/平均评分"""
    if not mysql_enabled() or not ensure_schema():
        return {}

    def _run(conn):
        out = {}
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n, COUNT(DISTINCT user_uuid) AS u FROM `{TABLE_METRICS}`")
            r = cur.fetchone() or {}
            out["total_reports"] = int(r.get("n") or 0)
            out["total_users"] = int(r.get("u") or 0)
            cur.execute(
                f"SELECT COUNT(*) AS n, COUNT(DISTINCT user_uuid) AS u FROM `{TABLE_METRICS}` "
                f"WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
            )
            r = cur.fetchone() or {}
            out["reports_7d"] = int(r.get("n") or 0)
            out["users_7d"] = int(r.get("u") or 0)
            cur.execute(f"SELECT COUNT(*) AS n, AVG(rating) AS r FROM `{TABLE_FEEDBACK}`")
            r = cur.fetchone() or {}
            out["total_feedback"] = int(r.get("n") or 0)
            out["avg_rating"] = float(r.get("r") or 0)
            cur.execute(
                f"SELECT AVG(score) AS s, AVG(win_rate) AS w, AVG(profit_loss_ratio) AS p "
                f"FROM `{TABLE_METRICS}` WHERE n_trades > 0"
            )
            r = cur.fetchone() or {}
            out["avg_score"] = float(r.get("s") or 0)
            out["avg_win_rate"] = float(r.get("w") or 0)
            out["avg_plr"] = float(r.get("p") or 0)
        return out

    try:
        return with_retry(_run) or {}
    except Exception:
        log.exception("tc_analytics get_overview failed")
        return {}


def get_recent_metrics(limit: int = 50) -> list:
    if not mysql_enabled() or not ensure_schema():
        return []

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, user_uuid, score, grade, style, n_trades, win_rate, "
                f"profit_loss_ratio, total_return_pct, max_drawdown_pct, pnl_bucket, "
                f"period_start, period_end, has_market, has_dabp, upload_source, created_at "
                f"FROM `{TABLE_METRICS}` ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            return list(cur.fetchall() or [])

    try:
        return with_retry(_run) or []
    except Exception:
        log.exception("tc_analytics get_recent_metrics failed")
        return []


def get_recent_feedback(limit: int = 100) -> list:
    if not mysql_enabled() or not ensure_schema():
        return []

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, user_uuid, rating, comment, report_score, report_style, created_at "
                f"FROM `{TABLE_FEEDBACK}` ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            return list(cur.fetchall() or [])

    try:
        return with_retry(_run) or []
    except Exception:
        log.exception("tc_analytics get_recent_feedback failed")
        return []


def get_distributions() -> dict:
    """评分分布 + 风格分布 + 万元盈亏分桶分布"""
    if not mysql_enabled() or not ensure_schema():
        return {}

    def _run(conn):
        out = {}
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT grade, COUNT(*) AS n FROM `{TABLE_METRICS}` "
                f"WHERE n_trades > 0 GROUP BY grade ORDER BY n DESC"
            )
            out["grade"] = list(cur.fetchall() or [])
            cur.execute(
                f"SELECT style, COUNT(*) AS n FROM `{TABLE_METRICS}` "
                f"WHERE style <> '' GROUP BY style ORDER BY n DESC"
            )
            out["style"] = list(cur.fetchall() or [])
            cur.execute(
                f"SELECT pnl_bucket, COUNT(*) AS n FROM `{TABLE_METRICS}` "
                f"WHERE pnl_bucket <> '' GROUP BY pnl_bucket ORDER BY n DESC"
            )
            out["pnl_bucket"] = list(cur.fetchall() or [])
        return out

    try:
        return with_retry(_run) or {}
    except Exception:
        log.exception("tc_analytics get_distributions failed")
        return {}


def save_feedback(payload: dict) -> bool:
    if not mysql_enabled() or not ensure_schema():
        return False
    m = payload or {}
    uuid = (m.get("user_uuid") or "").strip()[:40]
    if not uuid:
        return False
    rating = int(m.get("rating") or 0)
    if rating < 0 or rating > 5:
        return False

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_FEEDBACK}` (
                    user_uuid, rating, comment, report_score, report_style, ua_hash
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid, rating, (m.get("comment") or "")[:2000] or None,
                    m.get("report_score") if m.get("report_score") is not None else None,
                    (m.get("report_style") or "")[:32] or None,
                    (m.get("ua_hash") or "")[:32],
                ),
            )
        conn.commit()
        return True

    try:
        return bool(with_retry(_run))
    except Exception:
        log.exception("tc_analytics save_feedback failed")
        return False
