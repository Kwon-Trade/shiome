#!/usr/bin/env python3
"""ステージ1: 大型グループだけを対象に、4種類のデータを全部ダウンロードする。

これがうまくいったら、他のグループも同じ関数で追加していく。
途中で止めても再実行すれば続きからダウンロードされる(完了済みファイルはスキップ)。

実行例:
    python scripts/download_stage1_largecap.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shiome.config import date_range, ensure_dirs, load_settings, load_symbols  # noqa: E402
from shiome.data import funding_rate, futures_metrics, klines  # noqa: E402


def main() -> None:
    ensure_dirs()
    settings = load_settings()
    symbols_cfg = load_symbols()
    start, end = date_range(settings)
    interval = settings["intervals"]["klines"]

    large_cap = symbols_cfg["groups"]["large_cap"]
    if not large_cap:
        print("configs/symbols.yaml の large_cap が空です。先に build_symbol_list.py を実行してください。")
        return

    print(f"対象: {large_cap}")
    print(f"期間: {start} 〜 {end}\n")

    print("[1/4] 現物 1時間足klines")
    r1 = klines.download_and_build("spot", large_cap, interval, start, end)
    _print_summary(r1)

    print("\n[2/4] 先物(USD-M) 1時間足klines")
    r2 = klines.download_and_build("futures_um", large_cap, interval, start, end)
    _print_summary(r2)

    print("\n[3/4] 先物 daily metrics(建玉/ロングショート比率など)")
    r3 = futures_metrics.download_and_build(large_cap, start, end)
    for r in r3:
        status = "OK" if not r["failed"] else f"失敗{len(r['failed'])}件"
        print(f"  {r['symbol']}: 新規{r['downloaded']} / 既存{r['skipped']} / {status}")

    print("\n[4/4] ファンディングレート履歴")
    r4 = funding_rate.download_and_build(large_cap, start, end)
    _print_summary(r4)

    print("\n完了。data/processed/ 以下にparquetファイルができています。")


def _print_summary(results: list[dict]) -> None:
    for r in results:
        status = "OK" if not r["failed"] else f"失敗{len(r['failed'])}件(上場前の可能性あり)"
        parquet = "parquet作成済み" if r.get("parquet") else "parquet無し"
        print(f"  {r['symbol']}: 新規{r['downloaded']} / 既存{r['skipped']} / {status} / {parquet}")


if __name__ == "__main__":
    main()
