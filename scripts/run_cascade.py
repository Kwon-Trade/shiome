#!/usr/bin/env python3
"""第3ラウンド A: 清算の連鎖の後の反発を計算する。定義は docs/hypotheses_v3.md。

    dev    2023年末までのデータだけで計算(条件の形を決める期間。何度でもよい)
    final  2024年末までを読み、2024年を含めて計算(1回だけ。2回目は止まる)

実行例:
    python scripts/run_cascade.py dev
    python scripts/run_cascade.py dev --symbols BTCUSDT,ETHUSDT,DOGEUSDT   # 動作確認
"""
import argparse
import gc
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from shiome.cascade.events import (  # noqa: E402
    ALL_SIGNALS, BAR, MARKET_MIN_OTHERS, detect, load_sym, outcome, signal_bars,
)
from shiome.config import PROCESSED_DIR  # noqa: E402
from shiome.crosssection.data import DEV_END, HARD_END, full_universe  # noqa: E402
from shiome.crosssection.groups import assign_groups  # noqa: E402

OUT = PROCESSED_DIR / "cascade"
GUARDED = ("docs/hypotheses_v3.md", "src/shiome/cascade", "scripts/run_cascade.py")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dev", "final"])
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    tag = args.mode + ("_test" if args.symbols else "")
    out_path = OUT / f"trades_{tag}.parquet"
    commit = None
    if args.mode == "final" and not args.symbols:
        if _git("status", "--porcelain", *GUARDED):
            sys.exit("条件の記録または計算コードに未コミットの変更があります。先にコミットしてください。")
        if out_path.exists():
            sys.exit("2024年を含む計算は済んでいます(1回だけ)。")
        commit = _git("rev-parse", "HEAD")
    end = DEV_END if args.mode == "dev" else HARD_END
    symbols = args.symbols.split(",") if args.symbols else sorted(full_universe())

    rows, dailies, btc_drop = [], [], None
    for n, name in enumerate(symbols, 1):
        s = load_sym(name, end)
        if s is None:
            continue
        casc, bench, drop_only = detect(s)
        if name == "BTCUSDT":
            btc_drop = pd.Series(drop_only, index=pd.DatetimeIndex(s.t) + BAR)
        dailies.append(s.daily.assign(symbol=name))
        for kind, positions in (("cascade", casc), ("bench", bench)):
            for i in positions:
                sig = signal_bars(s, i)
                base = {"symbol": name, "kind": kind, "t0": pd.Timestamp(s.t[i]) + BAR,
                        "r30": s.r30[i], "oi30": s.oi30[i], "taker30": s.taker30[i]}
                for sname in ALL_SIGNALS:
                    j = sig[sname]
                    res = outcome(s, i, j, end) if j is not None else None
                    rows.append({**base, "signal": sname, "fired": j is not None, **(res or {})})
        print(f"[{n}/{len(symbols)}] {name}: 連鎖 {len(casc)} / 物差し {len(bench)}", flush=True)
        del s
        gc.collect()

    df = pd.DataFrame(rows)
    # 分類: 市場全体 = BTC も同じ30分で過去90日の下位1% / t0 までの30分にほかの5銘柄以上で連鎖
    ev = df[(df["kind"] == "cascade") & (df["signal"] == "S0")][["symbol", "t0"]]
    t_sorted = np.sort(ev["t0"].values)
    def others(row):
        a = np.searchsorted(t_sorted, (row.t0 - pd.Timedelta(minutes=30)).to_datetime64(), side="left")
        b = np.searchsorted(t_sorted, row.t0.to_datetime64(), side="right")
        same = ((ev["symbol"] == row.symbol) & (ev["t0"] >= row.t0 - pd.Timedelta(minutes=30)) & (ev["t0"] <= row.t0)).sum()
        return (b - a) - same
    df["n_others"] = [others(r) for r in df[["symbol", "t0"]].itertuples(index=False)]
    df["btc_drop"] = df["t0"].map(btc_drop).fillna(False).astype(bool) if btc_drop is not None else False
    df["scope"] = np.where(df["btc_drop"] | (df["n_others"] >= MARKET_MIN_OTHERS), "market", "single")
    daily = assign_groups(pd.concat(dailies, ignore_index=True))
    key = pd.MultiIndex.from_arrays([df["t0"].dt.floor("D"), df["symbol"]])
    dm = daily.set_index(["t", "symbol"])
    df["group"] = dm["group"].reindex(key).to_numpy()
    df["adv30_usd"] = dm["adv30_usd"].reindex(key).to_numpy()
    df["drop_bin"] = pd.cut(df["r30"], [-np.inf, -0.10, -0.05, 0], labels=["-10%超", "-5〜-10%", "-5%未満"]).astype(str)
    df.attrs["commit"] = commit
    df.to_parquet(out_path, index=False)
    if commit:
        (OUT / f"commit_{args.mode}.txt").write_text(commit)
    c = df[(df["signal"] == "S0")]
    print("保存:", out_path, "連鎖イベント", int((c["kind"] == "cascade").sum()), "物差し", int((c["kind"] == "bench").sum()))


if __name__ == "__main__":
    main()
