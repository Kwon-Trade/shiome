#!/usr/bin/env python3
"""ステージ5: data/processed/validation/ の結果から、成績表を含む
HTMLレポート1枚(reports/backtest_report.html)を作る。

実行例:
    python scripts/build_report.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shiome.config import PROCESSED_DIR  # noqa: E402

VALIDATION_DIR = PROCESSED_DIR / "validation"
REPORT_PATH = ROOT / "reports" / "backtest_report.html"

PHASE_KEYS = [
    "1_healthy_uptrend", "2_overleveraged_uptrend", "3_short_squeeze_setup",
    "4_distribution_top", "5_capitulation_bottom", "6_compression",
]
PHASE_LABELS = {
    "1_healthy_uptrend": "① 健全な上昇", "2_overleveraged_uptrend": "② 燃料過多の上昇",
    "3_short_squeeze_setup": "③ ショート踏み上げ準備", "4_distribution_top": "④ 天井の売り抜け",
    "5_capitulation_bottom": "⑤ 投げ売り後の底打ち", "6_compression": "⑥ 圧縮",
}
PHASE_DIRECTION = {
    "1_healthy_uptrend": "上昇を予想", "2_overleveraged_uptrend": "下落を予想",
    "3_short_squeeze_setup": "上昇を予想", "4_distribution_top": "下落を予想",
    "5_capitulation_bottom": "上昇を予想", "6_compression": "方向は予想せず、値幅拡大の有無で評価",
}
GROUP_KEYS = ["large_cap", "mid_cap_alt", "small_meme"]
GROUP_LABELS = {"large_cap": "大型", "mid_cap_alt": "中型アルト", "small_meme": "小型・ミーム"}


def n1(v):
    return "—" if v is None else f"{v:.1f}"


def n2(v):
    return "—" if v is None else f"{v:.2f}"


def sgn(v):
    return "—" if v is None else f"{'+' if v > 0 else ''}{v:.2f}%"


def badge(res):
    if res.get("n", 0) == 0:
        return ("no-data", "データ無し")
    if res.get("insufficient"):
        return ("pending", "判定保留")
    if res.get("passes_primary"):
        return ("pass", "合格")
    return ("fail", "不合格")


def h_badge(h):
    if not h:
        return ("no-data", "—")
    return ("pass", "○") if h.get("passes") else ("fail", "×")


def badge_html(key, label):
    return f'<span class="badge badge-{key}">{label}</span>'


def build_group_rows(results, groups):
    group_pass_counts = {}
    rows_by_group = {}
    for g in GROUP_KEYS:
        rows = []
        c = 0
        for p in PHASE_KEYS:
            res = results["holdout"][g][p]
            if res.get("passes_primary"):
                c += 1
            h24 = res.get("h24", {})
            h168 = res.get("h168", {})
            b_key, b_label = badge(res)
            rows.append({
                "label": PHASE_LABELS[p], "direction": PHASE_DIRECTION[p], "n": res.get("n", 0),
                "hit24": h24.get("hit_rate_pct"), "base24": h24.get("baseline_hit_rate_pct"),
                "ret24": h24.get("avg_return_pct"), "cost24": h24.get("avg_cost_pct"),
                "hit168": h168.get("hit_rate_pct"), "base168": h168.get("baseline_hit_rate_pct"),
                "ret168": h168.get("avg_return_pct"), "cost168": h168.get("avg_cost_pct"),
                "badge_key": b_key, "badge_label": b_label,
                "h24_badge": h_badge(h24), "h168_badge": h_badge(h168),
            })
        rows_by_group[g] = rows
        group_pass_counts[g] = c
    return rows_by_group, group_pass_counts


def render_group_table(g, rows, n_sym, pass_count):
    trs = []
    for row in rows:
        b_key, b_label = row["badge_key"], row["badge_label"]
        h24_key, h24_label = row["h24_badge"]
        h168_key, h168_label = row["h168_badge"]
        trs.append(f"""
        <tr>
          <td class="phase-cell">
            <div class="phase-name">{row['label']}</div>
            <div class="phase-dir">{row['direction']}</div>
          </td>
          <td class="num">{row['n']:,}</td>
          <td class="num">{n1(row['hit24'])}%<span class="vs">基準{n1(row['base24'])}%</span></td>
          <td class="num">{sgn(row['ret24'])}<span class="vs">コスト{n2(row['cost24'])}%</span></td>
          <td class="center"><span class="mini-badge mini-{h24_key}">{h24_label}</span></td>
          <td class="num">{n1(row['hit168'])}%<span class="vs">基準{n1(row['base168'])}%</span></td>
          <td class="num">{sgn(row['ret168'])}<span class="vs">コスト{n2(row['cost168'])}%</span></td>
          <td class="center"><span class="mini-badge mini-{h168_key}">{h168_label}</span></td>
          <td class="center">{badge_html(b_key, b_label)}</td>
        </tr>""")
    return f"""
    <section class="group-block">
      <div class="group-head">
        <h3>{GROUP_LABELS[g]}グループ <span class="n-sym">({n_sym}銘柄)</span></h3>
        <div class="group-verdict">合格局面数: <strong>{pass_count} / 6</strong>（2以上で合格）</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>局面</th><th>件数</th><th>24h的中率</th><th>24h値幅</th><th>24h判定</th>
              <th>168h的中率</th><th>168h値幅</th><th>168h判定</th><th>総合判定</th>
            </tr>
          </thead>
          <tbody>{''.join(trs)}</tbody>
        </table>
      </div>
    </section>"""


def build_spotlight(results):
    spot = []
    for g in GROUP_KEYS:
        b24 = results["holdout"][g]["_baseline"]["24"]["avg_abs_return"] * 100
        b168 = results["holdout"][g]["_baseline"]["168"]["avg_abs_return"] * 100
        p6 = results["holdout"][g]["6_compression"]
        spot.append({
            "label": GROUP_LABELS[g],
            "baseline24": b24, "phase24": p6.get("h24", {}).get("avg_return_pct"),
            "hit24": p6.get("h24", {}).get("hit_rate_pct"),
            "baseline168": b168, "phase168": p6.get("h168", {}).get("avg_return_pct"),
            "hit168": p6.get("h168", {}).get("hit_rate_pct"),
        })
    return spot


def render_spotlight_chart(spot):
    chart_w, chart_h = 640, 220
    pad_l, pad_r, pad_t, pad_b = 46, 16, 16, 34
    plot_w, plot_h = chart_w - pad_l - pad_r, chart_h - pad_t - pad_b
    max_val = max(max(s["baseline24"], s["phase24"]) for s in spot) * 1.15
    bar_group_w, bar_w, gap = plot_w / 3, 34, 14

    def y_of(v):
        return pad_t + plot_h - (v / max_val) * plot_h

    parts = []
    for i in range(5):
        frac = i / 4
        yy = pad_t + plot_h - frac * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{chart_w - pad_r}" y2="{yy:.1f}" class="gridline"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" class="axis-label" text-anchor="end">{frac * max_val:.1f}%</text>')

    for i, s in enumerate(spot):
        cx = pad_l + bar_group_w * i + bar_group_w / 2
        x_base, x_phase = cx - gap / 2 - bar_w, cx + gap / 2
        yb, yp = y_of(s["baseline24"]), y_of(s["phase24"])
        hb, hp = pad_t + plot_h - yb, pad_t + plot_h - yp
        parts.append(f'<rect x="{x_base:.1f}" y="{yb:.1f}" width="{bar_w}" height="{hb:.1f}" rx="3" class="bar-baseline"/>')
        parts.append(f'<rect x="{x_phase:.1f}" y="{yp:.1f}" width="{bar_w}" height="{hp:.1f}" rx="3" class="bar-phase"/>')
        parts.append(f'<text x="{x_base + bar_w/2:.1f}" y="{yb - 6:.1f}" class="bar-label" text-anchor="middle">{s["baseline24"]:.2f}%</text>')
        parts.append(f'<text x="{x_phase + bar_w/2:.1f}" y="{yp - 6:.1f}" class="bar-label" text-anchor="middle">{s["phase24"]:.2f}%</text>')
        parts.append(f'<text x="{cx:.1f}" y="{chart_h - pad_b + 20:.1f}" class="axis-label-g" text-anchor="middle">{s["label"]}</text>')

    return f'<svg viewBox="0 0 {chart_w} {chart_h}" class="spotlight-chart" role="img" aria-label="圧縮後の値幅比較チャート">{"".join(parts)}</svg>'


def render_supplementary(results, key, title, note):
    rows = []
    for g in GROUP_KEYS:
        c = sum(1 for p in PHASE_KEYS if results[key][g][p].get("passes_primary"))
        n_sym = results[key][g].get("_n_symbols")
        rows.append(f"<tr><td>{GROUP_LABELS[g]}</td><td class='num'>{n_sym}銘柄</td><td class='num'>{c} / 6</td></tr>")
    return f"""
    <div class="supp-card">
      <h4>{title}</h4>
      <p class="supp-note">{note}</p>
      <table class="supp-table">
        <thead><tr><th>グループ</th><th>対象銘柄数</th><th>合格局面数</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


