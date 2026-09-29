#!/usr/bin/env python3
"""第2ラウンド(銘柄間の比較)のHTMLレポートを作る。

入力: data/processed/crosssection/results_final.json(なければ results_dev.json)と panel_*.parquet
出力: reports/cross_section.html

実行例:
    python scripts/build_cross_section_report.py
"""
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from build_report import CSS  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402
from shiome.crosssection.evaluate import SIGNALS  # noqa: E402

CS_DIR = PROCESSED_DIR / "crosssection"
OUT = ROOT / "reports" / "cross_section.html"
HZ = ["24h", "7d", "28d"]
HZ_LABEL = {"24h": "24時間後", "7d": "7日後", "28d": "28日後"}
GROUP_LABEL = {"large_cap": "大型", "mid_cap_alt": "中型アルト", "small_meme": "小型・ミーム"}
HYPS = ["H1", "H2-7", "H2-14", "H2-28", "H3", "H4", "H5", "H6"]
SET_LABEL = {"full": "全銘柄(本番)", "set61": "第1ラウンドの61銘柄(参考)"}

EXTRA_CSS = """
.verdict-card.neutral { background: var(--accent-soft); border-color: var(--accent); }
.verdict-card.neutral .verdict-big { color: var(--accent); }
.verdict-card.good { background: var(--good-soft); border-color: var(--good); }
.verdict-card.good .verdict-big { color: var(--good); }
.win { font-family: 'IBM Plex Mono', monospace; font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.win.up { color: var(--good); } .win.down { color: var(--bad); } .win.flat { color: var(--fg-muted); }
.ci { display: block; font-size: 11px; color: var(--fg-faint); font-family: 'IBM Plex Mono', monospace; }
.pos { color: var(--good); } .neg { color: var(--bad); }
.hyp-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin-bottom: 18px; }
.hyp-card h3 { margin-bottom: 4px; }
.hyp-card .sub { color: var(--fg-muted); font-size: 13.5px; margin: 0 0 12px; }
.hyp-card table { min-width: 680px; }
.key-list { display: flex; flex-direction: column; gap: 12px; padding: 0; margin: 0; list-style: none; }
.key-list li { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; line-height: 1.7; }
.read-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 250px), 1fr)); gap: 14px; }
.read-grid > * { min-width: 0; }
.read-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; line-height: 1.7; font-size: 14px; }
.read-card strong { display: block; font-size: 15px; margin-bottom: 4px; }
.tag-cand { background: var(--good-soft); color: var(--good); }
.tag-no { background: var(--surface-2); color: var(--fg-faint); }
.period-sep td { border-top: 2px solid var(--border); }
details summary { cursor: pointer; color: var(--accent); font-size: 14px; margin: 8px 0; }
.note { font-size: 13px; color: var(--fg-muted); line-height: 1.7; }
"""


def g(d: dict, *keys, default=np.nan):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def fmt_win(v: float, lo: float = np.nan, hi: float = np.nan, ci: bool = True) -> str:
    if v is None or np.isnan(v):
        return "<span class='win flat'>—</span>"
    cls = "up" if v > 0.5 else ("down" if v < 0.5 else "flat")
    s = f"<span class='win {cls}'>{v * 100:.1f}%</span>"
    if ci and not np.isnan(lo):
        s += f"<span class='ci'>{lo * 100:.0f}〜{hi * 100:.0f}%</span>"
    return s


def fmt_ic(v: float, lo: float = np.nan, hi: float = np.nan) -> str:
    if v is None or np.isnan(v):
        return "—"
    cls = "pos" if v > 0 else "neg"
    s = f"<span class='{cls}'>{v:+.3f}</span>"
    if not np.isnan(lo):
        s += f"<span class='ci'>{lo:+.3f}〜{hi:+.3f}</span>"
    return s


def fmt_pct(v: float, digits: int = 3) -> str:
    if v is None or np.isnan(v):
        return "—"
    cls = "pos" if v > 0 else "neg"
    return f"<span class='{cls}'>{v * 100:+.{digits}f}%</span>"


