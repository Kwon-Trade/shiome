"""ラウンドB: H17「過熱ショート」。定義は docs/hypotheses_v2.md の B1〜B8。

- 毎日0・8・16時(UTC)に、比較対象の銘柄をFR(8時間あたりに換算)で並べ、上位5%に新しく入った銘柄を「きっかけ」とする
- ① きっかけの時点ですぐ空売り / ② 高値更新・建玉の増加が止まり、現物CVDがマイナスになるのを待って空売り(72時間まで)
- 24時間・7日持つ。損切りなし / +15%で損切り の両方
入る判断はすべて、その時点までに確定したデータだけで行う。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shiome.crosssection.data import (
    HOUR, load_funding_with_interval, load_futures_hourly, load_open_interest, load_spot_cvd,
)
from shiome.crosssection.evaluate import one_way_cost
from shiome.crosssection.groups import assign_groups
from shiome.crosssection.universe import DEAD_LOOKBACK_HOURS, daily_universe
from shiome.phases.percentile import rolling_percentile_rank

CHECK_HOURS = (0, 8, 16)
TOP_PCT = 0.05
FR_MAX_AGE = pd.Timedelta(hours=12)
QUIET_CHECKS = 3                    # 直前24時間(3回)は上位5%でなかった
SAME_SYMBOL_GAP = pd.Timedelta(days=7)
WAIT_HOURS = 72
STALL_HOURS = 6
HOLDS = {"24h": 24, "7d": 168}
STOP_PCT = 0.15
SQUEEZE_PCT = 0.30
OI_MAX_STALENESS = pd.Timedelta(hours=2)
LIQ_LEVERAGES = (10, 20)
LIQ_MMR = 0.005
LIQ_BAND = 0.85
LIQ_LOOKBACK_HOURS = 168
SHORT_LIQ_BAND = 1.10   # B10-2: 売値の+10%以内
STORM_PCT = 90          # B10-1: 直前24時間の値幅が、その銘柄の直近90日で上位10%


@dataclass
class Sym:
    name: str
    hours: pd.DatetimeIndex        # 足の開始時刻(連続)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray              # 抜けはNaN
    filled: np.ndarray             # 抜けは直前の値、上場廃止後は最後の価格
    live_ok: np.ndarray            # その足があり、直前24時間に出来高ゼロが無い
    oi_at: np.ndarray              # 各「時刻」(=足の開始時刻)より前の最新の建玉。古すぎればNaN
    cvd: np.ndarray                # 現物CVD(1時間ごと)
    fr: pd.DataFrame
    daily: pd.DataFrame
    range_pct: np.ndarray          # 各足が閉じた時点の「直前24時間の値幅」の百分位(その銘柄の直近90日)            # daily_universe の結果(t, eligible, adv30_usd)

    def pos(self, t: pd.Timestamp) -> int:
        """時刻 t に始まる足の位置(範囲外なら -1)。"""
        i = int((t - self.hours[0]) / HOUR)
        return i if 0 <= i < len(self.hours) else -1


def _asof_before(series: pd.Series, times: pd.DatetimeIndex, max_age: pd.Timedelta) -> np.ndarray:
    if series.empty:
        return np.full(len(times), np.nan)
    idx = series.index.values
    p = np.searchsorted(idx, times.values, side="left") - 1
    ok = p >= 0
    vals = np.full(len(times), np.nan)
    vals[ok] = series.to_numpy()[p[ok]]
    age = np.where(ok, times.values - idx[np.maximum(p, 0)], np.timedelta64(10**18, "ns"))
    vals[age > np.timedelta64(max_age)] = np.nan
    return vals


def load_sym(symbol: str, end: pd.Timestamp, with_oi: bool) -> Sym | None:
    daily = daily_universe(symbol, end)
    if daily.empty:
        return None
    h = load_futures_hourly(symbol, end)
    live = h["present"] & (h["volume"] > 0)
    last_live = live[live].index.max() if live.any() else h.index[0]
    filled = h["close"].loc[:last_live].ffill().reindex(h.index).ffill()
    zero = (h["present"] & (h["volume"] <= 0)).astype(int)
    dead = zero.rolling(DEAD_LOOKBACK_HOURS, min_periods=1).max().astype(bool)
    oi = load_open_interest(symbol, end) if with_oi else pd.Series(dtype=float)
    oi = oi[oi > 0]
    rng = (h["high"].rolling(24, min_periods=24).max() - h["low"].rolling(24, min_periods=24).min()) / h["close"]
    return Sym(
        name=symbol, hours=h.index,
        open=h["open"].to_numpy(), high=h["high"].to_numpy(), low=h["low"].to_numpy(),
        close=h["close"].to_numpy(), filled=filled.to_numpy(),
        live_ok=(h["present"] & ~dead).to_numpy(),
        oi_at=_asof_before(oi, h.index, OI_MAX_STALENESS),
        cvd=load_spot_cvd(symbol, h.index, end).to_numpy(),
        fr=load_funding_with_interval(symbol, end),
        daily=daily[["t", "symbol", "eligible", "adv30_usd"]],
        range_pct=rolling_percentile_rank(rng).to_numpy(),
    )


# ---------- きっかけ(イベント) ----------
def check_times(syms: dict[str, Sym], end: pd.Timestamp) -> pd.DatetimeIndex:
    start = min(s.hours[0] for s in syms.values()).ceil("D")
    t = pd.date_range(start, end - HOUR, freq="8h")
    return t[t.hour.isin(CHECK_HOURS)]


def fr_matrix(syms: dict[str, Sym], checks: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """判定時刻 × 銘柄 の「8時間あたりFR」と「比較対象か」。"""
    fr_cols, ok_cols = {}, {}
    for name, s in syms.items():
        rate8 = s.fr["rate"] * 8 / s.fr["interval_hours"].where(s.fr["interval_hours"] > 0, 8)
        fr_cols[name] = _asof_before(rate8, checks, FR_MAX_AGE)
        elig_day = s.daily.set_index("t")["eligible"].reindex(checks.floor("D")).fillna(False).to_numpy(dtype=bool)
        p = np.array([s.pos(c - HOUR) for c in checks])
        bar_ok = np.where(p >= 0, s.live_ok[np.maximum(p, 0)], False)
        ok_cols[name] = elig_day & bar_ok
    return pd.DataFrame(fr_cols, index=checks), pd.DataFrame(ok_cols, index=checks)


def find_events(fr: pd.DataFrame, ok: pd.DataFrame) -> pd.DataFrame:
    top = pd.DataFrame(False, index=fr.index, columns=fr.columns)
    for c in fr.index:
        row = fr.loc[c][ok.loc[c] & fr.loc[c].notna()]
        if len(row) == 0:
            continue
        k = max(1, int(round(TOP_PCT * len(row))))
        order = row.reset_index().sort_values([c, "index"], ascending=[False, True])["index"].tolist()
        top.loc[c, order[:k]] = True
    before = top.astype(int).shift(1, fill_value=0).rolling(QUIET_CHECKS, min_periods=1).max().astype(bool)
    cand = top & ~before
    events, last = [], {}
    for c in cand.index:
        for s in cand.columns[cand.loc[c].to_numpy()]:
            if s in last and c - last[s] < SAME_SYMBOL_GAP:
                continue
            last[s] = c
            events.append({"t0": c, "symbol": s, "fr8": float(fr.at[c, s]), "n_ok": int(ok.loc[c].sum())})
    return pd.DataFrame(events)


# ---------- ②: 失速の確認 ----------
def stall_entry(s: Sym, t0: pd.Timestamp) -> tuple[bool, pd.Timestamp | None]:
    """(判定できるか, 空売りする時刻)。72時間以内に3条件がそろわなければ時刻は None(見送り)。"""
    p0 = s.pos(t0)  # t0 に始まる足(無ければ -1)
    if p0 < STALL_HOURS or np.isnan(s.oi_at[p0]) or np.isnan(s.cvd[p0 - STALL_HOURS:p0]).any():
        return False, None
    for j in range(STALL_HOURS + 1, WAIT_HOURS + 1):
        y = p0 + j  # 時刻 t0 + j時間(= 位置 y の足の開始時刻)。閉じた足は p0 .. y-1
        if y >= len(s.hours):
            break
        if not s.live_ok[y - 1]:
            continue
        seg = s.high[p0:y]
        stalled = np.nanmax(seg[-STALL_HOURS:]) <= np.nanmax(seg[:-STALL_HOURS])
        oi_stop = s.oi_at[y] <= s.oi_at[y - STALL_HOURS]  # NaNならFalse
        cvd6 = s.cvd[y - STALL_HOURS:y]
        cvd_neg = (not np.isnan(cvd6).any()) and cvd6.sum() < 0
        if stalled and oi_stop and cvd_neg:
            return True, s.hours[y]
    return True, None


# ---------- 清算価格帯の推定(補助) ----------
def near_liquidation(s: Sym, x: pd.Timestamp) -> float:
    """売値の85%〜売値の間にある「推定」ロング清算量 ÷ 今の建玉。"""
    px = s.pos(x)
    if px < LIQ_LOOKBACK_HOURS + 1 or np.isnan(s.oi_at[px]):
        return np.nan
    price = s.close[px - 1]
    idx = np.arange(px - LIQ_LOOKBACK_HOURS, px + 1)
    oi = s.oi_at[idx]
    d_oi = np.diff(oi)
    p_open = s.close[idx[1:] - 1]  # 建玉が増えた1時間の終値
    near = 0.0
    for lev in LIQ_LEVERAGES:
        liq = p_open * (1 - 1 / lev + LIQ_MMR)
        m = (d_oi > 0) & (liq >= LIQ_BAND * price) & (liq < price)
        near += np.nansum(d_oi[m]) / len(LIQ_LEVERAGES)
    return float(near / oi[-1])


def near_short_liquidation(s: Sym, x: pd.Timestamp) -> float:
    """B10-2: 売値より上〜+10%以内にある「推定」ショート清算量 ÷ 今の建玉。"""
    px = s.pos(x)
    if px < LIQ_LOOKBACK_HOURS + 1 or np.isnan(s.oi_at[px]):
        return np.nan
    price = s.close[px - 1]
    idx = np.arange(px - LIQ_LOOKBACK_HOURS, px + 1)
    oi = s.oi_at[idx]
    d_oi = np.diff(oi)
    p_open = s.close[idx[1:] - 1]
    near = 0.0
    for lev in LIQ_LEVERAGES:
        liq = p_open * (1 + 1 / lev - LIQ_MMR)
        m = (d_oi > 0) & (liq > price) & (liq <= SHORT_LIQ_BAND * price)
        near += np.nansum(d_oi[m]) / len(LIQ_LEVERAGES)
    return float(near / oi[-1])


def storm_flag(s: Sym, x: pd.Timestamp) -> float:
    """B10-1: 売る時点で荒れ予報か(1.0/0.0)。90日分そろわなければNaN。"""
    p = s.pos(x) - 1
    if p < 0 or np.isnan(s.range_pct[p]):
        return np.nan
    return float(s.range_pct[p] >= STORM_PCT)


# ---------- 1回の空売り ----------
def short_trade(s: Sym, x: pd.Timestamp, hold: int, stop: bool, end: pd.Timestamp,
                market: pd.DataFrame, elig_syms: list[str], adv: float) -> dict | None:
    pe = s.pos(x) - 1  # 売値 = x-1時間の足の終値
    if pe < 0 or x + hold * HOUR > end or np.isnan(s.close[pe]):
        return None
    price = s.close[pe]
    win_h = s.high[pe + 1: pe + 1 + hold]
    win_l = s.low[pe + 1: pe + 1 + hold]
    exit_px = s.filled[pe + hold] if pe + hold < len(s.filled) else s.filled[-1]
    exit_time = x + hold * HOUR
    stopped = False
    if stop:
        hit = np.flatnonzero(win_h >= price * (1 + STOP_PCT))
        if len(hit):
            i = hit[0]
            o = s.open[pe + 1 + i]
            exit_px = max(price * (1 + STOP_PCT), o if not np.isnan(o) else 0.0)
            exit_time = s.hours[pe + 1 + i] + HOUR
            stopped = True
    n_held = int((exit_time - x) / HOUR)
    mae = np.nanmax(win_h[:n_held]) / price - 1 if np.isfinite(win_h[:n_held]).any() else 0.0
    mfe = 1 - np.nanmin(win_l[:n_held]) / price if np.isfinite(win_l[:n_held]).any() else 0.0
    ret = exit_px / price - 1
    cost = 2 * one_way_cost(np.array([adv]))[0]  # 往復手数料0.10% + 片道スリッページ×2

    fr = s.fr[(s.fr.index >= x) & (s.fr.index < exit_time)]
    fr_recv = 0.0
    for t_set, rate in fr["rate"].items():
        p = s.pos(t_set.floor("h") - HOUR)
        px = s.filled[p] if p >= 0 else price
        fr_recv += rate * px / price

    # 物差し: 同じ時刻・同じ期間に比較対象の全銘柄の平均を空売り
    t_a, t_b = x - HOUR, exit_time - HOUR
    if t_b in market.index and t_a in market.index:
        m = market.loc[t_b, elig_syms] / market.loc[t_a, elig_syms] - 1
        mkt = float(m.mean())
    else:
        mkt = np.nan
    pnl = -ret - cost
    return {"entry": x, "exit": exit_time, "ret": ret, "cost": cost, "pnl": pnl, "fr_recv": fr_recv,
            "pnl_fr": pnl + fr_recv, "mae": mae, "mfe": mfe, "stopped": stopped,
            "mkt_ret": mkt, "diff": -(ret - mkt)}


def run(syms: dict[str, Sym], end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    checks = check_times(syms, end)
    fr, ok = fr_matrix(syms, checks)
    events = find_events(fr, ok)
    # 上場廃止した銘柄は最後の価格のまま(ffill)
    market = pd.DataFrame({n: pd.Series(s.filled, index=s.hours) for n, s in syms.items()}).ffill()
    daily = assign_groups(pd.concat([s.daily for s in syms.values()], ignore_index=True))
    elig_by_day = daily[daily["eligible"]].groupby("t")["symbol"].apply(list).to_dict()
    adv_of = daily.set_index(["t", "symbol"])["adv30_usd"]
    group_of = daily.set_index(["t", "symbol"])["group"]

    ev_rows, trades = [], []
    for e in events.itertuples(index=False):
        s = syms[e.symbol]
        judgeable, t2 = stall_entry(s, e.t0)
        near = near_liquidation(s, e.t0)
        near_short = near_short_liquidation(s, e.t0)
        ev_rows.append({"t0": e.t0, "symbol": e.symbol, "fr8": e.fr8, "judgeable": judgeable, "entry2": t2,
                        "near_liq": near, "near_short_liq": near_short,
                        "group": group_of.get((e.t0.floor("D"), e.symbol), "")})
        for entry_kind, x in (("1", e.t0), ("2", t2)):
            if x is None:
                continue
            day = x.floor("D")
            elig = elig_by_day.get(day, [])
            adv = adv_of.get((day, e.symbol), np.nan)
            storm = storm_flag(s, x)
            for hz, hold in HOLDS.items():
                for stop in (False, True):
                    tr = short_trade(s, x, hold, stop, end, market, elig, adv)
                    if tr is None:
                        continue
                    trades.append({"t0": e.t0, "symbol": e.symbol, "entry_kind": entry_kind, "hold": hz,
                                   "stop": stop, "judgeable": judgeable, "near_liq": near,
                                   "near_short_liq": near_short, "storm": storm, **tr})
    return pd.DataFrame(ev_rows), pd.DataFrame(trades)


# ---------- 集計 ----------
def cluster_boot(values: np.ndarray, weeks: np.ndarray, n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    """週ごとのかたまりで引き直した平均の95%の幅。"""
    if len(values) < 10:
        return np.nan, np.nan
    uw, inv = np.unique(weeks, return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(uw))
    cnts = np.bincount(inv, minlength=len(uw)).astype(float)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(uw), size=(n_boot, len(uw)))
    means = sums[draw].sum(axis=1) / cnts[draw].sum(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(tr: pd.DataFrame) -> dict:
    n = len(tr)
    if n == 0:
        return {"n": 0}
    weeks = (tr["entry"].astype("int64") // (7 * 24 * 3600 * 10**9)).to_numpy()
    wins, losses = tr[tr["pnl"] > 0], tr[tr["pnl"] <= 0]
    out = {
        "n": n, "win": float((tr["pnl"] > 0).mean()),
        "avg_win": float(wins["pnl"].mean()) if len(wins) else np.nan,
        "avg_loss": float(losses["pnl"].mean()) if len(losses) else np.nan,
        "pnl": float(tr["pnl"].mean()), "pnl_fr": float(tr["pnl_fr"].mean()), "fr_recv": float(tr["fr_recv"].mean()),
        "mae_mean": float(tr["mae"].mean()), "mae_median": float(tr["mae"].median()), "mae_max": float(tr["mae"].max()),
        "squeeze_n": int((tr["mae"] >= SQUEEZE_PCT).sum()), "squeeze_rate": float((tr["mae"] >= SQUEEZE_PCT).mean()),
        "mfe_mean": float(tr["mfe"].mean()), "stopped_rate": float(tr["stopped"].mean()),
        "diff": float(tr["diff"].mean()), "mkt_ret": float(tr["mkt_ret"].mean()),
    }
    out["pnl_lo"], out["pnl_hi"] = cluster_boot(tr["pnl"].to_numpy(), weeks)
    d = tr["diff"].to_numpy()
    ok = ~np.isnan(d)
    out["diff_lo"], out["diff_hi"] = cluster_boot(d[ok], weeks[ok])
    return out
