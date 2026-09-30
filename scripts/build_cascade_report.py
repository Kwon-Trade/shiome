#!/usr/bin/env python3
"""第3ラウンド A(清算の連鎖の後の反発)のレポート。

入力: data/processed/cascade/trades_final.parquet(なければ trades_dev.parquet)
出力: data/processed/cascade/summary_{mode}.json と reports/cascade_rebound.html

実行例:
    python scripts/build_cascade_report.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from build_cross_section_report import EXTRA_CSS, fmt_win, g  # noqa: E402
from build_report import CSS  # noqa: E402
from shiome.cascade.events import SIGNALS  # noqa: E402
from shiome.cascade.stats import EXTRA, HZ, S0_FAMILY, full_summary  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402

CDIR = PROCESSED_DIR / "cascade"
OUT = ROOT / "reports" / "cascade_rebound.html"
SIG_LABEL = {
    "S0": "S0 すぐ買う(比較用)", "S1": "S1 建玉の減少が止まる", "S2-15": "S2 安値更新が15分止まる",
    "S2-30": "S2 安値更新が30分止まる", "S2-60": "S2 安値更新が60分止まる", "S3": "S3 テイカー比率が戻る",
    "S4": "S4 出来高が落ち着く", "S5": "S5 15分足の長い下ヒゲ", "S1+S2-30": "S1+S2(30分)", "S1+S3": "S1+S3",
    "S0-market": "【後付け】市場全体の連鎖 × S0", "S0-drop5": "【後付け】30分で5%以上の下げ × S0",
}
ALL = SIGNALS + EXTRA
HZ_LABEL = {"1h": "1時間後", "4h": "4時間後", "24h": "24時間後"}
PER_LABEL = {"2022": "2022", "2023": "2023", "2022-23": "2022〜23", "2024": "2024(確認)"}
SPLIT_LABEL = {"scope": "市場全体/その銘柄だけ", "group": "グループ", "drop_bin": "30分の下落の大きさ"}
VAL_LABEL = {"market": "市場全体の連鎖", "single": "その銘柄だけ", "large_cap": "大型", "mid_cap_alt": "中型アルト",
             "small_meme": "小型・ミーム"}


def p(v, d=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"<span class='{'pos' if v > 0 else 'neg'}'>{v * 100:+.{d}f}%</span>"


def ci(lo, hi):
    if lo is None or np.isnan(lo):
        return ""
    return f"<span class='ci'>{lo * 100:+.2f}〜{hi * 100:+.2f}%</span>"


def summary_table(res, periods, has24):
    rows = []
    for sig in ALL:
        for i, h in enumerate(HZ):
            cells = []
            for per in ("2022-23", "2024"):
                if per not in periods:
                    cells.append("<td class='num'>—</td>" * 4)
                    continue
                c = g(res, "main", "cascade", sig, h, per, default={})
                b = g(res, "main", "bench", sig, h, per, default={})
                diff = g(c, "net_mean") - g(b, "net_mean") if c.get("n") and b.get("n") else np.nan
                cells.append(f"<td class='num'>{g(c, 'n', default=0)}</td><td class='num'>{fmt_win(g(c, 'net_win'), ci=False)}</td>"
                             f"<td class='num'>{p(g(c, 'net_mean'))}{ci(g(c, 'net_lo'), g(c, 'net_hi'))}</td><td class='num'>{p(diff)}</td>")
            prom = ""
            if has24 and i == 0:
                prom = "".join(f"<div class='badge tag-cand'>{HZ_LABEL[h2]}</div>" for s2, h2 in res["promising"] if s2 == sig) or "<span class='badge tag-no'>—</span>"
            name = f"<td rowspan=3><div class='phase-name'>{SIG_LABEL[sig]}</div></td>" if i == 0 else ""
            last = f"<td rowspan=3 class='center'>{prom}</td>" if i == 0 else ""
            sep = " class='period-sep'" if i == 0 else ""
            rows.append(f"<tr{sep}>{name}<td>{HZ_LABEL[h]}</td>{''.join(cells)}{last}</tr>")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>合図</th><th>持つ期間</th><th>件数<span class='vs'>2022〜23</span></th><th>勝率<span class='vs'>コスト込み</span></th><th>平均損益<span class='vs'>コスト込み・95%の幅</span></th><th>物差しとの差</th>
<th>件数<span class='vs'>2024</span></th><th>勝率<span class='vs'>コスト込み</span></th><th>平均損益<span class='vs'>コスト込み・95%の幅</span></th><th>物差しとの差</th><th>有望</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def detail(res, sig, periods):
    rows = []
    for h in HZ:
        for j, per in enumerate(periods):
            c = g(res, "main", "cascade", sig, h, per, default={})
            sep = " class='period-sep'" if j == 0 else ""
            rows.append(
                f"<tr{sep}><td>{HZ_LABEL[h] if j == 0 else ''}</td><td>{PER_LABEL[per]}</td>"
                f"<td class='num'>{g(c, 'n', default=0)}<span class='ci'>イベント {g(c, 'n_events', default=0)}・見送り {g(c, 'n_events', default=0) - g(c, 'n_fired', default=0)}</span></td>"
                f"<td class='num'>{p(g(c, 'mean'))} / {p(g(c, 'median'))}<span class='ci'>下位10% {p(g(c, 'p10'))}・上位10% {p(g(c, 'p90'))}</span></td>"
                f"<td class='num'>{fmt_win(g(c, 'win'), ci=False)}</td>"
                f"<td class='num'>{p(g(c, 'net_mean'))}<span class='ci'>勝率 {g(c, 'net_win', default=0) * 100:.1f}%・スリッページ3倍 {p(g(c, 'stress_mean'))}</span></td>"
                f"<td class='num'>{p(g(c, 'mfe_mean'))}<span class='ci'>中央値 {p(g(c, 'mfe_median'))}・届くまで {g(c, 'mfe_min_median', default=np.nan):.0f}分</span></td>"
                f"<td class='num'>{p(g(c, 'mae_mean'))}<span class='ci'>二段目の下げ {g(c, 'second_leg', default=np.nan) * 100:.0f}%</span></td>"
                f"<td class='num'>{g(c, 'wait_median', default=np.nan):.0f}分</td></tr>")
    return f"""<div class="hyp-card"><h3>{SIG_LABEL[sig]}</h3><div class="table-wrap"><table>
