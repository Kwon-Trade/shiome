#!/usr/bin/env python3
"""第2ラウンド: 2022〜2024年にあった全銘柄のデータを追加ダウンロードする(2024年12月分まで)。

対象は configs/universe_2022_2024.yaml(scripts/build_full_universe_list.py で作成)のうち、
まだ手元に無い銘柄。2025年以降のファイルは取りにいかない(終了日を2024-12-31に固定)。

実行例:
    python scripts/download_full_universe.py prices    # 先物・現物の1時間足とFR
    python scripts/download_full_universe.py metrics   # 建玉など(日次ファイルで数が多い)

途中で止めても再実行すれば続きから(完了済みファイルはスキップ)。
"""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from shiome.config import CONFIGS_DIR, PROCESSED_DIR, ensure_dirs  # noqa: E402
from shiome.data import funding_rate, futures_metrics, klines  # noqa: E402

DATA_START = dt.date(2022, 1, 1)
DATA_END = dt.date(2024, 12, 31)  # これより後は取りにいかない


def _month_start(m: str) -> dt.date:
    return dt.date(int(m[:4]), int(m[5:7]), 1)


def _month_end(m: str) -> dt.date:
    y, mo = int(m[:4]), int(m[5:7])
    nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _range(first: str, last: str) -> tuple[dt.date, dt.date]:
    start = max(DATA_START, _month_start(first))
    end = min(DATA_END, _month_end(last))
    assert end <= DATA_END
    return start, end


CUTOFF_MS = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
TIME_COL = {"futures_um/klines/1h": "open_time", "spot/klines/1h": "open_time",
            "futures_um/funding_rate": "calc_time", "futures_um/metrics": "create_time"}


def _truncate(kind: str, symbol: str) -> None:
    """作ったファイルから2025年以降の行を削る。
    第1ラウンドの銘柄選びで直近の月次1時間足を取ってあった銘柄は、それが混ざるため。"""
    path = PROCESSED_DIR / kind / f"{symbol}.parquet"
    if not path.exists():
        return
    df = pd.read_parquet(path)
    col = TIME_COL[kind]
    t = pd.to_datetime(df[col]) if col == "create_time" else df[col]
    limit = pd.Timestamp("2025-01-01") if col == "create_time" else CUTOFF_MS
    keep = t < limit
    if not keep.all():
        df[keep.values].to_parquet(path, index=False)


def _has(kind: str, symbol: str) -> bool:
    return (PROCESSED_DIR / kind / f"{symbol}.parquet").exists()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("prices", "metrics"):
        sys.exit("使い方: python scripts/download_full_universe.py prices|metrics")
    ensure_dirs()
    universe = yaml.safe_load((CONFIGS_DIR / "universe_2022_2024.yaml").read_text(encoding="utf-8"))["symbols"]
    todo = [s for s in universe if not _has("futures_um/klines/1h", s) or not _has("futures_um/metrics", s)]
    print(f"対象 {len(universe)}銘柄のうち、未取得を含む {len(todo)}銘柄を処理します(モード: {mode})", flush=True)

    for i, symbol in enumerate(todo, 1):
        info = universe[symbol]
        start, end = _range(info["first_month"], info["last_month"])
        if mode == "prices":
            if not _has("futures_um/klines/1h", symbol):
                klines.download_and_build("futures_um", [symbol], "1h", start, end)
                _truncate("futures_um/klines/1h", symbol)
            if "spot_first_month" in info and not _has("spot/klines/1h", symbol):
                s_start, s_end = _range(info["spot_first_month"], info["spot_last_month"])
                remote = {symbol: info["spot_symbol"]} if info["spot_symbol"] != symbol else None
                klines.download_and_build("spot", [symbol], "1h", s_start, s_end, remote_symbol_map=remote)
                _truncate("spot/klines/1h", symbol)
            if not _has("futures_um/funding_rate", symbol):
                funding_rate.download_and_build([symbol], start, end)
                _truncate("futures_um/funding_rate", symbol)
        else:
            if not _has("futures_um/metrics", symbol):
                futures_metrics.download_and_build([symbol], start, end)
                _truncate("futures_um/metrics", symbol)
        print(f"[{i}/{len(todo)}] {symbol} 済み", flush=True)

    # 途中で止まって再実行した場合に削り忘れが残らないよう、最後にもう一度まとめて削る
    kinds = ("futures_um/klines/1h", "spot/klines/1h", "futures_um/funding_rate") if mode == "prices" else ("futures_um/metrics",)
    for symbol in todo:
        for kind in kinds:
            _truncate(kind, symbol)
    print("完了。", flush=True)


if __name__ == "__main__":
    main()
