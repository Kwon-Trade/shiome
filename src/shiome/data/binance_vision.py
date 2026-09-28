"""data.binance.vision (公開データのS3バケット) を扱う低レベル関数群。

- list_keys(): 指定prefix配下のファイル一覧・フォルダ一覧を取得(ページング対応)
- download_file(): 1ファイルをダウンロード。既に完全なファイルがあればスキップ(再開可能)

このモジュールはネットワーク越しの実データで一度も検証していない。
初回実行時にエンドポイントの形式(XML構造など)がズレていたら、
list_keys() のパース部分を実際のレスポンスに合わせて調整すること。
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import requests

from shiome.config import load_settings

_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


@dataclass
class ListResult:
    keys: list[str]
    common_prefixes: list[str]  # delimiter="/" のときの「フォルダ」相当


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "shiome-backtest/0.1"})
    return s


def list_keys(prefix: str, delimiter: str | None = "/", session: requests.Session | None = None) -> ListResult:
    """S3 ListObjects(v1)形式でバケット内を一覧する。ページング(NextMarker)にも対応。"""
    settings = load_settings()
    base = settings["urls"]["vision_bucket_listing"]
    sess = session or _session()

    keys: list[str] = []
    common_prefixes: list[str] = []
    marker = None

    while True:
        params = {"prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if marker:
            params["marker"] = marker

        resp = _get_with_retry(sess, base, params=params)
        root = ET.fromstring(resp.content)

        for contents in root.findall(f"{_S3_NS}Contents"):
            key = contents.find(f"{_S3_NS}Key")
            if key is not None and key.text:
                keys.append(key.text)

        for cp in root.findall(f"{_S3_NS}CommonPrefixes"):
            p = cp.find(f"{_S3_NS}Prefix")
            if p is not None and p.text:
                common_prefixes.append(p.text)

        is_truncated = root.find(f"{_S3_NS}IsTruncated")
        if is_truncated is not None and is_truncated.text == "true":
            next_marker_el = root.find(f"{_S3_NS}NextMarker")
            if next_marker_el is not None and next_marker_el.text:
                marker = next_marker_el.text
            elif keys:
                marker = keys[-1]
            else:
                break
        else:
            break

    return ListResult(keys=keys, common_prefixes=common_prefixes)


def _get_with_retry(sess: requests.Session, url: str, params: dict | None = None) -> requests.Response:
    settings = load_settings()
    max_retries = settings["download"]["max_retries"]
    backoff = settings["download"]["retry_backoff_sec"]
    timeout = settings["download"]["request_timeout_sec"]

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = sess.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            time.sleep(backoff * (2**attempt))
            continue

        if resp.status_code == 200:
            return resp
        if resp.status_code == 404:
            # 404は「そのファイルがそもそも存在しない」ことを意味し、
            # 待っても解決しない(未来のデータがまだ公開されていない/上場前など)。
            # リトライする意味が無いので即座に諦める。
            resp.raise_for_status()
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(backoff * (2**attempt))
            continue
        resp.raise_for_status()

    if last_exc:
        raise last_exc
    raise RuntimeError(f"failed to GET {url} after {max_retries} retries")


def download_file(key: str, dest_path: Path, session: requests.Session | None = None) -> bool:
    """1ファイルをダウンロード。戻り値: 新規にダウンロードしたら True, 既存のためスキップなら False。

    再開可能にするため、一時ファイル(.part)に書き込んでから最終ファイル名にrenameする。
    途中で中断されても .part は完成ファイルとして扱われないので、次回実行時に最初からやり直すだけで安全。
    """
    settings = load_settings()
    base = settings["urls"]["vision_base"]
    url = f"{base}/{key}"
    sess = session or _session()

    if dest_path.exists() and dest_path.stat().st_size > 0:
        return False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    resp = _get_with_retry(sess, url)
    tmp_path.write_bytes(resp.content)
    tmp_path.rename(dest_path)
    return True
