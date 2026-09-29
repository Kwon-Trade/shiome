"""同じ時間帯に多数の銘柄で一斉に出たシグナルを、まとめて1件として数える集計用。"""
from __future__ import annotations

import pandas as pd

NUMERIC_COLS_PREFIX = ("ret_", "mae_", "cost_pct")


def dedup_simultaneous(events: pd.DataFrame) -> pd.DataFrame:
    """同じ局面・同じ時刻(1時間単位)に複数銘柄でシグナルが出た場合、
    1件にまとめる(数値列は銘柄をまたいだ平均値を採用)。"""
    if events.empty:
        return events

    numeric_cols = [c for c in events.columns if c.startswith(NUMERIC_COLS_PREFIX)]
    other_cols = [c for c in events.columns if c not in numeric_cols]

    agg = {c: "mean" for c in numeric_cols}
    agg["symbol"] = lambda s: ",".join(sorted(set(s)))
    for c in other_cols:
        if c not in agg and c not in ("phase", "entry_time_ms"):
            agg[c] = "first"

    grouped = events.groupby(["phase", "entry_time_ms"], as_index=False).agg(agg)
    return grouped
