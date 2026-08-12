#!/usr/bin/env bash
# =============================================================================
#  사내 RAG 챗봇 - Rocky Linux 8.10 재현 설치 스크립트
#  (Windows에서 구성한 것과 동일: Ollama + Qwen3-4B + Qwen3-Embedding + RAG앱)
#
#  실행 방법:
#     chmod +x setup_rocky_linux.sh
#     ./setup_rocky_linux.sh
#
#  요구 사항:
#     - sudo 권한이 있는 일반 사용자로 실행 (root 아님)
#     - 아래 도메인 접근 가능: ollama.com, github.com, modelscope.cn, pypi.org, dnf repo
#       (huggingface.co / registry.ollama.ai 는 차단돼 있어도 됨 → ModelScope 사용)
#
#  ※ 이 스크립트는 Windows에서 검증한 구성을 리눅스로 '번역'한 것입니다.
#    Rocky Linux 실서버에서 실행해 주세요.
#  ※ 만약 실행 중 '\r' 관련 오류가 나면 (윈도우 줄바꿈 때문):
#       sed -i 's/\r$//' setup_rocky_linux.sh
# =============================================================================
set -eo pipefail

# ---- 설치 위치 (원하면 BASE_DIR 환경변수로 변경 가능) ----
BASE_DIR="${BASE_DIR:-$HOME/llm}"
MODELS="$BASE_DIR/models"
MF="$BASE_DIR/modelfiles"
RAG="$BASE_DIR/rag"
MS="https://modelscope.cn/models"

echo "==================================================================="
echo " 설치 위치 : $BASE_DIR"
echo "==================================================================="

# =============================================================================
# [0] 시스템 정보 (참고용)
# =============================================================================
echo "[0] 시스템 확인"
echo "  - CPU cores : $(nproc)"
echo "  - RAM       : $(free -h | awk '/Mem:/{print $2}')"
echo "  - OS        : $(source /etc/os-release; echo "$PRETTY_NAME")"

# =============================================================================
# [1] Ollama 설치 (systemd 서비스로 등록됨, localhost:11434)
# =============================================================================
echo "[1] Ollama 설치"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "  - 이미 설치됨: $(ollama --version 2>/dev/null || true)"
fi

# 서비스 기동 대기
sudo systemctl enable --now ollama 2>/dev/null || true
echo -n "  - Ollama 서버 대기"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then echo " ... OK"; break; fi
  echo -n "."; sleep 1
done

# =============================================================================
# [2] 폴더 생성
# =============================================================================
echo "[2] 폴더 생성"
mkdir -p "$MODELS" "$MF" "$RAG/app"

# =============================================================================
# [3] 모델 다운로드 (ModelScope - HF/Ollama레지스트리 차단 우회)
#     채팅 : Qwen3-4B-Q4_K_M.gguf     (~2.4GB)
#     임베딩: Qwen3-Embedding-0.6B-Q8_0.gguf (~610MB)
# =============================================================================
echo "[3] 모델 다운로드 (ModelScope)"
curl -L --fail --retry 3 --retry-delay 3 -C - \
  -o "$MODELS/Qwen3-4B-Q4_K_M.gguf" \
  "$MS/Qwen/Qwen3-4B-GGUF/resolve/master/Qwen3-4B-Q4_K_M.gguf"
curl -L --fail --retry 3 --retry-delay 3 -C - \
  -o "$MODELS/Qwen3-Embedding-0.6B-Q8_0.gguf" \
  "$MS/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/master/Qwen3-Embedding-0.6B-Q8_0.gguf"
ls -lh "$MODELS"

# =============================================================================
# [4] Modelfile 작성 + Ollama에 등록
#     ※ ollama create 가 GGUF 읽기 권한 오류를 내면:
#        chmod 755 "$HOME"   또는  모델을 /opt/llm/models(공용 읽기)로 이동
# =============================================================================
echo "[4] 모델 등록 (ollama create)"

# (Modelfile 은 절대경로 확장이 필요하므로 따옴표 없는 heredoc 사용)
cat > "$MF/qwen3-4b.Modelfile" <<EOF
FROM ${MODELS}/Qwen3-4B-Q4_K_M.gguf

