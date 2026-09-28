"""現物・USD-M先物の1時間足klines(ローソク足)をdata.binance.visionから取得する。

流れ:
  1) 対象期間をカバーする月次ファイル(monthly)を優先してダウンロード
  2) 直近、月次がまだ存在しない分は日次ファイル(daily)で補う
  3) zipを展開してCSVを読み込み、1銘柄1parquetに結合する

Binanceのklines CSV列(ヘッダ無し版・有り版どちらもあり得るので両対応):
  open_time, open, high, low, close, volume, close_time,
  quote_asset_volume, number_of_trades,
  taker_buy_base_asset_volume, taker_buy_quote_asset_volume, ignore
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
from shiome.data.date_utils import day_range, month_range

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
]

# 2024年頃を境に、ヘッダー付きファイルの列名が短縮された(例: quote_volume, count)。
# 常にKLINE_COLUMNSの正式名に揃える。
HEADER_RENAME_MAP = {
    "quote_volume": "quote_asset_volume",
    "count": "number_of_trades",
    "taker_buy_volume": "taker_buy_base_asset_volume",
    "taker_buy_quote_volume": "taker_buy_quote_asset_volume",
}

MARKET_PREFIX = {
    "spot": "data/spot",
    "futures_um": "data/futures/um",
}


def monthly_key(market: str, symbol: str, interval: str, year: int, month: int) -> str:
    prefix = MARKET_PREFIX[market]
    return f"{prefix}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year:04d}-{month:02d}.zip"


def daily_key(market: str, symbol: str, interval: str, d: dt.date) -> str:
    prefix = MARKET_PREFIX[market]
    return f"{prefix}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d.year:04d}-{d.month:02d}-{d.day:02d}.zip"


def raw_dir(market: str, symbol: str, interval: str) -> Path:
    return RAW_DIR / market / "klines" / interval / symbol


def plan_download_keys(market: str, symbol: str, interval: str, start: dt.date, end: dt.date) -> list[str]:
    """monthly優先、当月分(まだmonthlyが出ていない分)はdailyで埋める計画を作る。"""
    today = dt.date.today()
    last_full_month_end = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)

    keys: list[str] = []
    for m in month_range(start, min(end, last_full_month_end)):
        keys.append(monthly_key(market, symbol, interval, m.year, m.month))

    daily_start = max(start, dt.date(today.year, today.month, 1))
    if daily_start <= end:
        for d in day_range(daily_start, end):
            keys.append(daily_key(market, symbol, interval, d))

    return keys


def download_symbol_klines(market: str, symbol: str, interval: str, start: dt.date, end: dt.date) -> dict:
    """1銘柄分のklinesファイルをダウンロード。結果件数を返す(成功/失敗/スキップ)。"""
    settings = load_settings()
    keys = plan_download_keys(market, symbol, interval, start, end)
    dest_dir = raw_dir(market, symbol, interval)

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
                # 404は「そもそも上場前/未生成」の可能性が高いので致命的エラーとは分けて記録
                result["failed"].append({"key": key, "error": err})
            elif did_download:
                result["downloaded"] += 1
            else:
                result["skipped"] += 1

    return result


def read_kline_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            raw = f.read()
    first_line = raw.split(b"\n", 1)[0].decode("utf-8", errors="ignore")
    has_header = not first_line.strip().split(",")[0].lstrip("-").isdigit()
    df = pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        names=None if has_header else KLINE_COLUMNS,
    )
    if has_header:
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns=HEADER_RENAME_MAP)
    return df


def build_symbol_parquet(market: str, symbol: str, interval: str) -> Path | None:
    """ダウンロード済みzipを全部読み込み、時刻順に結合して1本のparquetにまとめる。"""
    dest_dir = raw_dir(market, symbol, interval)
    zip_files = sorted(dest_dir.glob("*.zip"))
    if not zip_files:
        return None

    frames = []
    for zp in zip_files:
        try:
            frames.append(read_kline_zip(zp))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {market}/{symbol}/{interval}: {zp.name} の読み込み失敗: {e}")

    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)

    out_dir = RAW_DIR.parent / "processed" / market / "klines" / interval
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def download_and_build(market: str, symbols: list[str], interval: str, start: dt.date, end: dt.date) -> list[dict]:
    results = []
    for symbol in tqdm(symbols, desc=f"{market} klines({interval})"):
        r = download_symbol_klines(market, symbol, interval, start, end)
        out_path = RAW_DIR.parent / "processed" / market / "klines" / interval / f"{symbol}.parquet"
        if r["downloaded"] > 0 or not out_path.exists():
            r["parquet"] = build_symbol_parquet(market, symbol, interval)
        else:
            r["parquet"] = out_path
        results.append(r)
    return results
