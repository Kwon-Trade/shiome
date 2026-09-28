#!/usr/bin/env python3
"""銘柄リストを作成し、configs/symbols.yaml に保存する(ステージ0)。

実行例:
    python scripts/build_symbol_list.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shiome.config import save_symbols  # noqa: E402
from shiome.data.symbols import build_symbol_groups  # noqa: E402


def main() -> None:
    print("Binanceから現物/先物の銘柄一覧・出来高・過去データの有無を取得しています...")
    result = build_symbol_groups()
    save_symbols(result)

    g = result["groups"]
    print("\n=== 銘柄リスト(下書き) ===")
    print(f"大型 ({len(g['large_cap'])}銘柄): {g['large_cap']}")
    print(f"中型アルト ({len(g['mid_cap_alt'])}銘柄): {g['mid_cap_alt']}")
    print(f"小型・ミーム ({len(g['small_meme'])}銘柄): {g['small_meme']}")
    print(f"\n上場廃止銘柄 ({len(result['delisted'])}銘柄、小型・ミームに含む): {result['delisted']}")
    print(f"\n現物データあり(現物CVD計算可) {len(result['has_spot_data'])}銘柄")
    print(f"現物データなし(②⑥のみ判定) {len(result['no_spot_data'])}銘柄: {result['no_spot_data']}")

    if result["uncertain_needs_manual_check"]:
        print(
            f"\n[要確認] 暗号資産か非暗号資産(株式/商品トークン等)か判断できなかった銘柄 "
            f"({len(result['uncertain_needs_manual_check'])}件): {result['uncertain_needs_manual_check']}"
        )
        print("→ これらは含めるかどうかユーザーに確認してください。")
    print("\nconfigs/symbols.yaml に保存しました。内容を確認してください。")


if __name__ == "__main__":
    main()
