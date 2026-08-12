"""Ollama 호출 헬퍼 (임베딩 + 채팅).

httpx 는 JSON 본문을 UTF-8 로 인코딩하므로 한국어가 깨지지 않는다.
(PowerShell 에서 겪은 인코딩 문제는 여기서는 발생하지 않음)
"""
from __future__ import annotations

import json
import time

import httpx

from .settings import OLLAMA

_BASE = OLLAMA["base_url"].rstrip("/")
# CPU 추론은 느릴 수 있으므로 채팅 생성 타임아웃은 넉넉히 준다.
_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
# 임베딩은 1건에 수 초면 끝난다. 간헐적으로 응답이 멈추는(wedge) 경우가 있어
# 짧은 타임아웃 + 재시도로 '무한 대기' 대신 빠르게 실패→새 연결 재시도하게 한다.
_EMBED_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_EMBED_RETRIES = 3


def embed(texts: list[str], keep_alive=None) -> list[list[float]]:
    """여러 문장을 임베딩. Qwen3-Embedding → 문장당 1024차원 벡터.

    keep_alive=0 을 주면 응답 직후 임베딩 모델을 메모리에서 내린다
    (저사양 환경에서 채팅 모델 로드 공간 확보용).
    """
    payload = {"model": OLLAMA["embedding_model"], "input": texts}
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    last = None
    for attempt in range(_EMBED_RETRIES):
        try:
            resp = httpx.post(f"{_BASE}/api/embed", json=payload, timeout=_EMBED_TIMEOUT)
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            # 멈춘(wedge) 요청은 타임아웃으로 끊고, 잠시 후 새 연결로 재시도
            if attempt < _EMBED_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    raise last


def chat(prompt: str, system: str | None = None) -> str:
    """단일 프롬프트로 생성. 응답 문자열을 반환."""
    body = {
        "model": OLLAMA["chat_model"],
        "prompt": prompt,
        "stream": False,
        "think": OLLAMA.get("think", False),
        "options": {"num_ctx": OLLAMA.get("num_ctx", 8192)},
    }
    # 채팅 모델을 메모리에 유지 → 다음 질문에서 콜드 로딩(약 60초) 회피
    ka = OLLAMA.get("keep_alive")
    if ka is not None:
        body["keep_alive"] = ka
    if system:
        body["system"] = system
    resp = httpx.post(f"{_BASE}/api/generate", json=body, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["response"]


def chat_stream(prompt: str, system: str | None = None):
    """스트리밍 생성: 생성되는 토큰(문자열)을 순차적으로 yield 한다.

    Ollama /api/generate 의 stream=true 응답(JSON Lines)을 파싱해 토큰만 흘려보낸다.
    프론트가 토큰을 즉시 받아 그려주므로 CPU 추론이 길어도 '멈춘 것처럼' 보이지 않는다.
    """
    body = {
        "model": OLLAMA["chat_model"],
        "prompt": prompt,
        "stream": True,
        "think": OLLAMA.get("think", False),
        "options": {"num_ctx": OLLAMA.get("num_ctx", 8192)},
    }
    ka = OLLAMA.get("keep_alive")
    if ka is not None:
        body["keep_alive"] = ka
    if system:
        body["system"] = system
    with httpx.stream("POST", f"{_BASE}/api/generate", json=body, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            tok = obj.get("response")
            if tok:
                yield tok
            if obj.get("done"):
                break
