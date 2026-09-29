"""3グループ(大型/中型アルト/小型・ミーム)の銘柄リストを組み立てる。

api.binance.com / fapi.binance.com はこの実行環境からブロックされているため、
data.binance.vision と同じS3バケットの一覧情報だけで銘柄選定を行う。

手順:
  1) S3上の data/futures/um/monthly/klines/ 配下から、過去に一度でも
     USDT建て先物klinesが存在した銘柄を全部拾う
  2) 銘柄ごとに「最新の月次ファイルがある年月」を調べる
     → 直近1〜2ヶ月以内ならactive(現存)、それより古ければdelisted(上場廃止)とみなす
  3) activeな銘柄について、直近の月次klineをダウンロードしてクオート出来高を合計し、
     出来高ランキングを作る(中型/小型の区分けに使う)
  4) 大型は時価総額ベースの手動候補リストと現存先物一覧の積集合から採用
  5) 現物(spot)側の全銘柄一覧も同様にS3から取得し、対応する現物ペアが
     存在するかどうか(現物CVDが計算できるか)を判定する
     (先物の「1000PEPE」のようなリベース銘柄は現物では「PEPE」表記になるため、
      倍率プレフィックスを外して照合する)

これは出来高・上場状況の「下書き」を作るだけ。最終的な採否はユーザー確認後に確定する。
"""
from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from shiome.config import RAW_DIR, load_settings
from shiome.data.binance_vision import download_file, list_keys
from shiome.data import klines

# 時価総額上位の「候補」。ここから現在Binance先物USDT無期限で取引中のものを優先的に採用する。
# 実際の時価総額順位はレポート作成時に見直すこと。
LARGE_CAP_CANDIDATES = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TONUSDT",
    "SHIBUSDT", "LTCUSDT", "BCHUSDT", "SUIUSDT", "NEARUSDT", "APTUSDT",
]

EXCLUDE_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

# Binanceは株式・貴金属・商品指数などに連動する「トークン化資産」の無期限先物も
# 同じfutures/umのバケットに置いている。これらは暗号資産ではないため除外する。
# (このセッションの知識には無い新しい上場も多いため、確信度の高いものだけを機械的に除外し、
#  判断が曖昧なものは EXCLUDE 対象にせず「要確認」として銘柄リストとは別に報告する)
EXCLUDE_NON_CRYPTO_SYMBOLS = {
    # 貴金属・商品
    "XAUUSDT", "XAGUSDT", "CLUSDT",
    # 株価指数・ETF
    "QQQUSDT", "SOXLUSDT", "SOXSUSDT", "EWYUSDT",
    # 米国個別株
    "AAPLUSDT", "AMZNUSDT", "ADBEUSDT", "AMDUSDT", "NVDAUSDT", "TSLAUSDT",
    "INTCUSDT", "MRVLUSDT", "MSTRUSDT", "AAOIUSDT", "CRCLUSDT", "HEIUSDT", "NBISUSDT",
    # 韓国株など
    "SKHYNIXUSDT", "SKHYUSDT", "SAMSUNGUSDT", "KORUUSDT", "SNXXUSDT", "SPCXUSDT",
    # 追加で見つかった株式・ETF
    "GOOGLUSDT", "SPYUSDT", "SNDKUSDT",
}

# 暗号資産か非暗号資産(株式トークンなど)か判断がつかなかった銘柄。
# 除外はしないが、レポート提示時にユーザーへ個別確認を促す。
UNCERTAIN_NON_CRYPTO_CANDIDATES = {
    "BZUSDT", "BTWUSDT", "BEATUSDT", "DRAMUSDT", "CYSUSDT", "APRUSDT",
    "TUTUSDT", "GIGGLEUSDT", "HOMEUSDT", "MUUSDT", "MUUUSDT",
    "BMTUSDT", "GPSUSDT", "SKYAIUSDT", "LITEUSDT",
}

_MULTIPLIER_RE = re.compile(r"^(1000000|100000|10000|1000|1M)([A-Z0-9]+)USDT$")


def futures_to_spot_symbol(futures_symbol: str) -> str:
    """先物のリベース銘柄名(例: 1000PEPEUSDT)を現物側の表記(PEPEUSDT)に変換する。"""
    m = _MULTIPLIER_RE.match(futures_symbol)
    if m:
        return f"{m.group(2)}USDT"
    return futures_symbol


def rebase_multiplier(futures_symbol: str) -> int:
    """先物のリベース倍率を返す(例: 1000PEPEUSDT -> 1000)。リベースでなければ1。

    現物・先物の価格差を計算する際、現物価格にこの倍率を掛けてから比較する。
    (docs/methodology.md #9)
    """
    m = _MULTIPLIER_RE.match(futures_symbol)
    if not m:
        return 1
    token = m.group(1)
    return 1000000 if token == "1M" else int(token)