# 컨텍스트 길이: RAG 검색결과+질문+답변 담을 여유. RAM 여건 고려해 8192.
PARAMETER num_ctx 8192

# Qwen3 권장 샘플링 (non-thinking 기준)
PARAMETER temperature 0.7
PARAMETER top_p 0.8
PARAMETER top_k 20
PARAMETER repeat_penalty 1.05
EOF

cat > "$MF/qwen3-embedding.Modelfile" <<EOF
FROM ${MODELS}/Qwen3-Embedding-0.6B-Q8_0.gguf
EOF

ollama create qwen3-4b        -f "$MF/qwen3-4b.Modelfile"
ollama create qwen3-embedding -f "$MF/qwen3-embedding.Modelfile"
ollama list

# =============================================================================
# [5] 모델 동작 간단 테스트 (실패해도 계속 진행)
# =============================================================================
echo "[5] 모델 테스트"
curl -fsS http://localhost:11434/api/embed \
  -d '{"model":"qwen3-embedding","input":"테스트 문장"}' \
  | head -c 120 || true
echo
curl -fsS http://localhost:11434/api/generate \
  -d '{"model":"qwen3-4b","prompt":"한 문장으로 자기소개해줘.","stream":false,"think":false,"options":{"num_predict":40}}' \
  || true
echo

# =============================================================================
# [6] Python 3.12 설치 + 가상환경
# =============================================================================
echo "[6] Python 3.12 설치"
sudo dnf install -y python3.12
python3.12 --version

# =============================================================================
# [7] 앱 소스 작성
# =============================================================================
echo "[7] 앱 소스 작성"

# ---- requirements.txt ----
cat > "$RAG/requirements.txt" <<'EOF'
# --- HTTP API (사내 프로그램이 호출할 챗봇 서버) ---
fastapi
uvicorn[standard]

# --- 설정/유틸 ---
pydantic
pydantic-settings
pyyaml
httpx

# --- DB 커넥터 ---
oracledb          # Oracle. thin 모드 = Oracle Instant Client 설치 불필요(순수 파이썬)
pymysql           # MySQL

# --- 벡터 검색 (RAG 색인 저장; 네이티브 의존성 없는 경량 구성) ---
numpy

# --- MCP 서버 (Oracle/MySQL 도구 노출) ---
mcp[cli]
EOF

# ---- config.yaml ----
cat > "$RAG/config.yaml" <<'EOF'
# =========================================================
#  사내 RAG 챗봇 설정
#  ★ 민감정보(개인정보/결제정보)가 없는 테이블/뷰만 등록하세요.
#  ★ DB 접속 비밀번호 등은 여기 두지 말고 .env 파일에 두세요.
# =========================================================

ollama:
  base_url: "http://localhost:11434"
  chat_model: "qwen3-4b"
  embedding_model: "qwen3-embedding"
  num_ctx: 8192
  think: false          # Qwen3 사고(thinking) 모드 off → CPU 속도 우선

retrieval:
  top_k: 5              # 질문당 가져올 문서 조각 수
  chunk_size: 800       # 텍스트 조각 최대 글자 수
  chunk_overlap: 100

vector_store:
  path: "./vectorstore.db"   # 벡터 저장 파일 (rag/ 기준 상대경로, SQLite)
  collection: "company_kb"

# ---------------------------------------------------------
#  DB별 색인 대상 (★ 민감정보 없는 테이블/뷰만 ★)
#    table        : 대상 테이블/뷰 이름
#    id_column    : 각 행의 고유 식별자 컬럼
#    text_columns : 임베딩할 텍스트 컬럼들 (딱 이 컬럼들만 읽습니다)
#    where        : (선택) 추가 조건. 없으면 null
# ---------------------------------------------------------
sources:
  oracle:
    enabled: false          # DB 준비되면 true 로 변경
    tables:
      - table: "KB_FAQ"
        id_column: "FAQ_ID"
        text_columns: ["TITLE", "CONTENT"]
        where: null

  mysql:
    enabled: false
    tables:
      - table: "notice"
        id_column: "id"
        text_columns: ["title", "body"]
        where: null
