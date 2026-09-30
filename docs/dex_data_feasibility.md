# 第3ラウンド B: DEXデータが取り出せるかの確認

調べた日: 2026-09-30。お金は払っていない。重い集計も、データの取り出しもしていない。
2025年以降のDEXデータの中身は見ていない。

## 結論(先に)

| 方法 | 取れる期間(2024年〜2026年8月) | あなたがやること | 費用 | 手間 | おすすめ |
|---|---|---|---|---|---|
| **Flipside** | **使えない**(下記) | — | — | — | ✕ |
| **Dune(有料 Analyst)** | Solana・Ethereum・Base・BNBなどの売買の表(`dex.trades`)で全期間を取れる見込み | アカウント作成、Analyst契約(月75ドル、年払いなら月65ドル)、APIキーを作ってこの環境に登録、ネットワーク許可に `api.dune.com` を追加 | 月75ドル(毎月4,000クレジット)。足りなければ1クレジット0.016ドル | 中(集計のSQLは私が書く) | ◎ 取れる範囲が一番広い。ただし実際のクレジット消費は1銘柄・1日分を試すまで分からない |
| **Google BigQuery 公開データ** | Ethereum: ERC-20の送金の表(`crypto_ethereum.token_transfers`)で全期間の見込み。**Solana: 使えない見込み**(2025年3月末で更新停止の報告があり、売買の表もない)。Base・BSC: 公開データなし | Googleアカウントで無料のサンドボックス(カード不要)を作る。試算は、私が書いたSQLを画面に貼るだけでも見られる | 毎月1TiBまで無料、超えると1TiBあたり6.25ドル(サンドボックスなら課金されない) | 中〜大(Ethereumでは「送金」から「売買」を自分で組み立てる必要がある) | ○ Ethereumのミーム(PEPE・SHIB・FLOKI・MOGなど)だけなら無料で試せる |

- **いちばん大事な点**: この環境のネットワーク方針で、CoinGecko・DexScreener・GeckoTerminal・Flipside・Dune・SolanaのRPC(ブロックチェーンのデータの窓口)への接続は**拒否された**(403)。回り道はしていない。
  Googleの窓口(BigQuery・認証)には接続できる。
- そのため、**手順3(WIF の1日分を小さく取り出す)はできなかった。** 取り出せる窓口がすべて接続拒否か、アカウントが必要なため。
- ミームの**コントラクトアドレス**(トークンの住所)は、調べる窓口(CoinGecko など)に接続できないため**空欄**にしている。記憶で書くと間違えるおそれがあるため、許可が出たら自動で埋める。

## 1. この環境から接続できるか(2026-09-30)

| 接続先 | 結果 |
|---|---|
| api.coingecko.com / api.dexscreener.com / api.geckoterminal.com | 拒否(403) |
| api-v2.flipsidecrypto.xyz / flipsidecrypto.xyz / docs.flipsidecrypto.xyz | 拒否(403) |
| api.dune.com / dune.com / docs.dune.com | 拒否(403) |
| api.mainnet-beta.solana.com(SolanaのRPC) / api.bitquery.io | 拒否(403) |
| bigquery.googleapis.com / oauth2.googleapis.com / www.googleapis.com / cloud.google.com | 接続できる |

料金や制限は、公開されている説明ページをウェブ検索で確かめた(下の「出典」)。Dune と Flipside の説明ページそのものも、この環境からは開けなかった。

## 2. 方法ごとの詳細

### Flipside → 使えない
- 2026年5月21日、Flipside はブロックチェーンのデータ事業を **SonarX に売却**し、AI事業(edisyl)に専念すると発表。
- データの画面とAPI(Flipspace)は **2026年6月17日で終了**。旧利用者は SonarX に移された。
- SonarX は企業向けの有料サービスで、無料枠や料金は公開情報からは確認できなかった。
- よって「無料枠があるか」「ez_dex_swaps に何年分あるか」は、**サービス自体が終わっているため確認できない**。

