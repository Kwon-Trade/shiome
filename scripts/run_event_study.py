#!/usr/bin/env python3
"""イベントスタディ(逆引き分析)。ルール作り期間(2022〜2024年)だけを使う。

結果は data/processed/event_study/ に保存する。

実行例:
    python scripts/run_event_study.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from tqdm import tqdm  # noqa: E402

from shiome.config import PROCESSED_DIR, load_settings  # noqa: E402
from shiome.eventstudy.combos import evaluate  # noqa: E402
from shiome.eventstudy.samples import build_symbol_samples  # noqa: E402
from shiome.eventstudy.stats import compare_single, extremeness_by_year, group_breakdown  # noqa: E402
from shiome.validation.regroup import historical_volume_groups  # noqa: E402

OUT_DIR = PROCESSED_DIR / "event_study"


def main() -> None:
    settings = load_settings()
    rng = np.random.default_rng(settings["validation"]["random_symbol_split_seed"])
    groups = historical_volume_groups()

    frames = []
    for group, symbols in groups.items():
        for symbol in tqdm(symbols, desc=f"サンプル作成({group})"):
            df = build_symbol_samples(symbol, group, rng)
            if not df.empty:
                frames.append(df)
    samples = pd.concat(frames, ignore_index=True)

    holdout_ms = int(pd.Timestamp(settings["split"]["holdout_start"]).timestamp() * 1000)
    assert samples["open_time"].max() < holdout_ms, "答え合わせ期間のデータが混入している"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    samples.to_parquet(OUT_DIR / "samples.parquet", index=False)
    print("サンプル数:", samples["kind"].value_counts().to_dict(), "銘柄数:", samples["symbol"].nunique())

    print("単独指標の比較(ブロック・ブートストラップ込み)...")
    compare_single(samples).to_parquet(OUT_DIR / "single.parquet", index=False)

    print("極端さ(両端で起きやすいか)の年別比較...")
    extremeness_by_year(samples).to_parquet(OUT_DIR / "extremeness.parquet", index=False)

    print("グループ別の内訳...")
    group_breakdown(samples).to_parquet(OUT_DIR / "by_group.parquet", index=False)

    print("組み合わせの評価(2022〜2023年で学習→2024年で評価)...")
    combos = evaluate(samples)
    combos["features"] = combos["features"].apply(lambda t: "|".join(t))
    combos.to_parquet(OUT_DIR / "combos.parquet", index=False)

    print("完了:", OUT_DIR)


if __name__ == "__main__":
    main()
