"""USD-M先物の daily metrics(5分間隔: 建玉・上位トレーダー比率・全体比率・テイカー比率)を取得する。

data.binance.vision にはmonthly版が無く、daily(1日1ファイル)のみ提供されている。
CSV列(想定・要検証): create_time, symbol, sum_open_interest, sum_open_interest_value,
  count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
  count_long_short_ratio, sum_taker_long_short_vol_ratio
実際の列名は初回ダウンロード後に必ず確認し、ズレていればここを直す。
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from shiome.config import RAW_DIR, load_settings
from shiome.data.binance_vision import download_file
from shiome.data.date_utils import day_range

PREFIX = "data/futures/um/daily/metrics"


def daily_key(symbol: str, d: dt.date) -> str:
    return f"{PREFIX}/{symbol}/{symbol}-metrics-{d.year:04d}-{d.month:02d}-{d.day:02d}.zip"


def raw_dir(symbol: str) -> Path:
    return RAW_DIR / "futures_um" / "metrics" / symbol


def download_symbol_metrics(symbol: str, start: dt.date, end: dt.date) -> dict:
    settings = load_settings()
    dest_dir = raw_dir(symbol)
    keys = [daily_key(symbol, d) for d in day_range(start, end)]

    result = {"symbol": symbol, "total": len(keys), "downloaded": 0, "skipped": 0, "failed": []}

    def _task(key: str):
        filename = key.rsplit("/", 1)[-1]
        dest = dest_dir / filename
        try:
            did_download = download_file(key, dest)
            return key, did_download, None
        except Exception as e:  # noqa: BLE001
            return key, False, str(e)

    with ThreadPoolExecutor(max_workers=settings["download"]["max_workers"]) as ex:
        futures = [ex.submit(_task, k) for k in keys]
        for fut in as_completed(futures):
            key, did_download, err = fut.result()
            if err is not None:
                result["failed"].append({"key": key, "error": err})
            elif did_download:
                result["downloaded"] += 1
            else:
                result["skipped"] += 1

    return result


def build_symbol_parquet(symbol: str) -> Path | None:
    import zipfile
    import io

    dest_dir = raw_dir(symbol)
    zip_files = sorted(dest_dir.glob("*.zip"))
    if not zip_files:
        return None

    frames = []
    for zp in zip_files:
        try:
            with zipfile.ZipFile(zp) as zf:
                name = zf.namelist()[0]
                with zf.open(name) as f:
                    df = pd.read_csv(io.BytesIO(f.read()))
            df.columns = [c.strip().lower() for c in df.columns]
            frames.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] futures_metrics/{symbol}: {zp.name} の読み込み失敗: {e}")

    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True)
    time_col = "create_time" if "create_time" in df.columns else df.columns[0]
    df = df.drop_duplicates(subset=[time_col]).sort_values(time_col).reset_index(drop=True)

    out_dir = RAW_DIR.parent / "processed" / "futures_um" / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def download_and_build(symbols: list[str], start: dt.date, end: dt.date) -> list[dict]:
    results = []
    for symbol in tqdm(symbols, desc="futures metrics(5m)"):
        r = download_symbol_metrics(symbol, start, end)
        r["parquet"] = build_symbol_parquet(symbol)
        results.append(r)
    return results
