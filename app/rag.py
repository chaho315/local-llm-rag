"""RAG 파이프라인: 질문 임베딩 → 벡터검색 → 프롬프트 구성 → 답변 생성.

※ 답변 규칙(뉴스 분석 시스템 프롬프트)은 Ollama 모델(qwen3-news)의 Modelfile SYSTEM 에
  들어 있으므로, 여기서는 system 을 따로 보내지 않는다(보내면 Modelfile SYSTEM 을 덮어씀).
  대신 컨텍스트에 언론사·발행일·제목 메타데이터를 넣어 출처 표기/시간 흐름이 가능하게 한다.
"""
from __future__ import annotations

import datetime

from .db import run_select
from .indexer import get_store
from .ollama_client import chat, chat_stream, embed
from .settings import RETRIEVAL


def retrieve(query: str, top_k: int | None = None):
    k = top_k or RETRIEVAL["top_k"]
    # 저사양(메모리) 환경: 질의 임베딩 직후 임베딩 모델을 내려 채팅 모델 로드 공간 확보
    qvec = embed([query], keep_alive=0)[0]
    res = get_store().query(qvec, n_results=k)
    return list(zip(res["documents"], res["metadatas"]))


def _lookup(table: str, row_id: str) -> dict:
    """출처의 제목/원문URL/언론사/발행일 을 DB에서 조회 (읽기전용). 실패 시 빈 값."""
    t = (table or "").upper()
    try:
        if t == "NEWS_RSS":
            rows = run_select(
                "mysql",
                "SELECT TITLE, LINK, SOURCE, CATEGORY, PUB_DATE FROM NEWS_RSS WHERE NEWS_ID=%s",
                (row_id,), limit=1,
            )
            if rows:
                r = rows[0]
                return {"title": r.get("TITLE"), "url": r.get("LINK"),
                        "source": r.get("SOURCE"), "category": r.get("CATEGORY"),
                        "pub_date": r.get("PUB_DATE")}
        elif t == "MMS_TEST_TB":
            rows = run_select(
                "mysql", "SELECT MSG_TITLE, SEND_DATE FROM MMS_TEST_TB WHERE MSG_ID=%s",
                (row_id,), limit=1,
            )
            if rows:
                return {"title": rows[0].get("MSG_TITLE"), "url": None,
                        "source": "사내 공지", "category": None,
                        "pub_date": str(rows[0].get("SEND_DATE") or "")}
        elif t == "STOCK_PRICE":
            parts = (row_id or "").split(":")   # row_id = "BASDT:SRTNCD"
            if len(parts) == 2:
                rows = run_select(
                    "mysql",
                    "SELECT ITMS_NM, MRKT_CTG, BAS_DT FROM STOCK_PRICE WHERE BAS_DT=%s AND SRTN_CD=%s",
                    (parts[0], parts[1]), limit=1,
                )
                if rows:
                    return {"title": f"{rows[0].get('ITMS_NM')} 시세", "url": None,
                            "source": "주식시세", "category": rows[0].get("MRKT_CTG"),
                            "pub_date": rows[0].get("BAS_DT")}
        elif t == "DART_FIN":
            parts = (row_id or "").split(":")   # row_id = "CORP:YEAR:REPRT:FS"
            if len(parts) == 4:
                rows = run_select(
                    "mysql",
                    "SELECT CORP_NM, REPRT_NM, FS_DIV FROM DART_FIN "
                    "WHERE CORP_CODE=%s AND BSNS_YEAR=%s AND REPRT_CODE=%s AND FS_DIV=%s LIMIT 1",
                    (parts[0], parts[1], parts[2], parts[3]), limit=1,
                )
                if rows:
                    r = rows[0]
                    fs = "연결" if r.get("FS_DIV") == "CFS" else "개별"
                    return {"title": f"{r.get('CORP_NM')} {parts[1]}년 {r.get('REPRT_NM')}",
                            "url": None, "source": "재무제표(DART)", "category": fs,
                            "pub_date": f"{parts[1]} {r.get('REPRT_NM')}"}
    except Exception:
        pass
    return {"title": None, "url": None, "source": None, "category": None, "pub_date": None}


def _source_dict(doc: str, meta: dict, info: dict) -> dict:
    """UI로 내려줄 출처 항목 (제목·원문URL·언론사·카테고리·발행일 + 본문 스니펫)."""
    snippet = (doc or "").strip()
    if len(snippet) > 600:
        snippet = snippet[:600] + "…"
    return {
        "db": meta.get("db"), "table": meta.get("table"), "row_id": meta.get("row_id"),
        "title": info.get("title"), "url": info.get("url"),
        "source": info.get("source"), "category": info.get("category"),
        "pub_date": info.get("pub_date"), "snippet": snippet,
    }