EOF

# ---- .env.example ----
cat > "$RAG/.env.example" <<'EOF'
# 이 파일을 복사해서 ".env" 로 저장한 뒤 실제 값을 입력하세요.
# .env 는 접속정보가 담기므로 외부에 올리지 마세요.

# --- Oracle (반드시 읽기전용 계정 권장) ---
ORACLE_USER=readonly_user
ORACLE_PASSWORD=change-me
ORACLE_DSN=10.0.0.10:1521/ORCLPDB1

# --- MySQL (반드시 읽기전용 계정 권장) ---
MYSQL_HOST=10.0.0.20
MYSQL_PORT=3306
MYSQL_USER=readonly_user
MYSQL_PASSWORD=change-me
MYSQL_DATABASE=company_db
EOF

# ---- app/__init__.py ----
cat > "$RAG/app/__init__.py" <<'EOF'
# 사내 RAG 챗봇 애플리케이션 패키지
EOF

# ---- app/settings.py ----
cat > "$RAG/app/settings.py" <<'EOF'
"""config.yaml + .env 를 읽어 설정값을 제공한다."""
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
EOF

# ---- app/ollama_client.py ----
cat > "$RAG/app/ollama_client.py" <<'EOF'
"""Ollama 호출 헬퍼 (임베딩 + 채팅). httpx 가 UTF-8로 전송 → 한글 안전."""
from __future__ import annotations

import httpx

from .settings import OLLAMA

_BASE = OLLAMA["base_url"].rstrip("/")
_TIMEOUT = httpx.Timeout(600.0, connect=10.0)


def embed(texts: list[str]) -> list[list[float]]:
    """여러 문장을 임베딩. Qwen3-Embedding → 문장당 1024차원 벡터."""
    resp = httpx.post(
        f"{_BASE}/api/embed",
        json={"model": OLLAMA["embedding_model"], "input": texts},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def chat(prompt: str, system: str | None = None) -> str:
    """단일 프롬프트로 생성. 응답 문자열을 반환."""
    body = {
        "model": OLLAMA["chat_model"],
        "prompt": prompt,
        "stream": False,
        "think": OLLAMA.get("think", False),
        "options": {"num_ctx": OLLAMA.get("num_ctx", 8192)},
    }
    if system:
        body["system"] = system
    resp = httpx.post(f"{_BASE}/api/generate", json=body, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["response"]
EOF

# ---- app/db.py ----
cat > "$RAG/app/db.py" <<'EOF'
"""Oracle / MySQL 읽기전용 접근 계층.

보안장치: ①SELECT만 허용 ②허용목록 테이블만 ③주입 토큰 차단.
그래도 DB 계정 자체를 '읽기전용'으로 만드는 것이 가장 확실합니다.
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
        return list(rows)
    finally:
        conn.close()
EOF

# ---- app/vector_store.py ----
cat > "$RAG/app/vector_store.py" <<'EOF'
"""의존성 최소 벡터 저장소 (numpy + 내장 sqlite3)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np


class VectorStore:
    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS docs ("
                "id TEXT PRIMARY KEY, document TEXT, metadata TEXT, embedding BLOB)"
            )
            c.commit()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert(self, ids, documents, embeddings, metadatas) -> None:
        rows = []
        for i, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            vec = np.asarray(emb, dtype=np.float32).tobytes()
            rows.append((i, doc, json.dumps(meta, ensure_ascii=False), vec))
        with closing(self._conn()) as c:
            c.executemany(
                "INSERT INTO docs(id, document, metadata, embedding) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "document=excluded.document, metadata=excluded.metadata, "
                "embedding=excluded.embedding",
                rows,
            )
            c.commit()

    def query(self, embedding, n_results: int = 5) -> dict:
        with closing(self._conn()) as c:
            data = c.execute(
                "SELECT id, document, metadata, embedding FROM docs"
            ).fetchall()
        if not data:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        ids = [r[0] for r in data]
        docs = [r[1] for r in data]
        metas = [json.loads(r[2]) for r in data]
        mat = np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in data])

        q = np.asarray(embedding, dtype=np.float32)
        mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
        q_n = q / (np.linalg.norm(q) + 1e-9)
        sims = mat_n @ q_n
        top = np.argsort(-sims)[:n_results]
        return {
            "ids": [ids[j] for j in top],
            "documents": [docs[j] for j in top],
            "metadatas": [metas[j] for j in top],
            "distances": [float(1.0 - sims[j]) for j in top],
        }

    def count(self) -> int:
        with closing(self._conn()) as c:
            return c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
