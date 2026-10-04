# 潮目 (shiome) バックテスト

暗号資産(Binance の先物)で、建玉・FR(資金調達率)・テイカーの売買などの指標から、その後の値動きを前もって言い当てられるかを確かめたプロジェクト。
**2026-10-04 に終了**(タグ `project-closed`)。

**結論: 3つのラウンドで約100通りを試し、21個を2025年以降のデータで答え合わせしたが、合格は0件。**
くわしくは [`docs/conclusion.md`](docs/conclusion.md)。

## 文書

| ファイル | 中身 |
|---|---|
| [`docs/conclusion.md`](docs/conclusion.md) | **最終の結論**(初心者向け)。目的、3ラウンドの流れ、試した数、分かったこと、直した不具合、試していない候補 |
| [`docs/methodology.md`](docs/methodology.md) | 第1ラウンド(6局面ルール)の決めごと。仮説A・Cの合格基準と、答え合わせを保留した理由 |
| [`docs/hypotheses_v2.md`](docs/hypotheses_v2.md) | 第2ラウンド(銘柄同士の比較・H17/H17L・F1)の条件と、試した順の記録 |
| [`docs/hypotheses_v3.md`](docs/hypotheses_v3.md) | 第3ラウンド(清算の連鎖の後の反発)の条件と、試した順の記録 |
| [`docs/dex_data_feasibility.md`](docs/dex_data_feasibility.md) | DEXデータが取れるかの調査(Flipside・Dune・BigQuery) |

## レポート(`reports/`)

ブラウザで開くと読める HTML ファイル。

| ファイル | 何の結果か |
|---|---|
| [`reports/backtest_report.html`](reports/backtest_report.html) | 第1ラウンド: 6局面ルールの検証。2025年以降の答え合わせで18通りすべて不合格 |
| [`reports/event_study.html`](reports/event_study.html) | 第1ラウンドの後の逆引き分析: 大きく動いた時点の直前に何が起きていたか(取引停止時間を除いた修正版) |
| [`reports/cross_section.html`](reports/cross_section.html) | 第2ラウンド: 銘柄同士の比較(H1〜H6)。全銘柄と、第1ラウンドの61銘柄での違い(銘柄選びの偏り) |
| [`reports/overheat_short.html`](reports/overheat_short.html) | 第2ラウンド: H17 過熱ショート(FRが全銘柄の上位5%に入った銘柄を空売り)。荒れ予報・清算価格帯(推定)の補助分析つき |
| [`reports/overheat_long.html`](reports/overheat_long.html) | 第2ラウンド: H17L 過熱ロング(FRが下位5%に入った銘柄を買う) |
| [`reports/holdout_v2.html`](reports/holdout_v2.html) | 第2ラウンドの答え合わせ(2025年1月〜2026年8月): H5・F1 とも不合格 |
| [`reports/cascade_rebound.html`](reports/cascade_rebound.html) | 第3ラウンド: 清算の連鎖の後の反発(2022〜2024年、36通り、耐久テストつき) |
| [`reports/cascade_holdout.html`](reports/cascade_holdout.html) | 第3ラウンドの答え合わせ(2025年1月〜2026年8月): 「30分で5%以上の下げ × すぐ買う × 4時間」は不合格 |

## セットアップ (Windows)

1. Python 3.11 以降をインストール
2. このフォルダで以下を実行して必要なライブラリを入れる

   ```
   pip install -r requirements.txt
   ```

データは Binance の公開データ(S3 の `data.binance.vision`)から無料で取る。アカウントは不要。

## データの取り直し方(すべてのデータと主要なレポートを再現する)

`data/`(ダウンロードしたデータ)は Git に入れていないので、新しい環境では下の順に実行する。
ダウンロードはどれも**途中で止めても、同じコマンドをもう一度実行すれば続きから再開**する。
長いダウンロードは `scripts/run_until_done.sh <ログファイル> <スクリプト> <引数>` で包むと、落ちても自動で再実行される(Linux/Mac。Windows では同じコマンドを手で再実行する)。

### 必要な空き容量と時間の目安

| | 目安 |
|---|---|
| 空き容量 | **35GB 以上**(全部そろえると約24GB: 生データ約7GB + 整理済みデータ約17GB。作業用の余裕を含む) |
| 時間 | 合計 **15〜20時間**ほど(ほとんどがダウンロード。回線と Binance 側の速さで変わる) |

### 第1ラウンド(6局面ルール・逆引き分析)

| 順 | コマンド | 中身 | 時間の目安 |
|---|---|---|---|
| 1 | `python scripts/build_symbol_list.py` | 銘柄リストの下書き。**`configs/symbols.yaml` はコミット済みなので、再現するときは実行しない**(実行すると今の出来高で作り直される) | — |
| 2 | `python scripts/download_stage1_group.py large_cap mid_cap_alt small_meme` | 約100銘柄の1時間足(先物・現物)・建玉・FR | 数時間 |
| 3 | `python scripts/build_indicators.py` | 1時間ごとの指標 | 数分 |
| 4 | `python scripts/build_phases.py` | 6局面の判定 | 数分 |
| 5 | `python scripts/build_validation.py` | 検証(2025年以降の答え合わせを含む) | 数分 |
| 6 | `python scripts/build_report.py` | → `reports/backtest_report.html` | 1分 |
| 7 | `python scripts/run_event_study.py` | 逆引き分析(2022〜2024年) | 数分 |
| 8 | `python scripts/build_event_study_report.py` | → `reports/event_study.html` | 1分 |

