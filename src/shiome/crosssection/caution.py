"""F1「要注意フィルター」。定義は docs/hypotheses_v2.md A1。

毎日0時の比較対象のうち、①上場から90日以内 ②過去7日の建玉増加率が上位20% ③過去24時間の上昇率が上位20%
のどれかに当てはまる銘柄を「要注意」とし、要注意(均等)と残り(均等)のその後の値動きを比べる。
売買コストは差し引かない(買う銘柄から外すふるいとして使うため)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.crosssection.evaluate import MIN_N_ALL, block_boot_mean

NEW_LISTING_DAYS = 90
TOP_PCT = 0.2
BLOCK_DAYS = 7
PASS_WIN = 0.52


def _top(g: pd.DataFrame, col: str) -> set[str]:
    v = g[g[col].notna()]
    if len(v) == 0:
        return set()
    k = max(1, int(round(TOP_PCT * len(v))))
    order = v.sort_values([col, "symbol"], ascending=[False, True])["symbol"].tolist()
    return set(order[:k])


def daily_caution(panel: pd.DataFrame, horizon: str) -> pd.DataFrame:
    d = panel[panel["eligible"]]
    rows = []
    for t, g in d.groupby("t", sort=True):
        if len(g) < MIN_N_ALL:
            continue
        flagged = set(g.loc[g["age_days"] <= NEW_LISTING_DAYS, "symbol"]) | _top(g, "h4_oi7") | _top(g, "h3_ret24")
        is_f = g["symbol"].isin(flagged)
        f_ret, r_ret = g.loc[is_f, f"fwd_{horizon}"], g.loc[~is_f, f"fwd_{horizon}"]
        if is_f.sum() == 0 or (~is_f).sum() == 0 or f_ret.notna().sum() == 0 or r_ret.notna().sum() == 0:
            continue
        diff = f_ret.mean() - r_ret.mean()
        rows.append({"t": t, "diff": diff, "rest_win": float(r_ret.mean() > f_ret.mean()),
                     "n": len(g), "n_flagged": int(is_f.sum()),
                     "n_new": int((g["age_days"] <= NEW_LISTING_DAYS).sum())})
    return pd.DataFrame(rows)


def summarize(daily: pd.DataFrame) -> dict:
    if len(daily) == 0:
        return {"n_days": 0}
    lo, hi = block_boot_mean(daily["diff"].to_numpy(dtype=float), BLOCK_DAYS)
    win_lo, win_hi = block_boot_mean(daily["rest_win"].to_numpy(dtype=float), BLOCK_DAYS)
    out = {"n_days": int(len(daily)), "rest_win": float(daily["rest_win"].mean()), "rest_win_lo": win_lo, "rest_win_hi": win_hi,
           "diff": float(daily["diff"].mean()), "diff_lo": lo, "diff_hi": hi,
           "avg_n": float(daily["n"].mean()), "avg_flagged": float(daily["n_flagged"].mean()),
           "avg_new": float(daily["n_new"].mean())}
    out["pass"] = bool(out["rest_win"] > PASS_WIN and not np.isnan(hi) and hi < 0)
    return out