### Dune → 有料なら取れる見込み(契約はしていない)
- 料金: **Analyst は月75ドル(年払いなら月65ドル)、毎月4,000クレジット**。超えた分は1クレジット0.016ドル。
- 無料プラン: 2026年9月10日から、7月21日より前に作ったアカウントは**見るだけ**(クエリを実行できない)に変更と報じられている。新しく作るアカウントの扱いは、接続できず確認できなかった。
- クレジットの減り方: 使った計算量に比例する(1回のクエリが数クレジットのことも数百クレジットのこともある。同じ内容でも書き方で7クレジット対583クレジットになった例が報告されている)。
- **必要なクレジットの目安(推測。実際には1銘柄・1日分を1回走らせないと分からない)**:
  - 「買っているウォレット数」「大口の買い越し」「流動性の追加・引き上げ」を1時間ごと・約30銘柄・約2年8か月分で集計する場合、1銘柄あたり数十〜数百クレジットと推測 → 全部で数千クレジット(Analyst の1〜2か月分)。
  - 「新規ウォレットの割合」は、各ウォレットが初めてその銘柄を買った時刻を全期間から探す必要があり、いちばん重い。
- 対応チェーン: Solana・Ethereum・Base・BNB Chain など主要チェーンは売買の表(`dex.trades`)がある。TON(DOGS)・Sui(HIPPO)は確認できていない。

### Google BigQuery 公開データ → Ethereum なら試せる
- 料金: **毎月1TiBまで無料**、超えると1TiBあたり6.25ドル(Googleの料金ページで確認)。**サンドボックス**ならカード不要で、課金されない(かわりに容量などの制限がある)。
- Solana(`bigquery-public-data.crypto_solana_mainnet_us`): **2025年3月31日で更新が止まった**とGoogleの開発者フォーラムで報告されている(その後の状況は未確認)。売買をまとめた表はなく、生の命令(instructions)から自分で売買を組み立てる必要があり、量も非常に大きい。→ **2024年〜2026年8月の用途には向かない見込み**。
- Ethereum(`bigquery-public-data.crypto_ethereum`): ERC-20の送金の表(`token_transfers`)がある(遅れは十数時間)。売買は「DEXのプールとの間の送金」から組み立てる。PEPE・SHIB・FLOKI・MEME・TURBO・NEIRO・MOG・PEOPLE・SPX が対象になりうる。
- Base・BNB Chain・TON・Sui: 公開データの一覧に見当たらない。
- 試算(dry run): **未実施**。アカウントが無いため。下の手順で、無料・カード不要で試算できる。

### 参考: ほかの候補(今回は調べる対象外)
- Bitquery(Solana の売買履歴をAPIで取れる。無料枠あり、とされる)— この環境からは接続拒否。
- DexScreener・GeckoTerminal — 足の値段は取れるが、ウォレット単位の集計はできない。

## 3. Binance先物にあるミームで、DEXで取引されている銘柄(候補)

- 先物の上場日は、手元の1時間足の最初の足(2022年1月1日の銘柄は「2022年より前」)。
- チェーンと主なDEXは一般的な知識によるもので、**CoinGecko に接続できるようになったら確認して、コントラクトアドレスと一緒に埋める**。