def is_candidate(r: dict, hyp: str, hz: str) -> bool:
    a, b = g(r, hyp, "all", hz, "2022-23"), g(r, hyp, "all", hz, "2024")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    try:
        return bool(a["ic"] > 0 and b["ic"] > 0 and a["win"] > 0.5 and b["win"] > 0.5
                    and a["pf_net"] > 0 and b["pf_net"] > 0)
    except KeyError:
        return False


def summary_table(r: dict, periods: list[str], has_2024: bool) -> str:
    rows = []
    for hyp in HYPS:
        if hyp not in r:
            continue
        for i, hz in enumerate(HZ):
            a = g(r, hyp, "all", hz, "2022-23", default={})
            b = g(r, hyp, "all", hz, "2024", default={})
            cand = is_candidate(r, hyp, hz)
            badge = ("<span class='badge tag-cand'>候補</span>" if cand else "<span class='badge tag-no'>—</span>") if has_2024 else ""
            name = f"<td rowspan=3><div class='phase-name'>{hyp}</div><div class='phase-dir'>{escape(SIGNALS[hyp][2])}</div></td>" if i == 0 else ""
            sep = " class='period-sep'" if i == 0 else ""
            rows.append(
                f"<tr{sep}>{name}<td>{HZ_LABEL[hz]}</td>"
                f"<td class='num'>{fmt_win(g(a, 'win'), ci=False)}</td><td class='num'>{fmt_win(g(b, 'win'), ci=False)}</td>"
                f"<td class='num'>{fmt_ic(g(a, 'ic'))}</td><td class='num'>{fmt_ic(g(b, 'ic'))}</td>"
                f"<td class='num'>{fmt_pct(g(a, 'pf_net'))}</td><td class='num'>{fmt_pct(g(b, 'pf_net'))}</td>"
                f"<td class='center'>{badge}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>仮説</th><th>比べる期間</th><th>勝率<br>2022〜23</th><th>勝率<br>2024</th>
<th>順位の相関<br>2022〜23</th><th>順位の相関<br>2024</th><th>コスト込み<br>(1日あたり)<br>2022〜23</th><th>コスト込み<br>(1日あたり)<br>2024</th><th>答え合わせ<br>候補</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def hyp_detail(r: dict, hyp: str, periods: list[str]) -> str:
    rows = []
    for hz in HZ:
        for j, per in enumerate(periods):
            a = g(r, hyp, "all", hz, per, default={})
            sep = " class='period-sep'" if j == 0 else ""
            per_label = {"2022-23": "2022〜23", "2024": "2024(確認)"}.get(per, per)
            rows.append(
                f"<tr{sep}><td>{HZ_LABEL[hz] if j == 0 else ''}</td><td>{per_label}</td>"
                f"<td class='num'>{fmt_win(g(a, 'win'), g(a, 'win_lo'), g(a, 'win_hi'))}</td>"
                f"<td class='num'>{fmt_ic(g(a, 'ic'), g(a, 'ic_lo'), g(a, 'ic_hi'))}</td>"
                f"<td class='num'>{fmt_pct(g(a, 'pf_gross'))}</td><td class='num'>{fmt_pct(-g(a, 'pf_cost'))}</td>"
                f"<td class='num'>{fmt_pct(g(a, 'pf_net'))}</td><td class='num'>{fmt_pct(g(a, 'pf_net_carry'))}</td>"
                f"<td class='num'>{g(a, 'n_days', default=0)}<span class='ci'>重ならない {g(a, 'n_independent', default=0)}</span></td>"
                f"<td class='num'>{g(a, 'avg_n', default=0):.0f}</td></tr>")
    group_rows = []
    for grp, label in GROUP_LABEL.items():
        for i, hz in enumerate(HZ):
            a = g(r, hyp, "groups", grp, hz, "2022-23", default={})
            b = g(r, hyp, "groups", grp, hz, "2024", default={})
            sep = " class='period-sep'" if i == 0 else ""
            group_rows.append(
                f"<tr{sep}><td>{label if i == 0 else ''}</td><td>{HZ_LABEL[hz]}</td>"
                f"<td class='num'>{fmt_win(g(a, 'win'), g(a, 'win_lo'), g(a, 'win_hi'))}</td><td class='num'>{fmt_win(g(b, 'win'), g(b, 'win_lo'), g(b, 'win_hi'))}</td>"
                f"<td class='num'>{fmt_ic(g(a, 'ic'))}</td><td class='num'>{fmt_ic(g(b, 'ic'))}</td>"
                f"<td class='num'>{fmt_pct(g(a, 'pf_net'))}</td><td class='num'>{fmt_pct(g(b, 'pf_net'))}</td>"
                f"<td class='num'>{g(a, 'avg_n', default=0):.0f}</td></tr>")
    return f"""<div class="hyp-card"><h3>{hyp}: {escape(SIGNALS[hyp][2])}</h3>
<div class="table-wrap"><table>
<thead><tr><th>比べる期間</th><th>年</th><th>勝率<span class='vs'>95%の幅</span></th><th>順位の相関<span class='vs'>95%の幅</span></th>
<th>コスト前<span class='vs'>1日あたり</span></th><th>コスト</th><th>コスト込み</th><th>FR込み<span class='vs'>参考</span></th><th>日数</th><th>平均銘柄数</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<details><summary>グループ別に見る(グループの中だけで並べ直した結果)</summary>
<div class="table-wrap"><table>
<thead><tr><th>グループ</th><th>比べる期間</th><th>勝率 2022〜23</th><th>勝率 2024</th><th>相関 2022〜23</th><th>相関 2024</th><th>コスト込み 2022〜23</th><th>コスト込み 2024</th><th>平均銘柄数</th></tr></thead>
<tbody>{''.join(group_rows)}</tbody></table></div></details></div>"""


def bench_table(r: dict) -> str:
    rows = []
    for hyp in ("H1", "H4", "H6"):
        if hyp not in r:
            continue
        for i, hz in enumerate(HZ):
            cells = []
            for per in ("2022-23", "2024"):
                b = g(r, hyp, "bench", hz, per, default={})
                cells.append(f"<td class='num'>{fmt_ic(g(b, 'alone'), g(b, 'alone_lo'), g(b, 'alone_hi'))}</td>"
                             f"<td class='num'>{fmt_ic(g(b, 'controlled'), g(b, 'controlled_lo'), g(b, 'controlled_hi'))}</td>")
            name = f"<td rowspan=3><div class='phase-name'>{hyp}</div></td>" if i == 0 else ""
            sep = " class='period-sep'" if i == 0 else ""
            rows.append(f"<tr{sep}>{name}<td>{HZ_LABEL[hz]}</td>{''.join(cells)}</tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>仮説</th><th>比べる期間</th><th>単独<span class='vs'>2022〜23</span></th><th>物差し込み<span class='vs'>2022〜23</span></th>
<th>単独<span class='vs'>2024</span></th><th>物差し込み<span class='vs'>2024</span></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def selection_table(results: dict) -> str:
    full, s61 = results.get("full", {}), results.get("set61", {})
    rows = []
    for hyp in HYPS:
        if hyp not in full or hyp not in s61:
            continue
        for i, hz in enumerate(HZ):
            cells = []
            for per in ("2022-23", "2024"):
                a, b = g(full, hyp, "all", hz, per, default={}), g(s61, hyp, "all", hz, per, default={})
                cells.append(f"<td class='num'>{fmt_win(g(a, 'win'), ci=False)}</td><td class='num'>{fmt_win(g(b, 'win'), ci=False)}</td>"
                             f"<td class='num'>{fmt_ic(g(a, 'ic'))}</td><td class='num'>{fmt_ic(g(b, 'ic'))}</td>")
            name = f"<td rowspan=3><div class='phase-name'>{hyp}</div></td>" if i == 0 else ""
            sep = " class='period-sep'" if i == 0 else ""
            rows.append(f"<tr{sep}>{name}<td>{HZ_LABEL[hz]}</td>{''.join(cells)}</tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>仮説</th><th>比べる期間</th>
<th>勝率 全銘柄<span class='vs'>2022〜23</span></th><th>勝率 61銘柄<span class='vs'>2022〜23</span></th><th>相関 全銘柄<span class='vs'>2022〜23</span></th><th>相関 61銘柄<span class='vs'>2022〜23</span></th>
<th>勝率 全銘柄<span class='vs'>2024</span></th><th>勝率 61銘柄<span class='vs'>2024</span></th><th>相関 全銘柄<span class='vs'>2024</span></th><th>相関 61銘柄<span class='vs'>2024</span></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def universe_stats(mode: str) -> dict:
    out = {}
    for set_name in ("full", "set61"):
        path = CS_DIR / f"panel_{mode}_{set_name}_base.parquet"
        if not path.exists():
            continue
        p = pd.read_parquet(path, columns=["t", "symbol", "eligible", "reason"])
        e = p[p["eligible"]]
        per_day = e.groupby("t").size()
        out[set_name] = {
            "n_symbols": int(p["symbol"].nunique()), "n_eligible_symbols": int(e["symbol"].nunique()),
            "median_by_year": {int(y): int(v) for y, v in per_day.groupby(per_day.index.year).median().items()},
            "reasons": {k: int(v) for k, v in p["reason"].value_counts().items()},
        }
    return out


def main() -> None:
    final = CS_DIR / "results_final.json"
    mode = "final" if final.exists() else "dev"
    results = json.loads((final if mode == "final" else CS_DIR / "results_dev.json").read_text(encoding="utf-8"))
    has_2024 = mode == "final"
    periods = ["2022", "2023", "2022-23"] + (["2024"] if has_2024 else [])
    full = results.get("full", {})
    cands = [(h, hz) for h in HYPS if h in full for hz in HZ if is_candidate(full, h, hz)] if has_2024 else []
    ustats = universe_stats(mode)

    if cands:
        verdict_cls, verdict_big = "good", f"{len(cands)}件"
        cand_txt = "、".join(f"<strong>{h}({HZ_LABEL[hz]})</strong>" for h, hz in cands)
        verdict_txt = (f"2022〜23年と2024年の両方で予想どおりの向きに効き、コストを引いてもプラスだったのは {cand_txt}。"
                       "ただし24通りを試した中での結果なので、2025年以降での答え合わせを通るまでは「使える」とは言えない。")
    else:
        verdict_cls, verdict_big = "neutral", "0件"
        verdict_txt = ("2022〜23年と2024年の両方で予想どおりの向きに効き、かつコストを引いてもプラス、という条件を満たした仮説は無かった。"
                       if has_2024 else "(2024年を含めた計算はまだ。2022〜23年だけの途中経過)")
    missing = [h for h in HYPS if h not in full]
    missing_note = f"<p class='note'>まだ計算していない仮説: {', '.join(missing)}</p>" if missing else ""

    details = "".join(hyp_detail(full, h, periods) for h in HYPS if h in full)
    fu = ustats.get("full", {})
    s6 = ustats.get("set61", {})
    reason_rows = "".join(f"<tr><td>{escape(k)}</td><td class='num'>{v:,}</td><td class='num'>{s6.get('reasons', {}).get(k, 0):,}</td></tr>"
                          for k, v in fu.get("reasons", {}).items())
    med = " / ".join(f"{y}年 {v}" for y, v in fu.get("median_by_year", {}).items())
    med61 = " / ".join(f"{y}年 {v}" for y, v in s6.get("median_by_year", {}).items())

    html = f"""<title>潮目 銘柄間比較</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 第2ラウンド: 銘柄間の比較</div>
    <h1>どの銘柄が、他より上がりやすいか</h1>
    <p class="hero-sub">毎日UTC0時に全銘柄を1つの数値で並べ、上位20%と下位20%のその後の値動きを比べた。2022〜23年で形を作り、2024年は1回だけ確認。2025年以降のデータは読み込んでいない。</p>
    <div class="verdict-card {verdict_cls}"><div class="verdict-big">{verdict_big}</div>
      <div class="verdict-text"><strong>答え合わせ候補</strong><br>{verdict_txt}</div></div>
  </header>

  <section>
    <h2>数字の読み方</h2>
    <div class="read-grid">
      <div class="read-card"><strong>勝率(いちばん大事)</strong>毎日「良くなると予想した側」と「悪くなると予想した側」の平均を比べ、予想した側が勝った日の割合。でたらめに選べば50%前後になる。<span class="pos">緑</span>=50%超、<span class="neg">赤</span>=50%未満。</div>
      <div class="read-card"><strong>順位の相関</strong>並べた順位と、その後の値動きの順位がどれだけ揃ったか(−1〜+1)。予想どおりならプラス。0.02〜0.05でも毎日積み重なれば意味があることがあるが、小さい数字は偶然でも出る。下の小さい数字は95%の幅で、0をまたいでいれば「偶然と区別できない」。</div>
      <div class="read-card"><strong>コスト込み(1日あたり)</strong>良い側を買い・悪い側を売る組み合わせを実際に作ったとして、手数料と注文時の不利な価格ずれ(出来高が少ない銘柄ほど大きい)を引いた損益。+0.01%/日で年およそ+3.7%。FR込みは持ち高にかかる資金調達料も足した参考値。</div>
    </div>
  </section>

  <section>
    <h2>全体の一覧(全銘柄・本番)</h2>
    <p class="lede">答え合わせ候補の条件: 2022〜23年と2024年の両方で「相関がプラス」「勝率50%超」「コスト込みがプラス」。</p>
    {summary_table(full, periods, has_2024)}
    {missing_note}
  </section>

  <section>
    <h2>仮説ごとの詳しい結果(全銘柄・本番)</h2>
    <p class="lede">7日後・28日後は毎日の組が重なる(隣の日とほとんど同じ期間を比べている)ため、実際に独立した回数は「重ならない」の数くらいしかない。</p>
    {details}
  </section>

  <section>
    <h2>物差しと比べて上乗せがあるか(H1・H4・H6)</h2>
    <p class="lede">FR・建玉・先物/現物比が、単に「最近上がった銘柄」「値動きの激しい銘柄」を言い換えているだけではないかを確かめる。毎日、その後の値動きの順位を「調べたい数値」と物差し(過去7・14・28日と24時間の値動き、24時間の値幅)で同時に説明し、調べたい数値の効き目(予想どおりならプラス)が物差しを入れても残るかを見る。</p>
    {bench_table(full)}
  </section>

  <section>
    <h2>銘柄の選び方で結果はどれだけ変わったか</h2>
    <p class="lede">第1ラウンドの銘柄リスト(2026年に出来高が多い銘柄が中心)の61銘柄だけで同じ計算をした結果と並べる。差が大きいほど、銘柄の選び方(生き残りバイアス)が結果をゆがめていたことになる。</p>
    {selection_table(results)}
  </section>

  <section>
    <h2>データと比較対象</h2>
    <ul class="key-list">
      <li>全銘柄: 2022〜2024年にBinance先物にあったUSDT建て銘柄 {fu.get('n_symbols', '—')}(上場廃止を含む。指数先物4つは除外)。1日でも比較対象になったのは {fu.get('n_eligible_symbols', '—')}銘柄。1日あたりの比較対象の中央値: {med}。</li>
      <li>61銘柄(参考): 1日あたりの比較対象の中央値: {med61}。</li>
      <li>比較対象の条件: 過去30日の1日平均出来高が500万ドル以上、直前24時間に出来高ゼロの時間が無い、先物上場から7日以上。その時点までのデータだけで判定。</li>
    </ul>
    <div class="table-wrap" style="margin-top:14px"><table class="supp-table">
      <thead><tr><th>判定(銘柄×日の数)</th><th>全銘柄</th><th>61銘柄</th></tr></thead><tbody>{reason_rows}</tbody></table></div>
  </section>

  <section>
    <h2>試した回数</h2>
    <p>候補の判定に使う組み合わせは24通り(並べ方8通り×期間3通り)。何も効いていなくても、5%の偶然で1つ前後は「効いて見える」ものが出る回数。条件と記録は <code>docs/hypotheses_v2.md</code>。</p>
  </section>

  <footer>作成: scripts/build_cross_section_report.py ／ 計算: scripts/run_cross_section.py({mode}) ／ 2025年以降のデータは読み込んでいない。</footer>
</div>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
