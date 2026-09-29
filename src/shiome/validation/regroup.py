"""大型/中型アルト/小型・ミームのグループ分けを、ルール作り期間(2022〜2024年)の
出来高だけを使って再計算する(docs/methodology.md #7)。

symbols.yaml時点のグループ分けはダウンロード時点(2026年)の出来高で作ったため、
答え合わせ期間の情報が混ざっている可能性がある。ここでは2022-01-01〜2024-12-31の
先物klinesのクオート出来高合計だけを使って中型/小型を区分けし直す
(大型は市場規模の識名的な選定であり、この期間の情報だけから漏れる心配は無いため据え置く)。
"""
from __future__ import annotations

import pandas as pd

from shiome.config import PROCESSED_DIR, load_settings, load_symbols


def historical_volume_groups() -> dict:
    settings = load_settings()
    symbols_cfg = load_symbols()
    rule_end = pd.Timestamp(settings["split"]["rule_building_end"])
    rule_start = pd.Timestamp(settings["date_range"]["start"])

    large_cap = list(symbols_cfg["groups"]["large_cap"])
    delisted = set(symbols_cfg["delisted"])

    candidates = []
    for g in ("mid_cap_alt", "small_meme"):
        for s in symbols_cfg["groups"][g]:
            if s not in large_cap and s not in candidates:
                candidates.append(s)

    volume: dict[str, float] = {}
    for symbol in candidates:
        path = PROCESSED_DIR / "futures_um" / "klines" / "1h" / f"{symbol}.parquet"
        if not path.exists():
            volume[symbol] = 0.0
            continue
        df = pd.read_parquet(path, columns=["open_time", "quote_asset_volume"])
        dt = pd.to_datetime(df["open_time"], unit="ms")
        mask = (dt >= rule_start) & (dt <= rule_end)
        volume[symbol] = float(df.loc[mask, "quote_asset_volume"].astype(float).sum())

    non_delisted = [s for s in candidates if s not in delisted]
    non_delisted_sorted = sorted(non_delisted, key=lambda s: volume.get(s, 0.0), reverse=True)

    mid_n = len(symbols_cfg["groups"]["mid_cap_alt"])
    mid_cap_alt = non_delisted_sorted[:mid_n]
    small_meme = non_delisted_sorted[mid_n:] + sorted(s for s in candidates if s in delisted)

    return {
        "large_cap": large_cap,
        "mid_cap_alt": mid_cap_alt,
        "small_meme": small_meme,
    }


def symbol_to_group_map() -> dict[str, str]:
    groups = historical_volume_groups()
    out = {}
    for g, symbols in groups.items():
        for s in symbols:
            out[s] = g
    return out
