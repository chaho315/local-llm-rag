"""사내 프로그램이 호출할 챗봇 HTTP API (FastAPI).

실행:  uvicorn app.api:app --host 127.0.0.1 --port 8000
문서:  http://127.0.0.1:8000/docs  (Swagger UI 자동 생성)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .indexer import reindex_all
from .ollama_client import chat as _warm_chat
from .rag import answer, answer_stream

app = FastAPI(title="사내 RAG 챗봇 API", version="1.0")

# 로컬/사내망 페이지가 API를 호출할 수 있도록 CORS 허용 (내부 전용)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_WEB_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def home() -> FileResponse:
    """사용자용 챗봇 웹 UI 페이지."""
    return FileResponse(_WEB_DIR / "index.html")


@app.on_event("startup")
def _warmup_model() -> None:
    """서버 기동 직후 채팅 모델을 백그라운드로 미리 로드(첫 질문의 콜드 로딩 지연 제거).

    별도 스레드에서 돌려 서버 起動(요청 수신)을 막지 않는다. keep_alive 설정으로
    로드된 모델이 메모리에 유지된다.
    """
    def _run() -> None:
        try:
            _warm_chat("준비 확인")
        except Exception:
            pass  # 워밍업 실패는 무시(다음 실제 질문에서 로드)

    threading.Thread(target=_run, daemon=True).start()


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
    """사용자 질문을 받아 RAG 답변을 반환(비스트리밍, 호환용)."""
    return answer(req.message, req.top_k)


@app.post("/chat/stream")
def chat_stream_endpoint(req: ChatRequest) -> StreamingResponse:
    """스트리밍 RAG 답변(NDJSON). 한 줄에 이벤트 1개:
      {"type":"sources","sources":[...]}  # 출처(먼저 1회)
      {"type":"token","text":"..."}       # 생성 토큰(여러 번)
      {"type":"done"}                      # 종료
      {"type":"error","message":"..."}     # 오류
    """
    def gen():
        try:
            for kind, payload in answer_stream(req.message, req.top_k):
                if kind == "sources":
                    yield json.dumps({"type": "sources", "sources": payload}, ensure_ascii=False) + "\n"
                elif kind == "token":
                    yield json.dumps({"type": "token", "text": payload}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(e)[:200]}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/reindex")
def reindex_endpoint() -> dict:
    """DB를 다시 읽어 벡터 색인을 갱신 (데이터 변경 후 호출)."""
    return {"indexed": reindex_all()}
