#!/usr/bin/env python3
"""第3ラウンド: 5分足をダウンロードする(2022-01〜2024-12 のみ。2025年以降は取りにいかない)。

対象は configs/universe_2022_2024.yaml の全銘柄(これまでと同じ)。容量を節約するため、
銘柄ごとに月次zipを取ってきて必要な列だけの parquet にまとめ、zip はすぐ消す。

実行例:
    python scripts/download_5m.py futures
    python scripts/download_5m.py spot

途中で止めても再実行すれば続きから(parquet が完成している銘柄は飛ばす)。
"""
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from shiome.config import CONFIGS_DIR, PROCESSED_DIR, ensure_dirs  # noqa: E402
from shiome.data import klines  # noqa: E402

DATA_START = dt.date(2022, 1, 1)
DATA_END = dt.date(2024, 12, 31)  # これより後は取りにいかない
CUTOFF_MS = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
KEEP = ["open_time", "open", "high", "low", "close", "volume", "quote_asset_volume", "taker_buy_quote_asset_volume"]


def _month_start(m: str) -> dt.date:
    return dt.date(int(m[:4]), int(m[5:7]), 1)


def _month_end(m: str) -> dt.date:
    y, mo = int(m[:4]), int(m[5:7])
    return dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)


def build(market: str, symbol: str) -> bool:
    zips = sorted(klines.raw_dir(market, symbol, "5m").glob("*.zip"))
    frames = []
    for z in zips:
        df = klines.read_kline_zip(z)
        frames.append(df[KEEP])
    if not frames:
        return False
    df = pd.concat(frames, ignore_index=True)
    df = df[df["open_time"] < CUTOFF_MS].drop_duplicates("open_time").sort_values("open_time")
    for c in KEEP[1:5]:
        df[c] = df[c].astype(np.float64)
    for c in KEEP[5:]:
        df[c] = df[c].astype(np.float32)
    df = df.rename(columns={"quote_asset_volume": "quote_volume", "taker_buy_quote_asset_volume": "taker_buy_quote"})
    out = PROCESSED_DIR / market / "klines" / "5m" / f"{symbol}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.rename(out)  # 書き終わってから名前を付ける(途中で止まっても壊れたファイルが残らない)
    return True


def main() -> None:
    market = {"futures": "futures_um", "spot": "spot"}.get(sys.argv[1] if len(sys.argv) > 1 else "")
    if market is None:
        sys.exit("使い方: python scripts/download_5m.py futures|spot")
    ensure_dirs()
    universe = yaml.safe_load((CONFIGS_DIR / "universe_2022_2024.yaml").read_text(encoding="utf-8"))["symbols"]
    todo = []
    for s, info in universe.items():
        if market == "spot":
            if "spot_first_month" not in info:
                continue
            first, last, remote = info["spot_first_month"], info["spot_last_month"], info["spot_symbol"]
        else:
            first, last, remote = info["first_month"], info["last_month"], s
        if not (PROCESSED_DIR / market / "klines" / "5m" / f"{s}.parquet").exists():
            todo.append((s, first, last, remote))
    print(f"{len(todo)}銘柄を取得します({market} 5分足、2024年12月分まで)", flush=True)
    for i, (s, first, last, remote) in enumerate(todo, 1):
        start = max(DATA_START, _month_start(first))
        end = min(DATA_END, _month_end(last))
        klines.download_symbol_klines(market, s, "5m", start, end, remote_symbol=remote)
        ok = build(market, s)
        shutil.rmtree(klines.raw_dir(market, s, "5m"), ignore_errors=True)  # 容量節約
        print(f"[{i}/{len(todo)}] {s} {'済み' if ok else 'データなし'}", flush=True)
    print("完了。", flush=True)


if __name__ == "__main__":
    main()