<thead><tr><th>持つ期間</th><th>年</th><th>件数</th><th>損益 平均/中央値<span class='vs'>コスト前</span></th><th>勝率<span class='vs'>コスト前</span></th><th>コスト込み平均</th>
<th>戻りの最大幅<span class='vs'>24時間以内</span></th><th>最大の逆行<span class='vs'>24時間以内</span></th><th>待ち時間<span class='vs'>中央値</span></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></div>"""


def robust_tables(res, periods):
    rb = res.get("robustness", {})
    pers = [x for x in periods if x in ("2022-23", "2024")]
    rows = []
    for fam in S0_FAMILY:
        for i, h in enumerate(HZ):
            cells = []
            for per in pers:
                for d in ("-d0", "-d5", "-d10", "-d15"):
                    c = g(rb, "delay", fam, d, h, per, default={})
                    cells.append(f"<td class='num'>{p(g(c, 'net_mean'))}</td>")
                c0 = g(rb, "delay", fam, "-d0", h, per, default={})
                t = g(rb, "top_days_removed", fam, h, per, default={})
                cells.append(f"<td class='num'>{p(g(c0, 'stress_mean'))}</td><td class='num'>{p(g(t, 'net_mean'))}<span class='ci'>{g(t, 'n', default=0)}件</span></td>")
            name = f"<td rowspan=3><div class='phase-name'>{SIG_LABEL[fam]}</div></td>" if i == 0 else ""
            sep = " class='period-sep'" if i == 0 else ""
            rows.append(f"<tr{sep}>{name}<td>{HZ_LABEL[h]}</td>{''.join(cells)}</tr>")
    head = "".join(f"<th>遅れ0分<span class='vs'>{PER_LABEL[x]}</span></th><th>5分</th><th>10分</th><th>15分</th><th>スリッページ3倍</th><th>上位10日を除く</th>" for x in pers)
    days = "; ".join(f"{PER_LABEL[x]}: {', '.join(g(rb, 'top_days_removed', '_days', x, default=[]))}" for x in pers)
    mrows = []
    months = sorted(set().union(*[set(g(rb, "monthly", f, default={}).keys()) for f in S0_FAMILY]))
    for m in months:
        cells = []
        for fam in S0_FAMILY:
            r = g(rb, "monthly", fam, m, default={})
            cells.append(f"<td class='num'>{r.get('n', 0)}</td>" + "".join(f"<td class='num'>{p(r.get(f'sum_{h}', np.nan), 1)}</td>" for h in HZ))
        mrows.append(f"<tr><td>{m}</td>{''.join(cells)}</tr>")
    mhead = "".join(f"<th>{SIG_LABEL[f]}<span class='vs'>件数</span></th><th>1時間</th><th>4時間</th><th>24時間</th>" for f in S0_FAMILY)
    return f"""<div class="table-wrap"><table><thead><tr><th>条件</th><th>持つ期間</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="note">数字はコスト込みの平均損益(1回あたり)。除いた上位10日 — {days}</p>
