"""뉴스 RSS 다중 피드 수집 → 본문/요약 → DB(NEWS_RSS) → 신규만 임베딩 색인.

피드 목록: rag/rss_feeds.txt  (형식:  SOURCE|CATEGORY|SCRAPE|URL)
  - SCRAPE=1 : 기사 링크에 들어가 본문 스크래핑
  - SCRAPE=0 : 기사 페이지를 열지 않고 RSS 제공 요약(description)만 저장
              (개인 리더 용도 등 이용약관/저작권 고려가 필요한 매체에 권장)
  파일이 없으면 .env 의 RSS_URL 단일 피드로 동작.

동작: RSS(바이트 파싱, 인코딩선언 존중) → guid/link 로 전역 중복제거 →
      DB에 이미 있는 기사 건너뜀 → 신규만 본문/요약 확보 → 저장(INDEXED_YN='N') →
      미색인 행 임베딩 → 벡터스토어 upsert → 'Y' 갱신.

실행:  python -m app.ingest_rss   [단일RSS_URL]
설정(.env): RSS_MAX(회당 신규 상한, 기본 150), RSS_DELAY(스크래핑 지연초, 0.5),
           NEWS_WRITER_USER/PASSWORD, RSS_INSECURE, RSS_CA_BUNDLE

※ 뉴스 기사는 저작권이 있습니다. 사내 RAG 내부 활용에 한정하고 매체 약관을 준수하세요.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import httpx
import pymysql
from bs4 import BeautifulSoup

from .indexer import _chunk, get_store
from .ollama_client import embed
from .settings import BASE_DIR, RETRIEVAL, mysql_env

MAX_ARTICLES = int(os.getenv("RSS_MAX", "1000"))    # 한 회 전체 신규 상한(안전장치)
PER_FEED = int(os.getenv("RSS_PER_FEED", "50"))     # 피드당 신규 상한(피드 간 공평 분배)
MAX_CHUNKS_PER_DOC = int(os.getenv("RSS_MAX_CHUNKS", "6"))  # 기사당 임베딩 청크 상한(초대형 기사 독점 방지)
INDEX_MAX = int(os.getenv("RSS_INDEX_MAX", "0"))    # 회당 색인 상한(0=전체). 시간당=최신 N건만 빨리, 야간 백필=0(전량)
FETCH_DELAY = float(os.getenv("RSS_DELAY", "0.5"))  # 본문 스크래핑 시 요청 간 지연(초)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsRAGBot/1.0 (internal use)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
FEEDS_FILE = BASE_DIR / "rss_feeds.txt"


def _make_client() -> httpx.Client:
    """사내 SSL검사 프록시 대응: truststore 로 OS 신뢰저장소 사용(권장).
    RSS_CA_BUNDLE(사내 루트CA 경로) 또는 RSS_INSECURE=1(검증생략, 최후수단) 지원."""
    verify = True
    if os.getenv("RSS_INSECURE", "").lower() in ("1", "true", "yes"):
        verify = False
    elif os.getenv("RSS_CA_BUNDLE"):
        verify = os.getenv("RSS_CA_BUNDLE")
    else:
        try:
            import ssl
            import truststore
            verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            pass
    return httpx.Client(verify=verify, follow_redirects=True)


# --------------------------------------------------------------------------- #
#  단일 인스턴스 lock (수동 실행 + 시간당 스케줄 동시 실행 방지)
# --------------------------------------------------------------------------- #
LOCK_FILE = BASE_DIR / "ingest_rss.lock"
LOCK_STALE = 600   # 초: 이 시간 이상 갱신 안 된 lock 은 죽은 프로세스로 간주하고 무시


def _touch_lock() -> None:
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def acquire_lock() -> bool:
    """다른 수집 인스턴스가 실행 중이면 False. (락 파일 mtime 기반, 실행 중 주기적으로 갱신)"""
    if LOCK_FILE.exists():
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
        except OSError:
            age = 1e9
        if age < LOCK_STALE:
            print(f">>> 다른 수집 인스턴스가 실행 중입니다(lock {int(age)}초 전 갱신). 이번 실행을 건너뜁니다.")
            return False
        print(f">>> 오래된 lock({int(age)}초, 죽은 프로세스로 추정) 무시하고 진행합니다.")
    _touch_lock()
    return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  피드 목록
# --------------------------------------------------------------------------- #
def load_feeds() -> list[dict]:
    feeds: list[dict] = []
    if FEEDS_FILE.exists():
        for line in FEEDS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|", 3)]
            if len(parts) < 4:
                continue
            source, category, scrape, url = parts
            feeds.append({
                "source": source, "category": category,
                "scrape": scrape.lower() in ("1", "true", "y", "yes"),
                "url": url,
            })
    else:
        feeds.append({
            "source": "RSS", "category": "", "scrape": True,
            "url": os.getenv("RSS_URL", "http://rss.edaily.co.kr/edaily_news.xml"),
        })
    return feeds


def _news_id(guid: str, link: str) -> str:
    """안정적 고유 ID. guid(≤64) 우선, 없거나 길면 link 의 sha1."""
    v = (guid or link or "").strip()
    if v and len(v) <= 64:
        return v
    return hashlib.sha1(v.encode("utf-8")).hexdigest() if v else ""


def parse_rss(content: bytes, feed: dict) -> list[dict]:
    """RSS 바이트 → item 목록. 바이트로 파싱해 EUC-KR 등 인코딩 선언을 존중한다."""
    root = ET.fromstring(content)
    items, seen = [], set()
    for it in root.iterfind(".//item"):
        def _t(tag: str) -> str:
            el = it.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        nid = _news_id(_t("guid"), _t("link"))
        if not nid or nid in seen:
            continue
        seen.add(nid)
        # 카테고리 분류: 큐레이션된 카테고리 피드는 피드 라벨 우선,
        # '전체' 피드는 기사별 RSS <category> 우선 사용
        fcat = feed["category"]
        category = fcat if (fcat and fcat != "전체") else (_t("category") or fcat)
        items.append({
            "news_id": nid, "title": _t("title"), "link": _t("link"),
            "category": category, "author": _t("author"),
            "pub_date": _t("pubDate"), "summary": _t("description"), "source": feed["source"],
        })
    return items


# --------------------------------------------------------------------------- #
#  기사 본문 스크래핑 (범용)
# --------------------------------------------------------------------------- #
def scrape_article(client: httpx.Client, url: str) -> str:
    try:
        resp = client.get(url, headers={"User-Agent": UA}, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"      [경고] 본문 요청 실패: {type(e).__name__} {str(e)[:50]}")
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    node = (soup.find(attrs={"itemprop": "articleBody"})
            or soup.find(class_="news_body")
            or soup.find(class_="article_body")
            or soup.find(id="article_content")
            or soup.find("article"))
    if node:
        for tag in node(["script", "style"]):
            tag.decompose()
        text = node.get_text("\n", strip=True)
    else:
        meta = soup.find("meta", attrs={"property": "og:description"})
        text = meta.get("content", "") if meta else ""
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text


# --------------------------------------------------------------------------- #
#  DB
# --------------------------------------------------------------------------- #
def writer_conn():
    env = mysql_env()
    return pymysql.connect(
        host=env["host"], port=env["port"],
        user=os.getenv("NEWS_WRITER_USER", "newswriter"),
        password=os.getenv("NEWS_WRITER_PASSWORD", "CHANGE_ME_PASSWORD"),
        database=env["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def existing_ids(conn, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    ph = ",".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        cur.execute(f"SELECT NEWS_ID FROM NEWS_RSS WHERE NEWS_ID IN ({ph})", ids)
        return {r["NEWS_ID"] for r in cur.fetchall()}


def insert_articles(conn, articles: list[dict]) -> int:
    sql = (
        "INSERT IGNORE INTO NEWS_RSS "
        "(NEWS_ID, SOURCE, TITLE, LINK, CATEGORY, AUTHOR, PUB_DATE, SUMMARY, CONTENT, INDEXED_YN) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'N')"
    )
    n = 0
    with conn.cursor() as cur:
        for a in articles:
            cur.execute(sql, (
                a["news_id"], a.get("source", "")[:100], a["title"][:500], a["link"][:1000],
                a["category"][:100], a["author"][:100], a["pub_date"][:64],
                a["summary"], a.get("content", ""),
            ))
            n += cur.rowcount
    conn.commit()
    return n


def _mark_indexed(conn, ids: list[str]) -> None:
    if not ids:
        return
    ph = ",".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        cur.execute(f"UPDATE NEWS_RSS SET INDEXED_YN='Y' WHERE NEWS_ID IN ({ph})", ids)
    conn.commit()


def index_unindexed(conn, batch: int = 25) -> int:
    """미색인 행을 임베딩. batch 건마다 커밋해 진행을 저장(중단 시 재개 가능,
    긴 트랜잭션/커넥션 idle 방지 → 동시 실행 hang 증상 예방)."""
    with conn.cursor() as cur:
        # PUB_DATE 가 varchar(RFC822)라 날짜정렬 불가 → 상한(LIMIT)만 적용.
        # 시간당 실행은 INDEX_MAX(예:300)로 빨리 끝내 lock 을 풀고, 야간 백필이 0(전량)으로 나머지를 소진.
        _lim = f" LIMIT {INDEX_MAX}" if INDEX_MAX > 0 else ""
        cur.execute("SELECT NEWS_ID, TITLE, SUMMARY, CONTENT FROM NEWS_RSS WHERE INDEXED_YN='N'" + _lim)
        rows = cur.fetchall()
    conn.commit()   # SELECT 스냅샷 트랜잭션 즉시 종료 (임베딩 동안 트랜잭션 유지 안 함)
    if not rows:
        return 0
    store = get_store()
    size, overlap = RETRIEVAL["chunk_size"], RETRIEVAL["chunk_overlap"]
    total = 0
    done: list[str] = []
    for r in rows:
        body = r["CONTENT"] or r["SUMMARY"] or ""
        text = f"제목: {r['TITLE']}\n{body}".strip()
        chunks = _chunk(text, size, overlap)[:MAX_CHUNKS_PER_DOC]   # 기사당 청크 상한
        if chunks:
            ids = [f"mysql:NEWS_RSS:{r['NEWS_ID']}:{j}" for j in range(len(chunks))]
            metas = [{"db": "mysql", "table": "NEWS_RSS", "row_id": r["NEWS_ID"]} for _ in chunks]
            for k in range(0, len(chunks), 32):
                store.upsert(ids=ids[k:k+32], documents=chunks[k:k+32],
                             embeddings=embed(chunks[k:k+32]), metadatas=metas[k:k+32])
        done.append(r["NEWS_ID"])
        total += 1
        if len(done) >= batch:      # 진행 저장(배치 커밋)
            _mark_indexed(conn, done)
            _touch_lock()           # 임베딩 장시간 동안 lock 신선도 유지(동시 실행 방지)
            print(f"    ...색인 {total}/{len(rows)}")
            done = []
    _mark_indexed(conn, done)
    return total


# --------------------------------------------------------------------------- #
#  메인
# --------------------------------------------------------------------------- #
def main() -> None:
    # 색인 전용 모드: 피드 수집 없이 미색인(INDEXED_YN='N') 백로그만 임베딩
    if len(sys.argv) > 1 and sys.argv[1] in ("--index-only", "index"):
        if not acquire_lock():
            return
        conn = writer_conn()
        try:
            print(">>> 백로그 임베딩 전용 모드 (피드 수집 생략)")
            n = index_unindexed(conn)
            print(f">>> 완료: 신규 색인 {n} 건")
        finally:
            conn.close()
            release_lock()
        return

    if len(sys.argv) > 1:  # 단일 URL 직접 지정 시
        feeds = [{"source": "RSS", "category": "", "scrape": True, "url": sys.argv[1]}]
    else:
        feeds = load_feeds()
    if not acquire_lock():
        return
    print(f">>> 피드 {len(feeds)}개 수집 시작 (회당 신규 상한 {MAX_ARTICLES}, 피드당 {PER_FEED})")

    conn = writer_conn()
    try:
        with _make_client() as client:
            total = 0
            for f in feeds:
                _touch_lock()   # 긴 실행 동안 lock 신선도 유지
                if total >= MAX_ARTICLES:
                    print("  (전체 신규 상한 도달 — 나머지는 다음 회차에)")
                    break
                try:
                    r = client.get(f["url"], headers={"User-Agent": UA}, timeout=_TIMEOUT)
                    r.raise_for_status()
                    items = parse_rss(r.content, f)
                except Exception as e:
                    print(f"  [피드 실패] {f['source']}/{f['category']}: {type(e).__name__} {str(e)[:60]}")
                    continue

                have = existing_ids(conn, [i["news_id"] for i in items])
                room = min(PER_FEED, MAX_ARTICLES - total)   # 피드당 상한 + 전체 안전장치
                new_items = [i for i in items if i["news_id"] not in have][:room]
                mode = "본문" if f["scrape"] else "요약"
                print(f"  [{f['source']}/{f['category']}] 전체 {len(items)} · 신규 {len(new_items)} ({mode})")

                for idx, a in enumerate(new_items, 1):
                    if f["scrape"]:
                        a["content"] = scrape_article(client, a["link"])
                        if idx < len(new_items):
                            time.sleep(FETCH_DELAY)
                    else:
                        a["content"] = ""   # RSS 요약(summary)만 색인
                if new_items:
                    ins = insert_articles(conn, new_items)
                    total += ins

        indexed = index_unindexed(conn)
        print(f">>> 임베딩 색인(신규): {indexed} 건")
    finally:
        conn.close()
        release_lock()
    print(">>> 완료")


if __name__ == "__main__":
    main()