CSS = """
:root {
  --bg: #F5F6F8; --surface: #FFFFFF; --surface-2: #EEF0F4; --border: #DDE1E8;
  --fg: #1B1F27; --fg-muted: #63697A; --fg-faint: #9099AA;
  --accent: #2C4870; --accent-soft: #EAF0FA;
  --good: #1E7A4C; --good-soft: #E6F5EC;
  --bad: #B23A2E; --bad-soft: #FBEAE8;
  --warn: #9A6B12; --warn-soft: #FBF1DE;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14161B; --surface: #1B1E26; --surface-2: #21242D; --border: #333846;
    --fg: #E7E9EE; --fg-muted: #9BA1B0; --fg-faint: #6B7180;
    --accent: #7FA6DE; --accent-soft: #22304A;
    --good: #5FBE8B; --good-soft: #16281F;
    --bad: #E28074; --bad-soft: #2E1B19;
    --warn: #D9B25E; --warn-soft: #2E2716;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #14161B; --surface: #1B1E26; --surface-2: #21242D; --border: #333846;
  --fg: #E7E9EE; --fg-muted: #9BA1B0; --fg-faint: #6B7180;
  --accent: #7FA6DE; --accent-soft: #22304A;
  --good: #5FBE8B; --good-soft: #16281F;
  --bad: #E28074; --bad-soft: #2E1B19;
  --warn: #D9B25E; --warn-soft: #2E2716;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg);
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
  margin: 0; padding: 0 16px; padding-block: 32px;
}
.page { max-width: 920px; margin: 0 auto; }
h1, h2, h3, h4 { font-family: 'Fraunces', Georgia, serif; text-wrap: balance; margin: 0; }
h1 { font-size: clamp(28px, 5vw, 38px); font-weight: 600; letter-spacing: -0.01em; }
h2 { font-size: 22px; font-weight: 600; margin-bottom: 12px; }
h3 { font-size: 18px; font-weight: 600; }
h4 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
p { line-height: 1.7; color: var(--fg); max-width: 68ch; }
.eyebrow {
  font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--fg-muted); margin-bottom: 10px;
}
header.hero { padding-block: 8px 28px; border-bottom: 1px solid var(--border); margin-bottom: 28px; }
.hero-sub { color: var(--fg-muted); margin-top: 10px; font-size: 15px; }
.verdict-card {
  background: var(--bad-soft); border: 1px solid var(--bad);
  border-radius: 12px; padding: 22px 24px; margin-top: 20px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 20px;
}
.verdict-big { font-family: 'Fraunces', serif; font-size: 40px; font-weight: 700; color: var(--bad); }
.verdict-text { flex: 1; min-width: 240px; color: var(--fg); line-height: 1.7; }
.verdict-text strong { color: var(--fg); }
.stat-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0 32px; }
.stat-tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px; flex: 1; min-width: 140px;
}
.stat-tile .label { font-size: 12px; color: var(--fg-muted); margin-bottom: 4px; }
.stat-tile .value { font-family: 'IBM Plex Mono', monospace; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
section { margin-bottom: 40px; }
section > p.lede { color: var(--fg-muted); margin-top: -4px; margin-bottom: 18px; }
.group-block {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; margin-bottom: 20px;
}
.group-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.n-sym { color: var(--fg-muted); font-size: 14px; font-weight: 400; font-family: 'IBM Plex Sans', sans-serif; }
.group-verdict { font-size: 14px; color: var(--fg-muted); font-family: 'IBM Plex Mono', monospace; }
.group-verdict strong { color: var(--fg); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 720px; }
thead th {
  text-align: left; font-weight: 600; color: var(--fg-muted); font-size: 11.5px;
  text-transform: uppercase; letter-spacing: 0.04em; padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}
tbody td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tbody tr:last-child td { border-bottom: none; }
td.num { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.center { text-align: center; }
.vs { display: block; font-size: 11px; color: var(--fg-faint); }
.phase-name { font-weight: 600; }
.phase-dir { font-size: 12px; color: var(--fg-muted); margin-top: 2px; }
.badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12.5px; font-weight: 600; }
.badge-fail { background: var(--bad-soft); color: var(--bad); }
.badge-pending { background: var(--warn-soft); color: var(--warn); }
.badge-pass { background: var(--good-soft); color: var(--good); }
.badge-no-data { background: var(--surface-2); color: var(--fg-faint); }
.mini-badge { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 13px; }
.mini-pass { color: var(--good); }
.mini-fail { color: var(--bad); }
.mini-no-data { color: var(--fg-faint); }
.spotlight { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; }
.spotlight-chart { width: 100%; height: auto; margin: 12px 0 4px; }
.gridline { stroke: var(--border); stroke-width: 1; }
.axis-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; fill: var(--fg-faint); }
.axis-label-g { font-family: 'IBM Plex Sans', sans-serif; font-size: 12px; fill: var(--fg-muted); }
.bar-baseline { fill: var(--fg-faint); }
.bar-phase { fill: var(--accent); }
.bar-label { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; fill: var(--fg); font-variant-numeric: tabular-nums; }
.legend { display: flex; gap: 18px; font-size: 13px; color: var(--fg-muted); margin-top: 6px; }
.legend-swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
.sw-baseline { background: var(--fg-faint); }
.sw-phase { background: var(--accent); }
.supp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.supp-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.supp-note { font-size: 13px; color: var(--fg-muted); margin: 4px 0 12px; line-height: 1.6; }
.supp-table { font-size: 13px; min-width: 0; }
.supp-table th, .supp-table td { padding: 6px 8px; }
.method-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.method-card { background: var(--surface-2); border-radius: 10px; padding: 14px 16px; }
.method-card .k { font-size: 12px; color: var(--fg-muted); margin-bottom: 4px; }
.method-card .v { font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 600; }
.check-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.check-list li { display: flex; gap: 10px; align-items: flex-start; line-height: 1.6; }
.check-icon { color: var(--good); font-weight: 700; flex-shrink: 0; }
footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--fg-faint); font-size: 12.5px; line-height: 1.8; }
"""


