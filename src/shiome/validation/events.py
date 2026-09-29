"""局面の「発生イベント」を組み立てる: 重複排除・売買タイミング・値動き集計・
上場廃止時の決済・コスト計算(docs/methodology.md #2, #3, #8)。
"""
from __future__ import annotations

import pandas as pd

from shiome.config import PROCESSED_DIR, load_settings

HORIZONS = (4, 24, 72, 168)


def _cost_pct(volume_usd: float) -> float:
    """往復コスト(%) = 往復手数料 + 片道スリッページ×2(往復分)。"""
    settings = load_settings()
    cost_cfg = settings["cost_model"]
    fee = cost_cfg["round_trip_fee_pct"]
    slippage_one_way = cost_cfg["slippage_tiers_usd_volume"][-1]["slippage_pct"]  # デフォルト(最下層)
    for tier in cost_cfg["slippage_tiers_usd_volume"]:
        if volume_usd >= tier["min_usd"]:
            slippage_one_way = tier["slippage_pct"]
            break
    return fee + 2 * slippage_one_way


def _extract_entries(phase_series: pd.Series, min_gap_bars: int) -> list[int]:
    """局面が(False/NaN)->Trueに切り替わった最初の時点だけを、24時間以上の間隔をあけて抽出する。"""
    is_true = phase_series == True  # noqa: E712
    prev_true = is_true.shift(1, fill_value=False)
    starts = is_true & ~prev_true
    start_idx = list(phase_series.index[starts])

    kept = []
    last_kept = -min_gap_bars - 1
    for idx in start_idx:
        pos = phase_series.index.get_loc(idx)
        if pos - last_kept >= min_gap_bars:
            kept.append(pos)
            last_kept = pos
    return kept


def build_symbol_events(symbol: str, is_delisted: bool) -> pd.DataFrame:
    """1銘柄・6局面分のイベント一覧(1イベント1行)を返す。"""
    settings = load_settings()
    min_gap_bars = settings["validation"]["min_recount_gap_hours"]
    direction_map = settings["validation"]["phase_expected_direction"]

    path = PROCESSED_DIR / "phases" / f"{symbol}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path).reset_index(drop=True)
    n = len(df)
    open_ = df["open"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    close = df["close"].astype(float).values
    quote_vol = df["volume"].astype(float).values * close  # 出来高の目安(USD)

    rows = []
    for i, phase_key in enumerate(["1_healthy_uptrend", "2_overleveraged_uptrend", "3_short_squeeze_setup",
                                    "4_distribution_top", "5_capitulation_bottom", "6_compression"], start=1):
        col = f"phase_{i}"
        if col not in df.columns:
            continue
        direction = direction_map[phase_key]  # "up" / "down" / "neutral"
        dir_sign = {"up": 1, "down": -1, "neutral": 0}[direction]

        entries = _extract_entries(df[col], min_gap_bars)
        for t in entries:
            entry_idx = t + 1
            if entry_idx >= n:
                continue  # 次の足が無い(データ終端)ので売買できない
            entry_price = open_[entry_idx]
            if entry_price <= 0:
                continue

            trailing_start = max(0, entry_idx - 24)
            volume_usd_24h = float(quote_vol[trailing_start:entry_idx].sum())
            cost_pct = _cost_pct(volume_usd_24h)

            row = {
                "symbol": symbol, "phase": phase_key, "phase_num": i,
                "entry_bar": entry_idx, "entry_time_ms": int(df["open_time"].iloc[entry_idx]),
                "entry_price": entry_price, "direction": direction, "dir_sign": dir_sign,
                "cost_pct": cost_pct,
            }

            for h in HORIZONS:
                exit_idx = entry_idx + h
                delisted_exit = False
                if exit_idx < n:
                    exit_price = open_[exit_idx]
                    window_high = high[entry_idx:exit_idx + 1].max()
                    window_low = low[entry_idx:exit_idx + 1].min()
                elif is_delisted:
                    # 上場廃止銘柄: 最後の値で強制決済したものとして扱う(docs/methodology.md #8)
                    exit_price = close[-1]
                    window_high = high[entry_idx:].max()
                    window_low = low[entry_idx:].min()
                    delisted_exit = True
                else:
                    # 現存銘柄でデータがまだその先まで無いだけ(打ち切り) -> この期間は評価しない
                    row[f"ret_{h}h"] = None
                    row[f"mae_{h}h"] = None
                    row[f"delisted_exit_{h}h"] = None
                    continue

                ret = exit_price / entry_price - 1
                if dir_sign != 0:
                    directional_ret = ret * dir_sign
                    # 逆行幅(MAE): 期待方向と逆に動いた最大の割合
                    if dir_sign > 0:
                        mae = (entry_price - window_low) / entry_price
                    else:
                        mae = (window_high - entry_price) / entry_price
                else:
                    directional_ret = abs(ret)  # ⑥は方向を評価しない(値幅の大きさで評価)
                    mae = None

                row[f"ret_{h}h"] = directional_ret
                row[f"mae_{h}h"] = mae
                row[f"delisted_exit_{h}h"] = delisted_exit

            rows.append(row)

    return pd.DataFrame(rows)
