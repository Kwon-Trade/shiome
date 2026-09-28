"""ファンディングレート履歴の取得。

data.binance.vision と同じS3バケットに月次の一括データ(data/futures/um/monthly/fundingRate/)が
あることを確認できたため、fapi.binance.com のライブAPIではなくこちらを使う
(このクラウド実行環境では fapi.binance.com への直接アクセスがブロックされているため)。

注意: 日次(daily)ファイルは提供されていない。そのため実行中の月(まだ月次ファイルが
出ていない直近分)は翌月にならないと取得できない。バックテストの「答え合わせ期間」には
影響しない(直近1ヶ月弱が欠けるだけ)。

CSV列: calc_time, funding_interval_hours, last_funding_rate
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from shiome.config import RAW_DIR, load_settings
from shiome.data.binance_vision import download_file
from shiome.data.date_utils import month_range

PREFIX = "data/futures/um/monthly/fundingRate"


def monthly_key(symbol: str, year: int, month: int) -> str:
    return f"{PREFIX}/{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"


def raw_dir(symbol: str) -> Path:
    return RAW_DIR / "futures_um" / "funding_rate" / symbol


def _last_full_month_end(today: dt.date) -> dt.date:
    return dt.date(today.year, today.month, 1) - dt.timedelta(days=1)


def download_symbol_funding_rate(symbol: str, start: dt.date, end: dt.date) -> dict:
    settings = load_settings()
    today = dt.date.today()
    effective_end = min(end, _last_full_month_end(today))
    dest_dir = raw_dir(symbol)

    keys = [
        monthly_key(symbol, m.year, m.month)
        for m in month_range(start, effective_end)
    ] if start <= effective_end else []

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
            print(f"[warn] funding_rate/{symbol}: {zp.name} の読み込み失敗: {e}")

    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True)
    time_col = "calc_time" if "calc_time" in df.columns else df.columns[0]
    df = df.drop_duplicates(subset=[time_col]).sort_values(time_col).reset_index(drop=True)

    out_dir = RAW_DIR.parent / "processed" / "futures_um" / "funding_rate"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def download_and_build(symbols: list[str], start: dt.date, end: dt.date) -> list[dict]:
    results = []
    for symbol in tqdm(symbols, desc="funding rate"):
        r = download_symbol_funding_rate(symbol, start, end)
        r["parquet"] = build_symbol_parquet(symbol)
        results.append(r)
    return results
