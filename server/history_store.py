# -*- coding: utf-8 -*-
"""交易日指标 + 情绪评分 — MySQL 持久化与历史查询"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from db_store import ensure_schema, mysql_enabled, with_retry

log = logging.getLogger("mingri.history")

TABLE_DAILY = "daily_market"


def _trade_d_from_metrics(metrics: dict) -> str:
    raw = (metrics.get("date") or "").replace("-", "")
    return raw[:8]


def _row_to_history_item(row: dict) -> dict:
    """数据库行 → /api/sentiment/history 列表项"""
    try:
        blob = json.loads(row.get("history_json") or "{}")
        if blob:
            return blob
    except Exception:
        pass
    idx = float(row.get("index_chg") or 0)
    return {
        "date": row.get("date_display"),
        "score": int(row.get("score") or 0),
        "level": row.get("level_label") or "",
        "levelClass": row.get("level_class") or "",
        "levelColor": row.get("level_color") or "",
        "indexChg": idx,
        "indexChgText": f"{idx:+.2f}%",
        "indexUp": idx >= 0,
        "position": int(row.get("position_pct") or 0),
        "promote": int(row.get("promote_rate") or 0),
        "limitUp": int(row.get("limit_up") or 0),
    }


def build_history_item(metrics: dict, sentiment: dict, *, ui_level: str, level_class: str) -> dict:
    idx = float(metrics.get("index_chg") or 0)
    return {
        "date": metrics.get("date"),
        "score": int(sentiment.get("score") or 0),
        "level": ui_level,
        "levelClass": level_class,
        "levelColor": sentiment.get("levelColor") or "",
        "indexChg": idx,
        "indexChgText": f"{idx:+.2f}%",
        "indexUp": idx >= 0,
        "position": int(sentiment.get("positionPercent") or 0),
        "promote": round(float(metrics.get("promote_rate") or 0)),
        "limitUp": int(metrics.get("limit_up_count") or 0),
    }


def save_daily_record(
    trade_d: str,
    prev_d: Optional[str],
    metrics: dict,
    sentiment: dict,
    *,
    history_item: dict,
    indicators: Optional[list] = None,
    grid9: Optional[list] = None,
    peripheral: Optional[list] = None,
    auction: Optional[list] = None,
    indicator_sections: Optional[list] = None,
) -> bool:
    if not mysql_enabled() or not ensure_schema():
        return False
    trade_d = (trade_d or _trade_d_from_metrics(metrics))[:8]
    if len(trade_d) != 8:
        return False

    metrics_s = json.dumps(metrics, ensure_ascii=False)
    sentiment_s = json.dumps(sentiment, ensure_ascii=False)
    history_s = json.dumps(history_item, ensure_ascii=False)
    indicators_s = json.dumps(indicators or [], ensure_ascii=False)
    grid9_s = json.dumps(grid9 or [], ensure_ascii=False)
    peripheral_s = json.dumps(peripheral or [], ensure_ascii=False)
    auction_s = json.dumps(auction or [], ensure_ascii=False)
    sections_s = json.dumps(indicator_sections or [], ensure_ascii=False)

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_DAILY}` (
                    trade_date, date_display, prev_trade_date,
                    score, level_label, level_class, level_color,
                    index_chg, position_pct, promote_rate, limit_up,
                    empty_warning,
                    metrics_json, sentiment_json, indicators_json, history_json,
                    grid9_json, peripheral_json, auction_json, indicator_sections_json
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    date_display=VALUES(date_display),
                    prev_trade_date=VALUES(prev_trade_date),
                    score=VALUES(score),
                    level_label=VALUES(level_label),
                    level_class=VALUES(level_class),
                    level_color=VALUES(level_color),
                    index_chg=VALUES(index_chg),
                    position_pct=VALUES(position_pct),
                    promote_rate=VALUES(promote_rate),
                    limit_up=VALUES(limit_up),
                    empty_warning=VALUES(empty_warning),
                    metrics_json=VALUES(metrics_json),
                    sentiment_json=VALUES(sentiment_json),
                    indicators_json=VALUES(indicators_json),
                    history_json=VALUES(history_json),
                    grid9_json=VALUES(grid9_json),
                    peripheral_json=VALUES(peripheral_json),
                    auction_json=VALUES(auction_json),
                    indicator_sections_json=VALUES(indicator_sections_json)
                """,
                (
                    trade_d,
                    metrics.get("date") or f"{trade_d[:4]}-{trade_d[4:6]}-{trade_d[6:8]}",
                    (prev_d or "")[:8] or None,
                    int(sentiment.get("score") or 0),
                    history_item.get("level") or "",
                    history_item.get("levelClass") or "",
                    sentiment.get("levelColor") or "",
                    float(metrics.get("index_chg") or 0),
                    int(sentiment.get("positionPercent") or 0),
                    round(float(metrics.get("promote_rate") or 0)),
                    int(metrics.get("limit_up_count") or 0),
                    1 if sentiment.get("emptyWarning") else 0,
                    metrics_s,
                    sentiment_s,
                    indicators_s,
                    history_s,
                    grid9_s,
                    peripheral_s,
                    auction_s,
                    sections_s,
                ),
            )
        conn.commit()

    try:
        with_retry(_run)
        return True
    except Exception:
        log.exception("save daily record failed trade_d=%s", trade_d)
        return False


