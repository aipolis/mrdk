#!/usr/bin/env python3
"""Probe market volume sources vs Tonghuashun-style 沪深两市成交额."""
import re
import requests

def yi_from_yuan(yuan: float) -> float:
    return round(yuan / 1e8)


def em_index(secid: str, name: str) -> None:
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    r = requests.get(url, params={"secid": secid, "fields": "f57,f58,f6,f47,f48"}, timeout=15)
    d = (r.json().get("data") or {})
    f6, f48 = d.get("f6"), d.get("f48")
    print(f"EM {name}: f6={f6} f48={f48} -> yi f6={yi_from_yuan(float(f6 or 0)) if f6 else 0}")


def tencent_amounts() -> None:
    r = requests.get(
        "https://qt.gtimg.cn/q=sh000001,sz399001,sz399106",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    for sym in ("sh000001", "sz399001", "sz399106"):
        m = re.search(rf'v_{sym}="([^"]+)"', r.text)
        if not m:
            continue
        parts = m.group(1).split("~")
        amt37 = float(parts[37]) * 1e4 if len(parts) > 37 else 0
        print(f"Tencent {sym}: field37*yi={yi_from_yuan(amt37)}")


def em_clist_sum() -> None:
    from fetcher import _fetch_em_a_share_snapshot

    snap = _fetch_em_a_share_snapshot()
    print(f"EM clist sum: {snap.get('amount_raw')}亿 rows={snap.get('rows')}")


if __name__ == "__main__":
    em_index("1.000001", "上证")
    em_index("0.399001", "深成指")
    em_index("0.399106", "深证综指")
    tencent_amounts()
    print("---")
    print("Current codes 000001+399106 tencent:")
    r = requests.get("https://qt.gtimg.cn/q=sh000001,sz399106", timeout=15)
    total = 0.0
    for sym in ("sh000001", "sz399106"):
        m = re.search(rf'v_{sym}="([^"]+)"', r.text)
        if m:
            parts = m.group(1).split("~")
            if len(parts) > 37:
                total += float(parts[37]) * 1e4
    print(f"  total yi={yi_from_yuan(total)}")
    print("THS-style 000001+399001 tencent:")
    r = requests.get("https://qt.gtimg.cn/q=sh000001,sz399001", timeout=15)
    total = 0.0
    for sym in ("sh000001", "sz399001"):
        m = re.search(rf'v_{sym}="([^"]+)"', r.text)
        if m:
            parts = m.group(1).split("~")
            if len(parts) > 37:
                total += float(parts[37]) * 1e4
    print(f"  total yi={yi_from_yuan(total)}")
    try:
        em_clist_sum()
    except Exception as e:
        print("clist", e)
