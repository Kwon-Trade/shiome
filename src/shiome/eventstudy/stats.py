"""急騰直前・急落直前・普通の時点の3グループで、指標の分布を比較する。

比較には銘柄ごとの90日パーセンタイル順位を使う(銘柄をまたいでも公平に比べられる)。
- AUC: 「イベント直前の値が、普通の時点の値より大きい確率」。0.5なら差なし、
  0.5より大きければイベント直前は高め、小さければ低め。
- p値: マン・ホイットニーのU検定(分布の形を仮定しない検定)。検定の回数が多いので
  ボンフェローニ補正(検定数を掛ける)した値も出す。
- 信頼区間: 大きな相場変動は多くの銘柄で同じ週に起きやすく、サンプル同士が独立でない。
  p値はその分だけ甘く出るため、週単位のブロック・ブートストラップでAUCの95%区間も出す。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from shiome.eventstudy.samples import ALL_FEATURES, OFFSETS, REFERENCE_COLS

WEEK_MS = 7 * 24 * 3600 * 1000


def _auc(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([a, b])).rank().to_numpy()
    return float((ranks[: len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)))


def _block_bootstrap_auc(ev: pd.DataFrame, rd: pd.DataFrame, col: str, n_boot: int, rng: np.random.Generator):
    ev_w = (ev["open_time"] // WEEK_MS).to_numpy()
    rd_w = (rd["open_time"] // WEEK_MS).to_numpy()
    weeks = np.union1d(ev_w, rd_w)
    ev_by = {w: ev[col].to_numpy()[ev_w == w] for w in np.unique(ev_w)}
    rd_by = {w: rd[col].to_numpy()[rd_w == w] for w in np.unique(rd_w)}
    empty = np.array([])
    aucs = []
    for _ in range(n_boot):
        pick = rng.choice(weeks, size=len(weeks), replace=True)
        a = np.concatenate([ev_by.get(w, empty) for w in pick])
        b = np.concatenate([rd_by.get(w, empty) for w in pick])
        aucs.append(_auc(a, b))
    return float(np.nanpercentile(aucs, 2.5)), float(np.nanpercentile(aucs, 97.5))


def compare_single(samples: pd.DataFrame, n_boot: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    random = samples[samples["kind"] == "random"]
    n_tests = len(ALL_FEATURES) * len(OFFSETS) * 2
    rows = []
    for direction in ("surge", "crash"):
        events = samples[samples["kind"] == direction]
        for k in OFFSETS:
            for col, label in ALL_FEATURES:
                raw, pct = f"{col}__t{k}", f"{col}__pct__t{k}"
                ev = events[["open_time", raw, pct]].dropna()
                rd = random[["open_time", raw, pct]].dropna()
                if len(ev) < 30 or len(rd) < 30:
                    continue
                p = mannwhitneyu(ev[pct], rd[pct], alternative="two-sided").pvalue
                auc = _auc(ev[pct].to_numpy(), rd[pct].to_numpy())
                lo, hi = _block_bootstrap_auc(ev, rd, pct, n_boot, rng)
                rows.append({
                    "direction": direction, "offset_h": k, "feature": col, "label": label,
                    "is_reference": col in REFERENCE_COLS,
                    "n_event": len(ev), "n_random": len(rd),
                    "event_mean": ev[raw].mean(), "event_median": ev[raw].median(),
                    "random_mean": rd[raw].mean(), "random_median": rd[raw].median(),
                    "event_pct_median": ev[pct].median(), "random_pct_median": rd[pct].median(),
                    "auc": auc, "auc_ci_lo": lo, "auc_ci_hi": hi,
                    "p_value": p, "p_bonferroni": min(1.0, p * n_tests),
                })
    out = pd.DataFrame(rows)
    out["effect"] = (out["auc"] - 0.5).abs()
    out["robust"] = (out["auc_ci_lo"] > 0.5) | (out["auc_ci_hi"] < 0.5)
    out["significant"] = out["p_bonferroni"] < 0.05
    return out


def group_breakdown(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group, g in samples.groupby("group"):
        random = g[g["kind"] == "random"]
        for direction in ("surge", "crash"):
            events = g[g["kind"] == direction]
            for k in OFFSETS:
                for col, label in ALL_FEATURES:
                    pct = f"{col}__pct__t{k}"
                    ev, rd = events[pct].dropna(), random[pct].dropna()
                    if len(ev) < 30 or len(rd) < 30:
                        continue
                    rows.append({"group": group, "direction": direction, "offset_h": k, "feature": col,
                                 "label": label, "n_event": len(ev), "auc": _auc(ev.to_numpy(), rd.to_numpy())})
    return pd.DataFrame(rows)


def decile_lift(samples: pd.DataFrame, direction: str, feature: str, offset: int) -> pd.DataFrame:
    """指標を10段階(パーセンタイル順位)に分け、各段階でイベントが普通の時点の何倍起きているか。"""
    pct = f"{feature}__pct__t{offset}"
    ev = samples.loc[samples["kind"] == direction, pct].dropna()
    rd = samples.loc[samples["kind"] == "random", pct].dropna()
    bins = np.linspace(0, 100, 11)
    ev_share = np.histogram(ev, bins=bins)[0] / len(ev)
    rd_share = np.histogram(rd, bins=bins)[0] / len(rd)
    return pd.DataFrame({
        "decile": np.arange(1, 11),
        "event_share": ev_share, "random_share": rd_share,
        "lift": np.where(rd_share > 0, ev_share / np.where(rd_share > 0, rd_share, 1), np.nan),
    })
