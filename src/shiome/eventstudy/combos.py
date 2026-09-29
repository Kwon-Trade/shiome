"""2〜3指標の組み合わせで、急騰/急落の直前をどれだけ普通の時点と見分けられるかを評価する。

組み合わせを数十通り試すと、たまたま良く見えるものが必ず出てくる。そこで
2022〜2023年のサンプルで組み合わせ方(重み)を学習し、2024年のサンプルで見分けの精度(AUC)を測る。
単独指標も同じ手順で測り、組み合わせと公平に比べる。

各指標は「パーセンタイル順位の中心からのずれ」と「その2乗」の2つの特徴量にする。
2乗を入れるのは、「高すぎても低すぎても危ない」(両端で起きやすい)形も捉えるため。
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from shiome.eventstudy.samples import ALL_FEATURES, OFFSETS, REFERENCE_COLS

TEST_START = pd.Timestamp("2024-01-01")


def _design(df: pd.DataFrame, cols: tuple[str, ...], k: int) -> np.ndarray:
    parts = []
    for c in cols:
        z = (df[f"{c}__pct__t{k}"].to_numpy() - 50) / 50
        parts += [z, z ** 2]
    return np.column_stack(parts)


def evaluate(samples: pd.DataFrame, max_size: int = 3) -> pd.DataFrame:
    test_ms = int(TEST_START.timestamp() * 1000)
    cols_all = [c for c, _ in ALL_FEATURES]
    rows = []
    for direction in ("surge", "crash"):
        sub = samples[samples["kind"].isin([direction, "random"])]
        for k in OFFSETS:
            for size in range(1, max_size + 1):
                for cols in combinations(cols_all, size):
                    need = [f"{c}__pct__t{k}" for c in cols]
                    d = sub.dropna(subset=need)
                    train, test = d[d["open_time"] < test_ms], d[d["open_time"] >= test_ms]
                    y_tr = (train["kind"] == direction).to_numpy()
                    y_te = (test["kind"] == direction).to_numpy()
                    if y_tr.sum() < 50 or y_te.sum() < 50 or (~y_te).sum() < 50:
                        continue
                    model = LogisticRegression(max_iter=1000).fit(_design(train, cols, k), y_tr)
                    score = model.predict_proba(_design(test, cols, k))[:, 1]
                    rows.append({
                        "direction": direction, "offset_h": k, "size": size, "features": cols,
                        "uses_reference": any(c in REFERENCE_COLS for c in cols),
                        "n_train": len(train), "n_test": len(test), "n_test_event": int(y_te.sum()),
                        "auc_test": roc_auc_score(y_te, score),
                    })
    return pd.DataFrame(rows)
