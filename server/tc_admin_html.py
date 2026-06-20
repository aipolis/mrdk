# -*- coding: utf-8 -*-
"""TradeCheck 后台单页:服务端渲染 HTML,token 鉴权。"""
from __future__ import annotations

import html
from datetime import datetime


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


def _fmt_dt(d) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return str(d)


def _short_uuid(u: str) -> str:
    s = _esc(u or "")
    if len(s) <= 14:
        return s
    return s[:8] + "…" + s[-5:]


def render_admin(overview: dict, dists: dict, metrics: list, feedback: list) -> str:
    o = overview or {}
    grade_rows = (dists or {}).get("grade", []) or []
    style_rows = (dists or {}).get("style", []) or []
    pnl_rows = (dists or {}).get("pnl_bucket", []) or []

    def _stat(label, val, sub=""):
        return (
            f'<div class=stat><div class=v>{_esc(val)}</div>'
            f'<div class=l>{_esc(label)}</div>'
            f'{("<div class=s>"+_esc(sub)+"</div>") if sub else ""}</div>'
        )

    stats_html = "".join([
        _stat("总报告", o.get("total_reports", 0), f"近7日 +{o.get('reports_7d',0)}"),
        _stat("独立用户", o.get("total_users", 0), f"近7日 +{o.get('users_7d',0)}"),
        _stat("反馈数", o.get("total_feedback", 0), f"平均 {o.get('avg_rating',0):.2f} 星"),
        _stat("平均评分", f"{o.get('avg_score',0):.1f}", "0-100"),
        _stat("平均胜率", f"{o.get('avg_win_rate',0):.1f}%", ""),
        _stat("平均盈亏比", f"{o.get('avg_plr',0):.2f}", "<1 为负期望"),
    ])

    def _dist_table(title, rows, key):
        tot = sum(int(r.get("n") or 0) for r in rows) or 1
        body = "".join([
            f"<tr><td>{_esc(r.get(key) or '-')}</td>"
            f"<td class=r>{_esc(r.get('n'))}</td>"
            f"<td class=r>{int(r.get('n') or 0)*100//tot}%</td></tr>"
            for r in rows
        ]) or "<tr><td colspan=3 class=muted>暂无数据</td></tr>"
        return (
            f'<div class=panel><h3>{_esc(title)}</h3>'
            f'<table><thead><tr><th>分类</th><th class=r>数量</th><th class=r>占比</th></tr></thead>'
            f"<tbody>{body}</tbody></table></div>"
        )

    dist_html = (
        _dist_table("评分等级分布", grade_rows, "grade") +
        _dist_table("交易风格分布", style_rows, "style") +
        _dist_table("万元净盈亏分布", pnl_rows, "pnl_bucket")
    )

    fb_rows = "".join([
        f"<tr><td>{_fmt_dt(r.get('created_at'))}</td>"
        f"<td>{_short_uuid(r.get('user_uuid'))}</td>"
        f"<td class=r><b>{'★'*int(r.get('rating') or 0)}</b><span class=muted>{'☆'*(5-int(r.get('rating') or 0))}</span></td>"
        f"<td>{_esc(r.get('comment') or '')}</td>"
        f"<td class=r>{_esc(r.get('report_score') or '')}</td>"
        f"<td>{_esc(r.get('report_style') or '')}</td></tr>"
        for r in (feedback or [])
    ]) or "<tr><td colspan=6 class=muted>暂无反馈</td></tr>"

    metric_rows = "".join([
        f"<tr><td>{_fmt_dt(r.get('created_at'))}</td>"
        f"<td>{_short_uuid(r.get('user_uuid'))}</td>"
        f"<td class=r>{_esc(r.get('score'))}</td>"
        f"<td>{_esc(r.get('grade'))}</td>"
        f"<td>{_esc(r.get('style'))}</td>"
        f"<td class=r>{_esc(r.get('n_trades'))}</td>"
        f"<td class=r>{float(r.get('win_rate') or 0):.1f}%</td>"
        f"<td class=r>{float(r.get('profit_loss_ratio') or 0):.2f}</td>"
        f"<td class=r>{float(r.get('total_return_pct') or 0):+.1f}%</td>"
        f"<td class=r>{float(r.get('max_drawdown_pct') or 0):.1f}%</td>"
        f"<td>{_esc(r.get('pnl_bucket'))}</td>"
        f"<td>{_esc(r.get('period_start'))}~{_esc(r.get('period_end'))}</td>"
        f"<td class=r>{'图' if r.get('has_market') else ''}{'·打板' if r.get('has_dabp') else ''}</td>"
        f"<td>{_esc(r.get('upload_source'))}</td></tr>"
        for r in (metrics or [])
    ]) or "<tr><td colspan=14 class=muted>暂无数据</td></tr>"

    return f"""<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<meta name=viewport content="width=1200">
<title>TradeCheck 后台</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f4f6fa;color:#1d2839;font-size:13.5px}}
.wrap{{max-width:1380px;margin:0 auto;padding:20px}}
header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}}
header h1{{margin:0;font-size:20px}}
header .now{{color:#7a8699;font-size:12px}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:18px}}
.stat{{background:#fff;border:1px solid #e7ecf3;border-radius:10px;padding:14px 16px}}
.stat .v{{font-size:22px;font-weight:700;color:#1f3a52}}
.stat .l{{margin-top:2px;color:#566;font-size:12px}}
.stat .s{{margin-top:2px;color:#9aa6b8;font-size:11px}}
.dists{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:18px}}
.panel{{background:#fff;border:1px solid #e7ecf3;border-radius:10px;padding:14px 16px}}
.panel h3{{margin:0 0 8px;font-size:14px;color:#1f3a52}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:6px 8px;border-bottom:1px solid #eef1f5;text-align:left}}
th{{color:#7a8699;font-weight:500;background:#fafbfd}}
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums}}
.muted{{color:#9aa6b8;text-align:center;padding:18px}}
.section{{background:#fff;border:1px solid #e7ecf3;border-radius:10px;padding:14px 16px;margin-bottom:14px;overflow:auto}}
.section h2{{margin:0 0 10px;font-size:15px;color:#1f3a52}}
.section .ct{{color:#7a8699;font-size:12px;margin-left:8px;font-weight:400}}
tr:hover td{{background:#fafcff}}
</style></head><body>
<div class=wrap>
<header><h1>TradeCheck 后台</h1><div class=now>更新于 {_fmt_dt(datetime.now())}</div></header>
<div class=stats>{stats_html}</div>
<div class=dists>{dist_html}</div>
<div class=section><h2>最近反馈<span class=ct>({len(feedback or [])})</span></h2>
<table><thead><tr><th style=width:130px>时间</th><th style=width:120px>用户</th><th class=r style=width:90px>评分</th><th>评论</th><th class=r style=width:60px>报告分</th><th style=width:160px>风格</th></tr></thead>
<tbody>{fb_rows}</tbody></table></div>
<div class=section><h2>最近报告<span class=ct>({len(metrics or [])})</span></h2>
<table><thead><tr><th style=width:130px>时间</th><th>用户</th><th class=r>分</th><th>等级</th><th>风格</th><th class=r>笔数</th><th class=r>胜率</th><th class=r>盈亏比</th><th class=r>收益率</th><th class=r>回撤</th><th>万元桶</th><th>区间</th><th class=r>含图</th><th>来源</th></tr></thead>
<tbody>{metric_rows}</tbody></table></div>
</div></body></html>"""
