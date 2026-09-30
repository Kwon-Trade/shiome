#!/usr/bin/env python3
"""第3ラウンド A の点検(2023年末までのデータだけ)。

1. 先読みの点検: データを 2023-07-01 で切って作り直しても、それより前のイベント・合図の時刻・閾値が変わらないこと
2. 1件の手計算用の中身を表示する

実行例:
    python scripts/check_cascade.py ADAUSDT AVAXUSDT BNBUSDT
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from shiome.cascade.events import BAR, detect, load_sym, signal_bars  # noqa: E402
from shiome.crosssection.data import DEV_END  # noqa: E402

CUT = pd.Timestamp("2023-07-01")


def events_with_signals(name: str, end: pd.Timestamp) -> dict:
    s = load_sym(name, end)
    out = {}
    if s is None:  # 90日分のデータがそろわない(上場直後など)
        return out
    casc, bench, _ = detect(s)
    for kind, pos in (("cascade", casc), ("bench", bench)):
        for i in pos:
            t0 = pd.Timestamp(s.t[i]) + BAR
            sig = signal_bars(s, i)
            out[(kind, t0)] = ({k: (None if v is None else pd.Timestamp(s.t[v])) for k, v in sig.items()},
                               float(s.thr_r[i]), float(s.thr_oi[i]))
    return out


def main() -> None:
    bad = 0
    for name in sys.argv[1:]:
        full = events_with_signals(name, DEV_END)
        part = events_with_signals(name, CUT)
        lim = CUT - pd.Timedelta(hours=7)  # 合図は6時間まで待つので、それより前のイベントを比べる
        a = {k: v for k, v in full.items() if k[1] < lim}
        b = {k: v for k, v in part.items() if k[1] < lim}
        same = a.keys() == b.keys() and all(a[k] == b[k] for k in a)
        bad += not same
        print(f"{name}: 切る前 {len(a)}件 / 切った後 {len(b)}件 → {'一致' if same else '不一致'}")
    print("先読みの点検:", "問題なし" if bad == 0 else f"{bad}銘柄で不一致")

    s = load_sym(sys.argv[1], DEV_END)
    casc, _, _ = detect(s)
    i = casc[len(casc) // 2]
    sl = slice(i - 7, i + 4)
    df = pd.DataFrame({"open": s.o[sl], "high": s.h[sl], "low": s.lo[sl], "close": s.c[sl], "quote_vol": s.qv[sl],
                       "taker_buy": s.tb[sl], "oi": s.oi[sl]}, index=pd.DatetimeIndex(s.t[sl]))
    print(f"\n手計算用: {sys.argv[1]} のイベント(足の開始 {pd.Timestamp(s.t[i])})")
    print(df.to_string())
    print("30分の値動き", s.r30[i], "下位1%の境目", s.thr_r[i])
    print("30分の建玉変化", s.oi30[i], "下位1%の境目", s.thr_oi[i], "テイカー買いの割合", s.taker30[i])
    print("合図:", {k: (None if v is None else str(pd.Timestamp(s.t[v]))) for k, v in signal_bars(s, i).items()})


if __name__ == "__main__":
    main()