def discover_all_time_symbols(market: str) -> list[str]:
    """S3バケットの一覧から、過去に一度でもklinesが存在した銘柄フォルダを全部拾う。"""
    prefix = {
        "spot": "data/spot/monthly/klines/",
        "futures_um": "data/futures/um/monthly/klines/",
    }[market]
    result = list_keys(prefix, delimiter="/")
    symbols = []
    for p in result.common_prefixes:
        parts = p.strip("/").split("/")
        if parts:
            name = parts[-1]
            if (
                name.endswith("USDT")
                and name.isascii()
                and not name.endswith(EXCLUDE_SUFFIXES)
                and name not in EXCLUDE_NON_CRYPTO_SYMBOLS
            ):
                symbols.append(name)
    return sorted(set(symbols))


def _latest_month(market: str, symbol: str) -> tuple[int, int] | None:
    prefix_map = {
        "spot": "data/spot/monthly/klines",
        "futures_um": "data/futures/um/monthly/klines",
    }
    r = list_keys(f"{prefix_map[market]}/{symbol}/1h/", delimiter=None)
    if not r.keys:
        return None
    last_key = max(r.keys)
    m = re.search(r"(\d{4})-(\d{2})", last_key)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def find_latest_months(market: str, symbols: list[str], max_workers: int = 30) -> dict[str, tuple[int, int] | None]:
    out: dict[str, tuple[int, int] | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_latest_month, market, s): s for s in symbols}
        for fut in as_completed(futs):
            s = futs[fut]
            out[s] = fut.result()
    return out


def _prev_year_month(today: dt.date) -> tuple[int, int]:
    first_of_month = dt.date(today.year, today.month, 1)
    prev = first_of_month - dt.timedelta(days=1)
    return prev.year, prev.month


def split_active_delisted(latest_months: dict[str, tuple[int, int] | None]) -> tuple[list[str], list[str]]:
    threshold = _prev_year_month(dt.date.today())
    active, delisted = [], []
    for sym, ym in latest_months.items():
        if ym is not None and ym >= threshold:
            active.append(sym)
        else:
            delisted.append(sym)
    return sorted(active), sorted(delisted)


def estimate_recent_quote_volume(symbol: str, year: int, month: int) -> float:
    """直近の月次klineをダウンロードして、その月のクオート出来高合計を返す(ランキング用)。"""
    key = klines.monthly_key("futures_um", symbol, "1h", year, month)
    dest_dir = klines.raw_dir("futures_um", symbol, "1h")
    dest = dest_dir / key.rsplit("/", 1)[-1]
    try:
        download_file(key, dest)
        df = klines.read_kline_zip(dest)
        return float(df["quote_asset_volume"].astype(float).sum())
    except Exception:  # noqa: BLE001
        return 0.0


def rank_by_recent_volume(symbols_with_month: dict[str, tuple[int, int]], max_workers: int = 10) -> dict[str, float]:
    volume: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(estimate_recent_quote_volume, s, ym[0], ym[1]): s
            for s, ym in symbols_with_month.items()
        }
        for fut in as_completed(futs):
            s = futs[fut]
            volume[s] = fut.result()
    return volume


def build_symbol_groups(large_n: int = 10, mid_n: int = 40, small_n: int = 50) -> dict:
    print("  先物(USD-M)の全銘柄一覧を取得中...")
    all_time_futures = discover_all_time_symbols("futures_um")
    print(f"  {len(all_time_futures)}銘柄(現存+上場廃止)を検出。現存/廃止を判定中...")
    latest_months = find_latest_months("futures_um", all_time_futures)
    active, delisted = split_active_delisted(latest_months)
    print(f"  現存: {len(active)}銘柄 / 上場廃止: {len(delisted)}銘柄")

    print("  出来高ランキング用に直近月のklineをダウンロード中...")
    active_with_month = {s: latest_months[s] for s in active}
    volume = rank_by_recent_volume(active_with_month)

    large_cap = [s for s in LARGE_CAP_CANDIDATES if s in active][:large_n]

    remaining_active = [s for s in active if s not in large_cap]
    remaining_sorted = sorted(remaining_active, key=lambda s: volume.get(s, 0.0), reverse=True)

    mid_cap_alt = remaining_sorted[:mid_n]
    rest_active = remaining_sorted[mid_n:]

    # 小型・ミームグループ = 出来高下位の現存銘柄 + 上場廃止銘柄(全部)
    small_meme_active_n = max(0, small_n - len(delisted))
    small_meme = rest_active[:small_meme_active_n] + delisted

    print("  現物(spot)側の銘柄一覧を取得中(現物CVDの有無判定用)...")
    all_time_spot = set(discover_all_time_symbols("spot"))
    all_selected = large_cap + mid_cap_alt + small_meme
    has_spot_data = sorted(
        s for s in all_selected if futures_to_spot_symbol(s) in all_time_spot
    )
    no_spot_data = sorted(set(all_selected) - set(has_spot_data))

    uncertain_flagged = sorted(UNCERTAIN_NON_CRYPTO_CANDIDATES & set(all_selected))

    return {
        "uncertain_needs_manual_check": uncertain_flagged,
        "groups": {
            "large_cap": large_cap,
            "mid_cap_alt": mid_cap_alt,
            "small_meme": small_meme,
        },
        "delisted": delisted,
        "has_spot_data": has_spot_data,
        "no_spot_data": no_spot_data,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
