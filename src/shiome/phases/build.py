"""ステージ3: 指標(data/processed/indicators/)から局面判定を計算し、
data/processed/phases/ に保存する。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from shiome.config import PROCESSED_DIR
from shiome.phases.rules import compute_phases

INDICATORS_DIR = PROCESSED_DIR / "indicators"
PHASES_DIR = PROCESSED_DIR / "phases"


def build_symbol_phases(symbol: str, thresholds: dict | None = None) -> pd.DataFrame | None:
    path = INDICATORS_DIR / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    has_spot = df["spot_cvd"].notna().any()
    df = compute_phases(df, has_spot=has_spot, thresholds=thresholds)
    return df


def build_and_save(symbol: str) -> Path | None:
    df = build_symbol_phases(symbol)
    if df is None:
        return None
    PHASES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PHASES_DIR / f"{symbol}.parquet"
    df.to_parquet(out_path, index=False)
    return out_path