def fetch_history_list(days: int) -> list[dict]:
    """按交易日倒序取最近 days 条历史列表项。"""
    if not mysql_enabled() or not ensure_schema():
        return []

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM `{TABLE_DAILY}`
                ORDER BY trade_date DESC
                LIMIT %s
                """,
                (max(1, min(days, 120)),),
            )
            rows = cur.fetchall() or []
        return [_row_to_history_item(r) for r in rows]

    try:
        return with_retry(_run) or []
    except Exception:
        log.exception("fetch history list failed")
        return []


def fetch_daily_detail(trade_d: str) -> Optional[dict]:
    """单日完整指标 + 情绪（供后续扩展详情页）。"""
    if not mysql_enabled() or not ensure_schema():
        return None
    trade_d = (trade_d or "").replace("-", "")[:8]

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM `{TABLE_DAILY}` WHERE trade_date=%s LIMIT 1",
                (trade_d,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "tradeDate": trade_d,
            "metrics": json.loads(row.get("metrics_json") or "{}"),
            "sentiment": json.loads(row.get("sentiment_json") or "{}"),
            "indicators": json.loads(row.get("indicators_json") or "[]"),
            "history": json.loads(row.get("history_json") or "{}"),
            "grid9": json.loads(row.get("grid9_json") or "[]"),
            "peripheral": json.loads(row.get("peripheral_json") or "[]"),
            "auction": json.loads(row.get("auction_json") or "[]"),
            "indicatorSections": json.loads(row.get("indicator_sections_json") or "[]"),
        }

    try:
        return with_retry(_run)
    except Exception:
        log.exception("fetch daily detail failed")
        return None


def count_daily_records() -> int:
    if not mysql_enabled() or not ensure_schema():
        return 0

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM `{TABLE_DAILY}`")
            row = cur.fetchone()
        return int((row or {}).get("c") or 0)

    try:
        return with_retry(_run) or 0
    except Exception:
        return 0


def list_stored_trade_dates(limit: int = 120) -> list[str]:
    if not mysql_enabled() or not ensure_schema():
        return []

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT trade_date FROM `{TABLE_DAILY}` ORDER BY trade_date DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return [str(r["trade_date"]) for r in rows]

    try:
        return with_retry(_run) or []
    except Exception:
        return []


def count_daily_with_sections() -> int:
    if not mysql_enabled() or not ensure_schema():
        return 0

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM `{TABLE_DAILY}`
                WHERE indicator_sections_json IS NOT NULL
                  AND indicator_sections_json != ''
                  AND indicator_sections_json != '[]'
                """
            )
            row = cur.fetchone()
        return int((row or {}).get("c") or 0)

    try:
        return with_retry(_run) or 0
    except Exception:
        return 0


def history_db_status() -> dict:
    return {
        "enabled": mysql_enabled(),
        "table": TABLE_DAILY,
        "rowCount": count_daily_records(),
        "sectionsRowCount": count_daily_with_sections(),
        "latest": (list_stored_trade_dates(1) or [None])[0],
    }
