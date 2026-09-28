# 潮目 (shiome) バックテスト

暗号資産の6局面ルールが将来の値動きを予測できるかを検証するプロジェクト。

## 進め方(5段階)

1. **データ取得** ← 今ここ
2. 指標計算
3. 局面判定
4. 検証
5. レポート

## セットアップ (Windows)

1. Python 3.11 以降をインストール
2. このフォルダで以下を実行して必要なライブラリを入れる

   ```
   pip install -r requirements.txt
   ```

## ステージ0: 銘柄リスト作成

```
python scripts/build_symbol_list.py
```

`configs/symbols.yaml` に大型/中型アルト/小型・ミームの3グループ(+上場廃止銘柄)が保存される。
内容を確認し、必要なら手動で調整してから次に進む。

## ステージ1: 大型グループのデータ取得(お試し)

```
python scripts/download_stage1_largecap.py
```

- `data/raw/` に生ファイル(zip/API取得結果)
- `data/processed/` に銘柄ごとのparquetファイル

が作られる。途中で止めても再実行すれば続きから再開される(完了済みファイルはスキップ)。

うまくいったら `configs/symbols.yaml` の他グループも同じ流れで追加していく。

## フォルダ構成

```
configs/        設定ファイル(期間・銘柄リスト・コストモデルなど)
src/shiome/     ライブラリ本体
  data/         データ取得(binance.vision, fapi)
scripts/        実行スクリプト
data/           ダウンロードしたデータ(git管理外)
state/          再開用の進捗記録(git管理外)
```
