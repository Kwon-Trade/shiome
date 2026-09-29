#!/usr/bin/env python3
"""答え合わせ(2025-01〜2026-08、H5 と F1)の結果レポート。入力: data/processed/crosssection/holdout_v2.json

実行例:
    python scripts/build_holdout_v2_report.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cross_section_report import EXTRA_CSS, g  # noqa: E402
from build_report import CSS  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402

CS = PROCESSED_DIR / "crosssection"
OUT = ROOT / "reports" / "holdout_v2.html"


def pct(v, d=2):
    return f"{v * 100:+.{d}f}%"


def ok(b):
    return "<span class='badge badge-pass'>満たす</span>" if b else "<span class='badge badge-fail'>満たさない</span>"


def main() -> None:
    r = json.loads((CS / "holdout_v2.json").read_text(encoding="utf-8"))
    ref = json.loads((CS / "f1_reference_2022_2024.json").read_text(encoding="utf-8"))
    final = json.loads((CS / "results_final.json").read_text(encoding="utf-8"))["full"]["H5"]["all"]["24h"]
    h, f = r["H5"]["24h"], r["F1"]["24h"]
    f7 = r["F1"]["7d_reference"]
    fr = ref["24h"]["2022-24"]
    n_pass = int(r["H5"]["pass"]) + int(r["F1"]["pass"])
    html = f"""<title>潮目 答え合わせ</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 第2ラウンド 答え合わせ(2025年1月〜2026年8月)</div>
    <h1>H5 と F1 を、まだ見ていない期間で確かめた</h1>
    <p class="hero-sub">2022〜2024年で選んだ H5 と、後付けの F1 の2つだけを、2025-01-01〜2026-08-31 の判断日で1回だけ計算した。
    比較対象は当時 Binance 先物にあった暗号資産 661銘柄(株式・ETF・金属などに連動する先物は除外)。1日あたり平均 {h['avg_n']:.0f}銘柄を比べた。基準を記録したコミット: {r['commit'][:7]}。</p>
    <div class="verdict-card"><div class="verdict-big">合格 {n_pass}/2</div>
      <div class="verdict-text"><strong>どちらも不合格。</strong>順位の上では予想どおりの向きが少し残ったが、H5 はコストを引くと、F1 は差の大きさが偶然と区別できず、事前に決めた合格の条件を満たさなかった。</div></div>
  </header>

  <section>
    <h2>H5: 上場30〜90日の銘柄は、古い銘柄より弱い(24時間後)</h2>
    <p class="lede">古い銘柄を買い・新しい銘柄を売る組み合わせで判定。合格の条件は3つすべて(事前に決めた §7 の条件をそのまま当てはめた)。</p>
    <div class="table-wrap"><table>
      <thead><tr><th>条件</th><th>答え合わせ(2025〜26)</th><th>参考: 2022〜23</th><th>参考: 2024</th><th>判定</th></tr></thead>
      <tbody>
        <tr><td>勝率が50%超</td><td class="num">{h['win'] * 100:.1f}%</td><td class="num">{final['2022-23']['win'] * 100:.1f}%</td><td class="num">{final['2024']['win'] * 100:.1f}%</td><td>{ok(h['win'] > 0.5)}</td></tr>
        <tr><td>順位の相関がプラス</td><td class="num">{h['ic']:+.3f}<span class="ci">{h['ic_lo']:+.3f}〜{h['ic_hi']:+.3f}</span></td><td class="num">{final['2022-23']['ic']:+.3f}</td><td class="num">{final['2024']['ic']:+.3f}</td><td>{ok(h['ic'] > 0)}</td></tr>
        <tr><td>コスト込みの差(1日あたり)がプラス</td><td class="num">{pct(h['pf_net'], 3)}<span class="ci">コスト前 {pct(h['pf_gross'], 3)}</span></td><td class="num">{pct(final['2022-23']['pf_net'], 3)}</td><td class="num">{pct(final['2024']['pf_net'], 3)}</td><td>{ok(h['pf_net'] > 0)}</td></tr>
      </tbody></table></div>
    <p class="note">勝つ日は多く(53.8%)、順位もわずかに揃ったが、コストを引く前から平均ではマイナス。新しい銘柄がたまに大きく跳ねる日の負けが、小さな勝ちの積み重ねを上回った(2022〜23年の7日・28日後でも見えていた形)。</p>
  </section>

  <section>
    <h2>F1: 要注意の銘柄は、残りの銘柄より弱い(24時間後)</h2>
    <p class="lede">要注意 = 上場90日以内・過去7日の建玉増加率が上位20%・過去24時間の上昇率が上位20% のどれか。買う銘柄から外すふるいとして使うので、コストは引かない。合格の条件は2つとも。</p>
    <div class="table-wrap"><table>
      <thead><tr><th>条件</th><th>答え合わせ(2025〜26)</th><th>参考: 2022〜24(判定に使わない)</th><th>判定</th></tr></thead>
      <tbody>
        <tr><td>残りが勝った日が52%超</td><td class="num">{f['rest_win'] * 100:.1f}%</td><td class="num">{fr['rest_win'] * 100:.1f}%</td><td>{ok(f['rest_win'] > 0.52)}</td></tr>
        <tr><td>平均の差(要注意−残り)の95%区間の上限が0未満</td><td class="num">{pct(f['diff'], 3)}<span class="ci">{pct(f['diff_lo'], 3)}〜{pct(f['diff_hi'], 3)}</span></td><td class="num">{pct(fr['diff'], 3)}<span class="ci">{pct(fr['diff_lo'], 3)}〜{pct(fr['diff_hi'], 3)}</span></td><td>{ok(f['diff_hi'] < 0)}</td></tr>
      </tbody></table></div>
    <p class="note">残りの銘柄が勝つ日は多かった(54.1%)が、平均の差は2022〜24年の −0.12%/日 から −0.02%/日 に縮み、95%区間は0をまたいだ。
    1日あたり平均 {f['avg_flagged']:.0f}銘柄(うち上場90日以内 {f['avg_new']:.0f})が要注意になった。
    参考の7日後: 残りが勝った日 {f7['rest_win'] * 100:.1f}%、平均の差 {pct(f7['diff'], 3)}(区間 {pct(f7['diff_lo'], 3)}〜{pct(f7['diff_hi'], 3)})。</p>
  </section>

  <section>
    <h2>この結果の読み方</h2>
    <ul class="key-list">
      <li>第2ラウンドでは、候補判定の対象42通り(補助分析を含めて52通り)を試し、答え合わせにかけたのは H5 と F1 の2つ。どちらも通らなかったので、<strong>このラウンドから「使える」と言える仮説は無い</strong>。</li>
      <li>「上場して日が浅い銘柄」「建玉や値段が急に増えた銘柄」が他より弱い日が多い、という傾向そのものは2025年以降にも少し残っていた。ただし弱い日の差は小さく、たまに起きる大きな跳ね上がりで帳消しになるため、平均では役に立つほどの差にならなかった。</li>
      <li>2025年以降のデータは、この2つの答え合わせで使った。同じ期間で別の仮説を確かめると「答えを見てから作った」ことになるため、今後の検証には2026年9月以降の新しいデータが必要になる。</li>
    </ul>
  </section>
  <footer>作成: scripts/build_holdout_v2_report.py ／ 計算: scripts/run_holdout_v2.py run(1回だけ) ／ 条件と記録: docs/hypotheses_v2.md の「答え合わせ」の節</footer>
</div>
"""
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
