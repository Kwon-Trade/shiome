#!/usr/bin/env python3
"""ステージ2: 全銘柄の1時間足指標を計算する。

実行例:
    python scripts/build_indicators.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tqdm import tqdm  # noqa: E402

from shiome.config import all_symbols, load_symbols  # noqa: E402
from shiome.indicators.build import build_and_save  # noqa: E402


def main() -> None:
    symbols_cfg = load_symbols()
    symbols = all_symbols(symbols_cfg)

    ok, skipped = [], []
    for symbol in tqdm(symbols, desc="指標計算"):
        path = build_and_save(symbol)
        if path is None:
            skipped.append(symbol)
        else:
            ok.append(symbol)

    print(f"\n完了: {len(ok)}/{len(symbols)}銘柄")
    if skipped:
        print(f"先物klinesが無く計算できなかった銘柄({len(skipped)}件): {skipped}")


if __name__ == "__main__":
    main()
