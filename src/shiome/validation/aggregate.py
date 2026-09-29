"""局面ごと・グループごとの成績を集計し、合格判定を行う。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import load_settings
from shiome.validation.baseline import group_baseline
from shiome.validation.bootstrap import block_bootstrap_ci
from shiome.validation.events import HORIZONS

PHASE_KEYS = [
    "1_healthy_uptrend", "2_overleveraged_uptrend", "3_short_squeeze_setup",
    "4_distribution_top", "5_capitulation_bottom", "6_compression",
]


def _block_id(entry_time_ms: pd.Series) -> pd.Series:
    settings = load_settings()
    block_days = settings["validation"]["bootstrap"]["block_days"]
    block_ms = block_days * 24 * 3600 * 1000
    return entry_time_ms // block_ms


def summarize_phase(events: pd.DataFrame, baseline: dict, primary_horizon: int, min_n: int) -> dict:
    """1局面・1グループ分の events(その局面だけに絞り込み済み)を集計する。"""
    n = len(events)
    result = {"n": n, "insufficient": n < min_n}
    if n == 0:
        return result

    dir_sign = events["dir_sign"].iloc[0]
    block_ids = _block_id(events["entry_time_ms"])

    for h in HORIZONS:
        ret_col = f"ret_{h}h"
        valid = events[ret_col].notna()
        vals = events.loc[valid, ret_col].astype(float)
        blocks = block_ids[valid]
        mae_col = f"mae_{h}h"
        mae_vals = events.loc[valid, mae_col].astype(float)
        n_eval = int(valid.sum())

        entry = {
            "n_eval": n_eval,
            "avg_return_pct": float(vals.mean() * 100) if n_eval else None,
            "avg_mae_pct": float(mae_vals.mean() * 100) if n_eval and dir_sign != 0 else None,
        }

        if n_eval > 0:
            if dir_sign != 0:
                hit_indicator = (vals > 0).astype(float)
                baseline_hit_rate = baseline[h]["up_rate"] if dir_sign > 0 else baseline[h]["down_rate"]
            else:
                baseline_abs = baseline[h]["avg_abs_return"]
                hit_indicator = (vals.abs() > baseline_abs).astype(float)
                baseline_hit_rate = 0.5  # 「基準より値幅が大きい/小さい」を五分五分とみなす

            hit_mean, hit_lo, hit_hi = block_bootstrap_ci(hit_indicator, blocks)
            ret_mean, ret_lo, ret_hi = block_bootstrap_ci(vals.abs() if dir_sign == 0 else vals, blocks)
            cost_mean = float(events.loc[valid, "cost_pct"].mean())

            entry.update({
                "hit_rate_pct": hit_mean * 100,
                "hit_rate_ci_lo_pct": hit_lo * 100,
                "baseline_hit_rate_pct": baseline_hit_rate * 100 if baseline_hit_rate == baseline_hit_rate else None,
                "avg_cost_pct": cost_mean,
                "return_ci_lo_pct": ret_lo * 100,
                "clearly_better_direction": bool(hit_lo * 100 > baseline_hit_rate * 100) if baseline_hit_rate == baseline_hit_rate else False,
                "beats_cost": bool(ret_lo * 100 > cost_mean),
            })
            entry["passes"] = bool(entry["clearly_better_direction"] and entry["beats_cost"])
        result[f"h{h}"] = entry

    result["primary"] = result.get(f"h{primary_horizon}", {})
    result["passes_primary"] = bool(result["primary"].get("passes", False)) and not result["insufficient"]
    return result


def summarize_group_period(events: pd.DataFrame, group_symbols: list[str], period_start: pd.Timestamp, period_end: pd.Timestamp) -> dict:
    settings = load_settings()
    min_n = settings["validation"]["min_sample_size"]
    primary_h = settings["validation"]["primary_horizon_hours"]

    mask = (events["symbol"].isin(group_symbols)) & (events["entry_time_ms"] >= period_start.value // 10**6) & \
           (events["entry_time_ms"] <= period_end.value // 10**6)
    group_events = events[mask]

    baseline = group_baseline(group_symbols, period_start, period_end)

    out = {}
    for phase_key in PHASE_KEYS:
        phase_events = group_events[group_events["phase"] == phase_key]
        out[phase_key] = summarize_phase(phase_events, baseline, primary_h, min_n)
    out["_baseline"] = baseline
    out["_n_symbols"] = len(group_symbols)
    return out
