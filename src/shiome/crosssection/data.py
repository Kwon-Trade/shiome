"""第2ラウンド用のデータ読み込み。

- 2025年以降は絶対に読まない(HARD_END)。読み込み直後に切り捨て、それより後を要求されたら止める。
- 仕組み作り・動作確認の間は2023年末まで(DEV_END)に絞り、2024年は最後の1回だけ使う。
- 1時間足は「抜けている時間」も行として持つ(present=False)。行ずらしではなく時刻で計算するため。
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from shiome.config import CONFIGS_DIR, PROCESSED_DIR

HARD_END = pd.Timestamp("2025-01-01")  # これ以降のデータは読まない
DEV_END = pd.Timestamp("2024-01-01")   # 仕組み作りの間はここまで
HOUR = pd.Timedelta(hours=1)


def _check_end(end: pd.Timestamp) -> int:
    if end > HARD_END:
        raise ValueError(f"{end} は答え合わせ期間(2025年以降)にかかるため読み込めません")
    return int(end.timestamp() * 1000)


def _ms_to_ts(ms) -> pd.DatetimeIndex:
    # 時刻の単位をナノ秒にそろえる(pandas 3はデータによってms/usになり、比較がずれるのを防ぐ)
    return pd.DatetimeIndex(pd.to_datetime(ms, unit="ms")).as_unit("ns")


def load_futures_hourly(symbol: str, end: pd.Timestamp) -> pd.DataFrame | None:
    """先物1時間足。index=足の開始時刻(抜けを含む連続した1時間刻み)。"""
    end_ms = _check_end(end)
    path = PROCESSED_DIR / "futures_um" / "klines" / "1h" / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["open_time", "high", "low", "close", "volume", "quote_asset_volume"])
    df = df[df["open_time"] < end_ms].drop_duplicates("open_time").sort_values("open_time")
    if df.empty:
        return None
    df.index = _ms_to_ts(df.pop("open_time"))
    df = df.astype(float).rename(columns={"quote_asset_volume": "quote_volume"})
    grid = pd.date_range(df.index[0], df.index[-1], freq="h")
    df = df.reindex(grid)
    df["present"] = df["close"].notna()
    return df


def load_spot_quote_volume(symbol: str, index: pd.DatetimeIndex, end: pd.Timestamp) -> pd.Series:
    """現物のUSDT建て出来高(先物の時刻に合わせる)。現物データが無ければ全部NaN。"""
    end_ms = _check_end(end)
    path = PROCESSED_DIR / "spot" / "klines" / "1h" / f"{symbol}.parquet"
    if not path.exists():
        return pd.Series(np.nan, index=index)
    s = pd.read_parquet(path, columns=["open_time", "quote_asset_volume"])
    s = s[s["open_time"] < end_ms].drop_duplicates("open_time")
    return pd.Series(s["quote_asset_volume"].astype(float).values, index=_ms_to_ts(s["open_time"])).reindex(index)


def load_funding(symbol: str, end: pd.Timestamp) -> pd.Series:
    """ファンディングレートの確定値。index=確定時刻。"""
    end_ms = _check_end(end)
    path = PROCESSED_DIR / "futures_um" / "funding_rate" / f"{symbol}.parquet"
    if not path.exists():
        return pd.Series(dtype=float)
    fr = pd.read_parquet(path, columns=["calc_time", "last_funding_rate"])
    fr = fr[fr["calc_time"] < end_ms].drop_duplicates("calc_time").sort_values("calc_time")
    return pd.Series(fr["last_funding_rate"].astype(float).values, index=_ms_to_ts(fr["calc_time"]))


def load_open_interest(symbol: str, end: pd.Timestamp) -> pd.Series:
    """建玉(枚数ベース。価格の上下で数字が動かないようにUSD換算ではなく枚数を使う)。index=記録時刻。"""
    _check_end(end)
    path = PROCESSED_DIR / "futures_um" / "metrics" / f"{symbol}.parquet"
    if not path.exists():
        return pd.Series(dtype=float)
    m = pd.read_parquet(path, columns=["create_time", "sum_open_interest"])
    m["dt"] = pd.to_datetime(m["create_time"])
    m = m[m["dt"] < end].drop_duplicates("dt").sort_values("dt")
    return pd.Series(m["sum_open_interest"].astype(float).values, index=pd.DatetimeIndex(m["dt"]).as_unit("ns"))


@lru_cache(maxsize=1)
def full_universe() -> dict:
    """2022〜2024年にあった全銘柄(configs/universe_2022_2024.yaml)。"""
    with open(CONFIGS_DIR / "universe_2022_2024.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["symbols"]


@lru_cache(maxsize=1)
def _listing_overrides() -> dict:
    with open(CONFIGS_DIR / "listing_dates.yaml", "r", encoding="utf-8") as f:
        out = dict(yaml.safe_load(f)["before_data_start"])
    for sym, info in full_universe().items():
        if "listed" in info:
            out.setdefault(sym, info["listed"])
    return out


def listing_time(symbol: str, first_bar: pd.Timestamp) -> pd.Timestamp:
    """先物の上場時刻。2022年より前に上場した銘柄はS3のファイル名一覧から調べた日付(月)、
    それ以外は手元データの最初の足。"""
    before = _listing_overrides()
    if symbol in before:
        return pd.Timestamp(before[symbol])  # "2020-01" は月初として扱う(どれも90日以上前なので影響しない)
    if first_bar <= pd.Timestamp("2022-01-01"):
        raise ValueError(f"{symbol}: 手元データの開始日より前に上場した銘柄の上場日が分かりません")
    return first_bar
