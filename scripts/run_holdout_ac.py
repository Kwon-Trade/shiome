#!/usr/bin/env python3
"""仮説A・Cの答え合わせ(2025年以降)。合格基準は docs/methodology.md #12。

基準を書いた状態がコミット済みであることを確認してから実行し、そのコミットを結果に記録する。

実行例:
    python scripts/run_holdout_ac.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from tqdm import tqdm  # noqa: E402

from shiome.config import PROCESSED_DIR, load_symbols  # noqa: E402
from shiome.eventstudy.holdout import (  # noqa: E402
    _holdout_start_ms, auc_uplift, first_futures_time, lift, symbol_table, train_models,
)
from shiome.validation.regroup import historical_volume_groups  # noqa: E402

ES_DIR = PROCESSED_DIR / "event_study"

# docs/methodology.md #12 の基準(結果を見た後に変更しない)
A_LIFT_MIN, A_CI_LO_MIN = 1.5, 1.2
C_LIFT_MAX = 0.7
A_LO, A_HI = 10, 90
C_LO, C_HI = 40, 60


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def evaluate(table: pd.DataFrame, models: dict, fr_col: str = "funding_rate") -> dict:
    a = lift(table, fr_col, A_LO, A_HI, band=False)
    c = lift(table, fr_col, C_LO, C_HI, band=True)
    u = auc_uplift(table, models)
    return {
        "A": {**a, "pass": bool(a["lift"] >= A_LIFT_MIN and a["ci_lo"] >= A_CI_LO_MIN)},
        "C": {**c, "pass": bool(c["lift"] <= C_LIFT_MAX)},
        "AUC": {**u, "pass": bool(u["diff_ci_lo"] > 0)},
        "A_surge_only": lift(table, fr_col, A_LO, A_HI, band=False, event_kinds=("surge",)),
        "A_crash_only": lift(table, fr_col, A_LO, A_HI, band=False, event_kinds=("crash",)),
        "n_symbols": int(table["symbol"].nunique()),
    }


def main() -> None:
    if _git("status", "--porcelain", "docs/methodology.md", "src/shiome/eventstudy/holdout.py", "scripts/run_holdout_ac.py"):
        sys.exit("合格基準または評価コードに未コミットの変更があります。先にコミットしてください。")
    commit = _git("rev-parse", "HEAD")

    symbols_cfg = load_symbols()
    delisted = set(symbols_cfg["delisted"])
    group_of = {s: g for g, ss in historical_volume_groups().items() for s in ss}
    rule_samples = pd.read_parquet(ES_DIR / "samples.parquet")
    cohort51 = set(rule_samples["symbol"].unique())
    holdout_ms = _holdout_start_ms()

    frames = []
    for symbol in tqdm(sorted(group_of), desc="答え合わせ期間のデータ"):
        first = first_futures_time(symbol)
        if first is None:
            continue
        t = symbol_table(symbol, symbol in delisted)
        if t.empty:
            continue
        t["group"] = group_of[symbol]
        t["cohort"] = "cohort51" if symbol in cohort51 else ("new" if first >= holdout_ms else "other")
        frames.append(t)
    table = pd.concat(frames, ignore_index=True)

    models = train_models(rule_samples)
    main51 = table[(table["cohort"] == "cohort51") & (table["group"] == "small_meme")]
    new = table[table["cohort"] == "new"]

    results = {
        "preregistration_commit": commit,
        "criteria": {"A_lift_min": A_LIFT_MIN, "A_ci_lo_min": A_CI_LO_MIN, "C_lift_max": C_LIFT_MAX},
        "main_cohort51_small_meme": evaluate(main51, models),
        "new_listings": evaluate(new, models),
        "reference": {
            "cohort51_small_meme_fr_diff": evaluate(main51, models, "funding_rate_diff"),
            "new_listings_fr_diff": evaluate(new, models, "funding_rate_diff"),
            "cohort51_large_cap": evaluate(table[(table["cohort"] == "cohort51") & (table["group"] == "large_cap")], models),
            "cohort51_mid_cap_alt": evaluate(table[(table["cohort"] == "cohort51") & (table["group"] == "mid_cap_alt")], models),
        },
        "symbols": {c: sorted(table.loc[table["cohort"] == c, "symbol"].unique()) for c in ("cohort51", "new", "other")},
    }
    other = table[table["cohort"] == "other"]
    if other["symbol"].nunique() > 0:
        results["reference"]["other_listings"] = evaluate(other, models)

    m = results["main_cohort51_small_meme"]
    results["verdict_pass"] = bool(m["A"]["pass"] and m["C"]["pass"] and m["AUC"]["pass"])

    out = ES_DIR / "holdout_ac.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print("基準のコミット:", commit)
    print(json.dumps({k: results[k] for k in ("main_cohort51_small_meme", "new_listings", "verdict_pass")},
                     ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
