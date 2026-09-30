#!/usr/bin/env python3
"""第3ラウンド A の答え合わせ(S0-drop5 × 4時間、2025-01〜2026-08)のレポート。入力: data/processed/cascade/holdout_s0drop5_4h.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cross_section_report import EXTRA_CSS  # noqa: E402
from build_report import CSS  # noqa: E402
from shiome.config import PROCESSED_DIR  # noqa: E402

OUT = ROOT / "reports" / "cascade_holdout.html"


def pc(v, d=2):
    return f"<span class='{'pos' if v > 0 else 'neg'}'>{v * 100:+.{d}f}%</span>"


def rng(x):
    return f"<span class='ci'>{x['lo'] * 100:+.2f}〜{x['hi'] * 100:+.2f}%</span>"


def ok(b):
    return "<span class='badge badge-pass'>満たす</span>" if b else "<span class='badge badge-fail'>満たさない</span>"


def main() -> None:
    r = json.loads((PROCESSED_DIR / "cascade" / "holdout_s0drop5_4h.json").read_text(encoding="utf-8"))
    m, b, p = r["main"], r["bench"], r["practical"]
    months = "".join(f"<tr><td>{k}</td><td class='num'>{v['n']}</td><td class='num'>{pc(v['sum'], 1)}</td><td class='num'>{pc(v['mean'])}</td></tr>"
                     for k, v in p["monthly"].items())
    prac = "".join(f"<tr><td>{name}</td><td class='num'>{x['n']}</td><td class='num'>{pc(x['mean'])}{rng(x)}</td><td class='num'>{x['win'] * 100:.1f}%</td></tr>"
                   for name, x in (("遅れなし(本番の条件)", m), ("検知から5分遅れ", p["delay_5min"]), ("検知から15分遅れ", p["delay_15min"]),
                                   ("スリッページ3倍", p["slippage_x3"]), ("イベントが多かった上位10日を除く", p["top10_days_removed"])))
    oct_sum = p["monthly"].get("2025-10", {}).get("sum", 0.0)
    html = f"""<title>潮目 清算連鎖の答え合わせ</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>{CSS}{EXTRA_CSS}</style>
<div class="page">
  <header class="hero">
    <div class="eyebrow">SHIOME — 第3ラウンド A 答え合わせ(2025年1月〜2026年8月)</div>
    <h1>「30分で5%以上の下げ × すぐ買う × 4時間」を確かめた</h1>
    <p class="hero-sub">清算の連鎖(先物価格の急落と建玉の急減が同時、テイカーの売り優勢)のうち30分で5%以上下げたものを、検知した5分足の次の足の始値ですぐ買い、4時間持った場合。
    2025年1月〜2026年8月の暗号資産の先物661銘柄で、事前に記録した条件どおり1回だけ計算した。基準を記録したコミット: {r['commit'][:7]}。</p>
    <div class="verdict-card"><div class="verdict-big">不合格</div>
      <div class="verdict-text"><strong>合格の条件を2つとも満たさなかった。</strong>平均はプラスだったが偶然と区別できず、清算を伴わない下げ(物差し)より良くもなかった。儲けのほとんどは2025年10月の大暴落1回から来ている。</div></div>
  </header>
  <section><h2>合格の条件</h2>
    <div class="table-wrap"><table><thead><tr><th>条件</th><th>結果</th><th>判定</th></tr></thead><tbody>
      <tr><td>① コスト込みの平均がプラスで、95%の幅の下限も0より上</td><td class="num">{pc(m['mean'])}{rng(m)}<span class='ci'>{m['n']}件・中央値 {m['median'] * 100:+.2f}%・勝率 {m['win'] * 100:.1f}%</span></td><td>{ok(r['pass_1_mean_and_ci_above_0'])}</td></tr>
      <tr><td>② 物差し(同じ幅の下げで建玉が減っていない場面、すぐ買って4時間)より平均が高い</td><td class="num">{pc(m['mean'])} 対 物差し {pc(b['mean'])}<span class='ci'>物差し {b['n']}件・勝率 {b['win'] * 100:.1f}%</span></td><td>{ok(r['pass_2_beats_bench'])}</td></tr>
    </tbody></table></div></section>
  <section><h2>実用の判定(合否とは別)</h2>
    <div class="table-wrap"><table><thead><tr><th>場合</th><th>件数</th><th>コスト込み平均<span class='vs'>95%の幅</span></th><th>勝率</th></tr></thead><tbody>{prac}</tbody></table></div>
    <ul class="key-list" style="margin-top:14px">
      <li>1か月あたり平均 {p['per_month_avg_count']:.0f}件。毎回同じ金額で買った場合の累積の損益は {pc(p['cumulative_sum'], 0)}(1回の金額に対する%)だが、そのうち<strong>2025年10月だけで {pc(oct_sum, 0)}</strong>(10月10日の大暴落からの戻り)。10月を除くと累積はマイナス。</li>
      <li>途中の最大の落ち込み(累積損益の最高値からの下落): {pc(p['max_drawdown'], 0)}(1回の金額に対する%)。</li>
      <li>除いた上位10日: {', '.join(p['top10_days'])}</li></ul>
    <details><summary>月ごとの件数と損益を開く</summary><div class="table-wrap"><table><thead><tr><th>月</th><th>件数</th><th>損益の合計</th><th>1回あたり</th></tr></thead><tbody>{months}</tbody></table></div></details>
  </section>
  <section><h2>この結果の読み方</h2><ul class="key-list">
    <li>清算の連鎖の直後に買うと、<strong>まれに起きる相場全体の大暴落の後には大きく戻る</strong>(2023年8月、2025年10月など)。しかし普段の連鎖では、勝つ回数と負ける回数はほぼ半々で、平均はほぼゼロ。</li>
    <li>2025年以降は、清算を伴わない急落(物差し)でも同じくらい戻っていて、「清算を伴う下げの方が戻りやすい」という違いは見られなかった。</li>
    <li>この条件は2022〜23年の結果を見てから作った後付けのもので、第3ラウンド A では36通りを試した。答え合わせを通らなかったので、<strong>このまま使える作戦とは言えない</strong>。</li>
  </ul></section>
  <footer>作成: scripts/build_cascade_holdout_report.py ／ 計算: scripts/run_cascade_holdout.py run(1回だけ) ／ 条件と記録: docs/hypotheses_v3.md §13</footer>
</div>
"""
    OUT.write_text(html, encoding="utf-8")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
