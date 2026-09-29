#!/usr/bin/env python3
"""イベントスタディ(逆引き分析)の結果を reports/event_study.html にまとめる。

先に scripts/run_event_study.py を実行しておくこと。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from build_report import CSS  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402
from shiome.eventstudy.combos import TEST_START, _design  # noqa: E402
from shiome.eventstudy.samples import FEATURE_NAMES, FEATURES, REFERENCE_FEATURES  # noqa: E402
from shiome.eventstudy.stats import decile_lift  # noqa: E402

ES_DIR = PROCESSED_DIR / "event_study"
REPORT_PATH = ROOT / "reports" / "event_study.html"
GROUP_LABELS = {"large_cap": "大型", "mid_cap_alt": "中型アルト", "small_meme": "小型・ミーム"}
DIR_LABELS = {"surge": "急騰", "crash": "急落"}
SHORT = {
    "spot_taker_ratio_24h": "現物CVD", "fut_taker_ratio_24h": "先物CVD", "oi_chg_pct_24h": "建玉変化",
    "funding_rate": "FR水準", "funding_rate_diff": "FR差", "trader_ratio_diff": "上位比率差",
    "spot_futures_price_diff_pct": "価格差", "past_ret_24h": "[参考]値動き", "past_range_24h": "[参考]値幅",
}


def single_ranking(single: pd.DataFrame, ext: pd.DataFrame, direction: str, cols: list[str]) -> list[dict]:
    """指標ごとに「水準の差」と「極端さの差」のうち強い方を採用し、効果の大きい順に並べる。"""
    out = []
    for col in cols:
        s = single[(single["direction"] == direction) & (single["feature"] == col)]
        e = ext[(ext["direction"] == direction) & (ext["feature"] == col)]
        best_shift = s.loc[s["effect"].idxmax()] if len(s) else None
        best_ext = e.loc[e["auc_all"].idxmax()] if len(e) else None
        shift_eff = best_shift["effect"] if best_shift is not None else 0
        ext_eff = (best_ext["auc_all"] - 0.5) if best_ext is not None else 0
        if ext_eff > shift_eff:
            stable = best_ext["min_year_auc"] > 0.5
            out.append({"col": col, "shape": "両端(高すぎ・低すぎ)で起きやすい", "offset": int(best_ext["offset_h"]),
                        "auc": best_ext["auc_all"], "effect": ext_eff, "stable": stable,
                        "stable_note": f"年別の最小AUC {best_ext['min_year_auc']:.3f}({int(best_ext['n_years'])}年分)"})
        else:
            higher = best_shift["auc"] > 0.5
            out.append({"col": col, "shape": "高いと起きやすい" if higher else "低いと起きやすい",
                        "offset": int(best_shift["offset_h"]), "auc": best_shift["auc"], "effect": shift_eff,
                        "stable": bool(best_shift["robust"]),
                        "stable_note": f"95%区間 {best_shift['auc_ci_lo']:.3f}〜{best_shift['auc_ci_hi']:.3f}"})
    out.sort(key=lambda r: r["effect"], reverse=True)
    for r in out:
        r["strength"] = "強め" if r["effect"] >= 0.08 else "中" if r["effect"] >= 0.05 else "弱い" if r["effect"] >= 0.02 else "ほぼ差なし"
    return out


def render_ranking(rows: list[dict]) -> str:
    trs = []
    for i, r in enumerate(rows, 1):
        mark = '<span class="mini-badge mini-pass">安定</span>' if r["stable"] else '<span class="mini-badge mini-no-data">不安定</span>'
        trs.append(f"""<tr><td class="num">{i}</td><td><div class="phase-name">{FEATURE_NAMES[r['col']]}</div>
          <div class="phase-dir">{r['shape']}</div></td><td class="num">{r['offset']}h前</td>
          <td class="num">{r['auc']:.3f}</td><td>{r['strength']}</td><td>{mark}<span class="vs">{r['stable_note']}</span></td></tr>""")
    return f"""<div class="table-wrap"><table class="rank-table"><thead><tr><th>順位</th><th>指標と形</th><th>時点</th>
      <th>AUC</th><th>差の強さ</th><th>安定性</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>"""


def lift_cell(v: float) -> str:
    if np.isnan(v):
        return '<td class="num lift">—</td>'
    strength = min(abs(v - 1) / 1.0, 1) * 70
    var = "--hot" if v > 1 else "--cold"
    return f'<td class="num lift" style="background: color-mix(in oklab, var({var}) {strength:.0f}%, transparent)">{v:.2f}</td>'


def render_lift_table(samples: pd.DataFrame, rows_spec: list[tuple[str, str, str]]) -> str:
    head = "".join(f"<th>{i}</th>" for i in range(1, 11))
    trs = []
    for col, direction, label in rows_spec:
        lift = decile_lift(samples, direction, col, 6)["lift"].to_numpy()
        trs.append(f"<tr><td class='lift-name'>{label}<span class='vs'>{DIR_LABELS[direction]}</span></td>{''.join(lift_cell(v) for v in lift)}</tr>")
    return f"""<div class="table-wrap"><table class="lift-table"><thead><tr><th>指標(6時間前)</th>{head}</tr></thead>
      <tbody>{''.join(trs)}</tbody></table></div>"""


def group_uplift(samples: pd.DataFrame) -> list[dict]:
    """大変動(急騰+急落)と普通の時点を見分けるAUCを、値幅だけ/値幅+αで比べる(2022-23年で学習→2024年で評価)。

    3つの指標が全て揃う同じ時点どうしで比べる。
    """
    test_ms = int(TEST_START.timestamp() * 1000)
    sets = [("値幅のみ", ("past_range_24h",)), ("値幅+FR", ("past_range_24h", "funding_rate")),
            ("値幅+建玉", ("past_range_24h", "oi_chg_pct_24h"))]
    need = [f"{c}__pct__t6" for c in ("past_range_24h", "funding_rate", "oi_chg_pct_24h")]
    out = []
    for g in [None, *GROUP_LABELS]:
        sub = samples if g is None else samples[samples["group"] == g]
        d = sub.dropna(subset=need)
        y = d["kind"].isin(["surge", "crash"])
        tr, te = d["open_time"] < test_ms, d["open_time"] >= test_ms
        row = {"group": g}
        for name, cols in sets:
            m = LogisticRegression(max_iter=1000).fit(_design(d[tr], cols, 6), y[tr])
            row[name] = roc_auc_score(y[te], m.predict_proba(_design(d[te], cols, 6))[:, 1])
        out.append(row)
    return out


CONDITIONS = [
    ("過去24hの値幅が上位10%(参考)", "past_range_24h", lambda v: v >= 90),
    ("建玉の24h変化率が上下10%", "oi_chg_pct_24h", lambda v: (v <= 10) | (v >= 90)),
    ("上位トレーダー比率差が上位10%", "trader_ratio_diff", lambda v: v >= 90),
    ("FR(水準)が上位10%", "funding_rate", lambda v: v >= 90),
    ("FR(水準)が下位10%", "funding_rate", lambda v: v <= 10),
    ("FR(水準)が40〜60(仮説C)", "funding_rate", lambda v: (v >= 40) & (v <= 60)),
]


def condition_table(samples: pd.DataFrame) -> str:
    """条件ごとに、大変動(急騰+急落)が普通の時点の何倍起きたかを、グループ別・年別に並べる。"""
    years = pd.to_datetime(samples["open_time"], unit="ms").dt.year

    def lift(sub: pd.DataFrame, col: str, cond, kinds=("surge", "crash")) -> float:
        c = f"{col}__pct__t6"
        ev = sub.loc[sub["kind"].isin(kinds), c].dropna()
        rd = sub.loc[sub["kind"] == "random", c].dropna()
        if len(ev) < 30 or len(rd) < 30:
            return np.nan
        base = cond(rd).mean()
        return cond(ev).mean() / base if base > 0 else np.nan

    trs = []
    for label, col, cond in CONDITIONS:
        cells = [lift(samples, col, cond)]
        cells += [lift(samples[samples["group"] == g], col, cond) for g in GROUP_LABELS]
        cells += [lift(samples[years == y], col, cond) for y in (2022, 2023, 2024)]
        trs.append(f"<tr><td class='lift-name'>{label}</td>{''.join(lift_cell(v) for v in cells)}</tr>")
    heads = "".join(f"<th>{h}</th>" for h in ["全体", *GROUP_LABELS.values(), "2022年", "2023年", "2024年"])
    return f"""<div class="table-wrap"><table class="lift-table"><thead><tr><th>条件(6時間前)</th>{heads}</tr></thead>
      <tbody>{''.join(trs)}</tbody></table></div>"""


def render_combo_table(combos: pd.DataFrame, direction: str, with_ref: bool, top: int = 5) -> str:
    t = combos[(combos["direction"] == direction) & (combos["uses_reference"] == with_ref)]
    t = t.sort_values("auc_test", ascending=False).head(top)
    trs = "".join(
        f"<tr><td>{' + '.join(SHORT[c] for c in r.features.split('|'))}</td><td class='num'>{r.offset_h}h前</td>"
        f"<td class='num'>{r.n_test_event:,}</td><td class='num'>{r.auc_test:.3f}</td></tr>"
        for r in t.itertuples())
    return f"""<table class="supp-table"><thead><tr><th>組み合わせ</th><th>時点</th><th>2024年の件数</th><th>AUC</th></tr></thead>
      <tbody>{trs}</tbody></table>"""


EXTRA_CSS = """
:root { --hot: #C2542D; --cold: #3F6FB0; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --hot: #E07A55; --cold: #6E9BD8; } }
:root[data-theme="dark"] { --hot: #E07A55; --cold: #6E9BD8; }
.verdict-card.neutral { background: var(--accent-soft); border-color: var(--accent); }
.verdict-card.neutral .verdict-big { color: var(--accent); font-size: 30px; }
.key-list { display: flex; flex-direction: column; gap: 12px; padding: 0; margin: 0; list-style: none; }
.key-list li { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; line-height: 1.7; }
.key-list li strong { color: var(--fg); }
.rank-table { min-width: 620px; }
.lift-table { min-width: 640px; }
.lift-table td.lift { text-align: center; font-size: 12.5px; padding: 8px 4px; }
.lift-table th { text-align: center; }
.lift-table th:first-child, .lift-name { text-align: left; white-space: nowrap; }
.lift-scale { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--fg-muted); margin-top: 10px; }
.lift-scale span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
.hyp { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.hyp h4 { margin-bottom: 6px; }
.hyp p { margin: 0; font-size: 14px; }
.hyp .tag { font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: var(--fg-muted); letter-spacing: .04em; }
.warn-icon { color: var(--warn); }
.hyp-grid, .quad-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 14px; }
.correction { margin-top: 14px; background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 12px; padding: 14px 18px; line-height: 1.7; font-size: 14px; }
.correction strong { display: block; color: var(--warn); margin-bottom: 4px; }
.stack-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
.stack-grid > *, .quad-grid > *, .hyp-grid > *, .supp-grid > * { min-width: 0; }
"""


def main() -> None:
    samples = pd.read_parquet(ES_DIR / "samples.parquet")
    single = pd.read_parquet(ES_DIR / "single.parquet")
    ext = pd.read_parquet(ES_DIR / "extremeness.parquet")
    combos = pd.read_parquet(ES_DIR / "combos.parquet")

    n_symbols = samples["symbol"].nunique()
    counts = samples["kind"].value_counts()
    deriv_cols = [c for c, _ in FEATURES]
    ref_cols = [c for c, _ in REFERENCE_FEATURES]

    rank_html = {}
    for d in DIR_LABELS:
        rank_html[d] = render_ranking(single_ranking(single, ext, d, deriv_cols))
        rank_html[d + "_ref"] = render_ranking(single_ranking(single, ext, d, ref_cols))

    lift_pooled = render_lift_table(samples, [
        ("funding_rate", "surge", "FR(水準)"), ("funding_rate", "crash", "FR(水準)"),
        ("funding_rate_diff", "surge", "FR(7日平均との差)"), ("funding_rate_diff", "crash", "FR(7日平均との差)"),
        ("oi_chg_pct_24h", "surge", "建玉の24h変化率"), ("oi_chg_pct_24h", "crash", "建玉の24h変化率"),
        ("trader_ratio_diff", "surge", "上位トレーダー比率−全体比率"), ("trader_ratio_diff", "crash", "上位トレーダー比率−全体比率"),
        ("fut_taker_ratio_24h", "surge", "先物CVD"), ("fut_taker_ratio_24h", "crash", "先物CVD"),
        ("past_range_24h", "surge", "[参考] 過去24hの値幅"), ("past_range_24h", "crash", "[参考] 過去24hの値幅"),
    ])
    small = samples[samples["group"] == "small_meme"]
    lift_small = render_lift_table(small, [
        ("funding_rate", "surge", "FR(水準)"), ("funding_rate", "crash", "FR(水準)"),
        ("funding_rate_diff", "surge", "FR(7日平均との差)"), ("funding_rate_diff", "crash", "FR(7日平均との差)"),
    ])

    uplift = group_uplift(samples)

    def plus(v: float) -> str:
        return f"{'+' if v >= 0 else ''}{v:.3f}"

    uplift_rows = "".join(
        f"<tr><td>{GROUP_LABELS.get(r['group'], '全体')}</td><td class='num'>{r['値幅のみ']:.3f}</td>"
        f"<td class='num'>{r['値幅+FR']:.3f}<span class='vs'>{plus(r['値幅+FR'] - r['値幅のみ'])}</span></td>"
        f"<td class='num'>{r['値幅+建玉']:.3f}<span class='vs'>{plus(r['値幅+建玉'] - r['値幅のみ'])}</span></td></tr>"
        for r in uplift)
    cond_html = condition_table(samples)

    html = f"""<title>潮目 逆引き分析</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>

<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 逆引き分析(イベントスタディ)</div>
    <h1>急騰・急落の直前に、何が起きていたか</h1>
    <p class="hero-sub">2022〜2024年(ルール作り期間)だけを使い、各銘柄の24時間値動きで上位5%・下位5%に入った「大イベント」の直前の指標を、普通の時点と比べた。2025年以降のデータは読み込んでいない。</p>
    <div class="verdict-card neutral">
      <div class="verdict-big">値幅以上の情報は無い</div>
      <div class="verdict-text">
        「上がるか下がるか」を教える指標はありませんでした。「大きく動く前兆」としていちばん強く安定していたのは、
        <strong>直前にすでに値動きが荒れていること</strong>(価格だけで分かる情報)でした。
        FR・建玉・上位トレーダー比率にも前兆らしい傾向はありますが、値幅と組み合わせても見分ける精度はほとんど上がりません。
      </div>
    </div>
    <div class="correction">
      <strong>前の版からの訂正</strong>
      上場廃止の前後などで取引が止まり、価格が動かない時間(出来高ゼロ)が「普通の時点」に混ざっていました。
      これを除いて集計し直したところ、前の版の「小型・ミームではFRが最も強い前兆」「FRが真ん中なら静か」という結論は、
      ほとんどがこの混入による見かけの効果でした(FRだけの見分け精度 0.72→0.60、FR40〜60の倍率 0.52→0.98)。
      以下はすべて除外後の数字です。
    </div>
    <div class="stat-row">
      <div class="stat-tile"><div class="label">対象銘柄</div><div class="value">{n_symbols}銘柄</div></div>
      <div class="stat-tile"><div class="label">急騰の直前</div><div class="value">{counts.get('surge', 0):,}件</div></div>
      <div class="stat-tile"><div class="label">急落の直前</div><div class="value">{counts.get('crash', 0):,}件</div></div>
      <div class="stat-tile"><div class="label">普通の時点</div><div class="value">{counts.get('random', 0):,}件</div></div>
    </div>
  </header>

  <section>
    <h2>わかったこと</h2>
    <ul class="key-list">
      <li><strong>方向を教える指標は無い。</strong>どの指標も、急騰の直前と急落の直前で同じ向きにずれていました。たとえばFRが上位10%のとき、急騰は約1.8倍、急落も約1.5倍で、どちらに動くかは分かりません。</li>
      <li><strong>いちばん強く安定した前兆は「直前の値幅」。</strong>過去24時間の値幅が上位10%のとき、大変動は普段の約2.0倍でした。大型・中型・小型のどれでも(1.8〜2.4倍)、2022〜2024年のどの年でも(1.7〜2.2倍)同じです。荒れた相場はさらに荒れやすい、というよく知られた性質です。</li>
      <li><strong>デリバティブ指標の前兆は弱いか、年によってぶれる。</strong>建玉変化が上下10%の極端なときは約1.3倍で小さいものの安定。上位トレーダー比率差が高いときは約1.5倍(データは2023年以降のみ)。FRが上位10%のときは平均1.6倍ですが、2022年は0.74倍(むしろ起きにくい)、2024年は2.27倍と年によって大きく変わりました。</li>
      <li><strong>値幅に足しても精度はほぼ上がらない。</strong>2022〜2023年で学習し2024年で見分け精度(AUC)を測ると、値幅だけ0.615に対し、値幅+FRは0.618、値幅+建玉は0.614でした。グループ別に見ても差は±0.01程度です。</li>
    </ul>
  </section>

  <section>
    <h2>指標ランキング(デリバティブ指標)</h2>
    <p class="lede">AUCは「イベント直前の値が、普通の時点の値より大きい(または極端な)確率」。0.5なら差なし、0.6なら中程度の差。
      各指標について「高い/低いと起きやすい」と「両端で起きやすい」の強い方、6・12・24時間前のうち最も差が大きい時点を載せています。
      「安定」は、週単位で再抽出した95%区間が0.5をまたがない、または3年とも同じ向きに差があることを示します。</p>
    <div class="stack-grid">
      <div class="supp-card"><h4>急騰の直前</h4>{rank_html['surge']}</div>
      <div class="supp-card"><h4>急落の直前</h4>{rank_html['crash']}</div>
    </div>
    <h3 style="margin-top:24px;margin-bottom:8px;">参考: 価格だけの指標</h3>
    <div class="stack-grid">
      <div class="supp-card"><h4>急騰の直前</h4>{rank_html['surge_ref']}</div>
      <div class="supp-card"><h4>急落の直前</h4>{rank_html['crash_ref']}</div>
    </div>
  </section>

  <section class="spotlight">
    <div class="eyebrow">10段階で見た起きやすさ</div>
    <h2>指標の高さ別に、急騰・急落が何倍起きていたか</h2>
    <p>各指標を銘柄ごとの過去90日の中での順位で10段階に分け(1=最も低い、10=最も高い)、それぞれの段階で大イベントが普通の時点の何倍起きていたかを示します。1.00が「普通と同じ」。両端が赤く真ん中が青い指標は「極端なときほど大きく動く」形です。</p>
    {lift_pooled}
    <div class="lift-scale"><span><i class="sw" style="background: color-mix(in oklab, var(--hot) 60%, transparent)"></i>普通より起きやすい</span>
      <span><i class="sw" style="background: color-mix(in oklab, var(--cold) 60%, transparent)"></i>普通より起きにくい</span></div>
    <h3 style="margin-top:22px;margin-bottom:8px;">小型・ミームだけで見たFR</h3>
    {lift_small}
  </section>

  <section>
    <h2>組み合わせのランキング</h2>
    <p class="lede">2〜3指標の組み合わせを、2022〜2023年のデータで重み付けを決め、2024年のデータで見分け精度(AUC)を測りました。
      数十通りの組み合わせから「たまたま良く見える」ものを選ばないための手順です(2024年もルール作り期間内)。</p>
    <div class="quad-grid">
      <div class="supp-card"><h4>急騰: デリバティブ指標のみ</h4>{render_combo_table(combos, 'surge', False)}</div>
      <div class="supp-card"><h4>急落: デリバティブ指標のみ</h4>{render_combo_table(combos, 'crash', False)}</div>
      <div class="supp-card"><h4>急騰: 価格指標も含む</h4>{render_combo_table(combos, 'surge', True)}</div>
      <div class="supp-card"><h4>急落: 価格指標も含む</h4>{render_combo_table(combos, 'crash', True)}</div>
    </div>
    <h3 style="margin-top:24px;margin-bottom:8px;">値幅に何を足すと精度が上がるか(大変動の見分け、6時間前・2024年で評価)</h3>
    <div class="table-wrap"><table><thead><tr><th>対象</th><th>値幅のみ</th><th>値幅+FR</th><th>値幅+建玉</th></tr></thead>
      <tbody>{uplift_rows}</tbody></table></div>
    <p class="lede" style="margin-top:10px;">各セルの下の小さい数字は「値幅のみ」からの増減。同じ時点どうしで比べています。</p>

    <h3 style="margin-top:24px;margin-bottom:8px;">条件ごとの大変動の起きやすさ(グループ別・年別)</h3>
    {cond_html}
  </section>

  <section>
    <h2>次の一手の選択肢</h2>
    <p class="lede">先に決めた仮説A・Cは、ルール作り期間の中ですら基準に届かなくなったため、答え合わせは実行していません(2025年以降のデータは未読)。答え合わせ期間は見るたびに価値が下がるので、何に使うかを決めてから進めます。</p>
    <div class="hyp-grid">
      <div class="hyp"><div class="tag">選択肢1</div><h4>ここで区切る</h4>
        <p>「24時間の大変動については、デリバティブ指標は直前の値幅以上の情報をほぼ持たない」を今回の結論とし、答え合わせ期間は温存する。</p></div>
      <div class="hyp"><div class="tag">選択肢2</div><h4>「嵐の予報」を値幅で答え合わせ</h4>
        <p>直前24時間の値幅が上位10%なら大変動が普段の1.5倍以上、を答え合わせする。価格だけの仮説で新しさはないが、「潮目」に確かな土台を1つ作れる。</p></div>
      <div class="hyp"><div class="tag">選択肢3</div><h4>建玉変化の極端 → 大変動</h4>
        <p>効果は約1.3倍と小さいが、グループ・年をまたいで最も安定したデリバティブ指標。値幅に上乗せが無い点は割り引いて考える必要がある。</p></div>
      <div class="hyp"><div class="tag">選択肢4(おすすめしない)</div><h4>事前登録したA・Cをそのまま答え合わせ</h4>
        <p>基準はコミット済みなので実行はできるが、ルール作り期間ですでにA 1.44倍(基準1.5倍)・C 0.98倍(基準0.7倍)で、不合格の見込みが高い。</p></div>
    </div>
  </section>

  <section>
    <h2>注意点</h2>
    <ul class="check-list">
      <li><span class="check-icon warn-icon">!</span><span>対象は2022〜2024年に、取引が成立していた時間が180日以上ある{n_symbols}銘柄です。2025年以降に上場した銘柄は含みません。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>上位トレーダー比率のデータは2023年以降しかなく、この指標だけ件数が少なめです。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>大きな相場変動は多くの銘柄で同じ週に起きます。p値はその分だけ甘く出るため、判定には週単位の再抽出による区間も使いました。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>AUC 0.6前後は「外れも多いが、偶然よりは当たる」程度です。これはルール作り期間の中だけの結果です。</span></li>
    </ul>
  </section>

  <footer>潮目バックテスト — 逆引き分析。大イベントは銘柄ごとに24時間後の値動きの上位5%・下位5%、始まりの1時間のみ(同じ銘柄・方向は24時間あける)。
    普通の時点は上位/下位5%以外から銘柄ごとにイベントと同数を無作為抽出。取引が止まっている時間(その時点か直前24時間に出来高ゼロ、またはその後24時間がまるごと出来高ゼロ)は除外。指標は銘柄ごとの過去90日パーセンタイル順位で比較。</footer>
</div>
"""
    REPORT_PATH.write_text(html, encoding="utf-8")
    print("完了:", REPORT_PATH)


if __name__ == "__main__":
    main()
