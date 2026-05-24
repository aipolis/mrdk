# -*- coding: utf-8 -*-
"""首页 /api/sentiment/today 预计算缓存 — 后台刷新，请求秒回"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from config import HOME_CACHE_FILE, HOME_CACHE_MAX_STALE_SEC
from db_store import db_status, load_home_cache as load_mysql_cache, mysql_enabled, save_home_cache as save_mysql_cache

log = logging.getLogger("mingri.home_cache")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "payload": None,
    "context": {},
    "built_at": 0.0,
    "building": False,
    "last_error": "",
    "refresh_count": 0,
    "backend": "none",
}
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _refresh_interval_sec() -> int:
    """按时段调整刷新频率"""
    now = datetime.now()
    hm = now.hour * 60 + now.minute
    if 8 * 60 + 30 <= hm < 10 * 60:
        return int(os.getenv("HOME_CACHE_REFRESH_OPEN", "120"))
    if 10 * 60 <= hm < 15 * 60 + 30:
        return int(os.getenv("HOME_CACHE_REFRESH_INTRADAY", "300"))
    return int(os.getenv("HOME_CACHE_REFRESH_DEFAULT", "600"))


def _load_disk() -> bool:
    path = HOME_CACHE_FILE
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        payload = blob.get("payload")
        if not payload:
            return False
        with _lock:
            _state["payload"] = payload
            _state["context"] = blob.get("context") or {}
            _state["built_at"] = float(blob.get("built_at") or 0)
            _state["backend"] = "file"
        log.info("loaded home cache from disk age=%.0fs", time.time() - _state["built_at"])
        return True
    except Exception as e:
        log.warning("load disk cache failed: %s", e)
        return False


def _load_persisted() -> bool:
    """优先 MySQL，其次本地文件。"""
    if mysql_enabled():
        row = load_mysql_cache()
        if row and row.get("payload"):
            with _lock:
                _state["payload"] = row["payload"]
                _state["context"] = row.get("context") or {}
                _state["built_at"] = float(row.get("built_at") or 0)
                _state["backend"] = "mysql"
            log.info(
                "loaded home cache from mysql age=%.0fs",
                time.time() - _state["built_at"],
            )
            return True
    return _load_disk()


def _save_persisted(payload: dict, context: dict, built_at: float) -> None:
    saved_mysql = save_mysql_cache(payload, context, built_at)
    _save_disk(payload, context)
    with _lock:
        if saved_mysql:
            _state["backend"] = "mysql"
        elif _state.get("backend") != "mysql":
            _state["backend"] = "file"


def _save_disk(payload: dict, context: dict) -> None:
    path = HOME_CACHE_FILE
    if not path:
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp"
        blob = {
            "payload": payload,
            "context": context,
            "built_at": time.time(),
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        log.warning("save disk cache failed: %s", e)


def build_and_store(build_fn: Callable[[], tuple[dict, dict]]) -> bool:
    """同步构建并写入缓存；build_fn 返回 (payload, context)。"""
    with _lock:
        if _state["building"]:
            return False
        _state["building"] = True
    t0 = time.time()
    try:
        payload, context = build_fn()
        built_at = time.time()
        with _lock:
            _state["payload"] = payload
            _state["context"] = context
            _state["built_at"] = built_at
            _state["last_error"] = ""
            _state["refresh_count"] = int(_state.get("refresh_count") or 0) + 1
        _save_persisted(payload, context, built_at)
        log.info("home cache refreshed in %.1fs", time.time() - t0)
        return True
    except Exception as e:
        with _lock:
            _state["last_error"] = str(e)
        log.exception("home cache refresh failed")
        return False
    finally:
        with _lock:
            _state["building"] = False


def patch_home_cache(patch_fn: Callable[[dict], dict]) -> bool:
    """轻量更新首页缓存（如外围 10 分钟刷新），避免整包重算。"""
    with _lock:
        if not _state.get("payload"):
            return False
        payload = copy.deepcopy(_state["payload"])
        context = dict(_state.get("context") or {})
    try:
        new_payload = patch_fn(payload)
        built_at = time.time()
        with _lock:
            _state["payload"] = new_payload
            _state["built_at"] = built_at
            _state["refresh_count"] = int(_state.get("refresh_count") or 0) + 1
        _save_persisted(new_payload, context, built_at)
        return True
    except Exception:
        log.exception("patch home cache failed")
        return False


def get_snapshot() -> Optional[dict[str, Any]]:
    with _lock:
        payload = _state.get("payload")
        if not payload:
            return None
        age = time.time() - float(_state.get("built_at") or 0)
        return {
            "payload": copy.deepcopy(payload),
            "context": dict(_state.get("context") or {}),
            "built_at": _state.get("built_at"),
            "age_sec": age,
            "building": bool(_state.get("building")),
            "refresh_count": _state.get("refresh_count"),
            "last_error": _state.get("last_error"),
            "backend": _state.get("backend"),
        }


def ensure_memory_loaded() -> bool:
    """内存无缓存时尝试从 MySQL / 磁盘加载。"""
    with _lock:
        if _state.get("payload"):
            return True
    return _load_persisted()


def trigger_async_build(build_fn: Callable[[], tuple[dict, dict]]) -> None:
    threading.Thread(
        target=lambda: build_and_store(build_fn),
        daemon=True,
        name="home-cache-async",
    ).start()


def is_stale(max_age_sec: Optional[int] = None) -> bool:
    max_age = max_age_sec if max_age_sec is not None else _refresh_interval_sec()
    with _lock:
        if not _state.get("payload"):
            return True
        return (time.time() - float(_state.get("built_at") or 0)) > max_age


def is_expired() -> bool:
    with _lock:
        if not _state.get("payload"):
            return True
        age = time.time() - float(_state.get("built_at") or 0)
        return age > HOME_CACHE_MAX_STALE_SEC


def cache_status() -> dict:
    snap = get_snapshot()
    if not snap:
        return {
            "ready": False,
            "building": _state.get("building"),
            "last_error": _state.get("last_error"),
            "refresh_interval_sec": _refresh_interval_sec(),
            "mysql": db_status(),
        }
    return {
        "ready": True,
        "age_sec": round(snap["age_sec"], 1),
        "built_at": datetime.fromtimestamp(snap["built_at"]).isoformat(timespec="seconds"),
        "building": snap["building"],
        "refresh_count": snap["refresh_count"],
        "last_error": snap["last_error"],
        "context": snap["context"],
        "backend": snap.get("backend"),
        "refresh_interval_sec": _refresh_interval_sec(),
        "expired": snap["age_sec"] > HOME_CACHE_MAX_STALE_SEC,
        "mysql": db_status(),
    }


def _refresh_loop(build_fn: Callable[[], tuple[dict, dict]]) -> None:
    while not _stop.is_set():
        try:
            if is_stale():
                build_and_store(build_fn)
        except Exception:
            log.exception("refresh loop error")
        _stop.wait(_refresh_interval_sec())


def start_background_refresh(build_fn: Callable[[], tuple[dict, dict]]) -> None:
    global _thread
    _load_persisted()
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    threading.Thread(
        target=lambda: build_and_store(build_fn),
        daemon=True,
        name="home-cache-warm",
    ).start()
    _thread = threading.Thread(
        target=_refresh_loop,
        args=(build_fn,),
        daemon=True,
        name="home-cache-loop",
    )
    _thread.start()
    log.info("background home cache refresh started interval=%ss", _refresh_interval_sec())


def stop_background_refresh() -> None:
    _stop.set()
