"""ブロック・ブートストラップで平均値の95%信頼区間を求める(docs/methodology.md #5)。

イベントを発生日(7日単位のブロック)でグループ化し、ブロック単位で復元抽出して
再集計するのを何度も繰り返すことで、時系列の連続性(同じ週に近い銘柄が同時にシグナルを
出しやすい、という相関)を保ったまま信頼区間を推定する。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import load_settings


def block_bootstrap_ci(values: pd.Series, block_ids: pd.Series, rng: np.random.Generator | None = None) -> tuple[float, float, float]:
    """(平均, 信頼区間下限, 信頼区間上限) を返す。"""
    settings = load_settings()
    boot_cfg = settings["validation"]["bootstrap"]
    n_resamples = boot_cfg["n_resamples"]
    conf = boot_cfg["confidence_level"]

    values = values.reset_index(drop=True)
    block_ids = block_ids.reset_index(drop=True)
    unique_blocks = block_ids.unique()
    if len(unique_blocks) == 0 or len(values) == 0:
        return float("nan"), float("nan"), float("nan")

    rng = rng or np.random.default_rng(settings["validation"]["random_symbol_split_seed"])
    grouped = {b: values[block_ids == b].to_numpy() for b in unique_blocks}
    n_blocks = len(unique_blocks)

    means = np.empty(n_resamples)
    for i in range(n_resamples):
        sampled_blocks = rng.choice(unique_blocks, size=n_blocks, replace=True)
        sampled_values = np.concatenate([grouped[b] for b in sampled_blocks])
        means[i] = sampled_values.mean()

    lo = (1 - conf) / 2 * 100
    hi = (1 + conf) / 2 * 100
    return float(values.mean()), float(np.percentile(means, lo)), float(np.percentile(means, hi))
