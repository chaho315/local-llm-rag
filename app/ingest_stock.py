"""주식 시세정보(공공데이터포털/금융위) 수집 → STOCK_PRICE 저장 → 임베딩 색인.

- getStockPriceInfo 엔드포인트만 사용. 전일자(영업일 폴백) 기준. 매일 09시 스케줄 상정.
- 전 종목을 DB에 저장하고, 시가총액 상위 STOCK_MAX_INDEX 개를 임베딩(저사양 박스 고려, 0=전체).
- 뉴스 수집기(app.ingest_rss)와 같은 lock 을 공유해 임베딩이 동시에 돌지 않도록 한다.

실행:  python -m app.ingest_stock
설정(.env): STOCK_API_KEY, STOCK_MAX_INDEX(기본 500), STOCK_LOOKBACK(기본 10),
           NEWS_WRITER_USER/PASSWORD (쓰기 계정 재사용)
"""
from __future__ import annotations

import datetime
import os
import ssl
import time

import httpx
import pymysql

from .indexer import get_store
from .ingest_rss import acquire_lock, release_lock, _touch_lock  # 공유 lock(뉴스와 동시 임베딩 방지)
from .ollama_client import embed
from .settings import mysql_env

SERVICE_KEY = os.getenv(
    "STOCK_API_KEY",
    "YOUR_STOCK_API_KEY",
)
API_URL = "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo"
PAGE = 1000
LOOKBACK = int(os.getenv("STOCK_LOOKBACK", "10"))
MAX_INDEX = int(os.getenv("STOCK_MAX_INDEX", "500"))   # 임베딩 상한(시총 상위). 0=전체
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _client() -> httpx.Client:
    try:
        import truststore  # 사내 SSL검사 프록시 대응(OS 신뢰저장소)
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


# --------------------------------------------------------------------------- #
#  공공데이터 API
# --------------------------------------------------------------------------- #
def _get_page(client: httpx.Client, bas_dt: str, page: int):
    r = client.get(API_URL, params={
        "serviceKey": SERVICE_KEY, "resultType": "json",
        "numOfRows": str(PAGE), "pageNo": str(page), "basDt": bas_dt,
    })
    r.raise_for_status()
    body = r.json()["response"]["body"]
    items = body.get("items") or {}
    item = items.get("item") if isinstance(items, dict) else None
    if item is None:
        item = []
    if isinstance(item, dict):
        item = [item]
    return int(body.get("totalCount", 0)), item


def fetch_day(client: httpx.Client, bas_dt: str) -> list[dict]:
    total, first = _get_page(client, bas_dt, 1)
    if total == 0:
        return []
    rows = list(first)
    pages = (total + PAGE - 1) // PAGE
    for p in range(2, pages + 1):
        _, more = _get_page(client, bas_dt, p)
        rows.extend(more)
        time.sleep(0.2)   # 초당 트랜잭션 여유
    return rows


def target_date(client: httpx.Client) -> str | None:
    """전일부터 소급하며 데이터가 존재하는 첫 영업일(YYYYMMDD) 반환."""
    for back in range(1, LOOKBACK + 1):
        d = (datetime.date.today() - datetime.timedelta(days=back)).strftime("%Y%m%d")
        total, _ = _get_page(client, d, 1)
        if total > 0:
            return d
    return None


