"""毎日0時(判断時刻 t)ごとの「銘柄×日」の表を作る。定義は docs/hypotheses_v2.md §3・§4。

並べる数値(シグナル)は t までに確定したデータだけで計算する:
- 価格 P(x) = x−1時間の足の終値(x までに閉じた足)
- FR は確定時刻が t より前のもの、建玉は記録時刻が t より前のもの
その後の値動き(fwd_*)だけが t より後のデータを使う。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.crosssection.data import (
    HOUR, load_funding, load_futures_hourly, load_open_interest, load_spot_quote_volume,
)
from shiome.crosssection.universe import daily_universe

DAY = pd.Timedelta(days=1)
HORIZONS = {"24h": 1, "7d": 7, "28d": 28}  # 日数
H2_LOOKBACKS = (7, 14, 28)
OI_MAX_STALENESS = pd.Timedelta(hours=2)
H6_MIN_COVERAGE = 0.9


def _price_at(close: pd.Series, times: pd.DatetimeIndex) -> np.ndarray:
    """時刻 x の価格 = x−1時間の足の終値(抜けならNaN)。"""
    return close.reindex(times - HOUR).to_numpy()


def _asof_before(series: pd.Series, times: pd.DatetimeIndex, max_age: pd.Timedelta) -> np.ndarray:
    """各時刻より前(その時刻ちょうどは含まない)の最後の値。max_ageより古ければNaN。"""
    if series.empty:
        return np.full(len(times), np.nan)
    idx = series.index.values
    pos = np.searchsorted(idx, times.values, side="left") - 1
    ok = pos >= 0
    vals = np.full(len(times), np.nan)
    vals[ok] = series.to_numpy()[pos[ok]]
    age = np.full(len(times), np.timedelta64("NaT"), dtype="timedelta64[ns]")
    age[ok] = times.values[ok] - idx[pos[ok]]
    vals[~(age <= np.timedelta64(max_age))] = np.nan
    return vals


def _window_sum_before(series: pd.Series, starts: pd.DatetimeIndex, ends: pd.DatetimeIndex) -> np.ndarray:
    """[start, end) に時刻が入る値の合計(FRの確定値など、不定期な記録用)。"""
    if series.empty:
        return np.full(len(starts), np.nan)
    idx = series.index.values
    csum = np.concatenate([[0.0], np.cumsum(series.to_numpy())])
    a = np.searchsorted(idx, starts.values, side="left")
    b = np.searchsorted(idx, ends.values, side="left")
    return csum[b] - csum[a]


def symbol_panel(symbol: str, end: pd.Timestamp, with_oi: bool = True) -> pd.DataFrame:
    uni = daily_universe(symbol, end)
    if uni.empty:
        return uni
    h = load_futures_hourly(symbol, end)
    t = pd.DatetimeIndex(uni["t"])
    close = h["close"]

    live = h["present"] & (h["volume"] > 0)
    last_live = live[live].index.max() if live.any() else h.index[0]
    stopped = last_live < end - HOUR  # 読み込み範囲の終わりより前に取引が止まった(上場廃止)
    last_price = close.loc[last_live]

    p_now = _price_at(close, t)
    out = uni.copy()
    out["price"] = p_now

    # ---- 並べる数値 ----
    fr = load_funding(symbol, end)
    out["h1_fr7"] = _window_sum_before(fr, t - 7 * DAY, t) / 7
    fr_start = fr.index[0] if not fr.empty else end
    out.loc[((t - 7 * DAY) < h.index[0]) | ((t - 7 * DAY) < fr_start - 8 * HOUR), "h1_fr7"] = np.nan  # 7日分のデータが無い

    p_1d = _price_at(close, t - DAY)
    for L in H2_LOOKBACKS:
        out[f"h2_{L}"] = p_1d / _price_at(close, t - (L + 1) * DAY) - 1
    out["h3_ret24"] = p_now / p_1d - 1

    if with_oi:
        oi = load_open_interest(symbol, end)
        oi = oi[oi > 0]
        oi_now = _asof_before(oi, t, OI_MAX_STALENESS)
        oi_7d = _asof_before(oi, t - 7 * DAY, OI_MAX_STALENESS)
        out["h4_oi7"] = oi_now / oi_7d - 1
    else:
        out["h4_oi7"] = np.nan

    out["h5_age"] = out["age_days"]

    spot_qv = load_spot_quote_volume(symbol, h.index, end)
    win = 7 * 24
    fut7 = h["quote_volume"].rolling(win, min_periods=int(win * H6_MIN_COVERAGE)).sum()
    spot7 = spot_qv.rolling(win, min_periods=int(win * H6_MIN_COVERAGE)).sum()
    ratio = (fut7 / spot7.where(spot7 > 0)).reindex(t - HOUR)
    out["h6_fs7"] = ratio.to_numpy()
    out["has_spot"] = bool(spot_qv.notna().any())

    hi = h["high"].rolling(24, min_periods=24).max().reindex(t - HOUR).to_numpy()
    lo = h["low"].rolling(24, min_periods=24).min().reindex(t - HOUR).to_numpy()
    out["range24"] = (hi - lo) / p_now

    # ---- その後の値動き(ここだけ t より後のデータを使う) ----
    for name, days in HORIZONS.items():
        exit_t = t + days * DAY
        p_exit = _price_at(close, exit_t)
        if stopped:
            after = (exit_t - HOUR) > last_live
            p_exit = np.where(after, last_price, p_exit)  # 途中で上場廃止 → 最後の価格で決済
        fwd = p_exit / p_now - 1
        fwd[exit_t > end] = np.nan  # 読み込み範囲の外にはみ出す日は使わない
        out[f"fwd_{name}"] = fwd

    # 持ち高の計算用: 1日ごとの値動き(抜けは直前の価格で埋め、上場廃止後は動かない)と、その日のFR
    filled = close.loc[:last_live].ffill().reindex(h.index).ffill()
    p0 = filled.reindex(t - HOUR).to_numpy()
    p1 = filled.reindex(t + DAY - HOUR).to_numpy()
    r1 = p1 / p0 - 1
    r1[(t + DAY) > end] = np.nan
    out["ret_1d"] = r1
    fund = _window_sum_before(fr, t, t + DAY)
    fund[((t + DAY) > end) | ((t - HOUR) >= last_live)] = np.nan
    out["fund_1d"] = fund
    return out
