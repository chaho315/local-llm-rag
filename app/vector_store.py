"""의존성 최소 벡터 저장소 (numpy + 내장 sqlite3).

chromadb 의 네이티브(Rust/DLL) 의존성을 피하려고 자체 구현했다.
- 벡터/문서/메타데이터를 SQLite 파일 하나에 저장
- 검색은 numpy 코사인 유사도(전량 로드 후 계산). 수만 건까지는 충분히 빠르며,
  그 이상 대용량이면 전용 벡터DB(sqlite-vec, Qdrant 등)로 교체를 권장.
- 스레드 안전을 위해 연산마다 커넥션을 새로 연다(FastAPI 스레드풀 대응).
"""
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
