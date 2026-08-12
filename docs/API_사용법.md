# 사내 RAG 챗봇 API 사용법

로컬 LLM(Ollama + Qwen3-4B) + MySQL(OLLAMA_LLM) 을 RAG로 연동한 챗봇 HTTP API 문서입니다.

- **검증일**: 2026-07-14 (아래 `/chat` 요청·응답은 실제 테스트 결과입니다)
- **Base URL**: `http://127.0.0.1:8000`
- **자동 문서(Swagger UI)**: `http://127.0.0.1:8000/docs`  ← 브라우저에서 바로 테스트 가능

---

## 1. 서버 실행 / 종료

```bat
REM 실행 (Windows)
cd C:\Users\user\Desktop\claude\llm\rag
start_api.bat

REM 내부적으로 실행되는 명령
.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

> 종료: 서버 콘솔 창에서 `Ctrl + C`. (백그라운드로 띄운 경우 해당 python 프로세스 종료)

---

## 2. 엔드포인트 요약

| 메서드 | Full URL | 설명 |
|---|---|---|
| `GET`  | `http://127.0.0.1:8000/health`  | 서버 상태 확인 |
| `POST` | `http://127.0.0.1:8000/chat`    | **질문 → RAG 답변** (핵심) |
| `POST` | `http://127.0.0.1:8000/reindex` | DB를 다시 읽어 벡터 색인 갱신 |

---

## 3. ⭐ POST /chat  (핵심 엔드포인트)

- **Full URL**: `http://127.0.0.1:8000/chat`
- **Method**: `POST`
- **Header**: `Content-Type: application/json`  (본문은 반드시 **UTF-8** — 한글 깨짐 방지)

### 요청 파라미터 (JSON body)

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `message` | string | ✅ 필수 | - | 사용자 질문 |
| `top_k`   | int    | ❌ 선택 | `5` (config.yaml) | 검색해 근거로 넣을 문서 조각 수. 크게 하면 근거↑·속도↓ |

### 응답 (JSON)

| 필드 | 타입 | 설명 |
|---|---|---|
| `answer`  | string | LLM이 생성한 답변 (근거 자료 기반) |
| `sources` | array  | 근거로 사용한 출처 목록. 각 항목: `{db, table, row_id}` |

---

### ✅ 실제 테스트한 요청/응답 (2026-07-14)

**요청**
```
POST http://127.0.0.1:8000/chat
Content-Type: application/json

{"message": "MMS 발송이 실패하면 어떻게 처리하나요?", "top_k": 3}
```

**응답 (HTTP 200)**
```json
{
  "answer": "MMS 발송이 실패한 경우, 관리자 콘솔의 재처리 메뉴에서 최대 3회까지 자동 재시도가 가능합니다. 3회 초과 실패 건은 수동 확인이 필요합니다.  \n[출처 1]",
  "sources": [
    { "db": "mysql", "table": "MMS_TEST_TB", "row_id": "4" },
    { "db": "mysql", "table": "MMS_TEST_TB", "row_id": "6" },
    { "db": "mysql", "table": "MMS_TEST_TB", "row_id": "1" }
  ]
}
```

---

### 호출 예시

**curl (Linux/macOS)**
```bash
curl -X POST "http://127.0.0.1:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "정산 주기가 어떻게 바뀌나요?", "top_k": 5}'
```

**curl (Windows cmd)**
```bat
curl -X POST "http://127.0.0.1:8000/chat" ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"정산 주기가 어떻게 바뀌나요?\", \"top_k\": 5}"
```

**Python**
```python
import requests
r = requests.post("http://127.0.0.1:8000/chat",
                  json={"message": "정산 주기가 어떻게 바뀌나요?", "top_k": 5})
print(r.json()["answer"])
```

**C# (.NET — 사내 프로그램 연동)**
```csharp
using System.Net.Http;
using System.Text;
using System.Text.Json;

var http = new HttpClient();
var body = new StringContent(
    JsonSerializer.Serialize(new { message = "정산 주기가 어떻게 바뀌나요?", top_k = 5 }),
    Encoding.UTF8, "application/json");          // ← UTF-8 필수(한글)
var res = await http.PostAsync("http://127.0.0.1:8000/chat", body);
var json = JsonDocument.Parse(await res.Content.ReadAsStringAsync());
Console.WriteLine(json.RootElement.GetProperty("answer").GetString());
```

**JavaScript (fetch)**
```javascript
const res = await fetch("http://127.0.0.1:8000/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "정산 주기가 어떻게 바뀌나요?", top_k: 5 })
});
console.log((await res.json()).answer);
```

---

## 4. POST /reindex  (색인 갱신)

DB 데이터가 바뀌거나 `config.yaml`의 대상 테이블을 변경한 뒤 호출합니다.

- **Full URL**: `http://127.0.0.1:8000/reindex`
- **Method**: `POST` (요청 본문 없음)

```bash
curl -X POST "http://127.0.0.1:8000/reindex"
```

**응답 예시** (oracle 0건, mysql 8건 색인됨)
```json
{ "indexed": { "oracle": 0, "mysql": 8 } }
```

---

## 5. GET /health  (상태 확인)

- **Full URL**: `http://127.0.0.1:8000/health`

```bash
curl "http://127.0.0.1:8000/health"
# → {"status":"ok"}
```

---

## 6. 참고 사항

- **인코딩**: 요청/응답 모두 UTF-8. 한글이 깨지면 클라이언트의 Content-Type/charset을 확인하세요.
- **첫 호출 지연**: 첫 `/chat` 요청은 Ollama가 모델을 메모리에 로드하므로 느립니다(이 PC 기준 약 30초). 이후 호출은 빨라집니다.
- **속도**: CPU 전용 추론이라 클라우드보다 느립니다(약 11~13 tok/s). 동시 사용자가 많으면 RAM 32GB+ / GPU 서버를 권장합니다.
- **근거 없는 질문**: 색인된 자료에서 근거를 못 찾으면 `"관련 자료를 찾지 못했습니다."` 를 반환합니다(환각 억제).
- **원격 접속**: 기본은 `127.0.0.1`(로컬 전용). 사내망에 노출하려면 `--host 0.0.0.0`으로 바꾸고 방화벽/인증(프록시)을 반드시 추가하세요.
