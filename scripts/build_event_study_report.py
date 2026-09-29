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
    test_ms = int(TEST_START.timestamp() * 1000)
    sets = [("値幅のみ", ("past_range_24h",)), ("FR差+FR水準", ("funding_rate_diff", "funding_rate")),
            ("値幅+FR差", ("past_range_24h", "funding_rate_diff"))]
    out = []
    for g in GROUP_LABELS:
        for d in DIR_LABELS:
            sub = samples[(samples["group"] == g) & samples["kind"].isin([d, "random"])]
            row = {"group": g, "direction": d}
            for name, cols in sets:
                dd = sub.dropna(subset=[f"{c}__pct__t6" for c in cols])
                tr, te = dd[dd["open_time"] < test_ms], dd[dd["open_time"] >= test_ms]
                m = LogisticRegression(max_iter=1000).fit(_design(tr, cols, 6), tr["kind"] == d)
                row[name] = roc_auc_score(te["kind"] == d, m.predict_proba(_design(te, cols, 6))[:, 1])
            out.append(row)
    return out


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
.stack-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
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
    uplift_rows = "".join(
        f"<tr><td>{GROUP_LABELS[r['group']]}</td><td>{DIR_LABELS[r['direction']]}</td>"
        f"<td class='num'>{r['値幅のみ']:.3f}</td><td class='num'>{r['FR差+FR水準']:.3f}</td>"
        f"<td class='num'>{r['値幅+FR差']:.3f}</td>"
        f"<td class='num'>{'+' if r['値幅+FR差'] - r['値幅のみ'] >= 0 else ''}{r['値幅+FR差'] - r['値幅のみ']:.3f}</td></tr>"
        for r in uplift)

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
      <div class="verdict-big">方向は×・前兆は○</div>
      <div class="verdict-text">
        「上がるか下がるか」を事前に教えてくれる指標は見つかりませんでした。一方で、
        <strong>「これから大きく動く(上か下かは問わない)」前兆</strong>ははっきり見えました。
        特に小型・ミームでは、FR(資金調達率)の極端さが最も強い前兆でした。
      </div>
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
      <li><strong>方向を教える指標は無い。</strong>急騰の直前と急落の直前で、どの指標もほぼ同じ方向にずれていました。例えばFRが極端に高いと急騰は約1.7倍、急落も約1.5倍起きやすく、どちらに動くかは分かりません。わずかに方向の手がかりになったのは先物CVD(急騰前にやや買い越し)だけで、差はごく小さいものでした。</li>
      <li><strong>「大きく動く前兆」は複数ある。</strong>FR(水準・7日平均との差)、建玉の変化率が上下どちらかに極端なとき、上位トレーダー比率差が高いときに、急騰も急落も1.3〜2倍起きやすくなっていました。2022・2023・2024年のどの年でも同じ傾向で、特定の年だけの現象ではありません。</li>
      <li><strong>最も強い前兆は「直前にすでに荒れていること」。</strong>参考として入れた「過去24時間の値幅」が上位10%のとき、急騰は約2.2倍、急落は約2.0倍でした。荒れた相場はさらに荒れやすい、というよく知られた性質です。デリバティブ指標の多くは、大型・中型ではこれ以上の情報をほとんど足しませんでした。</li>
      <li><strong>例外は小型・ミームのFR。</strong>小型・ミームでは、FRだけで2024年の見分け精度(AUC)が急騰0.72・急落0.67に達し、値幅だけ(0.67・0.60)を上回りました。逆にFRが普段どおり(真ん中の帯)のときは、大変動が普段の0.3〜0.5倍に減っていました。</li>
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
    <h3 style="margin-top:24px;margin-bottom:8px;">グループ別: FRは値幅に何を足すか(6時間前・2024年で評価)</h3>
    <div class="table-wrap"><table><thead><tr><th>グループ</th><th>方向</th><th>値幅のみ</th><th>FR差+FR水準</th><th>値幅+FR差</th><th>FRの上乗せ</th></tr></thead>
      <tbody>{uplift_rows}</tbody></table></div>
  </section>

  <section>
    <h2>次に答え合わせへ回す仮説の候補</h2>
    <p class="lede">どれも「上か下か」ではなく「大きく動くか」を予想する仮説です。売買の方向を決める道具ではなく、ポジションを小さくする・様子を見るといった判断の材料になります。</p>
    <div class="hyp-grid">
      <div class="hyp"><div class="tag">候補A・最有力</div><h4>小型・ミームのFR極端 → 大変動</h4>
        <p>小型・ミームで、FR(水準または7日平均との差)が過去90日の上位10%か下位10%にあるとき、24時間以内に上下どちらかの大変動(上位/下位5%級)が普段の約2倍起きる。</p></div>
      <div class="hyp"><div class="tag">候補B</div><h4>値幅+FRの「嵐の予報」</h4>
        <p>全グループで、直前24時間の値幅が上位20%、かつFRが上下10%の極端にあるとき、大変動が起きる率が普段より高い。</p></div>
      <div class="hyp"><div class="tag">候補C・逆側</div><h4>FR平常 → 静かな相場</h4>
        <p>FRが過去90日の真ん中あたり(40〜60%)にあるとき、24時間以内の大変動が普段より少ない(小型・ミームでは最も静かな帯で普段の0.3〜0.5倍)。「動かない日」を見分ける仮説。</p></div>
      <div class="hyp"><div class="tag">候補D・弱い</div><h4>大型・中型のFR上位 → 急騰寄り</h4>
        <p>大型・中型でFRが上位10%のとき、急騰(約1.6〜1.7倍)の方が急落(約1.3〜1.5倍)より起きやすい。差は小さく、方向の仮説としては最も弱い。</p></div>
    </div>
  </section>

  <section>
    <h2>注意点</h2>
    <ul class="check-list">
      <li><span class="check-icon warn-icon">!</span><span>対象は2022〜2024年に180日以上のデータがある{n_symbols}銘柄です。2025年以降に上場した銘柄は含みません。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>上位トレーダー比率のデータは2023年以降しかなく、この指標だけ件数が少なめです。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>大きな相場変動は多くの銘柄で同じ週に起きます。p値はその分だけ甘く出るため、判定には週単位の再抽出による区間も使いました。</span></li>
      <li><span class="check-icon warn-icon">!</span><span>AUC 0.6〜0.7は「外れも多いが、偶然よりは明らかに当たる」程度です。これはまだルール作り期間の中だけの結果で、2025年以降での答え合わせは済んでいません。</span></li>
    </ul>
  </section>

  <footer>潮目バックテスト — 逆引き分析。大イベントは銘柄ごとに24時間後の値動きの上位5%・下位5%、始まりの1時間のみ(同じ銘柄・方向は24時間あける)。
    普通の時点は上位/下位5%以外から銘柄ごとにイベントと同数を無作為抽出。指標は銘柄ごとの過去90日パーセンタイル順位で比較。</footer>
</div>
"""
    REPORT_PATH.write_text(html, encoding="utf-8")
    print("完了:", REPORT_PATH)


if __name__ == "__main__":
    main()
