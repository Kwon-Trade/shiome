#!/usr/bin/env python3
"""第2ラウンド: データの掃除と比較対象(ユニバース)の足切りを行い、日ごとの対象銘柄表を保存する。

値動きの成績は一切計算しない(対象銘柄の数と除外理由だけ)。2025年以降は読まない。

実行例:
    python scripts/build_universe.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from shiome.config import PROCESSED_DIR  # noqa: E402
from shiome.crosssection.data import HARD_END  # noqa: E402
from shiome.crosssection.universe import REASONS, daily_universe  # noqa: E402
from shiome.validation.regroup import symbol_to_group_map  # noqa: E402

OUT_DIR = PROCESSED_DIR / "crosssection"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    group_of = symbol_to_group_map()
    frames = []
    for path in sorted((PROCESSED_DIR / "futures_um" / "klines" / "1h").glob("*.parquet")):
        u = daily_universe(path.stem, HARD_END)
        if not u.empty:
            u["group"] = group_of.get(path.stem, "unknown")
            frames.append(u)
    uni = pd.concat(frames, ignore_index=True)
    assert uni["t"].max() < HARD_END
    uni.to_parquet(OUT_DIR / "universe.parquet", index=False)

    uni["year"] = uni["t"].dt.year
    elig = uni[uni["eligible"]]
    per_day = elig.groupby("t").size()
    print("2022-2024年にデータがある銘柄:", uni["symbol"].nunique(), " うち1日でも対象になった銘柄:", elig["symbol"].nunique())
    print("\n日ごとの対象銘柄数(年別):")
    print(per_day.groupby(per_day.index.year).describe()[["min", "25%", "50%", "75%", "max"]])
    print("\n対象銘柄数(グループ別・日ごとの中央値):")
    print(elig.groupby(["year", "group", "t"]).size().groupby(["year", "group"]).median().unstack())
    print("\n除外理由(銘柄×日の数, 年別):")
    print(uni.groupby(["year", "reason"]).size().unstack(0).reindex(REASONS).fillna(0).astype(int))
    print("\n参考: 出来高の基準を変えたときの対象銘柄数(日ごとの中央値, 年別)")
    ok = ~uni["reason"].isin(REASONS[:5])
    for thr in (1e6, 5e6, 10e6):
        n = uni[ok & (uni["adv30_usd"] >= thr)].groupby("t").size()
        print(f"  ${thr/1e6:.0f}M:", n.groupby(n.index.year).median().to_dict())
    print("\n1日でも対象になった銘柄:", sorted(elig["symbol"].unique()))
    never = sorted(set(uni["symbol"]) - set(elig["symbol"]))
    print("一度も対象にならなかった銘柄:", never)


if __name__ == "__main__":
    main()
