"""config.yaml + .env 를 읽어 설정값을 제공한다.

- config.yaml : 모델/검색/색인 대상(테이블 허용목록) 등 구조적 설정
- .env        : DB 접속정보(비밀번호 등) 민감값  (python-dotenv 없이 직접 파싱)
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent  # .../llm/rag


def _load_env(path: Path) -> None:
    """아주 단순한 .env 로더 (KEY=VALUE)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_env(BASE_DIR / ".env")

with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

OLLAMA = CONFIG["ollama"]
RETRIEVAL = CONFIG["retrieval"]
VECTOR = CONFIG["vector_store"]
SOURCES = CONFIG["sources"]


def oracle_env() -> dict:
    return {
        "user": os.getenv("ORACLE_USER", ""),
        "password": os.getenv("ORACLE_PASSWORD", ""),
        "dsn": os.getenv("ORACLE_DSN", ""),
    }


def mysql_env() -> dict:
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", ""),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", ""),
    }