| 先物の銘柄 | チェーン | 主なDEX | 先物の上場日 | コントラクトアドレス |
|---|---|---|---|---|
| 1000PEPEUSDT | Ethereum | Uniswap | 2023-05-05 | (未取得) |
| 1000SHIBUSDT | Ethereum | Uniswap | 2022年より前 | (未取得) |
| 1000FLOKIUSDT | Ethereum / BNB Chain | Uniswap / PancakeSwap | 2023-05-06 | (未取得) |
| MEMEUSDT | Ethereum | Uniswap | 2023-11-03 | (未取得) |
| PEOPLEUSDT | Ethereum | Uniswap | 2022年より前 | (未取得) |
| TURBOUSDT | Ethereum | Uniswap | 2024-05-30 | (未取得) |
| NEIROETHUSDT | Ethereum | Uniswap | 2024-09-06 | (未取得) |
| NEIROUSDT | Ethereum | Uniswap | 2024-09-16 | (未取得) |
| 1000000MOGUSDT | Ethereum | Uniswap | 2024-11-07 | (未取得) |
| SPXUSDT | Ethereum(Base・Solana にもあり) | Uniswap | 2024-12-10 | (未取得) |
| BRETTUSDT | Base | Aerodrome / Uniswap | 2024-08-20 | (未取得) |
| DEGENUSDT | Base | Aerodrome / Uniswap | 2024-11-15 | (未取得) |
| TOSHIUSDT | Base | Aerodrome / Uniswap | 2025-09-17 | (未取得) |
| 1000BONKUSDT | Solana | Raydium / Orca / Meteora | 2023-11-22 | (未取得) |
| WIFUSDT | Solana | Raydium / Orca / Meteora | 2024-01-18 | (未取得) |
| MYROUSDT | Solana | Raydium | 2024-03-05 | (未取得) |
| BOMEUSDT | Solana | Raydium | 2024-03-16 | (未取得) |
| MEWUSDT | Solana | Raydium | 2024-06-17 | (未取得) |
| POPCATUSDT | Solana | Raydium | 2024-08-22 | (未取得) |
| GOATUSDT | Solana | Raydium | 2024-10-24 | (未取得) |
| MOODENGUSDT | Solana | Raydium | 2024-10-25 | (未取得) |
| PNUTUSDT | Solana | Raydium | 2024-11-11 | (未取得) |
| ACTUSDT | Solana | Raydium | 2024-11-11 | (未取得) |
| BANUSDT | Solana | Raydium | 2024-11-18 | (未取得) |
| SLERFUSDT | Solana | Raydium | 2024-11-21 | (未取得) |
| CHILLGUYUSDT | Solana | Raydium | 2024-11-27 | (未取得) |
| PENGUUSDT | Solana | Raydium / Meteora | 2024-12-17 | (未取得) |
| FARTCOINUSDT | Solana | Raydium / Meteora | 2024-12-20 | (未取得) |
| AI16ZUSDT | Solana | Raydium / Meteora | 2025-01-02 | (未取得) |
| GRIFFAINUSDT | Solana | Raydium / Meteora | 2025-01-02 | (未取得) |
| ZEREBROUSDT | Solana | Raydium | 2025-01-02 | (未取得) |
| TRUMPUSDT | Solana | Meteora | 2025-01-18 | (未取得) |
| MELANIAUSDT | Solana | Meteora | 2025-01-20 | (未取得) |
| PIPPINUSDT | Solana | Raydium | 2025-01-24 | (未取得) |
| VINEUSDT | Solana | Raydium / Meteora | 2025-01-24 | (未取得) |
| JELLYJELLYUSDT | Solana | Raydium | 2025-03-26 | (未取得) |
| USELESSUSDT | Solana | Raydium / Meteora | 2025-08-15 | (未取得) |
| 1MBABYDOGEUSDT | BNB Chain | PancakeSwap | 2024-09-16 | (未取得) |
| 1000CATUSDT | BNB Chain | PancakeSwap | 2024-10-21 | (未取得) |
| 1000CHEEMSUSDT | BNB Chain | PancakeSwap | 2024-11-25 | (未取得) |
| 1000WHYUSDT | BNB Chain | PancakeSwap | 2024-11-25 | (未取得) |
| KOMAUSDT | BNB Chain | PancakeSwap | 2024-12-10 | (未取得) |
| TSTUSDT | BNB Chain | PancakeSwap | 2025-02-09 | (未取得) |
| MUBARAKUSDT | BNB Chain | PancakeSwap | 2025-03-17 | (未取得) |
| BROCCOLI714USDT | BNB Chain | PancakeSwap | 2025-03-21 | (未取得) |
| BANANAS31USDT | BNB Chain | PancakeSwap | 2025-03-22 | (未取得) |
| GIGGLEUSDT | BNB Chain | PancakeSwap | 2025-10-09 | (未取得) |
| 币安人生USDT | BNB Chain | PancakeSwap | 2025-10-20 | (未取得) |
| DOGSUSDT | TON | STON.fi / DeDust | 2024-08-26 | (未取得) |
| HIPPOUSDT | Sui | Cetus | 2024-11-13 | (未取得) |

