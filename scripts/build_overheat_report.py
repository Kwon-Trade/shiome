#!/usr/bin/env python3
"""ラウンドB(H17「過熱ショート」)のHTMLレポートを作る。

入力: data/processed/crosssection/overheat[_long]_final_full.json(なければ dev)
出力: reports/overheat_short.html(H17) / reports/overheat_long.html(H17L)

実行例:
    python scripts/build_overheat_report.py          # H17 過熱ショート
    python scripts/build_overheat_report.py long     # H17L 過熱ロング
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from build_cross_section_report import EXTRA_CSS, fmt_win, g  # noqa: E402
from build_report import CSS  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402

CS_DIR = PROCESSED_DIR / "crosssection"
SIDE = "long" if len(sys.argv) > 1 and sys.argv[1] == "long" else "short"
OUT = ROOT / "reports" / ("overheat_long.html" if SIDE == "long" else "overheat_short.html")
PREFIX = "overheat_long" if SIDE == "long" else "overheat"
KIND = ({"1": "① すぐ買う", "2": "② 下げ止まりを確認してから"} if SIDE == "long"
        else {"1": "① すぐ空売り", "2": "② 失速を確認してから"})
HOLD = {"24h": "24時間持つ", "7d": "7日持つ"}
STOP = {"nostop": "損切りなし", "stop": "−15%で損切り" if SIDE == "long" else "+15%で損切り"}
SQUEEZE = "−30%以上<br>の下げ" if SIDE == "long" else "+30%<br>踏み上げ"
BASE = "全銘柄平均を<br>買った場合との差" if SIDE == "long" else "全銘柄平均の<br>空売りとの差"
VARIANTS = [f"{k}|{h}|{s}" for k in KIND for h in HOLD for s in STOP]
PER_LABEL = {"2022": "2022", "2023": "2023", "2022-23": "2022〜23", "2024": "2024(確認)"}


def label(key: str) -> str:
    k, h, s = key.split("|")[:3]
    return f"{KIND[k]}<span class='vs'>{HOLD[h]}・{STOP[s]}</span>"


def p(v, d: int = 2, sign: bool = True) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    cls = "pos" if v > 0 else "neg"
    return f"<span class='{cls}'>{v * 100:{'+' if sign else ''}.{d}f}%</span>"


def ci(lo, hi) -> str:
    if lo is None or np.isnan(lo):
        return ""
    return f"<span class='ci'>{lo * 100:+.2f}〜{hi * 100:+.2f}%</span>"


def is_candidate(res: dict, key: str) -> bool:
    a = g(res, "periods", "2022-23", "variants", key, default={})
    b = g(res, "periods", "2024", "variants", key, default={})
    try:
        return all(x["n"] >= 30 and x["win"] > 0.5 and x["pnl"] > 0 and x["diff"] > 0 for x in (a, b))
    except KeyError:
        return False


def main_table(res: dict, periods: list[str], has_2024: bool) -> str:
    rows = []
    for key in VARIANTS:
        for j, per in enumerate(periods):
            v = g(res, "periods", per, "variants", key, default={})
            sep = " class='period-sep'" if j == 0 else ""
            cand = ""
            if j == 0 and has_2024:
                cand = "<span class='badge tag-cand'>候補</span>" if is_candidate(res, key) else "<span class='badge tag-no'>—</span>"
            rows.append(
                f"<tr{sep}><td>{label(key) if j == 0 else ''}</td><td>{PER_LABEL[per]}</td>"
                f"<td class='num'>{g(v, 'n', default=0)}</td>"
                f"<td class='num'>{fmt_win(g(v, 'win'), ci=False)}</td>"
                f"<td class='num'>{p(g(v, 'avg_win'))} / {p(g(v, 'avg_loss'))}</td>"
                f"<td class='num'>{p(g(v, 'pnl'))}{ci(g(v, 'pnl_lo'), g(v, 'pnl_hi'))}</td>"
                f"<td class='num'>{p(g(v, 'pnl_fr'))}</td>"
                f"<td class='num'>{p(g(v, 'diff'))}{ci(g(v, 'diff_lo'), g(v, 'diff_hi'))}</td>"
                f"<td class='num'>{p(g(v, 'mae_mean'), 1)} / {p(g(v, 'mae_median'), 1)} / {p(g(v, 'mae_max'), 0)}</td>"
                f"<td class='num'>{g(v, 'squeeze_n', default=0)}<span class='ci'>{g(v, 'squeeze_rate', default=0) * 100:.1f}%</span></td>"
                f"<td class='center'>{cand}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>入り方</th><th>年</th><th>件数</th><th>勝率</th><th>平均の勝ち / 負け</th><th>平均損益<span class='vs'>コスト込み</span></th>
<th>FR込み</th><th>{BASE}</th><th>最大逆行<span class='vs'>平均 / 中央値 / 最大</span></th><th>{SQUEEZE}</th><th>候補</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def liq_table(res: dict, periods: list[str]) -> str:
    rows = []
    for per in periods:
        for j, side in enumerate(("near", "far")):
            v = g(res, "liq", per, side, default={})
            sep = " class='period-sep'" if j == 0 else ""
            rows.append(
                f"<tr{sep}><td>{PER_LABEL[per] if j == 0 else ''}</td><td>{'近い' if side == 'near' else '遠い'}</td>"
                f"<td class='num'>{g(v, 'n', default=0)}</td><td class='num'>{p(g(v, 'mfe_mean'), 1, sign=False)}</td>"
                f"<td class='num'>{fmt_win(g(v, 'win'), ci=False)}</td><td class='num'>{p(g(v, 'pnl'))}{ci(g(v, 'pnl_lo'), g(v, 'pnl_hi'))}</td>"
                f"<td class='num'>{p(g(v, 'diff'))}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>年</th><th>推定清算価格帯</th><th>件数</th><th>下げの深さ<span class='vs'>持っている間の最大の下げ・平均</span></th><th>勝率</th><th>平均損益</th><th>全銘柄平均との差</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def flow_table(res: dict, periods: list[str]) -> str:
    rows = []
    for per in periods:
        r = g(res, "periods", per, default={})
        n_j, n_2 = g(r, "n_judgeable", default=0), g(r, "n_entry2", default=0)
        sk = g(r, "reference", "skipped_by_2|1|7d|nostop", default={})
        ref = g(r, "reference", "1|7d|nostop|judgeable", default={})
        rows.append(
            f"<tr><td>{PER_LABEL[per]}</td><td class='num'>{g(r, 'n_events', default=0)}</td><td class='num'>{n_j}</td>"
            f"<td class='num'>{n_2}<span class='ci'>見送り {n_j - n_2}</span></td>"
            f"<td class='num'>{fmt_win(g(ref, 'win'), ci=False)} ・ {p(g(ref, 'pnl'))}</td>"
            f"<td class='num'>{g(sk, 'n', default=0)}件 ・ {p(g(sk, 'pnl'))}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>年</th><th>きっかけ</th><th>②を判定できた</th><th>②で空売りした</th><th>①(②を判定できたものだけ)<span class='vs'>7日・損切りなし: 勝率・平均損益</span></th>
<th>②が見送ったものを①で売っていたら<span class='vs'>7日・損切りなし</span></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def storm_table(res: dict, periods: list[str]) -> str:
    rows = []
    for key in VARIANTS:
        for j, per in enumerate([x for x in periods if x in ("2022-23", "2024")]):
            r = g(res, "storm", per, key, default={})
            for side, name in (("storm", "荒れ予報あり"), ("calm", "なし")):
                v = g(r, side, default={})
                first = j == 0 and side == "storm"
                sep = " class='period-sep'" if first else ""
                rows.append(
                    f"<tr{sep}><td>{label(key) if first else ''}</td><td>{PER_LABEL[per] if side == 'storm' else ''}</td><td>{name}</td>"
                    f"<td class='num'>{g(v, 'n', default=0)}</td><td class='num'>{fmt_win(g(v, 'win'), ci=False)}</td>"
                    f"<td class='num'>{p(g(v, 'avg_win'))} / {p(g(v, 'avg_loss'))}</td><td class='num'>{p(g(v, 'pnl'))}</td>"
                    f"<td class='num'>{p(g(v, 'mae_mean'), 1)} / {p(g(v, 'mae_median'), 1)} / {p(g(v, 'mae_max'), 0)}</td>"
                    f"<td class='num'>{g(v, 'squeeze_n', default=0)}<span class='ci'>{g(v, 'squeeze_rate', default=0) * 100:.1f}%</span></td>"
                    f"<td class='num'>{p(g(v, 'diff'))}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>入り方</th><th>年</th><th>売る時点</th><th>件数</th><th>勝率</th><th>平均の勝ち / 負け</th><th>平均損益</th>
<th>最大逆行<span class='vs'>平均 / 中央値 / 最大</span></th><th>+30%<br>踏み上げ</th><th>全銘柄平均との差</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def short_liq_table(res: dict, periods: list[str]) -> str:
    rows = []
    for per in periods:
        for j, side in enumerate(("near", "far")):
            v = g(res, "short_liq", per, side, default={})
            vs = g(res, "short_liq", per, side + "_stop", default={})
            sep = " class='period-sep'" if j == 0 else ""
            rows.append(
                f"<tr{sep}><td>{PER_LABEL[per] if j == 0 else ''}</td><td>{'多い' if side == 'near' else '少ない'}</td>"
                f"<td class='num'>{g(v, 'n', default=0)}</td>"
                f"<td class='num'>{g(v, 'squeeze_n', default=0)}<span class='ci'>{g(v, 'squeeze_rate', default=0) * 100:.1f}%</span></td>"
                f"<td class='num'>{p(g(v, 'mae_mean'), 1)} / {p(g(v, 'mae_median'), 1)}</td>"
                f"<td class='num'>{g(vs, 'stopped_rate', default=0) * 100:.1f}%</td>"
                f"<td class='num'>{fmt_win(g(v, 'win'), ci=False)}</td><td class='num'>{p(g(v, 'pnl'))}</td></tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>年</th><th>すぐ上のショート清算帯(推定)</th><th>件数</th><th>+30%踏み上げ</th><th>最大逆行<span class='vs'>平均 / 中央値</span></th>
<th>+15%損切りに<br>かかった割合</th><th>勝率</th><th>平均損益</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def main() -> None:
    final = CS_DIR / f"{PREFIX}_final_full.json"
    mode = "final" if final.exists() else "dev"
    res = json.loads((final if mode == "final" else CS_DIR / f"{PREFIX}_dev_full.json").read_text(encoding="utf-8"))
    if SIDE == "long":
        write_long(res, mode)
        return
    has_2024 = mode == "final"
    periods = ["2022", "2023", "2022-23"] + (["2024"] if has_2024 else [])
    cands = [k for k in VARIANTS if is_candidate(res, k)] if has_2024 else []
    if cands:
        vcls, big = "good", f"{len(cands)}件"
        vtxt = ("2022〜23年と2024年の両方で、件数30件以上・勝率50%超・コスト込みの平均損益がプラス・全銘柄平均の空売りより良い、を満たしたのは "
                + "、".join(f"<strong>{label(k)}</strong>" for k in cands)
                + "。ラウンドAと合わせて32通りを試した中での結果なので、2025年以降での答え合わせを通るまでは「使える」とは言えない。")
    else:
        vcls, big = "neutral", "0件"
        vtxt = ("8通りのどれも、2022〜23年と2024年の両方で「勝率50%超・コスト込みでプラス・全銘柄平均の空売りより良い」を満たさなかった。"
                if has_2024 else "(2024年を含めた計算はまだ。2022〜23年だけの途中経過)")
    thr = res.get("liq_threshold", np.nan)

    html = f"""<title>潮目 過熱ショート</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — ラウンドB: H17 過熱ショート</div>
    <h1>FRが過熱した銘柄を空売りしたら</h1>
    <p class="hero-sub">毎日0・8・16時(UTC)に、FR(資金調達率)が全銘柄の上位5%に新しく入った銘柄を空売りした場合を、「すぐ売る」と「失速を確認してから売る」で比べた。2022〜23年で形を作り、2024年は1回だけ確認。2025年以降のデータは読み込んでいない。対象 {res.get('n_symbols', '—')}銘柄。</p>
    <div class="verdict-card {vcls}"><div class="verdict-big">{big}</div>
      <div class="verdict-text"><strong>答え合わせ候補</strong><br>{vtxt}</div></div>
  </header>

  <section>
    <h2>数字の読み方</h2>
    <div class="read-grid">
      <div class="read-card"><strong>勝率・平均の勝ち/負け</strong>空売りで儲かった取引の割合と、勝ったとき・負けたときの平均(手数料と注文時の価格ずれを引いた後)。勝率が高くても、負けが大きければ全体ではマイナスになる。</div>
      <div class="read-card"><strong>全銘柄平均の空売りとの差</strong>同じ時刻・同じ期間に「全銘柄をまんべんなく空売り」した場合と比べた差。2022年のような下げ相場では何を売っても儲かりやすいので、それを差し引いて「この銘柄を選んだ意味」を見る。</div>
      <div class="read-card"><strong>最大逆行・踏み上げ</strong>持っている間に、売った値段から最も上がった幅。+30%以上は「踏み上げられた」回数として数える。損切りあり版では+15%で買い戻すので、それ以上の逆行は途中で止まる。</div>
    </div>
  </section>

  <section>
    <h2>8通りの結果(全銘柄)</h2>
    <p class="lede">候補の条件: 2022〜23年と2024年の両方で、件数30件以上・勝率50%超・平均損益(コスト込み、FRは含めない)がプラス・全銘柄平均の空売りとの差がプラス。小さい数字は95%の幅(週ごとのかたまりで引き直した)。</p>
    {main_table(res, periods, has_2024)}
  </section>

  <section>
    <h2>②「失速を確認してから」の様子</h2>
    <p class="lede">②は、高値更新が6時間止まり・建玉が6時間前より増えておらず・直近6時間の現物の成り行き売りが買いを上回ったときに売る(きっかけから72時間まで)。現物データか建玉データが無い銘柄は判定できない。</p>
    {flow_table(res, periods)}
  </section>

  <section>
    <h2>補助: 近くに清算価格帯があると下げが深いか(推定)</h2>
    <p class="lede"><strong>清算価格帯は公開データからは分からないため、ここの数字はあくまで推定。</strong>売る前の7日間に建玉が増えた1時間ごとに、その価格で新しくロング(買い)が入り、レバレッジ10倍と20倍が半分ずつと仮定して強制決済される価格を見積もった。売値の85%〜売値の間にある量 ÷ 今の建玉 が2022〜23年の中央値({'—' if np.isnan(thr) else f'{thr:.3f}'})より多いものを「近い」とした。①・7日・損切りなしで比較。</p>
    {liq_table(res, periods)}
  </section>

  <section>
    <h2>補助: 荒れ予報あり/なし</h2>
    <p class="lede">売る時点の直前24時間の値幅が、その銘柄の直近90日の中で上位10%なら「荒れ予報あり」(第1ラウンドで大きな値動きが約2倍起きやすかった条件)。90日分のデータが無い銘柄は分けられないので数えていない。</p>
    {storm_table(res, periods)}
  </section>

  <section>
    <h2>補助: すぐ上にショートの清算帯があると踏み上げられやすいか(推定)</h2>
    <p class="lede"><strong>ここも推定。</strong>売る前の7日間に建玉が増えた1時間ごとに、同じ量のショート(売り)が入ったとみなし、レバレッジ10倍と20倍が半分ずつと仮定して強制決済される価格を見積もった。売値より上〜+10%以内にある量 ÷ 今の建玉 が2022〜23年の中央値({'—' if np.isnan(res.get('short_liq_threshold', np.nan)) else f"{res.get('short_liq_threshold'):.3f}"})より多いものを「多い」とした。①・7日で比較(損切りにかかった割合は+15%損切りあり版)。10倍・20倍の清算価格は入った価格の+9.5%・+4.5%なので、この数値は「最近、今の価格の近くで建玉が増えたか」とほぼ同じものを測っている可能性がある。</p>
    {short_liq_table(res, periods)}
  </section>

  <section>
    <h2>試した回数</h2>
    <p>候補の判定に使うのは8通り(入り方2 × 持つ期間2 × 損切り2)。ラウンドAの24通りと後付けの H2r を合わせて33通り。補助分析(下のロング清算帯・荒れ予報・すぐ上のショート清算帯)の10通りを含めると、見たものは43通り。定義と記録は <code>docs/hypotheses_v2.md</code> のラウンドBの節。</p>
  </section>
  <footer>作成: scripts/build_overheat_report.py ／ 計算: scripts/run_overheat.py({mode}) ／ 2025年以降のデータは読み込んでいない。</footer>