def main() -> None:
    results = json.load(open(VALIDATION_DIR / "results.json", encoding="utf-8"))
    groups = json.load(open(VALIDATION_DIR / "groups.json", encoding="utf-8"))

    rows_by_group, group_pass_counts = build_group_rows(results, groups)
    total_pass = sum(group_pass_counts.values())
    total_pass_168 = sum(
        sum(1 for p in PHASE_KEYS if results["holdout"][g][p].get("h168", {}).get("passes"))
        for g in GROUP_KEYS
    )
    n_events = sum(rows_by_group[g][0]["n"] for g in [])  # unused, kept for clarity
    total_events = sum(
        results["holdout"][g][p]["n"] for g in GROUP_KEYS for p in PHASE_KEYS
    )

    group_tables_html = "".join(
        render_group_table(g, rows_by_group[g], len(groups[g]), group_pass_counts[g]) for g in GROUP_KEYS
    )

    spot = build_spotlight(results)
    spotlight_chart_svg = render_spotlight_chart(spot)
    spot_rows = "".join(f"""
<tr>
  <td>{s['label']}</td>
  <td class="num">{s['baseline24']:.2f}%</td>
  <td class="num">{s['phase24']:.2f}%</td>
  <td class="num">{n1(s['hit24'])}%</td>
  <td class="num">{s['baseline168']:.2f}%</td>
  <td class="num">{s['phase168']:.2f}%</td>
  <td class="num">{n1(s['hit168'])}%</td>
</tr>""" for s in spot)

    supp_dedup = render_supplementary(
        results, "holdout_dedup", "同時多発シグナルをまとめた場合",
        "同じ時刻に複数銘柄で同じ局面が同時発生した場合、1件としてまとめ直した集計。結果は変わらず。"
    )
    supp_split = render_supplementary(
        results, "symbol_split_half_b", "銘柄ランダム半分割(補助検証)",
        "全銘柄をランダムに半分に分け、片方(下記の銘柄数)だけで全期間を再集計。時期で分けた検証と独立な確認だが、結果は同じ。"
    )

    html = f"""<title>潮目 局面検証レポート</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}</style>

<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 局面検証レポート</div>
    <h1>6つの局面ルールは、まだ使えるほどの根拠がない</h1>
    <p class="hero-sub">2022年〜2024年のデータで作った6つの市場局面ルールを、2025年以降の未知データで答え合わせした結果。</p>
    <div class="verdict-card">
      <div class="verdict-big">不合格</div>
      <div class="verdict-text">
        大型・中型アルト・小型/ミームのどのグループでも、6局面のうち<strong>2つ以上が合格</strong>という基準に届きませんでした。
        主指標の24時間後だけでなく、追加で確認した168時間後（7日後）でも同じく<strong>0局面</strong>でした。
      </div>
    </div>
    <div class="stat-row">
      <div class="stat-tile"><div class="label">対象銘柄</div><div class="value">100銘柄</div></div>
      <div class="stat-tile"><div class="label">検証期間</div><div class="value">2025年〜</div></div>
      <div class="stat-tile"><div class="label">シグナル件数</div><div class="value">{total_events:,}件</div></div>
      <div class="stat-tile"><div class="label">合格した局面</div><div class="value">{total_pass} / 18</div></div>
    </div>
  </header>

  <section>
    <h2>グループ別・局面別 成績表</h2>
    <p class="lede">
      「的中率」は局面発生後に予想方向へ動いた割合、「基準」はその銘柄群で無作為な時刻に取引した場合の的中率。
      「値幅」は方向込みの平均リターンから信頼区間の下限を使って判定し、「コスト」は往復手数料+出来高に応じたスリッページ。
      判定○は「的中率が統計的にはっきり基準を上回り、かつ値幅がコストを上回る」の両方を満たした場合。
    </p>
    {group_tables_html}
  </section>

  <section class="spotlight">
    <div class="eyebrow">注目ポイント</div>
    <h2>⑥圧縮は「値動きが縮む」方向に外れた</h2>
    <p>
      ⑥圧縮ルールは「値幅が縮んだ後は、その後の値動きが基準より大きくなる」という仮説でしたが、
      実際は逆でした。圧縮が起きた後の平均的な値動きは、全期間の平均（基準）より<strong>むしろ小さく</strong>なっていました。
      圧縮後に値幅が基準を上回った割合（的中率）も、24時間後で23〜38%、168時間後でも同水準にとどまり、
      五分五分の50%にすら届いていません。値幅そのものはコストを上回っていますが、これは暗号資産の値動きが
      そもそも往復0.1〜0.5%程度のコストよりずっと大きいためで、圧縮ルール固有の効果とは言えません。
    </p>
    {spotlight_chart_svg}
    <div class="legend">
      <span><span class="legend-swatch sw-baseline"></span>基準(全期間平均・24h)</span>
      <span><span class="legend-swatch sw-phase"></span>⑥圧縮後の平均値幅(24h)</span>
    </div>
    <div class="table-wrap" style="margin-top:18px;">
      <table>
        <thead><tr><th>グループ</th><th>基準24h</th><th>圧縮後24h</th><th>的中率24h</th><th>基準168h</th><th>圧縮後168h</th><th>的中率168h</th></tr></thead>
        <tbody>{spot_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>補助的な確認</h2>
    <p class="lede">主結果(答え合わせ期間・時系列で分割)以外に、2つの角度からも確認しましたが、結論は変わりませんでした。</p>
    <div class="supp-grid">{supp_dedup}{supp_split}</div>
  </section>

  <section>
    <h2>検証方法</h2>
    <div class="method-grid">
      <div class="method-card"><div class="k">ルール作り期間</div><div class="v">2022-01 〜 2024-12</div></div>
      <div class="method-card"><div class="k">答え合わせ期間</div><div class="v">2025-01 〜 現在</div></div>
      <div class="method-card"><div class="k">主指標(合格判定)</div><div class="v">24時間後</div></div>
      <div class="method-card"><div class="k">補助確認</div><div class="v">168時間後(7日)</div></div>
      <div class="method-card"><div class="k">しきい値の窓</div><div class="v">直近90日ローリング</div></div>
      <div class="method-card"><div class="k">信頼区間</div><div class="v">ブロック・ブートストラップ 95%</div></div>
      <div class="method-card"><div class="k">往復コスト</div><div class="v">手数料0.10% + 出来高連動スリッページ</div></div>
      <div class="method-card"><div class="k">重複排除</div><div class="v">局面開始の最初の1時間・24h以上の間隔</div></div>
    </div>
  </section>

  <section>
    <h2>自己チェック</h2>
    <ul class="check-list">
      <li><span class="check-icon">✓</span><span>先読み確認: BTC・ETH・現物なし銘柄(HYPE)でデータを途中で打ち切って再計算し、過去の判定が一切変わらないことを確認済み(真の不一致0件)。</span></li>
      <li><span class="check-icon">✓</span><span>グループ分けの先読み対策: 大型/中型/小型の区分けは、答え合わせ期間(2025年以降)を含まない2022〜2024年の出来高だけで再計算したものを使用。</span></li>
      <li><span class="check-icon">✓</span><span>上場廃止銘柄(31銘柄)を検証対象に含め、判定期間中に上場廃止した場合は最後の価格で強制決済したものとして損益に反映(生存者バイアス対策)。</span></li>
      <li><span class="check-icon">✓</span><span>判定と売買のタイミングを分離: 局面の判定はその足の終値まで、売買は次の足の始値から開始。</span></li>
    </ul>
  </section>

  <footer>
    潮目バックテスト検証ツール — データ取得: data.binance.vision (S3) / Binance Futures 公開データ。
    大型10銘柄・中型アルト40銘柄・小型/ミーム50銘柄、計100銘柄を対象。30件未満のサンプルは判定保留として扱い、合格判定には数えていません。
    この結果は現時点のルール定義・しきい値・期間に基づくものであり、ルールや前提を変えれば結果も変わり得ます。
  </footer>
</div>
"""

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"完了: {REPORT_PATH}")


if __name__ == "__main__":
    main()
