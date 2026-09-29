"""1時間足の指標を計算する(ステージ2: 指標計算)。

元の指示にある5つの指標:
  1) 現物CVD・先物CVD(テイカー買い-テイカー売りの累積と24時間変化)
  2) 建玉の24時間変化率
  3) ファンディングレート(直近値と7日平均との差)
  4) 上位トレーダーの比率と全体の比率の差
  5) 現物と先物の価格差

先読み防止のルール(docs/methodology.md参照):
  - CVD・OI変化率・funding系は全て「その時点までの過去データ」だけで計算する
  - metrics(5分間隔)・funding_rate(不定期)は、各1時間足の「足が閉じた時刻」以前の
    最新値をas-of backward joinで使う(その足の間に起きた未来の値は使わない)
  - 価格差は同時刻の終値同士の比較なので先読みではない(現在の状態を表すだけ)

上位トレーダー比率について:
  Binanceのmetricsには「全体」はアカウント数ベース(count_long_short_ratio)しか無く、
  「上位トレーダー」はアカウント数ベース(count_toptrader_long_short_ratio)と
  建玉サイズベース(sum_toptrader_long_short_ratio)の両方がある。
  ④天井の売り抜け「上位トレーダーはショート寄り」はポジションの偏りの話なので、
  上位トレーダー側は建玉サイズベース(sum_toptrader_long_short_ratio)を使う。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from shiome.config import PROCESSED_DIR
from shiome.data.symbols import rebase_multiplier

INDICATORS_DIR = PROCESSED_DIR / "indicators"


def _load_klines(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.sort_values("dt").drop_duplicates("dt").set_index("dt")
    return df


def _cvd_delta(df: pd.DataFrame) -> pd.Series:
    taker_buy = df["taker_buy_base_asset_volume"].astype(float)
    volume = df["volume"].astype(float)
    return 2 * taker_buy - volume  # 買い - 売り = 買い - (出来高-買い)


def build_symbol_indicators(symbol: str) -> pd.DataFrame | None:
    """1銘柄分の1時間足指標をまとめて計算する。futures klinesが無ければNoneを返す。"""
    fut = _load_klines(PROCESSED_DIR / "futures_um" / "klines" / "1h" / f"{symbol}.parquet")
    if fut is None:
        return None

    idx = fut.index
    bar_close = (idx + pd.Timedelta(hours=1) - pd.Timedelta(milliseconds=1)).astype("datetime64[ns]")

    out = pd.DataFrame(index=idx)
    out["open_time"] = fut["open_time"].astype("int64")
    out["open"] = fut["open"].astype(float)
    out["high"] = fut["high"].astype(float)
    out["low"] = fut["low"].astype(float)
    out["close"] = fut["close"].astype(float)
    out["volume"] = fut["volume"].astype(float)

    # --- 先物CVD ---
    fut_delta = _cvd_delta(fut).fillna(0)
    out["futures_cvd"] = fut_delta.cumsum()
    out["futures_cvd_chg_24h"] = out["futures_cvd"] - out["futures_cvd"].shift(24)

    # --- 現物CVD・現物先物価格差 ---
    spot = _load_klines(PROCESSED_DIR / "spot" / "klines" / "1h" / f"{symbol}.parquet")
    if spot is not None:
        spot = spot.reindex(idx)
        spot_delta = _cvd_delta(spot).fillna(0)
        out["spot_cvd"] = spot_delta.cumsum()
        out["spot_cvd_chg_24h"] = out["spot_cvd"] - out["spot_cvd"].shift(24)

        mult = rebase_multiplier(symbol)
        adj_spot_close = spot["close"].astype(float) * mult
        out["spot_close_adj"] = adj_spot_close
        out["spot_futures_price_diff_pct"] = (out["close"] - adj_spot_close) / adj_spot_close
    else:
        out["spot_cvd"] = np.nan
        out["spot_cvd_chg_24h"] = np.nan
        out["spot_close_adj"] = np.nan
        out["spot_futures_price_diff_pct"] = np.nan

    # --- 建玉・上位トレーダー比率・全体比率 ---
    metrics_path = PROCESSED_DIR / "futures_um" / "metrics" / f"{symbol}.parquet"
    if metrics_path.exists():
        m = pd.read_parquet(metrics_path)
        m["dt"] = pd.to_datetime(m["create_time"]).astype("datetime64[ns]")
        m = m.sort_values("dt")
        bar_close_df = pd.DataFrame({"bar_close": bar_close})
        merged = pd.merge_asof(
            bar_close_df,
            m[["dt", "sum_open_interest", "sum_toptrader_long_short_ratio", "count_long_short_ratio"]],
            left_on="bar_close",
            right_on="dt",
            direction="backward",
        )
        merged.index = idx

        out["open_interest"] = merged["sum_open_interest"].astype(float)
        out["oi_chg_pct_24h"] = out["open_interest"].pct_change(24).replace([np.inf, -np.inf], np.nan)

        out["toptrader_ratio"] = merged["sum_toptrader_long_short_ratio"].astype(float)
        out["overall_ratio"] = merged["count_long_short_ratio"].astype(float)
        out["trader_ratio_diff"] = out["toptrader_ratio"] - out["overall_ratio"]
    else:
        out["open_interest"] = np.nan
        out["oi_chg_pct_24h"] = np.nan
        out["toptrader_ratio"] = np.nan
        out["overall_ratio"] = np.nan
        out["trader_ratio_diff"] = np.nan

    # --- ファンディングレート ---
    funding_path = PROCESSED_DIR / "futures_um" / "funding_rate" / f"{symbol}.parquet"
    if funding_path.exists():
        fr = pd.read_parquet(funding_path)
        fr["dt"] = pd.to_datetime(fr["calc_time"], unit="ms").astype("datetime64[ns]")
        fr = fr.sort_values("dt")
        bar_close_df2 = pd.DataFrame({"bar_close": bar_close})
        merged_fr = pd.merge_asof(
            bar_close_df2, fr[["dt", "last_funding_rate"]], left_on="bar_close", right_on="dt", direction="backward"
        )
        merged_fr.index = idx
        out["funding_rate"] = merged_fr["last_funding_rate"].astype(float)
        out["funding_rate_7d_avg"] = out["funding_rate"].rolling(24 * 7, min_periods=24).mean()
        out["funding_rate_diff"] = out["funding_rate"] - out["funding_rate_7d_avg"]
    else:
        out["funding_rate"] = np.nan
        out["funding_rate_7d_avg"] = np.nan
        out["funding_rate_diff"] = np.nan

    out = out.reset_index(drop=True)
    return out


def build_and_save(symbol: str) -> Path | None:
    df = build_symbol_indicators(symbol)
    if df is None:
        return None
    INDICATORS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INDICATORS_DIR / f"{symbol}.parquet"
    df.to_parquet(out_path, index=False)
    return out_path