# --------------------------------------------------------------------------- #
#  DB 저장
# --------------------------------------------------------------------------- #
def _i(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _f(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def upsert(conn, items: list[dict]) -> int:
    sql = (
        "INSERT INTO STOCK_PRICE "
        "(BAS_DT,SRTN_CD,ISIN_CD,ITMS_NM,MRKT_CTG,CLPR,VS,FLT_RT,MKP,HIPR,LOPR,TRQU,TR_PRC,LSTG_ST_CNT,MRKT_TOT_AMT,INDEXED_YN) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'N') "
        "ON DUPLICATE KEY UPDATE CLPR=VALUES(CLPR),VS=VALUES(VS),FLT_RT=VALUES(FLT_RT),"
        "MKP=VALUES(MKP),HIPR=VALUES(HIPR),LOPR=VALUES(LOPR),TRQU=VALUES(TRQU),"
        "TR_PRC=VALUES(TR_PRC),LSTG_ST_CNT=VALUES(LSTG_ST_CNT),MRKT_TOT_AMT=VALUES(MRKT_TOT_AMT),INDEXED_YN='N'"
    )
    n = 0
    with conn.cursor() as cur:
        for a in items:
            cur.execute(sql, (
                a.get("basDt"), a.get("srtnCd"), a.get("isinCd"),
                (a.get("itmsNm") or "")[:120], a.get("mrktCtg"),
                _i(a.get("clpr")), _i(a.get("vs")), _f(a.get("fltRt")),
                _i(a.get("mkp")), _i(a.get("hipr")), _i(a.get("lopr")),
                _i(a.get("trqu")), _i(a.get("trPrc")), _i(a.get("lstgStCnt")), _i(a.get("mrktTotAmt")),
            ))
            n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------- #
#  색인(임베딩)
# --------------------------------------------------------------------------- #
def _fmt(x):
    return f"{x:,}" if isinstance(x, int) else ("-" if x is None else str(x))


def _doc(r: dict) -> str:
    d = r["BAS_DT"]
    dt = f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and len(d) == 8 else d
    fr = r["FLT_RT"]
    return (
        f"{r['ITMS_NM']}({r['SRTN_CD']}, {r['MRKT_CTG']}) {dt} 주식 시세: "
        f"종가 {_fmt(r['CLPR'])}원, 전일대비 {_fmt(r['VS'])}원({fr if fr is not None else '-'}%), "
        f"시가 {_fmt(r['MKP'])}원, 고가 {_fmt(r['HIPR'])}원, 저가 {_fmt(r['LOPR'])}원, "
        f"거래량 {_fmt(r['TRQU'])}주, 거래대금 {_fmt(r['TR_PRC'])}원, "
        f"상장주식수 {_fmt(r['LSTG_ST_CNT'])}주, 시가총액 {_fmt(r['MRKT_TOT_AMT'])}원."
    )


def _mark(conn, keys: list[tuple]) -> None:
    if not keys:
        return
    with conn.cursor() as cur:
        cur.executemany("UPDATE STOCK_PRICE SET INDEXED_YN='Y' WHERE BAS_DT=%s AND SRTN_CD=%s", keys)
    conn.commit()


def index_unindexed(conn, batch: int = 50) -> int:
    """미색인 종목을 시가총액 상위부터 임베딩. 회사별 1벡터(id=단축코드)로 당일 데이터 갱신."""
    limit = f" ORDER BY MRKT_TOT_AMT IS NULL, MRKT_TOT_AMT DESC" + (f" LIMIT {MAX_INDEX}" if MAX_INDEX > 0 else "")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT BAS_DT,SRTN_CD,ISIN_CD,ITMS_NM,MRKT_CTG,CLPR,VS,FLT_RT,MKP,HIPR,LOPR,"
            "TRQU,TR_PRC,LSTG_ST_CNT,MRKT_TOT_AMT FROM STOCK_PRICE WHERE INDEXED_YN='N'" + limit
        )
        rows = cur.fetchall()
    conn.commit()
    if not rows:
        return 0
    store = get_store()
    total, done = 0, []
    for r in rows:
        doc = _doc(r)
        vid = f"mysql:STOCK_PRICE:{r['SRTN_CD']}"   # 회사별 1벡터(당일 데이터로 덮어씀 → 벡터 수 유지)
        store.upsert(
            ids=[vid], documents=[doc], embeddings=embed([doc]),
            metadatas=[{"db": "mysql", "table": "STOCK_PRICE", "row_id": f"{r['BAS_DT']}:{r['SRTN_CD']}"}],
        )
        done.append((r["BAS_DT"], r["SRTN_CD"]))
        total += 1
        if len(done) >= batch:
            _mark(conn, done)
            _touch_lock()
            print(f"    ...색인 {total}/{len(rows)}")
            done = []
    _mark(conn, done)
    return total


def main() -> None:
    if not acquire_lock():
        return
    conn = writer_conn()
    try:
        with _client() as client:
            bas_dt = target_date(client)
            if not bas_dt:
                print(">>> 최근 영업일 데이터를 찾지 못했습니다(주말/공휴일 연속 또는 API 오류).")
                return
            print(f">>> 기준일자(전일 영업일): {bas_dt}")
            # 멱등 가드: 해당 영업일이 이미 수집·색인돼 있으면 생략(로그온 따라잡기 트리거가
            # 여러 번 돌아도 최신이면 API 재호출/재색인 낭비 없이 즉시 종료).
            with conn.cursor() as _cur:
                _cur.execute("SELECT COUNT(*) FROM STOCK_PRICE WHERE BAS_DT=%s AND INDEXED_YN='Y'", (bas_dt,))
                if _cur.fetchone()[0] > 0:
                    print(f">>> {bas_dt} 는 이미 수집·색인 완료 — 실행 생략(최신 상태).")
                    return
            items = fetch_day(client, bas_dt)
            print(f">>> 수집 종목 수: {len(items)}")
            n = upsert(conn, items) if items else 0
            print(f">>> DB 저장/갱신: {n} 종목")
        idx = index_unindexed(conn)
        print(f">>> 임베딩 색인: {idx} 종목 (상한 {MAX_INDEX or '전체'})")
    finally:
        conn.close()
        release_lock()
    print(">>> 완료")


if __name__ == "__main__":
    main()
