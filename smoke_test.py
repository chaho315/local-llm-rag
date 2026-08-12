"""DB 없이 RAG 파이프라인 전체를 검증하는 스모크 테스트.

가짜 사내 FAQ 3건을 색인한 뒤 질문 → 검색 → 답변까지 실제로 돌려본다.
실행:  python smoke_test.py
"""
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
