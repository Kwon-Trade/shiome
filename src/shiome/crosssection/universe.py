"""データの掃除と、比較対象(ユニバース)の足切り。定義は docs/hypotheses_v2.md の「掃除」「足切り」。

毎日UTC0時(判断時刻 t)ごとに、各銘柄を比較対象に入れるかを「t より前に確定したデータだけ」で決める。
t の時点で使えるのは、開始時刻が t-1時間以前の1時間足(= t までに閉じた足)だけ。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.crosssection.data import HOUR, load_futures_hourly, listing_time

MIN_ADV_USD = 5_000_000       # 過去30日の1日平均出来高(USD)の下限。固定値なので未来の情報を含まない
ADV_DAYS = 30
MIN_COVERAGE = 0.9            # 30日の窓のうちデータがある時間の割合の下限
NEW_LISTING_EXCLUDE_DAYS = 7  # 先物上場から最初の7日間は除外
DEAD_LOOKBACK_HOURS = 24      # 直前24時間に出来高ゼロの時間が1つでもあれば除外

REASONS = ("足が無い", "取引停止後", "直前24hに出来高ゼロ", "上場7日以内", "出来高の履歴不足", "出来高が基準未満", "対象")


def daily_universe(symbol: str, end: pd.Timestamp, min_adv_usd: float = MIN_ADV_USD) -> pd.DataFrame:
    h = load_futures_hourly(symbol, end)
    if h is None:
        return pd.DataFrame()
    first_bar = h.index[0]
    listed = listing_time(symbol, first_bar)

    zero = (h["present"] & (h["volume"] <= 0)).astype(int)
    dead_24h = zero.rolling(DEAD_LOOKBACK_HOURS, min_periods=1).max().astype(bool)
    live = h["present"] & (h["volume"] > 0)
    last_live = live[live].index.max() if live.any() else first_bar - HOUR

    win = ADV_DAYS * 24
    qv_sum = h["quote_volume"].fillna(0).rolling(win, min_periods=1).sum()
    n_present = h["present"].astype(int).rolling(win, min_periods=1).sum()

    # 判断時刻 t = 毎日0時。t-1時間の足が手元データの範囲にある日だけ。
    days = pd.date_range(first_bar.ceil("D"), (h.index[-1] + HOUR).floor("D"), freq="D")
    days = days[(days - HOUR >= first_bar) & (days < end)]  # 判断時刻も読み込み範囲の内側だけ
    last = days - HOUR  # t までに閉じた最後の足

    age_days = (days - listed) / pd.Timedelta(days=1)
    expected = np.minimum(win, ((days - listed) / HOUR).to_numpy())
    got = n_present.reindex(last).to_numpy()
    adv = qv_sum.reindex(last).to_numpy() / np.where(got > 0, got, np.nan) * 24
    coverage = got / np.where(expected > 0, expected, np.nan)

    out = pd.DataFrame({
        "t": days,
        "symbol": symbol,
        "has_bar": h["present"].reindex(last).to_numpy(),
        "halted": (last > last_live),
        "dead_24h": dead_24h.reindex(last).to_numpy(),
        "age_days": age_days.to_numpy(),
        "adv30_usd": adv,
        "adv_coverage": coverage,
    })
    reason = np.select(
        [~out["has_bar"], out["halted"], out["dead_24h"], out["age_days"] < NEW_LISTING_EXCLUDE_DAYS,
         ~(out["adv_coverage"] >= MIN_COVERAGE), ~(out["adv30_usd"] >= min_adv_usd)],
        list(REASONS[:-1]), default=REASONS[-1],
    )
    out["reason"] = reason
    out["eligible"] = out["reason"] == REASONS[-1]
    return out
