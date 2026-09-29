#!/usr/bin/env python3
"""第2ラウンドの仕組みの点検(2023年末までのデータだけを使う)。

1. 先読みの点検: データを途中(2023-07-01)で切って作り直しても、それより前の日の
   「並べる数値」「対象かどうか」が1つも変わらないこと
2. 仕組みの点検: 答え(その後の値動き)をそのまま並べる数値にすると勝率100%・相関ほぼ1になること、
   でたらめな数値なら勝率50%・相関0付近になること
3. データの点検: 対象銘柄の1時間の値動きが±50%を超える足を一覧にする(不具合の疑い)

実行例:
    python scripts/check_cross_section.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import shiome.crosssection.evaluate as ev  # noqa: E402
from shiome.crosssection.data import DEV_END, load_futures_hourly  # noqa: E402
from shiome.crosssection.panel import symbol_panel  # noqa: E402
from run_cross_section import build_panel, symbol_set  # noqa: E402

SIGNAL_COLS = ["eligible", "adv30_usd", "price", "h1_fr7", "h2_7", "h2_14", "h2_28", "h3_ret24",
               "h4_oi7", "h5_age", "h6_fs7", "range24"]


def same(a: pd.Series, b: pd.Series) -> bool:
    a, b = a.reset_index(drop=True), b.reset_index(drop=True)
    both_nan = a.isna() & b.isna()
    return bool((both_nan | (a == b)).all())


def truncation_check(set_name: str) -> None:
    cut = pd.Timestamp("2023-07-01")
    bad = []
    syms = symbol_set(set_name)
    for s in syms:
        full = symbol_panel(s, DEV_END)
        if full.empty:
            continue
        part = symbol_panel(s, cut)
        full = full[full["t"] < cut].reset_index(drop=True)
        if part.empty:
            if full["eligible"].any():
                bad.append((s, "切ると表が空になる"))
            continue
        if len(full) != len(part):
            bad.append((s, f"行数 {len(full)} vs {len(part)}"))
            continue
        for c in SIGNAL_COLS:
            if not same(full[c], part[c]):
                bad.append((s, c))
        for c in ("fwd_24h", "fwd_7d", "fwd_28d"):
            m = part[c].notna()
            if not same(full.loc[m, c], part.loc[m, c]):
                bad.append((s, c))
    print(f"[1] 先読みの点検({set_name}, {len(syms)}銘柄): ", "問題なし" if not bad else f"不一致 {bad[:20]}")


def plumbing_check(panel: pd.DataFrame) -> None:
    rng = np.random.default_rng(0)
    panel = panel.copy()
    panel["oracle"] = panel["fwd_24h"]
    ev.SIGNALS["ORACLE"] = ("oracle", +1, "答えそのもの")
    r = ev.evaluate(panel, "ORACLE", "24h", ["2022-23"])["2022-23"]
    print(f"[2] 答えを並べる数値にした場合: 勝率 {r['win']:.3f} 相関 {r['ic']:.3f}(1に近ければ正常)")
    for seed in range(3):
        panel["noise"] = rng.standard_normal(len(panel))
        ev.SIGNALS["NOISE"] = ("noise", +1, "でたらめ")
        r = ev.evaluate(panel, "NOISE", "24h", ["2022-23"])["2022-23"]
        print(f"    でたらめな数値 {seed}: 勝率 {r['win']:.3f} [{r['win_lo']:.3f}, {r['win_hi']:.3f}] 相関 {r['ic']:+.4f}"
              f"  コスト前 {r['pf_gross']*100:+.3f}%/日 コスト {r['pf_cost']*100:.3f}%/日")


def jump_check(panel: pd.DataFrame) -> None:
    rows = []
    elig = panel[panel["eligible"]].groupby("symbol")["t"].agg(["min", "max"])
    for s, (a, b) in elig.iterrows():
        h = load_futures_hourly(s, DEV_END)
        r = h["close"].pct_change(fill_method=None)
        j = r[(r.abs() > 0.5) & (r.index >= a - pd.Timedelta(days=30)) & (r.index <= b + pd.Timedelta(days=28))]
        rows += [(s, str(t), round(float(v), 3)) for t, v in j.items()]
    print(f"[3] 1時間で±50%を超える値動き(対象期間の前後): {len(rows)}件")
    for row in rows:
        print("   ", row)


def main() -> None:
    set_name = sys.argv[1] if len(sys.argv) > 1 else "set61"
    truncation_check(set_name)
    panel = build_panel(set_name, "dev", with_oi=False)
    plumbing_check(panel)
    jump_check(panel)


if __name__ == "__main__":
    main()
