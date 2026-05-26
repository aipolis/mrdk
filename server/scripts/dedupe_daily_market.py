#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除 daily_market 中展示日期重复的行。需在配置 MYSQL_* 环境变量后运行。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from history_store import dedupe_daily_market_records  # noqa: E402


def main() -> int:
    result = dedupe_daily_market_records()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
