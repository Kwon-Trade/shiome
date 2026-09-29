"""6つの局面ルールを判定する。

各局面は「価格上昇」のような単純な方向(符号)の条件と、「高い」「急増」のような
パーセンタイル条件の組み合わせ。パーセンタイルは percentile.rolling_percentile_rank()
で計算した、銘柄ごと・直近90日ローリング窓での百分位順位(0〜100)を使う。

現物CVDを使う局面(①③④⑤)は、現物データが無い銘柄では判定できない。
そのため②⑥は現物CVDの条件を持たない(元の指示どおり、現物が無い銘柄でも判定可能)。

窓が埋まっていない期間(助走期間)やmetricsデータが欠けている期間は、
その局面のNaN(=判定不可)として扱い、Falseにはしない。
"""
from __future__ import annotations

import pandas as pd

from shiome.config import load_settings
from shiome.phases.derived import add_derived_columns
from shiome.phases.percentile import rolling_percentile_rank

PHASE_NAMES = {
    1: "1_healthy_uptrend",
    2: "2_overleveraged_uptrend",
    3: "3_short_squeeze_setup",
    4: "4_distribution_top",
    5: "5_capitulation_bottom",
    6: "6_compression",
}


def _judged_mask(cols: list[pd.Series]) -> pd.Series:
    """判定に使う全ての列がNaNでない行だけTrue。"""
    mask = pd.Series(True, index=cols[0].index)
    for c in cols:
        mask &= c.notna()
    return mask


def compute_phases(df: pd.DataFrame, has_spot: bool, thresholds: dict | None = None) -> pd.DataFrame:
    """thresholds を渡すと configs/settings.yaml の phase_thresholds を上書きできる
    (しきい値を変えた場合の感度分析に使う。configs/settings.yaml自体は変更しない)。"""
    settings = load_settings()
    th = thresholds or settings["phase_thresholds"]
    high_p = th["high_percentile"]
    low_p = th["low_percentile"]
    extreme_low_p = 100 - th["extreme_percentile"]
    neutral_lo, neutral_hi = th["neutral_band"]
    zone_p = settings["validation"]["price_zone_high"]["percentile_threshold"]

    df = add_derived_columns(df)

    # --- パーセンタイル順位(全て銘柄ごと・直近90日ローリング窓・先読みなし) ---
    df["price_chg_24h_pct"] = rolling_percentile_rank(df["price_chg_24h"])
    df["futures_cvd_chg_24h_pct"] = rolling_percentile_rank(df["futures_cvd_chg_24h"])
    df["oi_chg_pct_24h_pct"] = rolling_percentile_rank(df["oi_chg_pct_24h"])
    df["funding_rate_pct"] = rolling_percentile_rank(df["funding_rate"])
    df["funding_rate_diff_pct"] = rolling_percentile_rank(df["funding_rate_diff"])
    df["trader_ratio_diff_pct"] = rolling_percentile_rank(df["trader_ratio_diff"])
    df["range_24h_pct"] = rolling_percentile_rank(df["range_24h"])
    df["drawdown_from_high_pct"] = rolling_percentile_rank(df["drawdown_from_high"])

    price_up = df["price_chg_24h"] > 0
    price_flat_or_down = df["price_chg_24h"] <= 0
    oi_up = df["oi_chg_pct_24h"] > 0
    fr_negative = df["funding_rate"] < 0
    fr_high = df["funding_rate_pct"] >= high_p
    fr_normal = df["funding_rate_pct"].between(neutral_lo, neutral_hi)

    # ============ ② 燃料過多の上昇(現物が無くても判定可能) ============
    futures_cvd_surge = df["futures_cvd_chg_24h_pct"] >= high_p
    oi_surge = df["oi_chg_pct_24h_pct"] >= high_p
    base_cols = [df["price_chg_24h"], df["futures_cvd_chg_24h_pct"], df["funding_rate_pct"], df["oi_chg_pct_24h_pct"]]
    phase2_judged = _judged_mask(base_cols)
    phase2 = price_up & futures_cvd_surge & fr_high & oi_surge
    if has_spot:
        spot_cvd_flat_or_down = df["spot_cvd_chg_24h"] <= 0
        phase2_judged &= df["spot_cvd_chg_24h"].notna()
        phase2 &= spot_cvd_flat_or_down
    df["phase_2"] = phase2.where(phase2_judged)

    # ============ ⑥ 圧縮(現物が無くても判定可能) ============
    range_narrow = df["range_24h_pct"] <= low_p
    fr_neutral_6 = fr_normal
    phase6_judged = _judged_mask([df["range_24h_pct"], df["oi_chg_pct_24h"], df["funding_rate_pct"]])
    phase6 = range_narrow & oi_up & fr_neutral_6
    df["phase_6"] = phase6.where(phase6_judged)

    if not has_spot:
        for i in (1, 3, 4, 5):
            df[f"phase_{i}"] = pd.NA
        return df

    spot_cvd_up = df["spot_cvd_chg_24h"] > 0
    spot_cvd_down = df["spot_cvd_chg_24h"] < 0
    spot_cvd_flat_or_down = df["spot_cvd_chg_24h"] <= 0

    # ============ ① 健全な上昇 ============
    oi_gentle_up = oi_up & (df["oi_chg_pct_24h_pct"] < high_p)
    phase1_judged = _judged_mask(
        [df["price_chg_24h"], df["spot_cvd_chg_24h"], df["funding_rate_pct"], df["oi_chg_pct_24h_pct"]]
    )
    phase1 = price_up & spot_cvd_up & fr_normal & oi_gentle_up
    df["phase_1"] = phase1.where(phase1_judged)

    # ============ ③ ショート踏み上げ準備 ============
    phase3_judged = _judged_mask([df["price_chg_24h"], df["oi_chg_pct_24h"], df["funding_rate"], df["spot_cvd_chg_24h"]])
    phase3 = price_flat_or_down & oi_up & fr_negative & spot_cvd_up
    df["phase_3"] = phase3.where(phase3_judged)

    # ============ ④ 天井の売り抜け ============
    price_near_high = df["drawdown_from_high_pct"] <= zone_p
    trader_divergence = df["trader_ratio_diff_pct"] <= low_p
    phase4_judged = _judged_mask(
        [df["drawdown_from_high_pct"], df["spot_cvd_chg_24h"], df["funding_rate_pct"], df["trader_ratio_diff_pct"]]
    )
    phase4 = price_near_high & spot_cvd_down & fr_high & trader_divergence
    df["phase_4"] = phase4.where(phase4_judged)

    # ============ ⑤ 投げ売り後の底打ち ============
    sharp_drop = df["price_chg_24h_pct"] <= extreme_low_p
    oi_crash = df["oi_chg_pct_24h_pct"] <= extreme_low_p
    fr_plunge = df["funding_rate_diff_pct"] <= extreme_low_p
    phase5_judged = _judged_mask(
        [df["price_chg_24h_pct"], df["oi_chg_pct_24h_pct"], df["funding_rate_diff_pct"], df["spot_cvd_chg_24h"]]
    )
    phase5 = sharp_drop & oi_crash & fr_plunge & spot_cvd_up
    df["phase_5"] = phase5.where(phase5_judged)

    return df
