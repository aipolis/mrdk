# -*- coding: utf-8 -*-
"""TradeCheck 代码标准化层
拼音简称/中文名 → 标准 6 位代码反查
数据存 MySQL,7 天刷新一次
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from db_store import db_connection, mysql_enabled

log = logging.getLogger(__name__)

_REFRESH_INTERVAL_SEC = 7 * 86400
_mem_cache: dict[str, dict] = {}


def _ensure_table() -> bool:
    if not mysql_enabled():
        return False
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS tc_code_map (
                    cache_key VARCHAR(96) PRIMARY KEY,
                    code VARCHAR(8) NOT NULL,
                    name VARCHAR(64) NOT NULL,
                    kind VARCHAR(16) NOT NULL,
                    updated_at INT NOT NULL,
                    INDEX idx_code (code),
                    INDEX idx_updated (updated_at)
                ) DEFAULT CHARSET=utf8mb4"""
            )
        conn.commit()
    return True


def _is_stale() -> bool:
    if not _ensure_table():
        return False  # 无 MySQL 时退化为内存缓存,永不"过期"重建
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(updated_at) FROM tc_code_map")
            row = cur.fetchone()
    if not row or not row[0]:
        return True
    return time.time() - int(row[0]) > _REFRESH_INTERVAL_SEC


def _rebuild_cache() -> int:
    """全量拉一次 A 股代码表写入 MySQL"""
    import akshare as ak
    from pypinyin import lazy_pinyin, Style

    log.info("[tc_code_resolver] 拉取全 A 股代码表中...")
    df = ak.stock_info_a_code_name()  # 列:code, name
    now = int(time.time())
    rows: list[tuple] = []
    for _, r in df.iterrows():
        code = str(r["code"]).zfill(6)
        name = str(r["name"]).strip()
        if not name or not code:
            continue
        rows.append((f"name:{name}", code, name, "name", now))
        py = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).upper()
        if py:
            rows.append((f"pinyin:{py}|{name}", code, name, "pinyin_named", now))
            rows.append((f"pinyin1st:{py}", code, name, "pinyin_first", now))

    if mysql_enabled():
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tc_code_map")
                cur.executemany(
                    "INSERT INTO tc_code_map (cache_key, code, name, kind, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    rows,
                )
            conn.commit()
    # 内存缓存(MySQL 不可用时的退化方案)
    _mem_cache.clear()
    for key, code, name, kind, _ in rows:
        _mem_cache[key] = {"code": code, "name": name, "kind": kind}
    log.info("[tc_code_resolver] 写入 %d 条记录", len(rows))
    return len(rows)


def _lookup_db(cache_key: str) -> Optional[str]:
    if mysql_enabled():
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code FROM tc_code_map WHERE cache_key=%s LIMIT 1",
                    (cache_key,),
                )
                row = cur.fetchone()
        if row:
            return row[0]
    item = _mem_cache.get(cache_key)
    return item["code"] if item else None


def resolve(symbol: Optional[str] = None, name: Optional[str] = None) -> Optional[str]:
    """返回标准 6 位代码;查不到返回 None。

    优先级:
      1. 中文名精确匹配
      2. 拼音首字母 + 中文名联合(消歧)
      3. 拼音首字母(取第一个候选)
      4. 输入本身就是 6 位数字(直接返回)
    """
    if _is_stale() or (mysql_enabled() and _lookup_db("name:" + (name or "_")) is None and not _mem_cache):
        try:
            _rebuild_cache()
        except Exception as e:
            log.warning("[tc_code_resolver] 重建失败: %s", e)

    if name:
        clean = name.strip()
        hit = _lookup_db("name:" + clean)
        if hit:
            return hit

    if symbol:
        s = symbol.strip().upper()
        if s.isdigit() and len(s) == 6:
            return s
        if name:
            hit = _lookup_db(f"pinyin:{s}|{name.strip()}")
            if hit:
                return hit
        hit = _lookup_db(f"pinyin1st:{s}")
        if hit:
            return hit

    return None
