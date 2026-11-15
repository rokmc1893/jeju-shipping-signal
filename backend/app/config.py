"""설정 로더 — .env + config/*.yaml. 표준 라이브러리 + PyYAML 만 사용."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _load_dotenv(path: Path) -> None:
    """python-dotenv 없이 .env 를 읽어 os.environ 에 넣는다(이미 있는 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@lru_cache(maxsize=1)
def datasets() -> dict:
    return yaml.safe_load((CONFIG_DIR / "datasets.yaml").read_text(encoding="utf-8"))["datasets"]


@lru_cache(maxsize=1)
def items_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "items.yaml").read_text(encoding="utf-8"))


def items() -> dict:
    return items_config()["items"]


def rules() -> dict:
    return items_config()["rules"]


def collect_config() -> dict:
    return items_config().get("collect", {})


def share_footnote(level: str) -> str:
    return items_config()["share_footnote"].get(level, "")


def data_dir() -> Path:
    p = Path(env("DATA_DIR", str(ROOT / "data" / "cache")))
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p
