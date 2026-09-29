#!/usr/bin/env python3
"""ステージ4: 検証。局面ごと・グループごとの成績を集計し、
data/processed/validation/ に結果を保存する。

実行例:
    python scripts/build_validation.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from tqdm import tqdm  # noqa: E402

from shiome.config import PROCESSED_DIR, load_settings, load_symbols  # noqa: E402
from shiome.validation.aggregate import summarize_group_period  # noqa: E402
from shiome.validation.dedup_signals import dedup_simultaneous  # noqa: E402
from shiome.validation.events import build_symbol_events  # noqa: E402
from shiome.validation.regroup import historical_volume_groups  # noqa: E402

VALIDATION_DIR = PROCESSED_DIR / "validation"


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(f"not serializable: {type(o)}")


def build_all_events() -> pd.DataFrame:
    symbols_cfg = load_symbols()
    delisted = set(symbols_cfg["delisted"])
    groups = historical_volume_groups()
    all_symbols = sorted(set(s for g in groups.values() for s in g))

    frames = []
    for symbol in tqdm(all_symbols, desc="イベント作成"):
        df = build_symbol_events(symbol, is_delisted=(symbol in delisted))
        if not df.empty:
            frames.append(df)
    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return events


def main() -> None:
    settings = load_settings()
    groups = historical_volume_groups()

    print("イベントを作成中(全銘柄・全局面)...")
    events = build_all_events()
    print(f"総イベント数: {len(events)}")

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    events.to_parquet(VALIDATION_DIR / "events.parquet", index=False)

    rule_start = pd.Timestamp(settings["date_range"]["start"])
    rule_end = pd.Timestamp(settings["split"]["rule_building_end"])
    holdout_start = pd.Timestamp(settings["split"]["holdout_start"])
    holdout_end = pd.Timestamp.now()

    results = {"holdout": {}, "rule_building": {}, "holdout_dedup": {}, "symbol_split_half_b": {}}

    print("グループ別・答え合わせ期間(主結果)を集計中...")
    for g, symbols in groups.items():
        results["holdout"][g] = summarize_group_period(events, symbols, holdout_start, holdout_end)

    print("グループ別・ルール作り期間(参考)を集計中...")
    for g, symbols in groups.items():
        results["rule_building"][g] = summarize_group_period(events, symbols, rule_start, rule_end)

    print("同時多発シグナルの重複排除版(答え合わせ期間)を集計中...")
    events_dedup = dedup_simultaneous(events)
    for g, symbols in groups.items():
        results["holdout_dedup"][g] = summarize_group_period(events_dedup, symbols, holdout_start, holdout_end)

    print("銘柄ランダム半分割(補助検証、全期間)を集計中...")
    seed = settings["validation"]["random_symbol_split_seed"]
    rng = np.random.default_rng(seed)
    all_symbols = sorted(set(s for g in groups.values() for s in g))
    shuffled = list(all_symbols)
    rng.shuffle(shuffled)
    half_b = set(shuffled[len(shuffled) // 2:])
    for g, symbols in groups.items():
        half_b_symbols = [s for s in symbols if s in half_b]
        results["symbol_split_half_b"][g] = summarize_group_period(events, half_b_symbols, rule_start, holdout_end)

    out_path = VALIDATION_DIR / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=_json_default)

    # groupsも保存しておく(レポート作成時に使う)
    with open(VALIDATION_DIR / "groups.json", "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    print(f"\n完了。結果を保存しました: {out_path}")


if __name__ == "__main__":
    main()
