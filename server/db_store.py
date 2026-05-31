# -*- coding: utf-8 -*-
"""云托管 MySQL 连接与表结构"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional

import pymysql

from config import MYSQL_ADDRESS, MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_USERNAME

log = logging.getLogger("mingri.db")

TABLE_HOME = "home_sentiment_cache"
TABLE_DAILY = "daily_market"
TABLE_INTRADAY = "intraday_market_snapshots"
TABLE_AUCTION_VOL = "auction_vol_snapshot"
CACHE_KEY = "default"
_schema_ready = False
MYSQL_CHARSET = "utf8mb4"
MYSQL_COLLATE = "utf8mb4_unicode_ci"


def mysql_enabled() -> bool:
    return bool(MYSQL_ADDRESS and MYSQL_USERNAME and MYSQL_PASSWORD)


def _parse_address() -> tuple[str, int]:
    addr = (MYSQL_ADDRESS or "").strip()
    if not addr:
        return "", 3306
    if ":" in addr:
        host, port_s = addr.rsplit(":", 1)
        return host.strip(), int(port_s)
    return addr, 3306


def _is_resume_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "resuming" in msg or "try connecting again" in msg


def _connect(*, use_db: bool = True):
    host, port = _parse_address()
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "user": MYSQL_USERNAME,
        "password": MYSQL_PASSWORD,
        "charset": MYSQL_CHARSET,
        "connect_timeout": 15,
        "read_timeout": 120,
        "write_timeout": 120,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
    }
    if use_db and MYSQL_DATABASE:
        kwargs["database"] = MYSQL_DATABASE
    return pymysql.connect(**kwargs)


@contextmanager
def db_connection(*, use_db: bool = True):
    conn = _connect(use_db=use_db)
    try:
        yield conn
    finally:
        conn.close()


def with_retry(fn: Callable, retries: int = 6):
    """fn(conn) -> result"""
    delay = 1.0
    last_exc: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            with db_connection() as conn:
                return fn(conn)
        except Exception as exc:
            last_exc = exc
            if _is_resume_error(exc) and attempt < retries - 1:
                log.warning("mysql waking up, retry in %.1fs (%s)", delay, exc)
                time.sleep(delay)
                delay = min(delay * 1.6, 10.0)
                continue
            raise
    if last_exc:
        raise last_exc


def ensure_schema() -> bool:
    global _schema_ready
    if _schema_ready or not mysql_enabled():
        return _schema_ready

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                f"DEFAULT CHARACTER SET {MYSQL_CHARSET} COLLATE {MYSQL_COLLATE}"
            )
            cur.execute(
                f"ALTER DATABASE `{MYSQL_DATABASE}` "
                f"CHARACTER SET {MYSQL_CHARSET} COLLATE {MYSQL_COLLATE}"
            )
        conn.select_db(MYSQL_DATABASE)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_HOME}` (
                    cache_key VARCHAR(64) NOT NULL PRIMARY KEY,
                    payload LONGTEXT NOT NULL,
                    context TEXT NOT NULL,
                    built_at DOUBLE NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_DAILY}` (
                    trade_date CHAR(8) NOT NULL PRIMARY KEY,
                    date_display VARCHAR(10) NOT NULL,
                    prev_trade_date CHAR(8) NULL,
                    score INT NOT NULL DEFAULT 0,
                    level_label VARCHAR(16) NOT NULL DEFAULT '',
                    level_class VARCHAR(16) NOT NULL DEFAULT '',
                    level_color VARCHAR(16) NOT NULL DEFAULT '',
                    index_chg DOUBLE NOT NULL DEFAULT 0,
                    position_pct INT NOT NULL DEFAULT 0,
                    promote_rate INT NOT NULL DEFAULT 0,
                    limit_up INT NOT NULL DEFAULT 0,
                    empty_warning TINYINT NOT NULL DEFAULT 0,
                    metrics_json LONGTEXT NOT NULL,
                    sentiment_json TEXT NOT NULL,
                    indicators_json TEXT NULL,
                    history_json TEXT NOT NULL,
                    grid9_json TEXT NULL,
                    peripheral_json TEXT NULL,
                    auction_json TEXT NULL,
                    indicator_sections_json TEXT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_date_display (date_display)
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_INTRADAY}` (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    trade_date CHAR(8) NOT NULL,
                    snap_time VARCHAR(5) NOT NULL,
                    ref_trade_date CHAR(8) NULL,
                    advice_date CHAR(8) NULL,
                    baseline_score INT NOT NULL DEFAULT 0,
                    intraday_score INT NULL,
                    display_score INT NOT NULL DEFAULT 0,
                    score_mode VARCHAR(16) NOT NULL DEFAULT '',
                    longkong_signal VARCHAR(16) NOT NULL DEFAULT '',
                    empty_warning TINYINT NOT NULL DEFAULT 0,
                    items_json LONGTEXT NULL,
                    snap_json LONGTEXT NULL,
                    sub_scores_json LONGTEXT NULL,
                    source_status_json TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_trade_time (trade_date, snap_time),
                    KEY idx_trade_date (trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
            for col_def in (
                "MODIFY COLUMN indicators_json LONGTEXT NULL",
                "MODIFY COLUMN sentiment_json LONGTEXT NOT NULL",
                "MODIFY COLUMN history_json LONGTEXT NOT NULL",
                "MODIFY COLUMN grid9_json LONGTEXT NULL",
                "MODIFY COLUMN peripheral_json LONGTEXT NULL",
                "MODIFY COLUMN auction_json LONGTEXT NULL",
                "MODIFY COLUMN indicator_sections_json LONGTEXT NULL",
                "ADD COLUMN grid9_json LONGTEXT NULL",
                "ADD COLUMN peripheral_json LONGTEXT NULL",
                "ADD COLUMN auction_json LONGTEXT NULL",
                "ADD COLUMN indicator_sections_json LONGTEXT NULL",
            ):
                try:
                    cur.execute(f"ALTER TABLE `{TABLE_DAILY}` {col_def}")
                except pymysql.err.OperationalError as exc:
                    if exc.args[0] not in (1060,):
                        raise
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_AUCTION_VOL}` (
                    trade_date CHAR(8) NOT NULL PRIMARY KEY,
                    vol_all_json LONGTEXT NOT NULL,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE}
                """
            )
            # 旧库可能是 utf8（3 字节），无法存 emoji（指标 icon 📈 等）
            for table in (TABLE_HOME, TABLE_DAILY):
                cur.execute(
                    f"ALTER TABLE `{table}` CONVERT TO CHARACTER SET {MYSQL_CHARSET} "
                    f"COLLATE {MYSQL_COLLATE}"
                )
        conn.commit()

    try:
        with db_connection(use_db=False) as conn:
            _run(conn)
        _schema_ready = True
        log.info("mysql schema ready db=%s", MYSQL_DATABASE)
        return True
    except Exception:
        log.exception("mysql schema init failed")
        return False


