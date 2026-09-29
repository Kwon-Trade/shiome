#!/usr/bin/env python3
"""答え合わせ(2025-01-01〜2026-08-31): H5 と F1 の2つだけを1回だけ計算する。docs/hypotheses_v2.md A1〜A3。

    python scripts/run_holdout_v2.py check   # 2025年以降のデータの点検だけ(成績は計算しない)
    python scripts/run_holdout_v2.py run     # 答え合わせ(1回だけ。2回目は止まる)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from shiome.config import CONFIGS_DIR, PROCESSED_DIR  # noqa: E402
from shiome.crosssection import data as cs_data  # noqa: E402
from shiome.crosssection.caution import daily_caution, summarize as f1_summary  # noqa: E402
from shiome.crosssection.evaluate import PERIODS, evaluate  # noqa: E402
from shiome.crosssection.panel import symbol_panel  # noqa: E402

OUT_DIR = PROCESSED_DIR / "crosssection"
PANEL = OUT_DIR / "panel_holdout.parquet"
RESULT = OUT_DIR / "holdout_v2.json"
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-09-01")
GUARDED = ("docs/hypotheses_v2.md", "configs/holdout_non_crypto.yaml", "configs/universe_2025_2026.yaml",
           "src/shiome/crosssection", "scripts/run_holdout_v2.py")
PERIODS["holdout"] = ("2025-01-01", "2026-09-01")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def build_panel() -> pd.DataFrame:
    if PANEL.exists():
        return pd.read_parquet(PANEL)
    cs_data.allow_holdout()
    symbols = yaml.safe_load((CONFIGS_DIR / "universe_2025_2026.yaml").read_text(encoding="utf-8"))["symbols"]
    frames = []
    for s in sorted(symbols):
        p = symbol_panel(s, cs_data.HOLDOUT_END, with_oi=True)
        if not p.empty:
            frames.append(p[p["t"] >= START - pd.Timedelta(days=40)])
    panel = pd.concat(frames, ignore_index=True)
    assert panel["t"].max() < END
    panel.to_parquet(PANEL, index=False)
    return panel


def check() -> None:
    """データの点検だけ。値動きの成績(H5・F1)は計算しない。"""
    panel = build_panel()
    h = panel[panel["t"] >= START]
    e = h[h["eligible"]]
    print("答え合わせ期間の判断日:", h["t"].min().date(), "〜", h["t"].max().date())
    print("比較対象になった銘柄:", e["symbol"].nunique(), " 1日あたりの対象数(月ごとの中央値):")
    print(e.groupby(e["t"].dt.to_period("M")).size().div(e.groupby(e["t"].dt.to_period("M"))["t"].nunique()).round(0).to_dict())
    print("除外理由(銘柄×日):", h["reason"].value_counts().to_dict())
    print("建玉の7日変化率がある割合(対象の銘柄×日、月ごと):")
    print(e.groupby(e["t"].dt.to_period("M"))["h4_oi7"].apply(lambda x: round(x.notna().mean(), 3)).to_dict())
    print("24時間後の値動きがある割合(対象):", round(e["fwd_24h"].notna().mean(), 4))
    # 1時間で±50%を超える値動き(対象になった日の前後)
    cs_data.allow_holdout()
    rows = []
    for s, g in e.groupby("symbol"):
        hh = cs_data.load_futures_hourly(s, cs_data.HOLDOUT_END)
        r = hh["close"].pct_change(fill_method=None)
        a, b = g["t"].min() - pd.Timedelta(days=1), g["t"].max() + pd.Timedelta(days=2)
        j = r[(r.abs() > 0.5) & (r.index >= a) & (r.index <= b)]
        for t, v in j.items():
            rows.append((s, str(t), round(float(v), 3), round(float(hh.loc[t, "quote_volume"]) / 1e6, 1)))
    print(f"1時間で±50%を超える値動き: {len(rows)}件 (銘柄, 時刻, 変化, その1時間の出来高[百万ドル])")
    for row in rows:
        print("   ", row)


def run() -> None:
    if _git("status", "--porcelain", *GUARDED):
        sys.exit("条件の記録または計算コードに未コミットの変更があります。先にコミットしてください。")
    if RESULT.exists():
        sys.exit("答え合わせは計算済みです(1回だけ)。")
    commit = _git("rev-parse", "HEAD")
    panel = build_panel()

    h5 = evaluate(panel, "H5", "24h", ["holdout"])["holdout"]
    h5_pass = bool(h5.get("ic", np.nan) > 0 and h5.get("win", np.nan) > 0.5 and h5.get("pf_net", np.nan) > 0)

    f1 = {}
    for hz in ("24h", "7d"):
        d = daily_caution(panel, hz)
        d = d[(d["t"] >= START) & (d["t"] < END)]
        f1[hz] = f1_summary(d)
    res = {"commit": commit, "period": ["2025-01-01", "2026-08-31"],
           "H5": {"24h": h5, "pass": h5_pass},
           "F1": {"24h": f1["24h"], "7d_reference": f1["7d"], "pass": f1["24h"].get("pass", False)}}
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    {"check": check, "run": run}[sys.argv[1]]()
