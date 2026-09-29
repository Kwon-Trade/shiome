"""グループ分け(大型 / 中型アルト / 小型・ミーム)。docs/hypotheses_v2.md §5。

銘柄数が組によって違う(全銘柄 約390 / 第1ラウンドの61)ため、固定の名簿ではなく
毎日その時点の出来高で分ける(未来の情報を使わない):
- 大型: 第1ラウンドと同じ10銘柄(固定)
- 残りのうち、その日の対象銘柄を過去30日の平均出来高で並べ、上半分 = 中型アルト、下半分 = 小型・ミーム
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import load_symbols


def assign_groups(panel: pd.DataFrame) -> pd.DataFrame:
    large = set(load_symbols()["groups"]["large_cap"])
    panel = panel.copy()
    is_large = panel["symbol"].isin(large)
    rest = panel["eligible"] & ~is_large
    pct = panel.loc[rest].groupby("t")["adv30_usd"].rank(pct=True, method="first")
    panel["group"] = np.where(is_large, "large_cap", "")
    panel.loc[pct.index, "group"] = np.where(pct > 0.5, "mid_cap_alt", "small_meme")
    return panel
