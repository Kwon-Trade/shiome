"""清算の連鎖(イベント)の検出と、「連鎖が止まった」合図での買い。定義は docs/hypotheses_v3.md §3〜§8。

5分足の位置 i について、足の開始時刻 = open_time[i]、足が閉じる時刻 = open_time[i] + 5分。
判定はすべて「その足が閉じた時刻までのデータ」だけで行い、買うのは次の足の始値。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shiome.config import PROCESSED_DIR
from shiome.crosssection.data import _check_end, load_open_interest
from shiome.crosssection.universe import daily_universe

BAR = pd.Timedelta(minutes=5)
WIN = 6                     # 30分 = 5分足6本
LOOKBACK = 90 * 288         # 過去90日
MIN_LOOKBACK = int(LOOKBACK * 0.9)
EXTREME_Q = 0.01            # 下位1%
TAKER_MAX = 0.45            # テイカー買いの割合 45%未満
GAP_BARS = 72               # 同じ銘柄は6時間あける
WAIT_BARS = 72              # 合図を待つのは6時間まで
PRE_BARS = 288              # イベント前24時間
HORIZONS = {"1h": 12, "4h": 48, "24h": 288}
S2_BARS = {"S2-15": 3, "S2-30": 6, "S2-60": 12}
VOL_CALM = 1.5
WICK = 0.5
MARKET_MIN_OTHERS = 5
SIGNALS = ["S0", "S1", "S2-15", "S2-30", "S2-60", "S3", "S4", "S5", "S1+S2-30", "S1+S3"]
# 耐久テスト(§12-2): 検知から5・10・15分遅れて買う(判定には使わない)
DELAYS = {"S0-d5": 1, "S0-d10": 2, "S0-d15": 3}
ALL_SIGNALS = SIGNALS + list(DELAYS)


@dataclass
class Sym:
    name: str
    t: np.ndarray        # 足の開始時刻(datetime64[ns]、5分刻みで連続)
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    filled: np.ndarray   # 抜けは直前の値、上場廃止後は最後の価格
    qv: np.ndarray
    tb: np.ndarray       # テイカー買いの出来高(USD)
    present: np.ndarray
    oi: np.ndarray       # 足が閉じた時刻までに記録された最新の建玉
    r30: np.ndarray
    oi30: np.ndarray
    taker30: np.ndarray
    ok30: np.ndarray     # 30分の窓がきれい(抜け・出来高ゼロなし、出来高の確認も通る)
    thr_r: np.ndarray    # 過去90日の30分値動きの下位1%
    thr_oi: np.ndarray
    daily: pd.DataFrame


def load_sym(symbol: str, end: pd.Timestamp) -> Sym | None:
    end_ms = _check_end(end)
    path = PROCESSED_DIR / "futures_um" / "klines" / "5m" / f"{symbol}.parquet"
    if not path.exists():
        return None
    k = pd.read_parquet(path)
    k = k[k["open_time"] < end_ms]
    if len(k) < LOOKBACK:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(k["open_time"], unit="ms")).as_unit("ns")
    k = k.set_index(idx).drop(columns="open_time")
    grid = pd.date_range(idx[0], idx[-1], freq="5min")
    k = k.reindex(grid)
    present = k["close"].notna().to_numpy()
    live = present & (k["volume"].fillna(0).to_numpy() > 0)
    last_live = int(np.flatnonzero(live)[-1]) if live.any() else 0
    filled = k["close"].ffill().to_numpy().copy()
    filled[last_live + 1:] = filled[last_live]

    oi_raw = load_open_interest(symbol, end)
    oi_raw = oi_raw[oi_raw > 0]
    close_t = grid + BAR
    if len(oi_raw):
        pos = np.searchsorted(oi_raw.index.values, close_t.values, side="right") - 1
        oi = np.where(pos >= 0, oi_raw.to_numpy()[np.maximum(pos, 0)], np.nan)
        age = close_t.values - oi_raw.index.values[np.maximum(pos, 0)]
        oi[(pos < 0) | (age > np.timedelta64(10, "m"))] = np.nan
    else:
        oi = np.full(len(grid), np.nan)

    c = k["close"].to_numpy()
    qv = k["quote_volume"].to_numpy(dtype=float)
    tb = k["taker_buy_quote"].to_numpy(dtype=float)
    r30 = c / pd.Series(c).shift(WIN).to_numpy() - 1
    oi30 = oi / pd.Series(oi).shift(WIN).to_numpy() - 1
    good = pd.Series(live.astype(float))
    clean = good.rolling(WIN).sum().to_numpy() == WIN  # 30分の足がすべてあり、出来高ゼロなし
    clean &= pd.Series(present).shift(WIN, fill_value=False).to_numpy()
    vol30 = pd.Series(qv).rolling(WIN).sum()
    taker30 = (pd.Series(tb).rolling(WIN).sum() / vol30.replace(0, np.nan)).to_numpy()
    med24 = vol30.rolling(PRE_BARS, min_periods=PRE_BARS // 2).median().shift(WIN)  # 窓の直前24時間
    vol_ok = (vol30 >= med24).to_numpy()
    thr_r = pd.Series(r30).rolling(LOOKBACK, min_periods=MIN_LOOKBACK).quantile(EXTREME_Q).shift(1).to_numpy()
    thr_oi = pd.Series(oi30).rolling(LOOKBACK, min_periods=MIN_LOOKBACK).quantile(EXTREME_Q).shift(1).to_numpy()
    daily = daily_universe(symbol, end)[["t", "eligible", "adv30_usd"]]
    return Sym(symbol, grid.values, k["open"].to_numpy(), k["high"].to_numpy(), k["low"].to_numpy(), c, filled,
               qv, tb, present, oi, r30, oi30, taker30, clean & vol_ok, thr_r, thr_oi, daily)


def _eligible_mask(s: Sym) -> np.ndarray:
    day = pd.DatetimeIndex(s.t + np.timedelta64(5, "m")).floor("D")
    elig = s.daily.set_index("t")["eligible"].reindex(day).fillna(False).to_numpy(dtype=bool)
    return elig


def _onsets(flag: np.ndarray) -> np.ndarray:
    out, last = [], -GAP_BARS - 1
    for i in np.flatnonzero(flag):
        if i - last >= GAP_BARS:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def detect(s: Sym) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(清算の連鎖イベントの位置, 物差し(清算を伴わない下落)の位置, BTC判定用の「値動きだけ下位1%」フラグ)"""
    base = s.ok30 & _eligible_mask(s) & ~np.isnan(s.thr_r)
    drop = base & (s.r30 <= s.thr_r)
    cascade = drop & ~np.isnan(s.thr_oi) & (s.oi30 <= s.thr_oi) & (s.taker30 < TAKER_MAX)
    bench = drop & ~np.isnan(s.oi30) & (s.oi30 >= 0)
    drop_only = ~np.isnan(s.thr_r) & (s.r30 <= s.thr_r)
    return _onsets(cascade), _onsets(bench), drop_only


