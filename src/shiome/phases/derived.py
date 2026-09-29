"""局面判定に使う派生指標(価格変化率・値幅・高値からの下落率)を計算する。

全て「その時点までの過去データ」だけを使う(先読みなし)。
"""
from __future__ import annotations

import pandas as pd

from shiome.config import load_settings


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    settings = load_settings()
    lookback_days = settings["validation"]["price_zone_high"]["lookback_days"]
    lookback_hours = lookback_days * 24

    df = df.copy()
    df["price_chg_24h"] = df["close"].pct_change(24)

    # 値幅(直近24時間のレンジ)。⑥「値幅縮小」の判定に使う。
    df["range_24h"] = (df["high"].rolling(24).max() - df["low"].rolling(24).min()) / df["close"]

    # 過去N日高値からの下落率。④「価格高値圏」の判定に使う(docs/methodology.md #10)。
    rolling_high = df["high"].rolling(lookback_hours, min_periods=lookback_hours).max()
    df["drawdown_from_high"] = (rolling_high - df["close"]) / rolling_high

    return df