# --- 首页缓存 ---


def load_home_cache() -> Optional[dict[str, Any]]:
    if not mysql_enabled() or not ensure_schema():
        return None

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, context, built_at FROM `{TABLE_HOME}` WHERE cache_key=%s LIMIT 1",
                (CACHE_KEY,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "payload": json.loads(row["payload"]),
            "context": json.loads(row["context"] or "{}"),
            "built_at": float(row["built_at"] or 0),
        }

    try:
        return with_retry(_run)
    except Exception:
        log.exception("mysql load home cache failed")
        return None


def save_home_cache(payload: dict, context: dict, built_at: float) -> bool:
    if not mysql_enabled() or not ensure_schema():
        return False
    payload_s = json.dumps(payload, ensure_ascii=False)
    context_s = json.dumps(context or {}, ensure_ascii=False)

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_HOME}` (cache_key, payload, context, built_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    payload=VALUES(payload),
                    context=VALUES(context),
                    built_at=VALUES(built_at)
                """,
                (CACHE_KEY, payload_s, context_s, built_at),
            )
        conn.commit()
        return True

    try:
        return bool(with_retry(_run))
    except Exception:
        log.exception("mysql save home cache failed")
        return False


# --- 竞价量快照（循环覆盖，最大 90 天） ---


def save_auction_vol_snapshot(trade_d: str, vol_all: dict) -> bool:
    if not mysql_enabled() or not ensure_schema() or not vol_all:
        return False
    vol_all_s = json.dumps(vol_all, ensure_ascii=False)

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO `{TABLE_AUCTION_VOL}` (trade_date, vol_all_json)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE vol_all_json=VALUES(vol_all_json)
                """,
                (trade_d[:8], vol_all_s),
            )
        conn.commit()
        return True

    try:
        return bool(with_retry(_run))
    except Exception:
        log.exception("save auction vol snapshot failed trade_d=%s", trade_d)
        return False


def load_auction_vol_snapshot(trade_d: str) -> Optional[dict]:
    if not mysql_enabled() or not ensure_schema():
        return None

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT vol_all_json FROM `{TABLE_AUCTION_VOL}` WHERE trade_date=%s LIMIT 1",
                (trade_d[:8],),
            )
            row = cur.fetchone()
        if not row:
            return None
        data = json.loads(row["vol_all_json"] or "{}")
        return {k: float(v) for k, v in data.items() if v} or None

    try:
        return with_retry(_run)
    except Exception:
        log.exception("load auction vol snapshot failed trade_d=%s", trade_d)
        return None


def cleanup_auction_vol_snapshots(keep_days: int = 90) -> int:
    if not mysql_enabled() or not ensure_schema():
        return 0

    def _run(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM `{TABLE_AUCTION_VOL}` "
                f"WHERE trade_date < DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL %s DAY), '%%Y%%m%%d')",
                (keep_days,),
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted

    try:
        deleted = with_retry(_run)
        if deleted:
            log.info("cleanup auction vol snapshots: deleted %s rows (keep %s days)", deleted, keep_days)
        return deleted
    except Exception:
        log.exception("cleanup auction vol snapshots failed")
        return 0


def db_status() -> dict:
    from history_store import history_db_status

    if not mysql_enabled():
        return {"enabled": False, "history": history_db_status()}
    ok = ensure_schema()
    row = load_home_cache() if ok else None
    hist = history_db_status()
    return {
        "enabled": True,
        "ready": ok,
        "database": MYSQL_DATABASE,
        "homeTable": TABLE_HOME,
        "homeHasRow": bool(row),
        "homeBuiltAt": row.get("built_at") if row else None,
        "history": hist,
    }
