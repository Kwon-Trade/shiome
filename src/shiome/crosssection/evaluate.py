"""銘柄間比較の評価。定義は docs/hypotheses_v2.md §5〜§7。

- 勝率: 毎日、良い側(上位20%)と悪い側(下位20%)の平均の値動きを比べ、良い側が上回った日の割合
- 順位の相関: 毎日のスピアマン相関(予想の向きをプラスにそろえる)の平均
- コスト込みの差: 良い側を買い・悪い側を売る組を毎日作り、Hの日数だけそのまま持って手放す(重なる組は資金を均等割り)
- 95%の幅: 日付のかたまりごとに引き直すブートストラップ(24h・7dは7日、28dは28日のかたまり)
どの銘柄を良い側・悪い側に入れるかは、その日の対象かどうかと並べる数値だけで決める(その後の値動きは使わない)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import load_settings
from shiome.crosssection.panel import HORIZONS

MIN_N_ALL = 10
MIN_N_GROUP = 5
QUANTILE = 0.2
H5_YOUNG = (30, 90)   # 上場30〜90日未満 = 新しい
H5_OLD = 90
H5_MIN_OLD = 5
BLOCK_DAYS = {"24h": 7, "7d": 7, "28d": 28}
N_BOOT = 1000
FEE_ONE_WAY = 0.10 / 2 / 100

# (列名, 予想の向き: +1=高いほど良い / -1=高いほど悪い, 表示名)
SIGNALS = {
    "H1": ("h1_fr7", -1, "FR(7日平均)が高いほど弱い"),
    "H2-7": ("h2_7", +1, "過去7日の上昇率が高いほど強い"),
    "H2-14": ("h2_14", +1, "過去14日の上昇率が高いほど強い"),
    "H2-28": ("h2_28", +1, "過去28日の上昇率が高いほど強い"),
    "H3": ("h3_ret24", -1, "直近24時間の上昇率が高いほど弱い"),
    "H4": ("h4_oi7", -1, "建玉の7日増加率が高いほど弱い"),
    "H5": ("h5_age", None, "上場30〜90日の銘柄は古い銘柄より弱い"),
    "H6": ("h6_fs7", -1, "先物出来高÷現物出来高が高いほど弱い"),
}


def _slippage_table() -> list[tuple[float, float]]:
    tiers = load_settings()["cost_model"]["slippage_tiers_usd_volume"]
    return sorted(((t["min_usd"], t["slippage_pct"] / 100) for t in tiers), reverse=True)


def one_way_cost(adv_usd: np.ndarray) -> np.ndarray:
    """片道コスト = 手数料0.05% + 出来高別スリッページ。"""
    slip = np.full(len(adv_usd), np.nan)
    for min_usd, pct in reversed(_slippage_table()):  # 小さい段から順に上書き
        slip = np.where(np.nan_to_num(adv_usd, nan=0) >= min_usd, pct, slip)
    return FEE_ONE_WAY + slip


# ---------- 毎日の良い側・悪い側 ----------
def daily_legs(panel: pd.DataFrame, hyp: str, min_n: int) -> dict[pd.Timestamp, tuple[list[str], list[str], pd.Series]]:
    """日付 → (良い側の銘柄, 悪い側の銘柄, 向きをそろえたスコア)。"""
    col, direction, _ = SIGNALS[hyp]
    d = panel[panel["eligible"] & panel[col].notna()]
    if hyp == "H5":
        d = d[d[col] >= H5_YOUNG[0]]
    legs = {}
    for t, g in d.groupby("t", sort=True):
        if len(g) < min_n:
            continue
        if hyp == "H5":
            young = g[g[col] < H5_YOUNG[1]]
            old = g[g[col] >= H5_OLD]
            if len(young) < 1 or len(old) < H5_MIN_OLD:
                continue
            score = pd.Series(np.where(g[col] >= H5_OLD, 1.0, 0.0), index=g["symbol"].values)
            legs[t] = (sorted(old["symbol"]), sorted(young["symbol"]), score)
            continue
        score = pd.Series(direction * g[col].to_numpy(), index=g["symbol"].values)
        order = score.reset_index().sort_values([0, "index"], ascending=[False, True])["index"].tolist()
        k = max(1, int(round(QUANTILE * len(order))))
        legs[t] = (order[:k], order[-k:], score)
    return legs


def daily_stats(panel: pd.DataFrame, legs: dict, horizon: str) -> pd.DataFrame:
    fwd = panel.set_index(["t", "symbol"])[f"fwd_{horizon}"]
    rows = []
    for t, (good, bad, score) in legs.items():
        f = fwd.loc[t]
        fg, fb = f.reindex(good), f.reindex(bad)
        if fg.notna().sum() == 0 or fb.notna().sum() == 0:
            continue
        spread = fg.mean() - fb.mean()
        both = pd.concat([score, f.reindex(score.index)], axis=1).dropna()
        ic = both.iloc[:, 0].rank().corr(both.iloc[:, 1].rank()) if len(both) >= 3 else np.nan
        rows.append({"t": t, "spread": spread, "win": float(spread > 0), "ic": ic,
                     "n": len(score), "k_good": len(good), "k_bad": len(bad)})
    return pd.DataFrame(rows)


# ---------- 持ち高のシミュレーション(コスト込み) ----------
def portfolio(panel: pd.DataFrame, legs: dict, horizon: str) -> pd.DataFrame:
    """毎日の組(良い側を買い1、悪い側を売り1)を資金の1/Hずつで作り、H日そのまま持って手放す。

    持っている間は値動きに応じて持ち高が増減する(毎日比率を戻さない)。売買は組を作る日と手放す日だけで、
    同じ銘柄の買いと売りが同じ日に重なる分は相殺してからコストをかける。
    """
    hold = HORIZONS[horizon]
    p = panel.set_index(["t", "symbol"])
    ret = p["ret_1d"].unstack().fillna(0.0)
    fund = p["fund_1d"].unstack().reindex_like(ret).fillna(0.0)
    adv = p["adv30_usd"].unstack().reindex_like(ret).ffill()
    days = ret.index
    cohort = pd.DataFrame(0.0, index=days, columns=ret.columns)
    for t, (good, bad, _) in legs.items():
        cohort.loc[t, good] += 1.0 / len(good)
        cohort.loc[t, bad] -= 1.0 / len(bad)
    # 価格の指数: level(t) = t時点の価格(組を作った日を基準に、持ち高の増減を計算するため)
    level = (1.0 + ret).cumprod().shift(1, fill_value=1.0)
    level = level.where(level > 0, np.nan).ffill().fillna(1e-12)
    scaled = cohort / level
    w = scaled.rolling(hold, min_periods=1).sum() * level / hold  # その日に持っている量
    expiring = scaled.shift(hold, fill_value=0.0) * level / hold    # H日前に作った組を手放す量
    trade = (cohort / hold - expiring).abs()
    first = min(legs) if legs else days[-1]
    sl = slice(first, None)
    w, trade, r = w.loc[sl], trade.loc[sl], ret.loc[sl]
    gross = (w * r).sum(axis=1)
    carry = -(w * fund.loc[sl]).sum(axis=1)  # 買いはFRを払い、売りは受け取る
    worst = FEE_ONE_WAY + max(x for _, x in _slippage_table())
    cost_rate = pd.DataFrame(one_way_cost(adv.loc[sl].to_numpy().ravel()).reshape(w.shape), index=w.index, columns=w.columns)
    cost = (trade * cost_rate.where(adv.loc[sl].notna(), worst)).sum(axis=1)
    return pd.DataFrame({"gross": gross, "cost": cost, "net": gross - cost, "carry": carry,
                         "net_carry": gross - cost + carry, "turnover": trade.sum(axis=1)})


# ---------- ブロックブートストラップ ----------
def block_boot_mean(values: np.ndarray, block: int, n_boot: int = N_BOOT, seed: int = 42) -> tuple[float, float]:
    v = values[~np.isnan(values)]
    n = len(v)
    if n < 2 * block:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = v[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(stats: pd.DataFrame, port: pd.DataFrame, horizon: str) -> dict:
    block = BLOCK_DAYS[horizon]
    out = {"n_days": int(len(stats)), "n_independent": int(len(stats) // HORIZONS[horizon])}
    if len(stats) == 0:
        return out
    for key in ("win", "ic", "spread"):
        v = stats[key].to_numpy(dtype=float)
        lo, hi = block_boot_mean(v, block)
        out[key] = float(np.nanmean(v))
        out[f"{key}_lo"], out[f"{key}_hi"] = lo, hi
    out["avg_n"] = float(stats["n"].mean())
    for key in ("gross", "cost", "net", "carry", "net_carry", "turnover"):
        out[f"pf_{key}"] = float(port[key].mean()) if len(port) else np.nan
    if len(port):
        out["pf_net_lo"], out["pf_net_hi"] = block_boot_mean(port["net"].to_numpy(), block)
    return out


PERIODS = {
    "2022": ("2022-01-01", "2023-01-01"),
    "2023": ("2023-01-01", "2024-01-01"),
    "2024": ("2024-01-01", "2025-01-01"),
    "2022-23": ("2022-01-01", "2024-01-01"),
}


def _slice(df: pd.DataFrame, col: str | None, period: str) -> pd.DataFrame:
    a, b = (pd.Timestamp(x) for x in PERIODS[period])
    idx = df[col] if col else df.index
    return df[(idx >= a) & (idx < b)]


def evaluate(panel: pd.DataFrame, hyp: str, horizon: str, periods: list[str], min_n: int = MIN_N_ALL) -> dict:
    legs = daily_legs(panel, hyp, min_n)
    stats = daily_stats(panel, legs, horizon)
    port = portfolio(panel, legs, horizon) if legs else pd.DataFrame(columns=["gross", "cost", "net", "carry", "net_carry", "turnover"])
    res = {}
    for per in periods:
        s = _slice(stats, "t", per) if len(stats) else stats
        pf = _slice(port, None, per) if len(port) else port
        res[per] = summarize(s, pf, horizon)
    return res
