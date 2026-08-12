"""Oracle / MySQL 읽기전용 접근 계층.

보안/컴플라이언스 장치:
  1) SELECT 외 구문 차단 (assert_read_only)
  2) config.yaml 에 등록된 테이블만 접근 허용 (assert_table_allowed)
  3) WHERE 절 등 자유 입력에 union/select/;/-- 등 주입 토큰 차단 (assert_safe_fragment)
※ 그래도 DB 계정 자체를 '읽기전용'으로 만드는 것이 가장 확실합니다.
"""
from __future__ import annotations

import re

import oracledb
import pymysql

from .settings import SOURCES, mysql_env, oracle_env

_SELECT_ONLY = re.compile(r"^\s*select\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|call|exec)\b",
    re.IGNORECASE,
)
_INJECT = re.compile(r"(;|--|/\*|\bunion\b|\bselect\b)", re.IGNORECASE)


def _allowed_tables(db_kind: str) -> set[str]:
    conf = SOURCES.get(db_kind, {}) or {}
    return {t["table"].upper() for t in conf.get("tables", [])}


def assert_read_only(sql: str) -> None:
    if not _SELECT_ONLY.match(sql) or _FORBIDDEN.search(sql):
        raise ValueError("읽기 전용(SELECT) 쿼리만 허용됩니다.")


def assert_table_allowed(db_kind: str, table: str) -> None:
    if table.upper() not in _allowed_tables(db_kind):
        raise ValueError(
            f"허용되지 않은 테이블: {table} "
            f"(config.yaml 의 sources.{db_kind} 에 등록해야 합니다)"
        )


def assert_safe_fragment(fragment: str) -> None:
    """WHERE 절/컬럼 목록 같은 자유 입력에 위험 토큰이 없는지 검사."""
    if fragment and _INJECT.search(fragment):
        raise ValueError("허용되지 않은 토큰(union/select/;/-- 등)이 포함되었습니다.")


# ---------------- 연결 ----------------
def oracle_conn():
    env = oracle_env()
    # thin 모드(기본): Oracle Instant Client 설치가 필요 없음
    return oracledb.connect(user=env["user"], password=env["password"], dsn=env["dsn"])


def mysql_conn():
    env = mysql_env()
    return pymysql.connect(
        host=env["host"], port=env["port"], user=env["user"],
        password=env["password"], database=env["database"],
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


# ---------------- 읽기전용 조회 ----------------
def run_select(db_kind: str, sql: str, params=None, limit: int = 500) -> list[dict]:
    """읽기전용 SELECT 실행 후 dict 리스트로 반환."""
    assert_read_only(sql)
    conn = oracle_conn() if db_kind == "oracle" else mysql_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ([] if db_kind == "oracle" else ()))
        rows = cur.fetchmany(limit)
        if db_kind == "oracle":
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        return list(rows)  # pymysql DictCursor 는 이미 dict
    finally:
        conn.close()