def answer(query: str, top_k: int | None = None) -> dict:
    hits = retrieve(query, top_k)
    if not hits:
        return {"answer": "제공된 자료만으로는 관련 내용을 찾지 못했습니다.", "sources": []}

    # 히트당 메타데이터 1회 조회 → 컨텍스트/출처에 재사용
    built = [(d, m, _lookup(m.get("table"), m.get("row_id"))) for d, m in hits]

    # system 미전달 → Modelfile(qwen3-news)의 뉴스 분석 SYSTEM 이 적용됨
    text = chat(_build_prompt(query, built))

    sources = [_source_dict(d, m, info) for d, m, info in built]
    return {"answer": text, "sources": sources}


def _build_context(built: list) -> str:
    """검색된 (문서, 메타, 조회정보) 목록을 참고자료 컨텍스트 문자열로 조립."""
    return "\n\n".join(
        f"[참고자료 {i + 1}] "
        f"출처: {info.get('source') or '미상'} | "
        f"발행일: {info.get('pub_date') or '미상'} | "
        f"제목: {info.get('title') or '(제목 없음)'}\n"
        f"{d}"
        for i, (d, m, info) in enumerate(built)
    )


# 서로 다른 종목/회사/항목이 한 컨텍스트에 섞였을 때 오결합·환각을 막는 접지(grounding) 규칙.
# 종목/회사는 '엄격히' 일치시키되(NHN 값을 하이닉스로 쓰는 오류 방지), 날짜는 다르면 '명시'하고
# 거부하지 않도록 한다(자료가 최신 1건뿐이라 '어제'와 날짜가 어긋나도 답을 주게).
_ANSWER_RULES = (
    "\n\n[답변 규칙 — 반드시 지킬 것]\n"
    "1) 각 [참고자료]는 서로 다른 종목·회사·항목일 수 있다. 질문의 대상(종목명·회사명)과 일치하는 "
    "자료만 사용하고, 다른 종목/회사의 수치를 절대 가져다 쓰지 마라.\n"
    "2) 질문 대상과 일치하는 자료가 하나도 없을 때에만 '제공된 자료에 해당 정보가 없습니다'라고 답하라.\n"
    "3) 자료의 날짜가 질문에서 말한 시점과 정확히 같지 않더라도, 대상(종목/회사)이 일치하면 그 자료로 "
    "답하되 '(YYYY-MM-DD 기준)'처럼 날짜를 밝혀라. 자료에 없는 수치는 지어내지 마라.\n"
    "4) 시세·재무 등 수치 질문은 해당 항목의 핵심 수치 위주로 간결히 답하라(장황한 배경 설명 생략).\n"
)


def _today_line() -> str:
    d = datetime.date.today()
    wd = "월화수목금토일"[d.weekday()]
    return (
        f"오늘 날짜: {d.year}년 {d.month}월 {d.day}일({wd}). "
        "질문의 '오늘/어제/이번 주/지난달/올해/작년' 등 시점 표현은 이 날짜를 기준으로 해석하라.\n\n"
    )


def _build_prompt(query: str, built: list) -> str:
    """오늘 날짜 + 검색 컨텍스트 + 접지 규칙 + 질문으로 최종 프롬프트 구성(answer/answer_stream 공용)."""
    return (
        _today_line()
        + "다음은 질문과 관련된 참고자료입니다.\n\n"
        + _build_context(built)
        + _ANSWER_RULES
        + f"\n질문: {query}"
    )


def answer_stream(query: str, top_k: int | None = None):
    """스트리밍 RAG: 먼저 ('sources', [...]) 1건, 이어서 ('token', 문자열) 여러 건을 yield.

    비스트리밍 answer() 와 동일한 검색/프롬프트를 쓰되, 생성 결과를 토큰 단위로 흘려보낸다.
    """
    hits = retrieve(query, top_k)
    if not hits:
        yield ("sources", [])
        yield ("token", "제공된 자료만으로는 관련 내용을 찾지 못했습니다.")
        return

    built = [(d, m, _lookup(m.get("table"), m.get("row_id"))) for d, m in hits]
    # 출처를 먼저 내려보내 프론트가 즉시 참조 카드를 준비할 수 있게 한다.
    yield ("sources", [_source_dict(d, m, info) for d, m, info in built])

    for tok in chat_stream(_build_prompt(query, built)):
        yield ("token", tok)
