"""イベントスタディ(逆引き分析)用のサンプルを作る。

- 大イベント: 24時間後の値動きが、その銘柄の上位5%(急騰)/下位5%(急落)に入る時点。
  急騰・急落が続く間の連続した時間を全部数えると件数が水増しされるため、
  「始まりの1時間」だけを採用し、同じ銘柄・同じ方向は24時間あける。
- 普通の時点: 上位/下位5%に入らない時点から、銘柄ごとにイベントと同数を無作為抽出。
- 各サンプル時点の6/12/24時間前の指標値(生の値と、銘柄ごとの90日パーセンタイル順位)を記録。

答え合わせ期間(2025年以降)に触れないよう、読み込んだデータを最初に2024年末で切り捨てる。
そのため「24時間後」が2025年にはみ出す2024年末ぎりぎりの時点は自動的に対象外になる。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shiome.config import PROCESSED_DIR, load_settings
from shiome.phases.percentile import rolling_percentile_rank

OFFSETS = (6, 12, 24)
FORWARD_HOURS = 24
EVENT_PCT = 5
MIN_GAP_HOURS = 24
MIN_VALID_HOURS = 180 * 24

# (列名, 表示名)
FEATURES = [
    ("spot_taker_ratio_24h", "現物CVD(24h買い越し比率)"),
    ("fut_taker_ratio_24h", "先物CVD(24h買い越し比率)"),
    ("oi_chg_pct_24h", "建玉の24h変化率"),
    ("funding_rate", "FR(水準)"),
    ("funding_rate_diff", "FR(7日平均との差)"),
    ("trader_ratio_diff", "上位トレーダー比率−全体比率"),
    ("spot_futures_price_diff_pct", "先物と現物の価格差"),
]
# 比較用の物差し。デリバティブ指標が「値動きの激しさ」以上の情報を持つかを見るため。
REFERENCE_FEATURES = [
    ("past_ret_24h", "参考: 過去24hの値動き"),
    ("past_range_24h", "参考: 過去24hの値幅"),
]
ALL_FEATURES = FEATURES + REFERENCE_FEATURES
REFERENCE_COLS = {c for c, _ in REFERENCE_FEATURES}
FEATURE_NAMES = dict(ALL_FEATURES)


def _rule_end() -> pd.Timestamp:
    settings = load_settings()
    return pd.Timestamp(settings["split"]["holdout_start"])  # この時刻より前だけ使う


def _spot_volume(symbol: str, open_time: pd.Series) -> pd.Series:
    path = PROCESSED_DIR / "spot" / "klines" / "1h" / f"{symbol}.parquet"
    if not path.exists():
        return pd.Series(np.nan, index=open_time.index)
    spot = pd.read_parquet(path, columns=["open_time", "volume"]).drop_duplicates("open_time")
    vol = spot.set_index("open_time")["volume"].astype(float)
    return pd.Series(open_time.map(vol).values, index=open_time.index)


def load_symbol_frame(symbol: str) -> pd.DataFrame | None:
    path = PROCESSED_DIR / "indicators" / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    cutoff_ms = int(_rule_end().timestamp() * 1000)
    df = df[df["open_time"] < cutoff_ms].reset_index(drop=True)  # 2025年以降は読まない
    if len(df) < MIN_VALID_HOURS:
        return None

    fut_vol_24h = df["volume"].astype(float).rolling(24).sum()
    df["fut_taker_ratio_24h"] = df["futures_cvd_chg_24h"] / fut_vol_24h.replace(0, np.nan)

    spot_vol = _spot_volume(symbol, df["open_time"])
    spot_vol_24h = spot_vol.rolling(24, min_periods=20).sum()
    df["spot_taker_ratio_24h"] = df["spot_cvd_chg_24h"] / spot_vol_24h.replace(0, np.nan)

    df["past_ret_24h"] = df["close"].pct_change(24)
    df["past_range_24h"] = (df["high"].rolling(24).max() - df["low"].rolling(24).min()) / df["close"]

    for col, _ in ALL_FEATURES:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan)
        df[f"{col}__pct"] = rolling_percentile_rank(df[col])

    df["fwd_ret_24h"] = df["close"].shift(-FORWARD_HOURS) / df["close"] - 1
    return df


def _onsets(flag: pd.Series) -> np.ndarray:
    """フラグが立ち始めた時点だけを、24時間以上の間隔をあけて返す(行位置)。"""
    starts = flag & ~flag.shift(1, fill_value=False)
    kept, last = [], -MIN_GAP_HOURS - 1
    for pos in np.flatnonzero(starts.to_numpy()):
        if pos - last >= MIN_GAP_HOURS:
            kept.append(pos)
            last = pos
    return np.array(kept, dtype=int)


def build_symbol_samples(symbol: str, group: str, rng: np.random.Generator) -> pd.DataFrame:
    df = load_symbol_frame(symbol)
    if df is None:
        return pd.DataFrame()

    valid = df["fwd_ret_24h"].notna()
    if valid.sum() < MIN_VALID_HOURS:
        return pd.DataFrame()
    hi = df.loc[valid, "fwd_ret_24h"].quantile(1 - EVENT_PCT / 100)
    lo = df.loc[valid, "fwd_ret_24h"].quantile(EVENT_PCT / 100)

    surge_flag = valid & (df["fwd_ret_24h"] >= hi)
    crash_flag = valid & (df["fwd_ret_24h"] <= lo)
    surge_pos = _onsets(surge_flag)
    crash_pos = _onsets(crash_flag)

    normal_pool = np.flatnonzero((valid & ~surge_flag & ~crash_flag).to_numpy())
    n_random = min(len(surge_pos) + len(crash_pos), len(normal_pool))
    random_pos = np.sort(rng.choice(normal_pool, size=n_random, replace=False))

    rows = []
    for kind, positions in (("surge", surge_pos), ("crash", crash_pos), ("random", random_pos)):
        for pos in positions:
            row = {
                "symbol": symbol, "group": group, "kind": kind,
                "open_time": int(df["open_time"].iat[pos]),
                "fwd_ret_24h": float(df["fwd_ret_24h"].iat[pos]),
                "threshold_hi": float(hi), "threshold_lo": float(lo),
            }
            for k in OFFSETS:
                src = pos - k
                for col, _ in ALL_FEATURES:
                    row[f"{col}__t{k}"] = float(df[col].iat[src]) if src >= 0 else np.nan
                    row[f"{col}__pct__t{k}"] = float(df[f"{col}__pct"].iat[src]) if src >= 0 else np.nan
            rows.append(row)
    return pd.DataFrame(rows)