EOF

# ---- app/indexer.py ----
cat > "$RAG/app/indexer.py" <<'EOF'
"""허용목록 테이블을 읽어 경량 벡터 저장소(VectorStore)에 색인한다."""
from __future__ import annotations

from . import db as dbmod
from .ollama_client import embed
from .settings import BASE_DIR, RETRIEVAL, SOURCES, VECTOR
from .vector_store import VectorStore

_STORE: VectorStore | None = None


def get_store() -> VectorStore:
    global _STORE
    if _STORE is None:
        _STORE = VectorStore(str((BASE_DIR / VECTOR["path"]).resolve()))
    return _STORE


def _chunk(text: str, size: int, overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out, i = [], 0
    step = max(1, size - overlap)
    while i < len(text):
        out.append(text[i : i + size])
        i += step
    return out


def _get(row: dict, col: str):
    """대소문자 차이를 흡수 (Oracle 은 대문자 반환)."""
    if col in row:
        return row[col]
    return row.get(col.upper(), row.get(col.lower()))


def index_db(db_kind: str) -> int:
    conf = SOURCES.get(db_kind, {}) or {}
    if not conf.get("enabled"):
        return 0

    store = get_store()
    size, overlap = RETRIEVAL["chunk_size"], RETRIEVAL["chunk_overlap"]
    total = 0

    for t in conf.get("tables", []):
        table, idcol, textcols = t["table"], t["id_column"], t["text_columns"]
        dbmod.assert_table_allowed(db_kind, table)

        select_cols = ", ".join([idcol] + textcols)
        where = f" WHERE {t['where']}" if t.get("where") else ""
        sql = f"SELECT {select_cols} FROM {table}{where}"
        rows = dbmod.run_select(db_kind, sql, limit=1_000_000)

        docs, ids, metas = [], [], []
        for row in rows:
            rid = str(_get(row, idcol))
            parts = [f"{c}: {_get(row, c)}" for c in textcols if _get(row, c)]
            text = "\n".join(parts)
            for j, ch in enumerate(_chunk(text, size, overlap)):
                docs.append(ch)
                ids.append(f"{db_kind}:{table}:{rid}:{j}")
                metas.append({"db": db_kind, "table": table, "row_id": rid})

        for k in range(0, len(docs), 32):
            batch = docs[k : k + 32]
            store.upsert(
                ids=ids[k : k + 32],
                documents=batch,
                embeddings=embed(batch),
                metadatas=metas[k : k + 32],
            )
            total += len(batch)

    return total


def reindex_all() -> dict:
    """활성화된 모든 DB를 다시 색인. 반환: {'oracle': n, 'mysql': m}"""
    return {kind: index_db(kind) for kind in ("oracle", "mysql")}
EOF

# ---- app/rag.py ----
cat > "$RAG/app/rag.py" <<'EOF'
"""RAG 파이프라인: 질문 임베딩 → 벡터검색 → 프롬프트 구성 → 답변 생성."""
from __future__ import annotations

from .indexer import get_store
from .ollama_client import chat, embed
from .settings import RETRIEVAL

SYSTEM = (
    "너는 KG그룹 사내 업무를 돕는 한국어 어시스턴트다. "
    "아래 '참고자료'의 내용만 근거로 정확하게 답하라. "
    "자료에 없는 내용은 모른다고 답하고 추측하지 마라. "
    "답변 마지막에 사용한 자료의 출처(표/ID)를 간단히 밝혀라."
)


def retrieve(query: str, top_k: int | None = None):
    k = top_k or RETRIEVAL["top_k"]
    qvec = embed([query])[0]
    res = get_store().query(qvec, n_results=k)
    return list(zip(res["documents"], res["metadatas"]))


def answer(query: str, top_k: int | None = None) -> dict:
    hits = retrieve(query, top_k)
    if not hits:
        return {"answer": "관련 자료를 찾지 못했습니다.", "sources": []}

    context = "\n\n".join(
        f"[출처 {i + 1}] {m.get('table')}#{m.get('row_id')}\n{d}"
        for i, (d, m) in enumerate(hits)
    )
    prompt = f"참고자료:\n{context}\n\n질문: {query}\n\n답변:"
    text = chat(prompt, system=SYSTEM)
    sources = [
        {"db": m.get("db"), "table": m.get("table"), "row_id": m.get("row_id")}
        for _, m in hits
    ]
    return {"answer": text, "sources": sources}
EOF

# ---- app/api.py ----
cat > "$RAG/app/api.py" <<'EOF'
"""사내 프로그램이 호출할 챗봇 HTTP API (FastAPI).

실행:  uvicorn app.api:app --host 127.0.0.1 --port 8000
문서:  http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .indexer import reindex_all
from .rag import answer

app = FastAPI(title="사내 RAG 챗봇 API", version="1.0")


class ChatRequest(BaseModel):
    message: str
    top_k: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest) -> dict:
    return answer(req.message, req.top_k)


@app.post("/reindex")
def reindex_endpoint() -> dict:
    return {"indexed": reindex_all()}
EOF

# ---- app/ingest_text.py ----
cat > "$RAG/app/ingest_text.py" <<'EOF'
"""임의 텍스트 파일(.txt/.md)을 색인에 추가. (인터넷/외부 문서 학습용)

실행:  python -m app.ingest_text  <폴더경로>
"""
from __future__ import annotations

import sys
from pathlib import Path

from .indexer import _chunk, get_store
from .ollama_client import embed
from .settings import RETRIEVAL


def ingest(folder: str) -> int:
    store = get_store()
    root = Path(folder)
    files = list(root.rglob("*.txt")) + list(root.rglob("*.md"))
    total = 0
    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        chunks = _chunk(text, RETRIEVAL["chunk_size"], RETRIEVAL["chunk_overlap"])
        if not chunks:
            continue
        ids = [f"file:{fp.name}:{i}" for i in range(len(chunks))]
        metas = [{"db": "file", "table": fp.name, "row_id": str(i)} for i in range(len(chunks))]
        store.upsert(ids=ids, documents=chunks, embeddings=embed(chunks), metadatas=metas)
        total += len(chunks)
    return total


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "./docs_ingest"
    print(f"ingested chunks: {ingest(target)}")
EOF

# ---- db_mcp.py ----
cat > "$RAG/db_mcp.py" <<'EOF'
"""읽기전용 DB MCP 서버 (Oracle + MySQL). 허용목록 테이블만 접근.

실행:  python db_mcp.py     (stdio 전송)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app import db as dbmod

mcp = FastMCP("company-db")


@mcp.tool()
def list_allowed_tables(db: str) -> list[str]:
    """조회 가능한(허용된) 테이블 목록. db 는 'oracle' 또는 'mysql'."""
    return sorted(dbmod._allowed_tables(db))


@mcp.tool()
def describe_table(db: str, table: str) -> list[dict]:
    """허용된 테이블의 컬럼 구조(이름/타입)를 반환."""
    dbmod.assert_table_allowed(db, table)
    if db == "oracle":
        sql = ("SELECT column_name, data_type FROM user_tab_columns "
               "WHERE table_name = :1 ORDER BY column_id")
        return dbmod.run_select("oracle", sql, [table.upper()])
    sql = ("SELECT column_name, data_type FROM information_schema.columns "
           "WHERE table_name = %s ORDER BY ordinal_position")
    return dbmod.run_select("mysql", sql, (table,))


@mcp.tool()
def query(db: str, table: str, columns: str = "*", where: str = "", limit: int = 50) -> list[dict]:
    """허용된 단일 테이블에서 읽기전용 SELECT."""
    dbmod.assert_table_allowed(db, table)
    dbmod.assert_safe_fragment(columns)
    dbmod.assert_safe_fragment(where)
    limit = max(1, min(int(limit), 500))
    where_sql = f" WHERE {where}" if where else ""
    sql = f"SELECT {columns} FROM {table}{where_sql}"
    return dbmod.run_select(db, sql, limit=limit)


if __name__ == "__main__":
    mcp.run()
EOF

# ---- smoke_test.py ----
cat > "$RAG/smoke_test.py" <<'EOF'
"""DB 없이 RAG 파이프라인 전체를 검증하는 스모크 테스트."""
from app.indexer import get_store
from app.ollama_client import embed
from app.rag import answer

DOCS = [
    "연차 휴가는 입사 1년차에 15일이 부여되며, 이후 매 2년마다 1일씩 늘어난다.",
    "사내 와이파이 비밀번호는 IT팀 그룹웨어 공지사항에서 확인할 수 있다.",
    "법인카드 사용 후에는 7일 이내에 그룹웨어에서 지출결의를 등록해야 한다.",
]


def main() -> None:
    store = get_store()
    ids = [f"test:{i}" for i in range(len(DOCS))]
    metas = [{"db": "test", "table": "HR_FAQ", "row_id": str(i)} for i in range(len(DOCS))]
    store.upsert(ids=ids, documents=DOCS, embeddings=embed(DOCS), metadatas=metas)
    print(">> 색인 완료:", len(DOCS), "건")

    q = "연차 휴가 며칠 받나요?"
    print(">> 질문:", q)
    r = answer(q)
    print(">> 답변:", r["answer"])
    print(">> 출처:", r["sources"])


if __name__ == "__main__":
    main()
EOF

# ---- 실행 스크립트 (.sh) ----
cat > "$RAG/start_api.sh" <<'EOF'
#!/usr/bin/env bash
# 사내 챗봇 API 서버 실행 (http://127.0.0.1:8000, 문서: /docs)
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
EOF

cat > "$RAG/reindex.sh" <<'EOF'
#!/usr/bin/env bash
# DB를 다시 읽어 벡터 색인 갱신
cd "$(dirname "$0")"
exec .venv/bin/python -c "from app.indexer import reindex_all; print(reindex_all())"
EOF

cat > "$RAG/start_mcp.sh" <<'EOF'
#!/usr/bin/env bash
# 읽기전용 DB MCP 서버 실행 (stdio)
cd "$(dirname "$0")"
exec .venv/bin/python db_mcp.py
EOF

chmod +x "$RAG/start_api.sh" "$RAG/reindex.sh" "$RAG/start_mcp.sh"

# =============================================================================
# [8] 가상환경 + 의존성 설치
# =============================================================================
echo "[8] 가상환경 + 의존성 설치"
python3.12 -m venv "$RAG/.venv"
"$RAG/.venv/bin/python" -m pip install --upgrade pip
"$RAG/.venv/bin/python" -m pip install -r "$RAG/requirements.txt"

# =============================================================================
# [9] 스모크 테스트 (DB 없이 RAG 전체 검증)
# =============================================================================
echo "[9] 스모크 테스트"
cd "$RAG"
PYTHONUTF8=1 "$RAG/.venv/bin/python" smoke_test.py

# =============================================================================
#  완료
# =============================================================================
cat <<EOF

===================================================================
 ✅ 설치 완료
===================================================================
 설치 위치 : $BASE_DIR

 다음 단계 (DB 연동):
   1) cp "$RAG/.env.example" "$RAG/.env"   후 접속정보 입력 (읽기전용 계정)
   2) $RAG/config.yaml 에 '비민감' 테이블 등록 + enabled: true
   3) $RAG/reindex.sh          # 색인 생성
   4) $RAG/start_api.sh        # API 서버 시작 → http://127.0.0.1:8000/docs

 원격 접속이 필요하면 방화벽 개방(예):
   sudo firewall-cmd --add-port=8000/tcp --permanent && sudo firewall-cmd --reload
   (단, 외부 노출 시 인증/프록시를 반드시 추가하세요)
===================================================================
EOF