外したもの: DOGE(独自チェーンでDEXの売買が中心ではない)、1000SATS・1000RATS(ビットコイン上のBRC-20でDEXの記録が取りにくい)、
ORDI・1000LUNC・WLFI・LA・PUMP・BOB・1000X・WEN など(ミームではない、または中身がはっきりしない)。

## 4. あなたにお願いしたいこと(決まったら)

どれも**お金はかからない**。

1. **ネットワークの許可を広げる**(リストの住所を埋めるため): Claude Code の画面上部にあるクラウド環境のメニュー → 「Edit」→ 「Network access」で、
   許可するドメインに `api.coingecko.com` と `api.dexscreener.com` を追加する(Dune を使うと決めたら `api.dune.com` も)。
   設定の説明: https://code.claude.com/docs/en/claude-code-on-the-web
2. **BigQuery を無料で試算する**(Ethereum のミームを使う場合):
   1. ブラウザで https://console.cloud.google.com を開き、Googleアカウントでログインする。
   2. 画面上部の「プロジェクトを選択」→「新しいプロジェクト」→ 名前(例: shiome)を入れて「作成」。
   3. 左のメニューから「BigQuery」を開く。カードの登録を求められなければ、そのまま**サンドボックス**(無料)で使える。
   4. 私が用意するSQLを、画面の入力欄に貼り付ける。**実行ボタンは押さない**。入力欄の右上に「このクエリを実行すると ○○ GB が処理されます」と出るので、その数字を教えてほしい(これが試算)。
3. **Dune を使うかは、2. の結果を見てから決める**のがおすすめ。使う場合も、まず1銘柄・1日分だけを走らせて、実際のクレジット消費を確かめてから全体を見積もる。

## 出典

- Flipside のデータ事業売却: [SonarX Acquires Flipside Crypto's Blockchain Data Business (SonarX)](https://www.sonarx.com/blog/sonarx-acquires-flipside-crypto-blockchain-data-business)、[Flipside sells blockchain data business to SonarX (edisyl)](https://www.edisyl.com/news/flipside-sells-blockchain-data-business-to-sonarx/)、[Flipspace — Shutting Down](https://flipsidecrypto.xyz/flipspace/)
- Dune の料金: [Dune Analytics Pricing 2026 (costbench)](https://costbench.com/software/onchain-analytics/dune-analytics/)、[Dune Analytics Pricing (comparedge)](https://comparedge.com/tools/dune-analytics/pricing)、[FAQs - Dune Docs](https://docs.dune.com/learning/how-tos/pricing-faqs)、[Dune updates free plan to view-only access (Crypto Briefing)](https://cryptobriefing.com/dune-free-plan-view-only-access/)
- BigQuery の料金: [BigQuery pricing (Google Cloud)](https://cloud.google.com/bigquery/pricing)(この環境から直接確認)
- BigQuery の Solana 公開データ: [Public Solana BigQuery Dataset Stopped Updating on March 31, 2025 (Google Developer forums)](https://discuss.google.dev/t/public-solana-bigquery-dataset-crypto-solana-mainnet-us-stopped-updating-on-march-31-2025/185629)、[Public Blockchain Datasets (blockchain-etl)](https://github.com/blockchain-etl/public-datasets)
