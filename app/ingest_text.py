"""임의 텍스트 파일(.txt/.md)을 색인에 추가한다.

용도: '인터넷 데이터' 학습.
  폐쇄망에서는 인터넷이 안 되므로, 인터넷 되는 PC에서 웹 문서를
  .txt/.md 로 저장 → 승인된 매체로 반입 → 이 스크립트로 색인에 추가.

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