`scripts/run_holdout_ac.py`(仮説A・Cの答え合わせ)は、根拠が崩れたため**実行していない**。

### 第2ラウンド(銘柄同士の比較・H17/H17L・F1)

| 順 | コマンド | 中身 | 時間の目安 |
|---|---|---|---|
| 1 | `python scripts/download_full_universe.py prices` | 2022〜2024年にあった全389銘柄の1時間足(先物・現物)とFR(銘柄一覧 `configs/universe_2022_2024.yaml` はコミット済み) | 約1時間 |
| 2 | `python scripts/download_full_universe.py metrics` | 同じ銘柄の建玉(日次ファイルで数が多い) | 約3時間 |
| 3 | `python scripts/build_universe.py` | 掃除と比較対象の足切りの確認 | 数分 |
| 4 | `python scripts/check_cross_section.py full --oi` | 先読みの点検(途中で切っても過去の値が変わらないか) | 数分 |
| 5 | `python scripts/run_cross_section.py final --sets full,set61 --hyps H1,H2-7,H2-14,H2-28,H3,H4,H5,H6` | H1〜H6(2022〜2024年) | 約30分 |
| 6 | `python scripts/build_cross_section_report.py` | → `reports/cross_section.html` | 1分 |
| 7 | `python scripts/run_overheat.py final --set full` | H17 過熱ショート | 約20分 |
| 8 | `python scripts/run_overheat.py final --set full --side long` | H17L 過熱ロング | 約25分 |
| 9 | `python scripts/build_overheat_report.py` と `python scripts/build_overheat_report.py long` | → `reports/overheat_short.html`・`reports/overheat_long.html` | 1分 |

答え合わせ(2025年1月〜2026年8月):

| 順 | コマンド | 中身 | 時間の目安 |
|---|---|---|---|
| 10 | `python scripts/download_holdout.py prices` | 答え合わせの661銘柄(`configs/universe_2025_2026.yaml`、コミット済み)の1時間足 | 約1時間 |
| 11 | `python scripts/download_holdout.py metrics` | 同じ銘柄の建玉 | 約4時間 |
| 12 | `python scripts/run_holdout_v2.py check` → `python scripts/run_holdout_v2.py run` | データの点検 → H5・F1 の答え合わせ | 約20分 |
| 13 | `python scripts/build_holdout_v2_report.py` | → `reports/holdout_v2.html` | 1分 |

### 第3ラウンド(清算の連鎖)

| 順 | コマンド | 中身 | 時間の目安 |
|---|---|---|---|
| 1 | `python scripts/download_5m.py futures` | 389銘柄の先物5分足(2022〜2024年) | 約2.5時間 |
| 2 | `python scripts/download_5m.py spot` | 現物5分足(今回の計算には使っていない。省略してよい) | 約2.5時間 |
| 3 | `python scripts/check_cascade.py ADAUSDT LUNAUSDT FTTUSDT` | 先読みの点検 | 数分 |
| 4 | `python scripts/run_cascade.py final` | 2022〜2024年の計算 | 約40分 |
| 5 | `python scripts/build_cascade_report.py` | → `reports/cascade_rebound.html` | 数分 |
| 6 | `python scripts/download_5m_holdout.py` | 答え合わせの661銘柄の先物5分足(2025年1月〜2026年8月)を継ぎ足す | 約3時間 |
| 7 | `python scripts/run_cascade_holdout.py check` → `python scripts/run_cascade_holdout.py run` | データの点検 → 答え合わせ | 約30分 |
| 8 | `python scripts/build_cascade_holdout_report.py` | → `reports/cascade_holdout.html` | 1分 |

### 注意

- `final`(2024年を含む計算)と `run`(答え合わせ)は、**1回だけ**の決まりを守るため、結果のファイルがすでにあると止まり、条件の文書やコードに未コミットの変更があっても止まる。新しい環境で再現するときは結果のファイルが無いので、そのまま動く。
- 開発用の `dev`(2023年末までのデータだけ)は何度でも実行できる。例: `python scripts/run_cross_section.py dev --sets full --hyps H1`、`python scripts/run_cascade.py dev`。
- 銘柄一覧(`configs/*.yaml`)は、作ったときの S3 のファイル一覧から作ったもの。作り直すと、その後に Binance が足したファイルで結果が変わることがあるので、再現にはコミット済みのものを使う。
- 2025年以降のデータは、上の答え合わせで**すでに使った**。新しい仮説を確かめるときは、2026年9月以降のデータを使う(`docs/conclusion.md` §6)。

## フォルダ構成

```
configs/        設定(期間・コスト・銘柄一覧・上場日・暗号資産でない先物の除外リスト)
src/shiome/     ライブラリ本体
  data/           データ取得(Binance 公開データ)
  indicators/     指標(第1ラウンド)
  phases/         6局面の判定(第1ラウンド)
  validation/     検証(第1ラウンド)
  eventstudy/     逆引き分析
  crosssection/   銘柄同士の比較・H17/H17L・F1(第2ラウンド)
  cascade/        清算の連鎖(第3ラウンド)
scripts/        実行スクリプト(上の表)
docs/           結論・条件の記録・調査
reports/        HTML レポート
data/           ダウンロードしたデータ(Git 管理外)
state/          ダウンロードのログ(Git 管理外)
```
