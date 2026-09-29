#!/usr/bin/env python3
"""答え合わせ(2025-01〜2026-08)の比較対象になりうる銘柄の一覧を作る。docs/hypotheses_v2.md A3。

S3のファイル名一覧だけを使い、ファイルの中身は読まない。
2025年1月〜2026年8月に先物の月次1時間足ファイルがある銘柄から、configs/holdout_non_crypto.yaml と
既存の除外(EXCLUDE_NON_CRYPTO_SYMBOLS。ただし現物がある銘柄は残す)を外して、
configs/universe_2025_2026.yaml に保存する。

実行例:
    python scripts/build_holdout_universe_list.py
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from shiome.config import CONFIGS_DIR  # noqa: E402
from shiome.data.binance_vision import list_keys  # noqa: E402
from shiome.data.symbols import EXCLUDE_NON_CRYPTO_SYMBOLS, futures_to_spot_symbol  # noqa: E402

FIRST, LAST = "2025-01", "2026-08"


def _months(prefix: str) -> list[str]:
    keys = list_keys(prefix, delimiter=None).keys
    return sorted({k.split("-1h-")[1][:7] for k in keys if k.endswith(".zip") and "-1h-" in k})


def survey(symbol: str) -> tuple[str, dict | None]:
    fut = [m for m in _months(f"data/futures/um/monthly/klines/{symbol}/1h/") if m <= LAST]
    if not any(FIRST <= m for m in fut):
        return symbol, None
    spot = [m for m in _months(f"data/spot/monthly/klines/{futures_to_spot_symbol(symbol)}/1h/") if m <= LAST]
    return symbol, {"first_month": fut[0], "last_month": fut[-1], "has_spot": bool(spot)}


def main() -> None:
    ex = yaml.safe_load((CONFIGS_DIR / "holdout_non_crypto.yaml").read_text(encoding="utf-8"))
    always_out = set(ex["commodity_tokens"]) | set(ex["index_contracts"]) | set(ex["non_crypto"]) | set(ex["uncertain_excluded"])
    root = list_keys("data/futures/um/monthly/klines/")
    names = [p.rstrip("/").split("/")[-1] for p in root.common_prefixes]
    names = [s for s in names if s.endswith("USDT")]
    with ThreadPoolExecutor(20) as pool:
        found = {s: info for s, info in pool.map(survey, names) if info}
    keep, dropped = {}, []
    for s, info in sorted(found.items()):
        if s in always_out or (s in EXCLUDE_NON_CRYPTO_SYMBOLS and not info["has_spot"]):
            dropped.append(s)
        else:
            keep[s] = info
    out = {"note": "2025年1月〜2026年8月にBinance USDⓈ-M先物に月次1時間足ファイルがある銘柄から、暗号資産ではない先物を除いたもの。"
                   "S3のファイル名一覧だけから作成(中身は読んでいない)。docs/hypotheses_v2.md A3。",
           "excluded": dropped, "symbols": keep}
    (CONFIGS_DIR / "universe_2025_2026.yaml").write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"全{len(found)}銘柄 → 比較対象になりうる {len(keep)}銘柄(除外 {len(dropped)})")


if __name__ == "__main__":
    main()
