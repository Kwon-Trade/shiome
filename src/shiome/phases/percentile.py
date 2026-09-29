"""銘柄ごと・時点ごとの「過去90日ローリング窓でのパーセンタイル順位」を計算する。

docs/methodology.md #1: 判定時点より前のデータだけを使う(先読み防止)。
窓が埋まるまで(=最初の90日間)はNaNになり、局面判定も行われない(助走期間)。
"""
from __future__ import annotations

import pandas as pd

from shiome.config import load_settings


def rolling_percentile_rank(series: pd.Series) -> pd.Series:
    """各時点について、直近90日(自分自身を含む)の中での百分位順位(0〜100)を返す。"""
    settings = load_settings()
    window_hours = settings["validation"]["percentile_lookback_days"] * 24
    return series.rolling(window_hours, min_periods=window_hours).rank(pct=True) * 100
