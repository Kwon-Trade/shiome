#!/usr/bin/env python3
"""ラウンドB: H17「過熱ショート」を計算する。定義は docs/hypotheses_v2.md B1〜B8。

    dev    2023年末までのデータだけで計算(仕組みの確認用。何度でもよい)
    final  2024年末までを読み、2024年を含めて計算(1回だけ。2回目は止まる)

実行例:
    python scripts/run_overheat.py dev --set set61
    python scripts/run_overheat.py final --set full
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from shiome.config import PROCESSED_DIR  # noqa: E402
from shiome.crosssection.data import DEV_END, HARD_END  # noqa: E402
from shiome.crosssection.evaluate import PERIODS  # noqa: E402
from shiome.crosssection.overheat import HOLDS, load_sym, run, summarize  # noqa: E402
from run_cross_section import symbol_set  # noqa: E402

OUT_DIR = PROCESSED_DIR / "crosssection"
GUARDED = ("docs/hypotheses_v2.md", "src/shiome/crosssection", "scripts/run_overheat.py")
PERIOD_LIST = {"dev": ["2022", "2023", "2022-23"], "final": ["2022", "2023", "2024", "2022-23"]}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _period(df: pd.DataFrame, per: str, col: str = "t0") -> pd.DataFrame:
    a, b = (pd.Timestamp(x) for x in PERIODS[per])
    return df[(df[col] >= a) & (df[col] < b)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dev", "final"])
    ap.add_argument("--set", default="full")
    args = ap.parse_args()
    out_path = OUT_DIR / f"overheat_{args.mode}_{args.set}.json"
    commit = None
    if args.mode == "final":
        if _git("status", "--porcelain", *GUARDED):
            sys.exit("条件の記録または計算コードに未コミットの変更があります。先にコミットしてください。")
        if out_path.exists():
            sys.exit(f"{out_path.name} は計算済みです(2024年は1回だけ)。")
        commit = _git("rev-parse", "HEAD")
    end = DEV_END if args.mode == "dev" else HARD_END

    syms = {}
    for name in symbol_set(args.set):
        s = load_sym(name, end, with_oi=True)
        if s is not None:
            syms[name] = s
    events, trades = run(syms, end)
    events.to_parquet(OUT_DIR / f"overheat_events_{args.mode}_{args.set}.parquet", index=False)
    trades.to_parquet(OUT_DIR / f"overheat_trades_{args.mode}_{args.set}.parquet", index=False)

    res = {"commit": commit, "n_symbols": len(syms), "periods": {}}
    for per in PERIOD_LIST[args.mode]:
        ev = _period(events, per)
        tr = _period(trades, per)
        r = {"n_events": int(len(ev)), "n_judgeable": int(ev["judgeable"].sum()),
             "n_entry2": int(ev["entry2"].notna().sum()), "variants": {}, "reference": {}}
        for kind in ("1", "2"):
            for hz in HOLDS:
                for stop in (False, True):
                    sub = tr[(tr["entry_kind"] == kind) & (tr["hold"] == hz) & (tr["stop"] == stop)]
                    key = f"{kind}|{hz}|{'stop' if stop else 'nostop'}"
                    r["variants"][key] = summarize(sub)
                    if kind == "1":
                        r["reference"][key + "|judgeable"] = summarize(sub[sub["judgeable"]])
        # ②で見送ったイベントで、①ならどうだったか
        skipped = ev[ev["judgeable"] & ev["entry2"].isna()][["t0", "symbol"]]
        s1 = tr[(tr["entry_kind"] == "1") & (tr["hold"] == "7d") & (~tr["stop"])].merge(skipped, on=["t0", "symbol"])
        r["reference"]["skipped_by_2|1|7d|nostop"] = summarize(s1)
        res["periods"][per] = r

    # 補助: 清算価格帯(推定)が近いか。境目は2022〜23年の中央値
    base = trades[(trades["entry_kind"] == "1") & (trades["hold"] == "7d") & (~trades["stop"])]
    base_dev = _period(base, "2022-23")
    thr = float(base_dev["near_liq"].median()) if base_dev["near_liq"].notna().any() else np.nan
    res["liq_threshold"] = thr
    res["liq"] = {}
    for per in PERIOD_LIST[args.mode]:
        b = _period(base, per)
        b = b[b["near_liq"].notna()]
        res["liq"][per] = {"near": summarize(b[b["near_liq"] > thr]), "far": summarize(b[b["near_liq"] <= thr])}

    # B10-1: 荒れ予報あり/なし(8通りそれぞれ)
    res["storm"] = {}
    for per in PERIOD_LIST[args.mode]:
        tr = _period(trades, per)
        r = {}
        for kind in ("1", "2"):
            for hz in HOLDS:
                for stop in (False, True):
                    sub = tr[(tr["entry_kind"] == kind) & (tr["hold"] == hz) & (tr["stop"] == stop)]
                    key = f"{kind}|{hz}|{'stop' if stop else 'nostop'}"
                    r[key] = {"storm": summarize(sub[sub["storm"] == 1.0]), "calm": summarize(sub[sub["storm"] == 0.0]),
                              "unknown_n": int(sub["storm"].isna().sum())}
        res["storm"][per] = r

    # B10-2: すぐ上のショート清算帯(推定)。境目は2022〜23年の中央値。①・7日で比べる
    one7 = trades[(trades["entry_kind"] == "1") & (trades["hold"] == "7d")]
    thr_s = _period(one7[~one7["stop"]], "2022-23")["near_short_liq"].median()
    res["short_liq_threshold"] = float(thr_s) if pd.notna(thr_s) else np.nan
    res["short_liq"] = {}
    for per in PERIOD_LIST[args.mode]:
        b = _period(one7, per)
        b = b[b["near_short_liq"].notna()]
        near, far = b[b["near_short_liq"] > thr_s], b[b["near_short_liq"] <= thr_s]
        res["short_liq"][per] = {"near": summarize(near[~near["stop"]]), "far": summarize(far[~far["stop"]]),
                                 "near_stop": summarize(near[near["stop"]]), "far_stop": summarize(far[far["stop"]])}

    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    last = PERIOD_LIST[args.mode][-1]
    r = res["periods"][last]
    print(f"{args.set} {args.mode}: 銘柄 {len(syms)} / イベント {r['n_events']}(②判定可 {r['n_judgeable']}, ②で売った {r['n_entry2']})")
    for key, v in r["variants"].items():
        print(f"  {key:18} 件数 {v.get('n', 0):5}  勝率 {v.get('win', float('nan')) * 100:5.1f}%  平均損益 {v.get('pnl', float('nan')) * 100:+6.2f}%"
              f"  市場平均との差 {v.get('diff', float('nan')) * 100:+6.2f}%  +30%踏み上げ {v.get('squeeze_n', 0)}")
    print("保存:", out_path)


if __name__ == "__main__":
    main()
