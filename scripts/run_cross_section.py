#!/usr/bin/env python3
"""第2ラウンド: 銘柄間比較(H1〜H6)を計算する。定義は docs/hypotheses_v2.md。

モード:
    dev    2023年末までのデータだけを読み、2022・2023年を計算する(仕組み作り・動作確認用。何度でもよい)
    final  2024年末までを読み、2024年を含めて計算する。仮説ごとに1回だけ(2回目は止まる)

銘柄の組:
    full   2022〜2024年にあった全銘柄(configs/universe_2022_2024.yaml)
    set61  第1ラウンドの銘柄リストのうち2022〜2024年にデータがあるもの(参考: 銘柄選びの偏りを見る)

実行例:
    python scripts/run_cross_section.py dev --sets set61 --hyps H1
    python scripts/run_cross_section.py final --sets full,set61 --hyps H1,H2-7,H2-14,H2-28,H3,H5,H6
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from shiome.config import PROCESSED_DIR, all_symbols, load_symbols  # noqa: E402
from shiome.crosssection.benchmark import fama_macbeth  # noqa: E402
from shiome.crosssection.data import DEV_END, HARD_END, full_universe  # noqa: E402
from shiome.crosssection.evaluate import MIN_N_GROUP, SIGNALS, evaluate  # noqa: E402
from shiome.crosssection.groups import assign_groups  # noqa: E402
from shiome.crosssection.panel import HORIZONS, symbol_panel  # noqa: E402

OUT_DIR = PROCESSED_DIR / "crosssection"
PERIODS = {"dev": ["2022", "2023", "2022-23"], "final": ["2022", "2023", "2024", "2022-23"]}
BENCH_HYPS = ("H1", "H4", "H6")
GUARDED = ("docs/hypotheses_v2.md", "src/shiome/crosssection", "scripts/run_cross_section.py")


def symbol_set(name: str) -> list[str]:
    universe = full_universe()
    if name == "full":
        return sorted(universe)
    if name == "set61":
        return sorted(s for s in all_symbols(load_symbols()) if s in universe)
    raise ValueError(name)


def build_panel(set_name: str, mode: str, with_oi: bool) -> pd.DataFrame:
    end = DEV_END if mode == "dev" else HARD_END
    tag = "oi" if with_oi else "base"
    cache = OUT_DIR / f"panel_{mode}_{set_name}_{tag}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = [p for s in symbol_set(set_name) if not (p := symbol_panel(s, end, with_oi=with_oi)).empty]
    panel = assign_groups(pd.concat(frames, ignore_index=True))
    assert panel["t"].max() < end
    panel.to_parquet(cache, index=False)
    return panel


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dev", "final"])
    ap.add_argument("--sets", default="full,set61")
    ap.add_argument("--hyps", default="H1")
    args = ap.parse_args()
    hyps = args.hyps.split(",")
    assert all(h in SIGNALS for h in hyps)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = OUT_DIR / f"results_{args.mode}.json"
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    if args.mode == "final":
        if _git("status", "--porcelain", *GUARDED):
            sys.exit("条件の記録または計算コードに未コミットの変更があります。先にコミットしてください。")
        for s in args.sets.split(","):
            done = [h for h in hyps if h in results.get(s, {})]
            if done:
                sys.exit(f"{s}: {done} は2024年を含めて計算済みです(2024年は1回だけ)。")
        results.setdefault("_commits", {})[",".join(hyps)] = _git("rev-parse", "HEAD")

    periods = PERIODS[args.mode]
    for set_name in args.sets.split(","):
        panel = build_panel(set_name, args.mode, with_oi="H4" in hyps)
        res = results.setdefault(set_name, {})
        for hyp in hyps:
            r = {"all": {}, "groups": {}, "bench": {}}
            for hz in HORIZONS:
                r["all"][hz] = evaluate(panel, hyp, hz, periods)
                for g in ("large_cap", "mid_cap_alt", "small_meme"):
                    sub = panel[panel["group"] == g]
                    r["groups"].setdefault(g, {})[hz] = evaluate(sub, hyp, hz, periods, min_n=MIN_N_GROUP)
                if hyp in BENCH_HYPS:
                    r["bench"][hz] = fama_macbeth(panel, hyp, hz, periods)
            res[hyp] = r
            a = r["all"]["24h"][periods[-1]]
            print(f"{set_name} {hyp}: 24h 勝率 {a.get('win', float('nan')):.3f} 相関 {a.get('ic', float('nan')):+.4f} "
                  f"日数 {a.get('n_days')} 平均銘柄数 {a.get('avg_n', float('nan')):.0f}", flush=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("保存:", out_path)


if __name__ == "__main__":
    main()
