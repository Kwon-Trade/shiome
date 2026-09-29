#!/usr/bin/env python3
"""第2ラウンド: 2022〜2024年にBinance先物(USDT建て無期限)にあった全銘柄の一覧を作る。

S3のファイル名一覧だけを使い、ファイルの中身は読まない。2025年以降のファイル名は数えない。
結果は configs/universe_2022_2024.yaml に保存する(銘柄ごとの先物・現物の月次ファイルの最初と最後の月、上場日)。

実行例:
    python scripts/build_full_universe_list.py
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

FIRST, LAST = "2022-01", "2024-12"
# コインではなく「指数」に連動する先物。コイン同士の比較には入れない(docs/hypotheses_v2.md §2)
INDEX_CONTRACTS = {"BTCDOMUSDT", "DEFIUSDT", "FOOTBALLUSDT", "BLUEBIRDUSDT"}


def _months(prefix: str, sep: str) -> list[str]:
    keys = list_keys(prefix, delimiter=None).keys
    ms = sorted({k.split(sep)[1][:7] for k in keys if k.endswith(".zip") and sep in k})
    return [m for m in ms if m <= LAST]  # 2025年以降のファイルは数えない


def _first_day(symbol: str) -> str | None:
    keys = list_keys(f"data/futures/um/daily/klines/{symbol}/1h/", delimiter=None).keys
    days = sorted(k.split("-1h-")[1][:10] for k in keys if k.endswith(".zip"))
    return days[0] if days else None


def survey(symbol: str) -> tuple[str, dict | None]:
    fut = _months(f"data/futures/um/monthly/klines/{symbol}/1h/", "-1h-")
    if not fut or fut[-1] < FIRST:
        return symbol, None
    info = {"first_month": fut[0], "last_month": fut[-1]}
    if "2021-10" <= fut[0] <= "2021-12":  # 2022-01-01時点で上場90日未満になりうる → 日付まで調べる
        info["listed"] = _first_day(symbol)
    elif fut[0] <= "2021-09":
        info["listed"] = fut[0]
    spot = futures_to_spot_symbol(symbol)
    sm = [m for m in _months(f"data/spot/monthly/klines/{spot}/1h/", "-1h-") if m >= FIRST]
    info["spot_symbol"] = spot
    if sm:
        info["spot_first_month"], info["spot_last_month"] = sm[0], sm[-1]
    return symbol, info


def main() -> None:
    root = list_keys("data/futures/um/monthly/klines/")
    names = [p.rstrip("/").split("/")[-1] for p in root.common_prefixes]
    # 先物にはレバレッジトークン(〜UPUSDT等)が無いので語尾での除外はしない(JUPUSDTを誤って外すため)
    names = [s for s in names if s.endswith("USDT")
             and s not in EXCLUDE_NON_CRYPTO_SYMBOLS and s not in INDEX_CONTRACTS]
    with ThreadPoolExecutor(20) as ex:
        found = {s: info for s, info in ex.map(survey, names) if info}
    out = {
        "note": "2022〜2024年にBinance USDⓈ-M先物に月次1時間足ファイルがあった銘柄(指数先物・非暗号資産を除く)。"
                "S3のファイル名一覧だけから作成(中身は読んでいない)。",
        "excluded_index_contracts": sorted(INDEX_CONTRACTS),
        "symbols": dict(sorted(found.items())),
    }
    path = CONFIGS_DIR / "universe_2022_2024.yaml"
    path.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    n_spot = sum("spot_first_month" in v for v in found.values())
    print(f"{len(found)}銘柄(うち現物データあり {n_spot})を {path} に保存しました")


if __name__ == "__main__":
    main()
