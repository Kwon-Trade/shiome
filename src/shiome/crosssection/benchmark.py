"""物差しとの比較(H1・H4・H6)。docs/hypotheses_v2.md §6。

毎日、銘柄間で「その後の値動きの順位」を「調べたい数値の順位」と物差し
(H2-7・H2-14・H2-28・H3・過去24時間の値幅)の順位で回帰し(Fama–MacBeth法)、
調べたい数値の係数(予想の向きをプラス)の日平均と95%の幅を出す。物差しなしの係数も並べる。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.crosssection.evaluate import BLOCK_DAYS, MIN_N_ALL, SIGNALS, _slice, block_boot_mean

CONTROLS = ("h2_7", "h2_14", "h2_28", "h3_ret24", "range24")


def _centered_rank(x: pd.Series) -> np.ndarray:
    return (x.rank(pct=True) - 0.5).to_numpy()


def daily_coefs(panel: pd.DataFrame, hyp: str, horizon: str) -> pd.DataFrame:
    col, direction, _ = SIGNALS[hyp]
    need = [col, *CONTROLS, f"fwd_{horizon}"]
    d = panel[panel["eligible"]].dropna(subset=need)
    rows = []
    for t, g in d.groupby("t", sort=True):
        if len(g) < MIN_N_ALL:
            continue
        y = _centered_rank(g[f"fwd_{horizon}"])
        x = _centered_rank(direction * g[col])
        ctrl = np.column_stack([_centered_rank(g[c]) for c in CONTROLS])
        alone = np.linalg.lstsq(np.column_stack([np.ones(len(g)), x]), y, rcond=None)[0][1]
        full = np.linalg.lstsq(np.column_stack([np.ones(len(g)), x, ctrl]), y, rcond=None)[0][1]
        rows.append({"t": t, "alone": alone, "controlled": full})
    return pd.DataFrame(rows)


def fama_macbeth(panel: pd.DataFrame, hyp: str, horizon: str, periods: list[str]) -> dict:
    coefs = daily_coefs(panel, hyp, horizon)
    out = {}
    for per in periods:
        c = _slice(coefs, "t", per) if len(coefs) else coefs
        r = {"n_days": int(len(c))}
        for key in ("alone", "controlled"):
            if len(c):
                v = c[key].to_numpy(dtype=float)
                r[key] = float(np.mean(v))
                r[f"{key}_lo"], r[f"{key}_hi"] = block_boot_mean(v, BLOCK_DAYS[horizon])
        out[per] = r
    return out
