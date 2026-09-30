#!/usr/bin/env python3
"""第3ラウンドの答え合わせ用: 先物5分足を2025-01〜2026-08の分だけダウンロードし、手元の2022〜2024年分に継ぎ足す。

対象は configs/universe_2025_2026.yaml。docs/hypotheses_v3.md §13 を記録・コミットした後にだけ使う。

実行例:
    python scripts/download_5m_holdout.py
"""
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from download_5m import KEEP, _month_end, _month_start  # noqa: E402
from shiome.config import CONFIGS_DIR, PROCESSED_DIR, ensure_dirs  # noqa: E402
from shiome.data import klines  # noqa: E402

START = dt.date(2025, 1, 1)
LAST = dt.date(2026, 8, 31)
END_MS = int(dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
OUT = PROCESSED_DIR / "futures_um" / "klines" / "5m"


def _done(symbol: str, end: dt.date) -> bool:
    path = OUT / f"{symbol}.parquet"
    if not path.exists():
        return False
    last = pd.read_parquet(path, columns=["open_time"])["open_time"].max()
    return pd.to_datetime(last, unit="ms") >= pd.Timestamp(end) + pd.Timedelta(hours=22)


def main() -> None:
    ensure_dirs()
    universe = yaml.safe_load((CONFIGS_DIR / "universe_2025_2026.yaml").read_text(encoding="utf-8"))["symbols"]
    todo = []
    for s, info in universe.items():
        start = max(START, _month_start(info["first_month"]))
        end = min(LAST, _month_end(info["last_month"]))
        if not _done(s, end):
            todo.append((s, start, end))
    print(f"{len(universe)}銘柄のうち {len(todo)}銘柄を取得します(先物5分足、2025-01〜2026-08)", flush=True)
    for i, (s, start, end) in enumerate(todo, 1):
        klines.download_symbol_klines("futures_um", s, "5m", start, end)
        frames = [klines.read_kline_zip(z)[KEEP] for z in sorted(klines.raw_dir("futures_um", s, "5m").glob("*.zip"))]
        if frames:
            new = pd.concat(frames, ignore_index=True)
            new = new[(new["open_time"] >= int(pd.Timestamp(START).timestamp() * 1000)) & (new["open_time"] < END_MS)]
            new = new.rename(columns={"quote_asset_volume": "quote_volume", "taker_buy_quote_asset_volume": "taker_buy_quote"})
            path = OUT / f"{s}.parquet"
            old = pd.read_parquet(path) if path.exists() else None
            df = pd.concat([old, new], ignore_index=True) if old is not None else new
            df = df.drop_duplicates("open_time").sort_values("open_time")
            for c in ("open", "high", "low", "close"):
                df[c] = df[c].astype("float64")
            for c in ("volume", "quote_volume", "taker_buy_quote"):
                df[c] = df[c].astype("float32")
            tmp = path.with_suffix(".tmp")
            df.to_parquet(tmp, index=False)
            tmp.rename(path)
        shutil.rmtree(klines.raw_dir("futures_um", s, "5m"), ignore_errors=True)
        print(f"[{i}/{len(todo)}] {s} {'済み' if frames else 'データなし'}", flush=True)
    print("完了。", flush=True)


if __name__ == "__main__":
    main()
