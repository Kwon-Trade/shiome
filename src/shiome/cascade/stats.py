"""第3ラウンド A の集計。定義は docs/hypotheses_v3.md §8・§9。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.crosssection.evaluate import FEE_ONE_WAY, one_way_cost
from shiome.crosssection.overheat import cluster_boot

HZ = ["1h", "4h", "24h"]
PERIODS = {"2022": ("2022-01-01", "2023-01-01"), "2023": ("2023-01-01", "2024-01-01"),
           "2022-23": ("2022-01-01", "2024-01-01"), "2024": ("2024-01-01", "2025-01-01")}
MIN_N = 30
EXTRA = ["S0-market", "S0-drop5"]           # §12-1 後付けの追加条件
S0_FAMILY = ["S0", "S0-market", "S0-drop5"]
DELAY_BASES = ["S0", "S0-d5", "S0-d10", "S0-d15"]
TOP_DAYS = 10


def expand(df: pd.DataFrame) -> pd.DataFrame:
    """S0(と遅れて買う版)から、S0-market・S0-drop5 の行を作って足す(物差しも同じ絞り込み)。"""
    parts = [df]
    for base in DELAY_BASES:
        b = df[df["signal"] == base]
        parts.append(b[b["scope"] == "market"].assign(signal=base.replace("S0", "S0-market", 1)))
        parts.append(b[b["r30"] <= -0.05].assign(signal=base.replace("S0", "S0-drop5", 1)))
    return pd.concat(parts, ignore_index=True)


def add_costs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    one_way = one_way_cost(df["adv30_usd"].to_numpy())
    slip = one_way - FEE_ONE_WAY
    df["cost"] = 2 * one_way                       # 往復手数料0.10% + 片道スリッページ×2
    df["cost_stress"] = 2 * (FEE_ONE_WAY + 3 * slip)  # 参考: スリッページ3倍
    for h in HZ:
        df[f"net_{h}"] = df[f"ret_{h}"] - df["cost"]
        df[f"stress_{h}"] = df[f"ret_{h}"] - df["cost_stress"]
    return df


def period(df: pd.DataFrame, per: str) -> pd.DataFrame:
    a, b = (pd.Timestamp(x) for x in PERIODS[per])
    return df[(df["t0"] >= a) & (df["t0"] < b)]


def summarize(sub: pd.DataFrame, h: str) -> dict:
    """sub: 同じ合図の行(fired=False を含む)。"""
    n_events = int(len(sub))
    t = sub[sub["fired"] & sub[f"ret_{h}"].notna()]
    out = {"n_events": n_events, "n_fired": int(sub["fired"].sum()), "n": int(len(t))}
    if len(t) == 0:
        return out
    r, net = t[f"ret_{h}"], t[f"net_{h}"]
    weeks = (t["entry_time"].astype("int64") // (7 * 24 * 3600 * 10**9)).to_numpy()
    out.update({
        "mean": float(r.mean()), "median": float(r.median()), "p10": float(r.quantile(0.1)), "p90": float(r.quantile(0.9)),
        "win": float((r > 0).mean()),
        "net_mean": float(net.mean()), "net_median": float(net.median()), "net_win": float((net > 0).mean()),
        "stress_mean": float(t[f"stress_{h}"].mean()),
        "cost_mean": float(t["cost"].mean()),
        "wait_median": float(t["wait_min"].median()),
    })
    out["net_lo"], out["net_hi"] = cluster_boot(net.to_numpy(dtype=float), weeks)
    t24 = t[t["mfe"].notna()] if "mfe" in t else t.iloc[0:0]
    if len(t24):
        out.update({"mfe_mean": float(t24["mfe"].mean()), "mfe_median": float(t24["mfe"].median()),
                    "mfe_min_median": float(t24["mfe_min"].median()),
                    "mae_mean": float(t24["mae"].mean()), "mae_median": float(t24["mae"].median()),
                    "second_leg": float(t24["second_leg"].astype(bool).mean())})
    return out


def robustness(df: pd.DataFrame, periods: list[str]) -> dict:
    """§12-2 の耐久テスト(参考)。df は add_costs・expand 済み。"""
    out: dict = {"delay": {}, "top_days_removed": {}, "monthly": {}}
    casc = df[df["kind"] == "cascade"]
    for fam in S0_FAMILY:
        for d in ("", "-d5", "-d10", "-d15"):
            name = f"{fam}{d}"  # expand() と同じ名前(例: S0-market-d5)
            for h in HZ:
                for per in periods:
                    out["delay"].setdefault(fam, {}).setdefault(d or "-d0", {}).setdefault(h, {})[per] = summarize(
                        period(casc[casc["signal"] == name], per), h)
    s0 = casc[casc["signal"] == "S0"]
    for per in [p for p in periods if p in ("2022-23", "2024")]:
        ev = period(s0, per)
        top = ev["t0"].dt.floor("D").value_counts().head(TOP_DAYS)
        out["top_days_removed"].setdefault("_days", {})[per] = [str(d.date()) for d in top.index]
        for fam in S0_FAMILY:
            sub = period(casc[casc["signal"] == fam], per)
            sub = sub[~sub["t0"].dt.floor("D").isin(top.index)]
            for h in HZ:
                out["top_days_removed"].setdefault(fam, {}).setdefault(h, {})[per] = summarize(sub, h)
    for fam in S0_FAMILY:
        sub = casc[(casc["signal"] == fam) & casc["fired"]]
        month = sub["t0"].dt.to_period("M").astype(str)
        rows = {}
        for m, g in sub.groupby(month):
            rows[m] = {"n": int(len(g)), **{f"sum_{h}": float(g[f"net_{h}"].sum()) for h in HZ},
                       **{f"mean_{h}": float(g[f"net_{h}"].mean()) for h in HZ}}
        out["monthly"][fam] = rows
    return out


def full_summary(df: pd.DataFrame, periods: list[str], signals: list[str]) -> dict:
    df = expand(add_costs(df))
    res: dict = {"main": {}, "splits": {}, "promising": []}
    for kind in ("cascade", "bench"):
        for sig in signals:
            for h in HZ:
                for per in periods:
                    sub = period(df[(df["kind"] == kind) & (df["signal"] == sig)], per)
                    res["main"].setdefault(kind, {}).setdefault(sig, {}).setdefault(h, {})[per] = summarize(sub, h)
    for col in ("scope", "group", "drop_bin"):
        for val in sorted(df[col].dropna().unique()):
            for sig in signals:
                for h in HZ:
                    for per in [p for p in periods if p in ("2022-23", "2024")]:
                        sub = period(df[(df["kind"] == "cascade") & (df["signal"] == sig) & (df[col] == val)], per)
                        s = summarize(sub, h)
                        res["splits"].setdefault(col, {}).setdefault(str(val), {}).setdefault(sig, {}).setdefault(h, {})[per] = s
    res["robustness"] = robustness(df, periods)
    if "2024" in periods:
        for sig in signals:
            for h in HZ:
                ok = True
                for per in ("2022-23", "2024"):
                    c = res["main"]["cascade"][sig][h][per]
                    b = res["main"]["bench"][sig][h][per]
                    ok &= c.get("n", 0) >= MIN_N and c.get("net_mean", -1) > 0 and c.get("net_win", 0) > 0.5
                    ok &= c.get("net_mean", -1) > b.get("net_mean", np.inf)
                if ok:
                    res["promising"].append([sig, h])
    return res
