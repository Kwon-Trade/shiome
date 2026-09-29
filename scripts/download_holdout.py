#!/usr/bin/env python3
"""答え合わせ用: configs/universe_2025_2026.yaml の銘柄の先物1時間足と建玉(metrics)を2026年8月分までダウンロードする。

H5・F1 には現物とFRは使わないので取らない。docs/hypotheses_v2.md A3。

実行例:
    python scripts/download_holdout.py prices
    python scripts/download_holdout.py metrics
"""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from shiome.config import CONFIGS_DIR, PROCESSED_DIR, ensure_dirs  # noqa: E402
from shiome.data import futures_metrics, klines  # noqa: E402

HOLDOUT_START = dt.date(2025, 1, 1)
HOLDOUT_LAST = dt.date(2026, 8, 31)


def _month_start(m: str) -> dt.date:
    return dt.date(int(m[:4]), int(m[5:7]), 1)


def _month_end(m: str) -> dt.date:
    y, mo = int(m[:4]), int(m[5:7])
    return dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)


def _covered(kind: str, symbol: str, end: dt.date) -> bool:
    path = PROCESSED_DIR / kind / f"{symbol}.parquet"
    if not path.exists():
        return False
    col = "open_time" if "klines" in kind else "create_time"
    try:
        x = pd.read_parquet(path, columns=[col])[col]
    except Exception:  # noqa: BLE001  途中で止まって書きかけになったファイルは作り直す
        return False
    last = pd.to_datetime(x, unit="ms") if col == "open_time" else pd.to_datetime(x)
    return last.max() >= pd.Timestamp(end) + pd.Timedelta(hours=23) - pd.Timedelta(hours=2)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("prices", "metrics"):
        sys.exit("使い方: python scripts/download_holdout.py prices|metrics")
    ensure_dirs()
    universe = yaml.safe_load((CONFIGS_DIR / "universe_2025_2026.yaml").read_text(encoding="utf-8"))["symbols"]
    kind = "futures_um/klines/1h" if mode == "prices" else "futures_um/metrics"
    todo = []
    for s, info in universe.items():
        start = max(HOLDOUT_START, _month_start(info["first_month"]))
        end = min(HOLDOUT_LAST, _month_end(info["last_month"]))
        if not _covered(kind, s, end):
            todo.append((s, start, end))
    print(f"{len(universe)}銘柄のうち {len(todo)}銘柄を取得します(モード: {mode})", flush=True)
    for i, (s, start, end) in enumerate(todo, 1):
        if mode == "prices":
            klines.download_and_build("futures_um", [s], "1h", start, end)
        else:
            futures_metrics.download_and_build([s], start, end)
        print(f"[{i}/{len(todo)}] {s} 済み", flush=True)
    print("完了。", flush=True)


if __name__ == "__main__":
    main()
