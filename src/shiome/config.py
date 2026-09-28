"""設定ファイル(configs/*.yaml)の読み込みと共通パス定義。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIGS_DIR = ROOT_DIR / "configs"
DATA_DIR = ROOT_DIR / "data"
STATE_DIR = ROOT_DIR / "state"

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def load_settings() -> dict:
    with open(CONFIGS_DIR / "settings.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_symbols() -> dict:
    with open(CONFIGS_DIR / "symbols.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_symbols(data: dict) -> None:
    path = CONFIGS_DIR / "symbols.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def all_symbols(symbols_cfg: dict) -> list[str]:
    """3グループ+上場廃止銘柄を重複なしで全部並べたリストを返す。"""
    seen: list[str] = []
    for group in symbols_cfg.get("groups", {}).values():
        for s in group:
            if s not in seen:
                seen.append(s)
    for s in symbols_cfg.get("delisted", []):
        if s not in seen:
            seen.append(s)
    return seen


def date_range(settings: dict) -> tuple[dt.date, dt.date]:
    start = dt.date.fromisoformat(settings["date_range"]["start"])
    end_raw = settings["date_range"].get("end")
    end = dt.date.fromisoformat(end_raw) if end_raw else dt.date.today()
    return start, end


def ensure_dirs() -> None:
    for d in [DATA_DIR, RAW_DIR, PROCESSED_DIR, STATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
