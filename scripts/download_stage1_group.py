#!/usr/bin/env python3
"""ステージ1: 指定グループのデータを全部ダウンロードする(大型グループ以外にも使える汎用版)。

実行例:
    python scripts/download_stage1_group.py mid_cap_alt small_meme
    python scripts/download_stage1_group.py large_cap

途中で止めても再実行すれば続きからダウンロードされる(完了済みファイルはスキップ)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shiome.config import date_range, ensure_dirs, load_settings, load_symbols  # noqa: E402
from shiome.data import funding_rate, futures_metrics, klines  # noqa: E402


def main() -> None:
    group_names = sys.argv[1:]
    if not group_names:
        print("使い方: python scripts/download_stage1_group.py <グループ名> [<グループ名> ...]")
        print("グループ名: large_cap / mid_cap_alt / small_meme")
        return

    ensure_dirs()
    settings = load_settings()
    symbols_cfg = load_symbols()
    start, end = date_range(settings)
    interval = settings["intervals"]["klines"]

    symbols: list[str] = []
    for g in group_names:
        group_symbols = symbols_cfg["groups"].get(g)
        if group_symbols is None:
            print(f"不明なグループ名: {g}")
            return
        for s in group_symbols:
            if s not in symbols:
                symbols.append(s)

    if not symbols:
        print("対象銘柄が空です。")
        return

    print(f"対象グループ: {group_names}")
    print(f"対象銘柄数: {len(symbols)}")
    print(f"期間: {start} 〜 {end}\n")

    print("[1/4] 現物 1時間足klines")
    r1 = klines.download_and_build("spot", symbols, interval, start, end)
    _print_summary(r1)

    print("\n[2/4] 先物(USD-M) 1時間足klines")
    r2 = klines.download_and_build("futures_um", symbols, interval, start, end)
    _print_summary(r2)

    print("\n[3/4] 先物 daily metrics(建玉/ロングショート比率など)")
    r3 = futures_metrics.download_and_build(symbols, start, end)
    _print_summary(r3)

    print("\n[4/4] ファンディングレート履歴")
    r4 = funding_rate.download_and_build(symbols, start, end)
    _print_summary(r4)

    print("\n完了。data/processed/ 以下にparquetファイルができています。")


def _print_summary(results: list[dict]) -> None:
    total_failed = 0
    for r in results:
        n_failed = len(r["failed"])
        total_failed += n_failed
        if n_failed > 1:
            status = f"要確認: 失敗{n_failed}件"
            parquet = "parquet作成済み" if r.get("parquet") else "parquet無し"
            print(f"  {r['symbol']}: 新規{r['downloaded']} / 既存{r['skipped']} / {status} / {parquet}")
    print(f"  (成功{len(results) - sum(1 for r in results if len(r['failed']) > 1)}/{len(results)}銘柄、失敗1件以下は上場前等の想定内なので省略表示)")


if __name__ == "__main__":
    main()
