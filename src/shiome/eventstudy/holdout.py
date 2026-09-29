"""仮説A・C(逆引き分析から生まれた仮説)の答え合わせ。

合格基準と定義は docs/methodology.md #12。実行前にコミット済みの基準をそのまま使い、
結果を見てから変えない。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from shiome.config import PROCESSED_DIR, load_settings
from shiome.eventstudy.combos import _design
from shiome.eventstudy.samples import EVENT_PCT, FORWARD_HOURS, MIN_VALID_HOURS, _onsets, load_symbol_frame

SIGNAL_OFFSET = 6
WEEK_MS = 7 * 24 * 3600 * 1000
FR_COLS = ("funding_rate", "funding_rate_diff")
BASE_MODEL = ("past_range_24h",)
FR_MODEL = ("past_range_24h", "funding_rate", "funding_rate_diff")


def _holdout_start_ms() -> int:
    return int(pd.Timestamp(load_settings()["split"]["holdout_start"]).timestamp() * 1000)


def first_futures_time(symbol: str) -> int | None:
    path = PROCESSED_DIR / "futures_um" / "klines" / "1h" / f"{symbol}.parquet"
    if not path.exists():
        return None
    return int(pd.read_parquet(path, columns=["open_time"])["open_time"].min())


def symbol_table(symbol: str, is_delisted: bool) -> pd.DataFrame:
    """答え合わせ期間の1銘柄分: 大変動の始まり(onset)と普通の時点の行だけを返す。"""
    df = load_symbol_frame(symbol, include_holdout=True)
    if df is None:
        return pd.DataFrame()

    if is_delisted:
        # 上場廃止で24時間後が無い場合は最後の価格で決済したものとする(#8)
        last_close = df["close"].iloc[-1]
        tail = df["fwd_ret_24h"].isna() & (df.index >= len(df) - FORWARD_HOURS)
        df.loc[tail, "fwd_ret_24h"] = last_close / df.loc[tail, "close"] - 1

    for col in FR_COLS + ("past_range_24h",):
        df[f"{col}__sig"] = df[f"{col}__pct"].shift(SIGNAL_OFFSET)  # 6時間前の値(全期間でずらしてから切り出す)

    df = df[df["open_time"] >= _holdout_start_ms()].reset_index(drop=True)
    valid = df["fwd_ret_24h"].notna() & df["tradable"]
    if valid.sum() < MIN_VALID_HOURS:
        return pd.DataFrame()

    hi = df.loc[valid, "fwd_ret_24h"].quantile(1 - EVENT_PCT / 100)
    lo = df.loc[valid, "fwd_ret_24h"].quantile(EVENT_PCT / 100)
    surge_flag = valid & (df["fwd_ret_24h"] >= hi)
    crash_flag = valid & (df["fwd_ret_24h"] <= lo)

    df["kind"] = np.where(valid & ~surge_flag & ~crash_flag, "normal", "")
    df.loc[_onsets(surge_flag), "kind"] = "surge"
    df.loc[_onsets(crash_flag), "kind"] = "crash"
    out = df[df["kind"] != ""][["open_time", "kind"] + [c for c in df.columns if c.endswith("__sig")]].copy()
    out["symbol"] = symbol
    return out


# ---------- 起きやすさ(倍率) ----------
def _week_counts(table: pd.DataFrame, cond: pd.Series, event_kinds: tuple[str, ...]):
    week = (table["open_time"] // WEEK_MS).to_numpy()
    weeks, idx = np.unique(week, return_inverse=True)
    is_ev = table["kind"].isin(event_kinds).to_numpy()
    is_nm = (table["kind"] == "normal").to_numpy()
    c = cond.to_numpy()
    n = len(weeks)
    return (np.bincount(idx, weights=is_ev & c, minlength=n), np.bincount(idx, weights=is_ev, minlength=n),
            np.bincount(idx, weights=is_nm & c, minlength=n), np.bincount(idx, weights=is_nm, minlength=n))


def lift(table: pd.DataFrame, col: str, lo: float | None, hi: float | None, band: bool,
         event_kinds=("surge", "crash"), n_boot: int = 1000, seed: int = 42) -> dict:
    """band=True: lo<=値<=hi の帯。band=False: 値<=lo または 値>=hi の両端。"""
    sig = f"{col}__sig"
    t = table[table[sig].notna()]
    v = t[sig]
    cond = v.between(lo, hi) if band else ((v <= lo) | (v >= hi))
    a, A, b, B = _week_counts(t, cond, event_kinds)

    def ratio(wt):
        ev_share = (a * wt).sum() / max((A * wt).sum(), 1e-12)
        nm_share = (b * wt).sum() / max((B * wt).sum(), 1e-12)
        return ev_share / nm_share if nm_share > 0 else np.nan

    point = ratio(np.ones(len(a)))
    rng = np.random.default_rng(seed)
    boots = [ratio(np.bincount(rng.integers(0, len(a), len(a)), minlength=len(a))) for _ in range(n_boot)]
    return {"lift": point, "ci_lo": float(np.nanpercentile(boots, 2.5)), "ci_hi": float(np.nanpercentile(boots, 97.5)),
            "n_event": int(A.sum()), "n_event_cond": int(a.sum()), "n_normal": int(B.sum()), "n_normal_cond": int(b.sum())}


# ---------- ③ AUCの上乗せ ----------
def train_models(rule_samples: pd.DataFrame) -> dict:
    """逆引き分析(2022〜2024年、小型・ミーム)のサンプルで重みを決める。答え合わせ期間では学習し直さない。"""
    d = rule_samples[rule_samples["group"] == "small_meme"]
    need = [f"{c}__pct__t{SIGNAL_OFFSET}" for c in FR_MODEL]
    d = d.dropna(subset=need)
    y = d["kind"].isin(["surge", "crash"]).to_numpy()
    return {name: LogisticRegression(max_iter=1000).fit(_design(d, cols, SIGNAL_OFFSET), y)
            for name, cols in (("base", BASE_MODEL), ("fr", FR_MODEL))}


def _as_design(table: pd.DataFrame, cols: tuple[str, ...]) -> np.ndarray:
    renamed = table.rename(columns={f"{c}__sig": f"{c}__pct__t{SIGNAL_OFFSET}" for c in cols})
    return _design(renamed, cols, SIGNAL_OFFSET)


def _weighted_auc(score_groups: np.ndarray, n_groups: int, pos: np.ndarray, w: np.ndarray) -> float:
    pw = np.bincount(score_groups, weights=w * pos, minlength=n_groups)
    nw = np.bincount(score_groups, weights=w * ~pos, minlength=n_groups)
    below = np.concatenate([[0], np.cumsum(nw)[:-1]])
    denom = pw.sum() * nw.sum()
    return float((pw * (below + 0.5 * nw)).sum() / denom) if denom > 0 else np.nan


def auc_uplift(table: pd.DataFrame, models: dict, n_boot: int = 1000, seed: int = 42) -> dict:
    need = [f"{c}__sig" for c in FR_MODEL]
    t = table.dropna(subset=need)
    pos = t["kind"].isin(["surge", "crash"]).to_numpy()
    groups = {}
    for name, cols in (("base", BASE_MODEL), ("fr", FR_MODEL)):
        score = models[name].predict_proba(_as_design(t, cols))[:, 1]
        uniq, inv = np.unique(score, return_inverse=True)
        groups[name] = (inv, len(uniq))
    week = (t["open_time"] // WEEK_MS).to_numpy()
    weeks, widx = np.unique(week, return_inverse=True)

    def both(wt_rows):
        return {k: _weighted_auc(g, n, pos, wt_rows) for k, (g, n) in groups.items()}

    point = both(np.ones(len(t)))
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        mult = np.bincount(rng.integers(0, len(weeks), len(weeks)), minlength=len(weeks))
        r = both(mult[widx].astype(float))
        diffs.append(r["fr"] - r["base"])
    return {"auc_base": point["base"], "auc_fr": point["fr"], "diff": point["fr"] - point["base"],
            "diff_ci_lo": float(np.percentile(diffs, 2.5)), "diff_ci_hi": float(np.percentile(diffs, 97.5)),
            "n_event": int(pos.sum()), "n_normal": int((~pos).sum())}
