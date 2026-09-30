#!/usr/bin/env python3
"""第3ラウンド A の答え合わせ: 「30分で5%以上の下げ × S0 × 4時間」を2025-01〜2026-08で1回だけ計算する。

定義・合格の条件は docs/hypotheses_v3.md §13。

    python scripts/run_cascade_holdout.py check   # データの点検だけ(成績は計算しない)
    python scripts/run_cascade_holdout.py run     # 答え合わせ(1回だけ。2回目は止まる)
"""
import gc
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from shiome.cascade.events import BAR, detect, load_sym, outcome  # noqa: E402
from shiome.config import CONFIGS_DIR, PROCESSED_DIR  # noqa: E402
from shiome.crosssection import data as cs_data  # noqa: E402
from shiome.crosssection.evaluate import FEE_ONE_WAY, one_way_cost  # noqa: E402
from shiome.crosssection.overheat import cluster_boot  # noqa: E402

OUT = PROCESSED_DIR / "cascade"
RESULT = OUT / "holdout_s0drop5_4h.json"
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-09-01")
DROP = -0.05
HOLD = "4h"
DELAYS = {"d0": 0, "d5": 1, "d15": 3}
TOP_DAYS = 10
GUARDED = ("docs/hypotheses_v3.md", "src/shiome/cascade", "scripts/run_cascade_holdout.py",
           "configs/universe_2025_2026.yaml", "configs/holdout_non_crypto.yaml")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _symbols() -> list[str]:
    return sorted(yaml.safe_load((CONFIGS_DIR / "universe_2025_2026.yaml").read_text(encoding="utf-8"))["symbols"])


def check() -> None:
    """5分足の点検だけ(月の抜け、範囲外の行)。値動きの成績は計算しない。"""
    u = yaml.safe_load((CONFIGS_DIR / "universe_2025_2026.yaml").read_text(encoding="utf-8"))["symbols"]
    miss, short, beyond = [], [], []
    for s, info in u.items():
        path = PROCESSED_DIR / "futures_um" / "klines" / "5m" / f"{s}.parquet"
        if not path.exists():
            miss.append(s)
            continue
        t = pd.to_datetime(pd.read_parquet(path, columns=["open_time"])["open_time"], unit="ms")
        if t.max() >= END:
            beyond.append(s)
        a = max(pd.Period(info["first_month"], "M"), pd.Period("2025-01", "M"))
        b = min(pd.Period(info["last_month"], "M"), pd.Period("2026-08", "M"))
        exp = {str(p) for p in pd.period_range(a, b, freq="M")}
        got = {str(p) for p in t.dt.to_period("M").unique()}
        if exp - got:
            short.append((s, sorted(exp - got)[:3]))
    print(f"5分足: {len(u)}銘柄 / ファイルなし {len(miss)} {miss[:10]} / 抜けている月がある {len(short)} {short[:10]} / 2026-09以降の行 {beyond[:10]}")


def run() -> None:
    if _git("status", "--porcelain", *GUARDED):
        sys.exit("条件の記録または計算コードに未コミットの変更があります。先にコミットしてください。")
    if RESULT.exists():
        sys.exit("答え合わせは計算済みです(1回だけ)。")
    commit = _git("rev-parse", "HEAD")
    cs_data.allow_holdout()
    end = cs_data.HOLDOUT_END

    rows, all_casc_t0 = [], []
    symbols = _symbols()
    for n, name in enumerate(symbols, 1):
        s = load_sym(name, end)
        if s is None:
            continue
        casc, bench, _ = detect(s)
        adv = s.daily.set_index("t")["adv30_usd"]
        for kind, positions in (("cascade", casc), ("bench", bench)):
            for i in positions:
                t0 = pd.Timestamp(s.t[i]) + BAR
                if not (START <= t0 < END):
                    continue
                if kind == "cascade":
                    all_casc_t0.append(t0)
                if s.r30[i] > DROP:
                    continue
                for dname, k in DELAYS.items():
                    res = outcome(s, i, i + k, end) if i + k < len(s.t) - 1 else None
                    if res is None:
                        continue
                    rows.append({"symbol": name, "kind": kind, "t0": t0, "r30": float(s.r30[i]), "delay": dname,
                                 "entry_time": res["entry_time"], "ret": res[f"ret_{HOLD}"],
                                 "adv30_usd": float(adv.get(t0.floor("D"), np.nan))})
        if n % 50 == 0:
            print(f"[{n}/{len(symbols)}]", flush=True)
        del s
        gc.collect()

    df = pd.DataFrame(rows)
    df = df[df["ret"].notna()].copy()
    one_way = one_way_cost(df["adv30_usd"].to_numpy())
    df["net"] = df["ret"] - 2 * one_way
    df["stress"] = df["ret"] - 2 * (FEE_ONE_WAY + 3 * (one_way - FEE_ONE_WAY))
    df.to_parquet(OUT / "holdout_s0drop5_trades.parquet", index=False)

    def stat(sub: pd.DataFrame, col: str = "net") -> dict:
        if len(sub) == 0:
            return {"n": 0}
        weeks = (sub["entry_time"].astype("int64") // (7 * 24 * 3600 * 10**9)).to_numpy()
        lo, hi = cluster_boot(sub[col].to_numpy(dtype=float), weeks)
        return {"n": int(len(sub)), "mean": float(sub[col].mean()), "lo": lo, "hi": hi,
                "median": float(sub[col].median()), "win": float((sub[col] > 0).mean())}

    main = df[(df["kind"] == "cascade") & (df["delay"] == "d0")].sort_values("entry_time")
    bench = df[(df["kind"] == "bench") & (df["delay"] == "d0")]
    m, b = stat(main), stat(bench)
    pass1 = bool(m.get("mean", -1) > 0 and m.get("lo", -1) > 0)
    pass2 = bool(m.get("mean", -1) > b.get("mean", np.inf))

    top = pd.Series(all_casc_t0).dt.floor("D").value_counts().head(TOP_DAYS)
    cum = main["net"].cumsum()
    mdd = float((cum - cum.cummax()).min()) if len(cum) else np.nan
    month = main["t0"].dt.to_period("M").astype(str)
    monthly = {k: {"n": int(len(g)), "sum": float(g["net"].sum()), "mean": float(g["net"].mean())} for k, g in main.groupby(month)}
    res = {
        "commit": commit, "period": ["2025-01-01", "2026-08-31"], "condition": "S0-drop5 x 4h",
        "main": m, "bench": b, "pass_1_mean_and_ci_above_0": pass1, "pass_2_beats_bench": pass2, "pass": pass1 and pass2,
        "practical": {
            "delay_5min": stat(df[(df["kind"] == "cascade") & (df["delay"] == "d5")]),
            "delay_15min": stat(df[(df["kind"] == "cascade") & (df["delay"] == "d15")]),
            "slippage_x3": stat(main, "stress"),
            "top10_days_removed": stat(main[~main["t0"].dt.floor("D").isin(top.index)]),
            "top10_days": [str(d.date()) for d in top.index],
            "per_month_avg_count": float(np.mean([v["n"] for v in monthly.values()])) if monthly else 0.0,
            "monthly": monthly,
            "cumulative_sum": float(cum.iloc[-1]) if len(cum) else np.nan,
            "max_drawdown": mdd,
        },
    }
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("main", "bench", "pass_1_mean_and_ci_above_0", "pass_2_beats_bench", "pass")},
                     ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    {"check": check, "run": run}[sys.argv[1]]()