<h4 style="margin-top:18px">月ごとの件数と損益(1回あたりのコスト込み損益の合計。毎回同じ金額で買った場合、1回の金額に対する%)</h4>
<details><summary>月ごとの表を開く</summary><div class="table-wrap"><table><thead><tr><th>月</th>{mhead}</tr></thead><tbody>{''.join(mrows)}</tbody></table></div></details>"""


def split_tables(res, periods):
    html = []
    for col, vals in res["splits"].items():
        for h in HZ:
            rows = []
            for val, sigs in vals.items():
                cells = []
                for sig in ALL:
                    parts = []
                    for per in ("2022-23", "2024"):
                        if per in periods:
                            c = g(sigs, sig, h, per, default={})
                            parts.append(f"{p(g(c, 'net_mean'))}<span class='ci'>{g(c, 'n', default=0)}件</span>")
                    cells.append(f"<td class='num'>{' / '.join(parts)}</td>")
                rows.append(f"<tr><td>{VAL_LABEL.get(val, val)}</td>{''.join(cells)}</tr>")
            head = "".join(f"<th>{s}</th>" for s in SIGNALS)
            html.append(f"<h4 style='margin-top:14px'>{SPLIT_LABEL[col]}・{HZ_LABEL[h]}(コスト込み平均。2022〜23 / 2024)</h4>"
                        f"<div class='table-wrap'><table><thead><tr><th>分類</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    return "".join(html)


def main() -> None:
    final = CDIR / "trades_final.parquet"
    mode = "final" if final.exists() else "dev"
    df = pd.read_parquet(final if mode == "final" else CDIR / "trades_dev.parquet")
    periods = ["2022", "2023", "2022-23"] + (["2024"] if mode == "final" else [])
    res = full_summary(df, periods, ALL)
    (CDIR / f"summary_{mode}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    has24 = mode == "final"
    s0 = df[(df["kind"] == "cascade") & (df["signal"] == "S0")]
    n_ev = {str(y): int(n) for y, n in s0["t0"].dt.year.value_counts().items()}
    n_ev = {y: n_ev.get(y, 0) for y in ("2022", "2023", "2024")}
    if has24:
        prom = res["promising"]
        big = f"{len(prom)}件"
        txt = ("2022〜23年と2024年の両方で、件数30件以上・コスト込みの平均損益がプラス・コスト込みの勝率50%超・物差しより良い、を満たしたのは "
               + "、".join(f"<strong>{SIG_LABEL[s]}({HZ_LABEL[h]})</strong>" for s, h in prom) + "。36通り(後付けの6通りを含む)を試した中での結果。答え合わせに回すかは相談して決める。"
               if prom else "36通りのどれも、2022〜23年と2024年の両方で「コスト込みでプラス・勝率50%超・物差しより良い」を満たさなかった。")
        vcls = "good" if prom else "neutral"
    else:
        big, vcls, txt = "途中", "neutral", "2022〜23年だけの結果(条件の形を決める期間)。2024年はまだ見ていない。"
    html = f"""<title>潮目 清算連鎖の反発</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 第3ラウンド A: 清算の連鎖の後の反発</div>
    <h1>清算の連鎖が止まったところで買ったら</h1>
    <p class="hero-sub">30分で「先物価格の急落」と「建玉の急減」が同時に(どちらもその銘柄の過去90日の下位1%)、テイカーの売りが優勢なときを清算の連鎖とみなし、
    止まった合図が出た次の5分足の始値で買った場合を調べた。2022〜23年で形を決め、2024年は1回だけ確認。2025年以降のデータは読み込んでいない。
    連鎖イベントの件数: 2022年 {n_ev['2022']}・2023年 {n_ev['2023']}・2024年 {n_ev['2024']}。</p>
    <div class="verdict-card {vcls}"><div class="verdict-big">{big}</div><div class="verdict-text"><strong>有望(目安)</strong><br>{txt}</div></div>
  </header>
  <section>
    <h2>数字の読み方</h2>
    <div class="read-grid">
      <div class="read-card"><strong>コスト込み</strong>往復手数料0.10%と、出来高が少ない銘柄ほど大きい注文時の価格ずれを引いた損益。急落の最中は板が薄いので、価格ずれ3倍の場合も参考に出した。</div>
      <div class="read-card"><strong>物差しとの差</strong>同じくらい急に下げたのに建玉は減っていない(清算を伴わない)場面で、同じ合図で買った場合との差。プラスなら「清算を伴う下げの方が戻りやすい」。</div>
      <div class="read-card"><strong>二段目の下げ</strong>買った後24時間以内に、イベントの安値をさらに割り込んだ割合。落ちるナイフをつかんだ回数の目安。</div>
    </div>
  </section>
  <section><h2>一覧(合図 × 持つ期間)</h2>
    <p class="lede">有望の目安: 2022〜23年と2024年の両方で、件数30件以上・コスト込みの平均損益がプラス・コスト込みの勝率50%超・物差しの同じ合図より高い。95%の幅は週ごとのかたまりで引き直した。</p>
    {summary_table(res, periods, has24)}</section>
  <section><h2>耐久テスト(S0 系。判定には使わない参考)</h2>
    <p class="lede">検知から5・10・15分遅れて買った場合、スリッページ3倍の場合、連鎖が特に多かった上位10日を除いた場合。遅れや悪条件で成績がどれだけ崩れるかを見る。</p>
    {robust_tables(res, periods)}</section>
  <section><h2>合図ごとの詳しい結果</h2>{''.join(detail(res, s, periods) for s in ALL)}</section>
  <section><h2>分類別</h2><details><summary>市場全体/その銘柄だけ・グループ・下落の大きさ別の表を開く</summary>{split_tables(res, periods)}</details></section>
  <section><h2>事前に分かっていたこと</h2><ul class="key-list">
    <li>第1ラウンドの局面⑤「投げ売り後の底打ち」(24時間の急落・建玉急減・FRの急低下・現物CVD上向き)は、2022〜2024年では24時間後の的中率52〜60%だったが、2025年以降のデータで34〜47%に落ちて不合格だった。</li>
    <li>試した組み合わせは36通り(事前に決めた合図10 × 持つ期間3 = 30通り + 2022〜23年の結果を見てから加えた後付けの「市場全体の連鎖 × S0」「30分で5%以上の下げ × S0」× 3期間 = 6通り)。後付けの2つは、2022〜23年の成績を条件づくりに使ったので、判断の材料は2024年の結果だけ。定義と記録は <code>docs/hypotheses_v3.md</code>。</li></ul></section>
  <footer>作成: scripts/build_cascade_report.py ／ 計算: scripts/run_cascade.py({mode}) ／ 2025年以降のデータは読み込んでいない。</footer>
</div>
"""
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
