"""DART 단일회사 전체 재무제표(fnlttSinglAcntAll) 수집 → DART_FIN 저장 → 매출액 중심 색인.

대상: KG이니시스(00264547). 2025년 4개 보고서(1분기/반기/3분기/사업) + 2026년 상반기(1분기/반기).
목적: 회사의 매출액 등 손익 지표를 LLM(RAG)로 활용.
실행:  python -m app.ingest_dart
설정(.env): DART_API_KEY, DART_CORP_CODE
"""
from __future__ import annotations

import os
import ssl

import httpx
import pymysql

from .indexer import get_store
from .ingest_rss import acquire_lock, release_lock, _touch_lock
from .ollama_client import embed
from .settings import mysql_env

API_KEY = os.getenv("DART_API_KEY", "YOUR_DART_API_KEY")
CORP_CODE = os.getenv("DART_CORP_CODE", "00264547")
CORP_NM = os.getenv("DART_CORP_NM", "KG이니시스")
API_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

REPRT_NM = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
FS_NM = {"CFS": "연결재무제표", "OFS": "개별재무제표"}

# (사업연도, 보고서코드) — 2025 전체 분기 + 2026 상반기
TARGETS = [
    ("2025", "11013"), ("2025", "11012"), ("2025", "11014"), ("2025", "11011"),
    ("2026", "11013"), ("2026", "11012"),
]
FS_LIST = ["CFS", "OFS"]
_TIMEOUT = httpx.Timeout(40.0, connect=10.0)


def _client() -> httpx.Client:
    try:
        import truststore
        return httpx.Client(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=_TIMEOUT)
    except Exception:
        return httpx.Client(timeout=_TIMEOUT)


def writer_conn():
    env = mysql_env()
    return pymysql.connect(
        host=env["host"], port=env["port"],
        user=os.getenv("NEWS_WRITER_USER", "newswriter"),
        password=os.getenv("NEWS_WRITER_PASSWORD", "CHANGE_ME_PASSWORD"),
        database=env["database"], charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def _amt(v):
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return None


def fetch(client, year, reprt, fs):
    r = client.get(API_URL, params={
        "crtfc_key": API_KEY, "corp_code": CORP_CODE,
        "bsns_year": year, "reprt_code": reprt, "fs_div": fs,
    })
    r.raise_for_status()
    j = r.json()
    return j.get("status"), j.get("message"), (j.get("list") or [])


def upsert(conn, rows, year, reprt, fs) -> int:
    sql = (
        "INSERT INTO DART_FIN (CORP_CODE,CORP_NM,BSNS_YEAR,REPRT_CODE,REPRT_NM,FS_DIV,SJ_DIV,SJ_NM,"
        "ACCOUNT_ID,ACCOUNT_NM,THSTRM_NM,THSTRM_AMOUNT,THSTRM_ADD_AMOUNT,FRMTRM_NM,FRMTRM_AMOUNT,ORD,CURRENCY,RCEPT_NO) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE ACCOUNT_NM=VALUES(ACCOUNT_NM),THSTRM_AMOUNT=VALUES(THSTRM_AMOUNT),"
        "THSTRM_ADD_AMOUNT=VALUES(THSTRM_ADD_AMOUNT),FRMTRM_AMOUNT=VALUES(FRMTRM_AMOUNT),RCEPT_NO=VALUES(RCEPT_NO)"
    )
    n = 0
    with conn.cursor() as cur:
        for i, a in enumerate(rows):
            ordv = _amt(a.get("ord")) or i
            cur.execute(sql, (
                CORP_CODE, CORP_NM, year, reprt, REPRT_NM.get(reprt, reprt), fs,
                a.get("sj_div"), (a.get("sj_nm") or "")[:60], (a.get("account_id") or "")[:120],
                (a.get("account_nm") or "")[:200], (a.get("thstrm_nm") or "")[:40],
                _amt(a.get("thstrm_amount")), _amt(a.get("thstrm_add_amount")),
                (a.get("frmtrm_nm") or "")[:40], _amt(a.get("frmtrm_amount")),
                ordv, a.get("currency"), a.get("rcept_no"),
            ))
            n += 1
    conn.commit()
    return n


def _find(rows, *keywords):
    """손익계산서(IS/CIS)에서 account_nm 이 keyword 를 포함하는 첫 계정 반환."""
    for a in rows:
        if a.get("sj_div") not in ("IS", "CIS"):
            continue
        nm = a.get("account_nm") or ""
        if any(k in nm for k in keywords):
            return a
    return None


def _won(v):
    n = _amt(v)
    return f"{n:,}원" if n is not None else "-"


def build_doc(rows, year, reprt, fs) -> str | None:
    sales = _find(rows, "매출액", "영업수익")
    if not sales:
        return None
    period = sales.get("thstrm_nm") or ""
    cogs = _find(rows, "매출원가")
    gp = _find(rows, "매출총이익")
    op = _find(rows, "영업이익")
    ni = _find(rows, "당기순이익", "분기순이익", "반기순이익", "순이익")
    lines = [f"{CORP_NM}(고유번호 {CORP_CODE}) {year}년 {REPRT_NM.get(reprt, reprt)} ({FS_NM.get(fs, fs)}) 손익 요약 [{period}]:"]
    lines.append(f"- 매출액: {_won(sales.get('thstrm_amount'))}" +
                 (f" (당기누적 {_won(sales.get('thstrm_add_amount'))})" if _amt(sales.get('thstrm_add_amount')) is not None else "") +
                 (f", 전기 {_won(sales.get('frmtrm_amount'))}" if _amt(sales.get('frmtrm_amount')) is not None else ""))
    if cogs: lines.append(f"- 매출원가: {_won(cogs.get('thstrm_amount'))}")
    if gp:   lines.append(f"- 매출총이익: {_won(gp.get('thstrm_amount'))}")
    if op:   lines.append(f"- 영업이익: {_won(op.get('thstrm_amount'))}")
    if ni:   lines.append(f"- 당기순이익: {_won(ni.get('thstrm_amount'))}")
    return "\n".join(lines)


def main() -> None:
    if not acquire_lock():
        return
    conn = writer_conn()
    store = get_store()
    indexed = 0
    try:
        with _client() as client:
            for year, reprt in TARGETS:
                for fs in FS_LIST:
                    try:
                        status, msg, rows = fetch(client, year, reprt, fs)
                    except Exception as e:
                        print(f"  [실패] {year}/{reprt}/{fs}: {type(e).__name__} {str(e)[:60]}")
                        continue
                    if status != "000" or not rows:
                        print(f"  [스킵] {year}/{REPRT_NM.get(reprt,reprt)}/{fs}: status={status} {msg}")
                        continue
                    n = upsert(conn, rows, year, reprt, fs)
                    doc = build_doc(rows, year, reprt, fs)
                    tag = "색인O" if doc else "매출없음"
                    print(f"  [{year}/{REPRT_NM.get(reprt,reprt)}/{fs}] 저장 {n}행 · {tag}")
                    if doc:
                        vid = f"mysql:DART_FIN:{CORP_CODE}:{year}:{reprt}:{fs}"
                        store.upsert(
                            ids=[vid], documents=[doc], embeddings=embed([doc]),
                            metadatas=[{"db": "mysql", "table": "DART_FIN",
                                        "row_id": f"{CORP_CODE}:{year}:{reprt}:{fs}"}],
                        )
                        indexed += 1
                        _touch_lock()
        print(f">>> 색인 완료: {indexed} 건(보고서×재무제표구분)")
    finally:
        conn.close()
        release_lock()
    print(">>> 완료")


if __name__ == "__main__":
    main()