</div>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


def write_long(res: dict, mode: str) -> None:
    has_2024 = mode == "final"
    periods = ["2022", "2023", "2022-23"] + (["2024"] if has_2024 else [])
    cands = [k for k in VARIANTS if is_candidate(res, k)] if has_2024 else []
    if cands:
        vcls, big = "good", f"{len(cands)}件"
        vtxt = ("2022〜23年と2024年の両方で、件数30件以上・勝率50%超・コスト込みの平均損益がプラス・全銘柄平均を買った場合より良い、を満たしたのは "
                + "、".join(f"<strong>{label(k)}</strong>" for k in cands)
                + "。ただし41通りを試した中での結果で、2025年以降は第1ラウンドの局面③の結果をすでに見ているため、答え合わせも完全な初見ではない。")
    else:
        vcls, big = "neutral", "0件"
        vtxt = ("8通りのどれも、2022〜23年と2024年の両方で「勝率50%超・コスト込みでプラス・全銘柄平均を買った場合より良い」を満たさなかった。"
                if has_2024 else "(2024年を含めた計算はまだ。2022〜23年だけの途中経過)")
    html = f"""<title>潮目 過熱ロング</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — ラウンドB: H17L 過熱ロング</div>
    <h1>FRが大きくマイナスの銘柄を買ったら</h1>
    <p class="hero-sub">H17(過熱ショート)の裏返し。毎日0・8・16時(UTC)に、FR(資金調達率)が全銘柄の下位5%に新しく入った銘柄を買った場合を、「すぐ買う」と「下げ止まりを確認してから買う」で比べた。2022〜23年で形を作り、2024年は1回だけ確認。2025年以降のデータは読み込んでいない。対象 {res.get('n_symbols', '—')}銘柄。</p>
    <div class="verdict-card {vcls}"><div class="verdict-big">{big}</div>
      <div class="verdict-text"><strong>答え合わせ候補</strong><br>{vtxt}</div></div>
  </header>

  <section>
    <h2>事前に分かっていたこと</h2>
    <ul class="key-list">
      <li>第1ラウンドの局面③「ショート踏み上げ準備」(価格が横ばい〜下落 + 建玉が増加 + FRがマイナス + 現物CVDが上昇 → 上がると予想)は不合格だった。
      24時間後の方向的中率は、2022〜2024年で51.7〜52.9%、2025年以降で47.1〜53.2%。どれもコストを上回らなかった。</li>
      <li>この判定は2025年以降のデータで行ったため、H17L を2025年以降で答え合わせしても、似た局面の成績をすでに一部見ていることになる。</li>
    </ul>
  </section>

  <section>
    <h2>8通りの結果(全銘柄)</h2>
    <p class="lede">候補の条件: 2022〜23年と2024年の両方で、件数30件以上・勝率50%超・平均損益(コスト込み、FRは含めない)がプラス・全銘柄平均を買った場合との差がプラス。最大逆行は、買った値段から最も下がった幅。FR込みは、FRがマイナスのときに買い側が受け取る分を足した参考値。</p>
    {main_table(res, periods, has_2024)}
  </section>

  <section>
    <h2>②「下げ止まりを確認してから」の様子</h2>
    <p class="lede">②は、安値更新が6時間止まり・建玉が6時間前より増えておらず・直近6時間の現物の成り行き買いが売りを上回ったときに買う(きっかけから72時間まで)。</p>
    {flow_table(res, periods)}
  </section>

  <section>
    <h2>試した回数</h2>
    <p>H17L の8通りを加えて、候補判定の対象は41通り(ラウンドA 24 + H17 8 + H2r 1 + H17L 8)。補助分析10通りを含めると51通り。定義と記録は <code>docs/hypotheses_v2.md</code> の H17L の節。</p>
  </section>
  <footer>作成: scripts/build_overheat_report.py long ／ 計算: scripts/run_overheat.py --side long({mode}) ／ 2025年以降のデータは読み込んでいない。</footer>
</div>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