# ---------- 合図 ----------
def signal_bars(s: Sym, i: int) -> dict[str, int | None]:
    """イベントの足 i の後、各合図が最初に出た足の位置(その足の次の足の始値で買う)。6時間以内に出なければ None。"""
    n = len(s.t)
    out: dict[str, int | None] = {k: None for k in ALL_SIGNALS}
    out["S0"] = i
    for name, k in DELAYS.items():
        out[name] = i + k if i + k < n - 1 else None
    pre = slice(max(0, i - WIN + 1 - PRE_BARS), i - WIN + 1)
    pre_taker = s.tb[pre] / np.where(s.qv[pre] > 0, s.qv[pre], np.nan)
    taker_med = np.nanmedian(pre_taker) if np.isfinite(pre_taker).any() else np.nan
    vol_med = np.nanmedian(s.qv[pre]) if np.isfinite(s.qv[pre]).any() else np.nan
    start = i - WIN + 1
    for j in range(i + 1, min(i + WAIT_BARS, n - 1) + 1):
        if not s.present[j]:
            continue
        s1 = j >= i + 2 and (s.oi[j] - s.oi[j - 1] >= 0) and (s.oi[j - 1] - s.oi[j - 2] >= 0)
        s2 = {}
        for name, kb in S2_BARS.items():
            if j >= i + kb:
                prev_min = np.nanmin(s.lo[start:j - kb + 1])
                s2[name] = bool(np.nanmin(s.lo[j - kb + 1:j + 1]) >= prev_min)
            else:
                s2[name] = False
        s3 = s4 = False
        if j >= i + 3:
            v3 = s.qv[j - 2:j + 1]
            if np.isfinite(v3).all() and v3.sum() > 0:
                s3 = bool(s.tb[j - 2:j + 1].sum() / v3.sum() >= taker_med)
                s4 = bool(v3.mean() <= VOL_CALM * vol_med)
        s5 = False
        close_t = pd.Timestamp(s.t[j]) + BAR
        if close_t.minute % 15 == 0 and j - 2 > i:
            seg = slice(j - 2, j + 1)
            if s.present[seg].all():
                hi, lw = np.max(s.h[seg]), np.min(s.lo[seg])
                op, cl = s.o[j - 2], s.c[j]
                rng = hi - lw
                s5 = bool(rng > 0 and (min(op, cl) - lw) >= WICK * rng)
        cond = {"S1": s1, **s2, "S3": s3, "S4": s4, "S5": s5,
                "S1+S2-30": s1 and s2["S2-30"], "S1+S3": s1 and s3}
        for k, v in cond.items():
            if v and out[k] is None:
                out[k] = j
        if all(v is not None for v in out.values()):
            break
    return out


def outcome(s: Sym, i: int, j: int, end: pd.Timestamp) -> dict | None:
    """足 j の合図で、足 j+1 の始値で買った場合の結果。途中で上場廃止なら最後の価格で決済。"""
    n = len(s.t)
    stopped = pd.Timestamp(s.t[-1]) + BAR < end - BAR  # 読み込み範囲の終わりより前にデータが終わった
    e = j + 1
    if e >= len(s.t) or not s.present[e] or np.isnan(s.o[e]):
        return None
    price = s.o[e]
    start = i - WIN + 1
    ev_low = np.nanmin(s.lo[start:e])  # イベントの安値(窓の始まりから買う時刻まで)
    res = {"entry_time": pd.Timestamp(s.t[e]), "price": price, "wait_min": (e - i - 1) * 5}
    for name, hb in HORIZONS.items():
        x = e + hb - 1  # 買ってから hb 本目の足の終値
        if x < n:
            res[f"ret_{name}"] = s.filled[x] / price - 1
        elif stopped:
            res[f"ret_{name}"] = s.filled[-1] / price - 1
        else:
            res[f"ret_{name}"] = np.nan  # 読み込み範囲の外
    x24 = e + HORIZONS["24h"]
    if x24 <= n or stopped:
        hi = s.h[e:x24]
        lw = s.lo[e:x24]
        if np.isfinite(hi).any():
            k = int(np.nanargmax(hi))
            res["mfe"] = hi[k] / price - 1
            res["mfe_min"] = (k + 1) * 5
            res["mae"] = np.nanmin(lw) / price - 1
            res["second_leg"] = bool(np.nanmin(lw) < ev_low)
        else:  # 上場廃止などで足が無い
            res.update({"mfe": 0.0, "mfe_min": np.nan, "mae": 0.0, "second_leg": False})
    return res
