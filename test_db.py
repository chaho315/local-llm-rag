"""MySQL(MMS_TEST_TB) → RAG 전체 흐름 테스트."""
from app.indexer import reindex_all
from app.rag import answer

print("INDEXED:", reindex_all())

questions = [
    "정산 주기가 어떻게 바뀌나요?",
    "MMS 발송이 실패하면 어떻게 처리하나요?",
    "신규 간편결제 프로모션 혜택이 뭐야?",
]
for q in questions:
    r = answer(q)
    print("\n" + "=" * 60)
    print("Q :", q)
    print("A :", r["answer"])
    print("출처:", [f"{s['table']}#{s['row_id']}" for s in r["sources"]])
