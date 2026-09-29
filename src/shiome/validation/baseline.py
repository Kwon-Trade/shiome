"""「全期間の平均的な値動き」の基準値を計算する(局面と比べる物差し)。

局面で絞り込まずに、対象グループの全時間について
「次の足の始値で買って(売って)N時間後の始値で決済したら」の
リターン分布を求める。エントリー方式は events.py と揃える(先読み無し)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import PROCESSED_DIR
from shiome.validation.events import HORIZONS


def symbol_baseline_returns(symbol: str, period_start: pd.Timestamp, period_end: pd.Timestamp) -> dict[int, np.ndarray]:
    """銘柄1つ分、各時間幅の「次の足始値エントリー→N時間後始値決済」リターン配列(方向なし)。"""
    path = PROCESSED_DIR / "phases" / f"{symbol}.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path, columns=["open_time", "open"])
    dt = pd.to_datetime(df["open_time"], unit="ms")
    in_period = (dt >= period_start) & (dt <= period_end)
    open_ = df["open"].astype(float).values

    out = {}
    for h in HORIZONS:
        entry = open_[:-1-h] if h + 1 < len(open_) else np.array([])
        exit_ = open_[1+h:] if h + 1 < len(open_) else np.array([])
        mask = in_period.values[: len(entry)]
        if len(entry) == 0:
            out[h] = np.array([])
            continue
        ret = exit_ / entry - 1
        out[h] = ret[mask]
    return out


def group_baseline(symbols: list[str], period_start: pd.Timestamp, period_end: pd.Timestamp) -> dict[int, dict]:
    """グループ内の全銘柄をまとめた基準値: 上昇率(方向の的中率の基準)と平均絶対値幅。"""
    combined: dict[int, list[np.ndarray]] = {h: [] for h in HORIZONS}
    for symbol in symbols:
        r = symbol_baseline_returns(symbol, period_start, period_end)
        for h in HORIZONS:
            if h in r and len(r[h]) > 0:
                combined[h].append(r[h])

    result = {}
    for h in HORIZONS:
        if combined[h]:
            arr = np.concatenate(combined[h])
        else:
            arr = np.array([])
        result[h] = {
            "up_rate": float((arr > 0).mean()) if len(arr) else float("nan"),
            "down_rate": float((arr < 0).mean()) if len(arr) else float("nan"),
            "avg_abs_return": float(np.abs(arr).mean()) if len(arr) else float("nan"),
            "n": int(len(arr)),
        }
    return result
