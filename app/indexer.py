"""허용목록 테이블을 읽어 경량 벡터 저장소(VectorStore)에 색인한다.

동작:
  config.yaml 의 sources 에서 enabled=true 인 DB의 각 테이블을 읽고,
  text_columns 를 합쳐 문장으로 만든 뒤 chunk 로 나눠 임베딩→저장.
"""
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
    """대소문자 차이를 흡수하며 컬럼 값 조회 (Oracle 은 대문자 반환)."""
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

        # 임베딩은 32개씩 배치 처리
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
