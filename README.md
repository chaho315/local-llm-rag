# 로컬 LLM RAG 챗봇 (Ollama + MySQL + FastAPI)

폐쇄망(에어갭) 환경을 상정해 만든 **로컬 LLM 기반 RAG(검색증강생성) 챗봇**입니다.
외부 API 없이 로컬 [Ollama](https://ollama.com) 모델로 임베딩·생성을 수행하고, MySQL에 저장된
뉴스·주식 시세·기업 재무(DART) 데이터를 검색해 근거와 함께 답변합니다.

> ⚠️ **공개 안내**: 이 저장소는 소스코드와 **공개 데이터(주식 시세·DART 재무)** 스냅샷만 포함합니다.
> 스크랩한 뉴스 기사 본문은 저작권 문제로 **제외**했습니다(`NEWS_RSS` 는 스키마만 제공).
> 모든 API 키·비밀번호는 플레이스홀더(`YOUR_...`, `CHANGE_ME_...`)로 치환되어 있으니
> 사용 시 본인의 값으로 `.env` 를 채우세요.

## 구성

| 계층 | 사용 기술 |
|---|---|
| LLM 엔진 | Ollama (chat: `qwen3-news`, embedding: `qwen3-embedding`) |
| 벡터 검색 | 경량 자체 벡터스토어 (numpy + sqlite, `vectorstore.db`) |
| 데이터 | MySQL 8.4 (`OLLAMA_LLM` 스키마: 뉴스/주식/DART) |
| API/UI | FastAPI + 단일 페이지 챗 UI(스트리밍) |
| 수집 | RSS 뉴스, 공공데이터포털 주식시세, DART 재무제표 |

## 동작 개요

```
질문 → 임베딩 → 벡터검색(관련 문서 top-k) → DB에서 원문 조회
     → 프롬프트 구성(근거+규칙) → LLM 생성(스트리밍) → 출처와 함께 답변
```

LLM이 DB에 직접 SQL을 날리지 않고, **미리 색인된 벡터스토어에서 검색한 근거를 프롬프트에 넣어**
그 근거만으로 답변하도록 합니다(환각 억제 + 출처 표기).

## 빠른 시작

1. **Ollama 설치 후 모델 준비**
   ```bash
   ollama create qwen3-news -f modelfiles/qwen3-news.Modelfile
   ollama pull qwen3-embedding   # 또는 modelfiles 참조
   ```
2. **MySQL 준비 + 스키마/데이터 적재**
   ```bash
   mysql -u root -p < db/init.sql              # 스키마 + 계정
   mysql -u root -p OLLAMA_LLM < db/schema.sql  # 테이블 구조(전체)
   mysql -u root -p OLLAMA_LLM < db/data_stock_dart.sql  # 주식·DART 데이터
   ```
3. **환경설정**
   ```bash
   cp .env.example .env   # 값 채우기 (API 키, DB 비번 등)
   pip install -r requirements.txt
   ```
4. **API 서버 실행**
   ```bash
   python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
   ```
   브라우저에서 http://127.0.0.1:8000 접속.

## 데이터 수집 (선택)

```bash
python -m app.ingest_rss          # 뉴스 RSS 수집·색인 (rss_feeds.txt)
python -m app.ingest_rss index    # 미색인 백로그만 색인(야간 백필용)
python -m app.ingest_stock        # 전 영업일 주식시세 수집·색인
python -m app.ingest_dart         # DART 재무제표 수집·색인
```

`scripts/` 의 배치파일과 함께 Windows 작업 스케줄러로 자동화할 수 있습니다.

## 디렉토리

```
app/            RAG 앱 (FastAPI, 수집기, 벡터스토어, Ollama 클라이언트)
app/static/     챗봇 웹 UI (단일 index.html, 스트리밍)
db/             init.sql, schema.sql, data_stock_dart.sql, my.ini
modelfiles/     Ollama Modelfile (qwen3-news 등)
scripts/        실행/스케줄 배치, 리눅스 셋업 스크립트
docs/           설치·API 가이드
rss_feeds.txt   뉴스 RSS 피드 목록
```

## 보안 주의

- `.env` 는 절대 커밋하지 마세요(`.gitignore` 에 포함).
- 소스의 API 키/비밀번호 기본값은 모두 플레이스홀더입니다. 실제 값은 `.env` 로만 주입하세요.
- 뉴스 기사 본문 등 저작권 있는 데이터를 재배포하지 마세요.

## 라이선스

코드는 자유롭게 사용하시되, 포함된 공개 데이터(주식·DART)의 원 출처 이용약관을 따르세요.
