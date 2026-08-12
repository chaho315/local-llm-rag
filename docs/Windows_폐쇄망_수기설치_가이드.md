# Windows 폐쇄망 — 수기(手記) 설치·운영 가이드

이 문서는 지금까지 구축한 **로컬 LLM RAG 챗봇 + 뉴스 RSS 자동수집** 전체를,
폐쇄망 Windows PC에서 **자동 설치 스크립트 없이 손으로 하나씩** 재현하기 위한 매뉴얼입니다.

- 최종 구성: `Ollama(Qwen3-4B/Embedding) + MySQL 8.4(OLLAMA_LLM) + Python RAG + 챗봇 API(+뉴스 RSS 수집)`
- 설치 루트(이 문서 기준): **`C:\llm`**  ← 원하는 경로로 바꿔도 되며, 이 문서의 `C:\llm`을 모두 그 경로로 치환하세요.
- 계정/비밀번호: DB `root`/`CHANGE_ME_PASSWORD`, 앱 계정 `llmuser`/`CHANGE_ME_PASSWORD`(읽기전용), 스키마 `OLLAMA_LLM`
- 관리자 권한: 대부분 불필요(사용자 폴더 설치). Ollama 설치 시에만 설치 관리자 권한이 필요할 수 있음.

> ⚠️ **가장 중요한 3가지 인코딩 규칙** (이번에 실제로 문제가 됐던 부분)
> 1. **`.bat` 파일은 반드시 ANSI 또는 순수 영문(ASCII)로 저장.** 한글을 넣으면 cmd가 깨뜨려 실행 실패합니다. → 이 문서의 .bat는 전부 영문입니다.
> 2. **`.sql`, `.env`, `config.yaml`, `.Modelfile`은 UTF-8로 저장** (한글 포함).
> 3. Windows PowerShell 스크립트(`.ps1`)에 한글을 넣으려면 **UTF-8(BOM 포함)**으로 저장.
> (메모장: "다른 이름으로 저장" → 인코딩에서 `ANSI` 또는 `UTF-8` 선택)

---

## [사전] 폐쇄망으로 반입할 준비물 체크리스트

인터넷 되는 PC에서 아래를 받아 USB 등 **승인된 매체**로 반입하세요.

- [ ] **Ollama 설치본**: `OllamaSetup.exe` (또는 이미 구성된 `Programs\Ollama` 폴더 + `%USERPROFILE%\.ollama` 통째)
- [ ] **모델 GGUF 2개**: `Qwen3-4B-Q4_K_M.gguf`(~2.4GB), `Qwen3-Embedding-0.6B-Q8_0.gguf`(~610MB)
- [ ] **MySQL**: `mysql-8.4.3-winx64.zip`
- [ ] **Python**: `python-3.12.10-amd64.exe`
- [ ] **pip 오프라인 패키지(wheel) 폴더**: 아래 명령으로 미리 받아둔 `wheels\` 폴더
      ```
      pip download -r requirements.txt -d wheels
      pip download pip setuptools wheel -d wheels
      ```
- [ ] **RAG 앱 소스 폴더** `rag\` (아래 [E-3] 파일 목록 참고)

> 💡 이 전부를 하나로 묶은 자동 설치본(`rag-chatbot-offline-windows.zip`)도 이미 있습니다.
> 이 문서는 그 자동 설치를 **손으로 똑같이 하는** 방법입니다.

---

## [A] 폴더 준비  (명령 프롬프트 `cmd`)

```bat
mkdir C:\llm
mkdir C:\llm\models
mkdir C:\llm\modelfiles
mkdir C:\llm\db
mkdir C:\llm\rag
```
반입한 GGUF 2개를 `C:\llm\models\` 에 복사합니다.

---

## [B] Ollama 설치 + 모델 등록

### B-1. Ollama 설치
- `OllamaSetup.exe` 실행 → 설치. 설치 후 Ollama가 백그라운드로 뜨며 `http://127.0.0.1:11434` 에서 대기합니다.
- 확인(cmd):
  ```bat
  ollama --version
  ```
  (명령을 못 찾으면 `"%LOCALAPPDATA%\Programs\Ollama\ollama.exe" --version`)

### B-2. Modelfile 2개 작성 (메모장, **UTF-8** 저장)

`C:\llm\modelfiles\qwen3-4b.Modelfile`
```
FROM C:/llm/models/Qwen3-4B-Q4_K_M.gguf
PARAMETER num_ctx 8192
PARAMETER temperature 0.7
PARAMETER top_p 0.8
PARAMETER top_k 20
PARAMETER repeat_penalty 1.05
```

`C:\llm\modelfiles\qwen3-embedding.Modelfile`
```
FROM C:/llm/models/Qwen3-Embedding-0.6B-Q8_0.gguf
```

### B-3. 모델 등록 (cmd)
```bat
ollama create qwen3-4b        -f C:\llm\modelfiles\qwen3-4b.Modelfile
ollama create qwen3-embedding -f C:\llm\modelfiles\qwen3-embedding.Modelfile
ollama list
```
`qwen3-4b`, `qwen3-embedding` 두 개가 보이면 성공.

> 대안(레지스트리 차단 환경): 인터넷 PC에서 위까지 마친 뒤 `%USERPROFILE%\.ollama\models` 폴더 전체를
> 폐쇄망 PC의 같은 위치로 복사하면 `ollama create` 없이 바로 `ollama list`에 나타납니다.

---

## [C] MySQL 8.4 설치·기동

### C-1. 압축 해제
`mysql-8.4.3-winx64.zip` 을 `C:\llm\db\` 에 풀어 `C:\llm\db\mysql-8.4.3-winx64\` 가 되도록 합니다.

### C-2. 설정파일 작성 — `C:\llm\db\my.ini` (메모장, ANSI 또는 UTF-8 저장; 내용은 영문이라 무방)
```ini
[mysqld]
basedir  = C:/llm/db/mysql-8.4.3-winx64
datadir  = C:/llm/db/data
port     = 3306
bind-address = 127.0.0.1
pid-file  = mysql.pid
log-error = mysql-error.log

character-set-server = utf8mb4
collation-server     = utf8mb4_0900_ai_ci

# 메모리 절약 (16GB PC에서 Ollama와 동시구동 시 OOM 방지)
performance_schema        = OFF
innodb_buffer_pool_size   = 128M
innodb_flush_log_at_trx_commit = 2
max_connections           = 50
table_open_cache          = 200
table_definition_cache    = 200
tmp_table_size            = 16M
max_heap_table_size       = 16M

[client]
port                 = 3306
default-character-set = utf8mb4
```

### C-3. 데이터 디렉토리 초기화 (최초 1회, cmd)
```bat
cd /d C:\llm\db
mysql-8.4.3-winx64\bin\mysqld.exe --defaults-file=C:\llm\db\my.ini --initialize-insecure
```
→ `C:\llm\db\data\` 가 생성되고 `root@localhost`가 **비밀번호 없이** 만들어집니다.

### C-4. 서버 기동 (cmd) — 이 창은 켜 둔 채로 다음 단계 진행
```bat
cd /d C:\llm\db
start "" /B mysql-8.4.3-winx64\bin\mysqld.exe --defaults-file=C:\llm\db\my.ini
```
확인(잠시 후):
```bat
mysql-8.4.3-winx64\bin\mysqladmin.exe -h 127.0.0.1 -u root ping
```
`mysqld is alive` 가 나오면 성공. (안 되면 `C:\llm\db\data\mysql-error.log` 확인)

---

## [D] `OLLAMA_LLM` 스키마 + `llmuser` 계정 만들기

### D-1. `C:\llm\db\init.sql` 작성 (메모장, **반드시 UTF-8** 저장 — 한글 데이터 포함)
```sql
CREATE DATABASE IF NOT EXISTS OLLAMA_LLM DEFAULT CHARACTER SET utf8mb4;

CREATE USER IF NOT EXISTS 'llmuser'@'%'         IDENTIFIED BY 'CHANGE_ME_PASSWORD';
CREATE USER IF NOT EXISTS 'llmuser'@'localhost' IDENTIFIED BY 'CHANGE_ME_PASSWORD';
GRANT SELECT ON OLLAMA_LLM.* TO 'llmuser'@'%';
GRANT SELECT ON OLLAMA_LLM.* TO 'llmuser'@'localhost';
FLUSH PRIVILEGES;

USE OLLAMA_LLM;

-- (선택) 동작 확인용 합성 샘플 데이터. 실제 운영 시 불필요하면 이 블록은 생략 가능.
DROP TABLE IF EXISTS MMS_TEST_TB;
CREATE TABLE MMS_TEST_TB (
  MSG_ID INT AUTO_INCREMENT PRIMARY KEY,
  MSG_TITLE VARCHAR(200), MSG_CONTENT TEXT, MSG_TYPE VARCHAR(20),
  SENDER_DEPT VARCHAR(50), RECIPIENT_GROUP VARCHAR(50), STATUS VARCHAR(20),
  PRIORITY INT, SEND_DATE DATE, USE_YN CHAR(1)
) DEFAULT CHARSET=utf8mb4;
INSERT INTO MMS_TEST_TB (MSG_TITLE, MSG_CONTENT, MSG_TYPE, SENDER_DEPT, RECIPIENT_GROUP, STATUS, PRIORITY, SEND_DATE, USE_YN) VALUES
('정산 주기 변경 안내','8월부터 가맹점 정산 주기가 월 2회에서 주 1회로 변경됩니다. 첫 적용일은 8월 6일입니다.','NOTICE','정산팀','가맹점','SENT',1,'2026-07-10','Y'),
('MMS 발송 실패 재처리 가이드','MMS 발송이 실패한 경우 관리자 콘솔의 재처리 메뉴에서 최대 3회까지 자동 재시도가 가능합니다.','INFO','메시징개발팀','개발자','SENT',3,'2026-06-28','Y');
```

### D-2. 실행 (cmd) — root는 아직 비밀번호 없음
```bat
cd /d C:\llm\db
mysql-8.4.3-winx64\bin\mysql.exe -h 127.0.0.1 -u root --default-character-set=utf8mb4 < C:\llm\db\init.sql
```

### D-3. root 비밀번호 설정 (cmd)
```bat
mysql-8.4.3-winx64\bin\mysql.exe -h 127.0.0.1 -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'CHANGE_ME_PASSWORD'; FLUSH PRIVILEGES;"
```

### D-4. 확인 (cmd) — 이제 root는 비밀번호 필요
```bat
mysql-8.4.3-winx64\bin\mysql.exe -h 127.0.0.1 -u llmuser -pCHANGE_ME_PASSWORD OLLAMA_LLM -e "SHOW TABLES;"
```

---

## [E] Python + 가상환경 + 패키지(오프라인)

### E-1. Python 3.12 설치
`python-3.12.10-amd64.exe` 실행 → 설치. (설치 경로를 알아두세요. 예: `C:\Users\<사용자>\AppData\Local\Programs\Python\Python312\python.exe`)
확인(cmd): `python --version` (PATH에 없으면 전체 경로 사용)

### E-2. `requirements.txt` 작성 — `C:\llm\rag\requirements.txt` (UTF-8)
```
fastapi
uvicorn[standard]
pydantic
pydantic-settings
pyyaml
httpx
oracledb
pymysql
numpy
mcp[cli]
cryptography
beautifulsoup4
truststore
```

### E-3. RAG 앱 소스 반입
반입한 `rag\` 폴더에서 아래 파일이 `C:\llm\rag\` 에 있어야 합니다.
```
C:\llm\rag\app\__init__.py
C:\llm\rag\app\settings.py
C:\llm\rag\app\ollama_client.py
C:\llm\rag\app\db.py
C:\llm\rag\app\vector_store.py
C:\llm\rag\app\indexer.py
C:\llm\rag\app\rag.py
C:\llm\rag\app\api.py
C:\llm\rag\app\ingest_text.py     (외부 텍스트 파일 색인용)
C:\llm\rag\app\ingest_rss.py      (뉴스 RSS 수집용 — [I]에서 사용)
C:\llm\rag\db_mcp.py
C:\llm\rag\smoke_test.py
```

### E-4. 가상환경 + 오프라인 설치 (cmd)  ※ `<PYTHON>` 은 E-1의 python 경로
```bat
cd /d C:\llm\rag
"<PYTHON>" -m venv C:\llm\rag\.venv
C:\llm\rag\.venv\Scripts\python.exe -m pip install --no-index --find-links C:\경로\wheels --upgrade pip
C:\llm\rag\.venv\Scripts\python.exe -m pip install --no-index --find-links C:\경로\wheels -r C:\llm\rag\requirements.txt
```
(`C:\경로\wheels` 는 반입한 wheel 폴더 위치)

---

## [F] 접속정보(.env) + 색인대상(config.yaml)

### F-1. `C:\llm\rag\.env` (메모장, UTF-8)
```
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=llmuser
MYSQL_PASSWORD=CHANGE_ME_PASSWORD
MYSQL_DATABASE=OLLAMA_LLM

# Oracle 미사용 시 config.yaml 에서 enabled: false 유지
ORACLE_USER=readonly_user
ORACLE_PASSWORD=change-me
ORACLE_DSN=10.0.0.10:1521/ORCLPDB1

# 뉴스 RSS 수집기 설정 ([I]에서 사용)
RSS_URL=http://rss.edaily.co.kr/edaily_news.xml
RSS_MAX=50
RSS_DELAY=1.0
NEWS_WRITER_USER=newswriter
NEWS_WRITER_PASSWORD=CHANGE_ME_PASSWORD
```

### F-2. `C:\llm\rag\config.yaml` (메모장, UTF-8)
```yaml
ollama:
  base_url: "http://localhost:11434"
  chat_model: "qwen3-4b"
  embedding_model: "qwen3-embedding"
  num_ctx: 4096          # 저사양(16GB) 기준. 여유 있으면 8192
  think: false

retrieval:
  top_k: 5
  chunk_size: 800
  chunk_overlap: 100

vector_store:
  path: "./vectorstore.db"
  collection: "company_kb"

sources:
  oracle:
    enabled: false
    tables:
      - table: "KB_FAQ"
        id_column: "FAQ_ID"
        text_columns: ["TITLE", "CONTENT"]
        where: null
  mysql:
    enabled: true
    tables:
      - table: "MMS_TEST_TB"
        id_column: "MSG_ID"
        text_columns: ["MSG_TITLE", "MSG_CONTENT"]
        where: null
      - table: "NEWS_RSS"
        id_column: "NEWS_ID"
        text_columns: ["TITLE", "SUMMARY", "CONTENT"]
        where: null
```

---

## [G] 색인 + 챗봇 API 기동·테스트

### G-1. 색인 (DB → 임베딩) (cmd)
```bat
cd /d C:\llm\rag
set PYTHONUTF8=1
.venv\Scripts\python.exe -c "from app.indexer import reindex_all; print(reindex_all())"
```
예: `{'oracle': 0, 'mysql': 2}` 처럼 나오면 성공.

### G-2. 챗봇 API 기동 (cmd) — 이 창은 켜 둔 채로
```bat
cd /d C:\llm\rag
.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```
- 브라우저: `http://127.0.0.1:8000/docs`

### G-3. 테스트 (다른 cmd 창)
```bat
curl -X POST "http://127.0.0.1:8000/chat" -H "Content-Type: application/json" -d "{\"message\": \"정산 주기가 어떻게 바뀌나요?\"}"
```

---

## [H] 실행/종료 배치 파일 만들기  (메모장, **영문 그대로 · ANSI 저장**)

`C:\llm\start_db.bat`
```bat
@echo off
start "" /B "C:\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe" --defaults-file="C:\llm\db\my.ini"
echo MySQL start requested (127.0.0.1:3306)
```

`C:\llm\stop_db.bat`
```bat
@echo off
"C:\llm\db\mysql-8.4.3-winx64\bin\mysqladmin.exe" -h 127.0.0.1 -u root --password=CHANGE_ME_PASSWORD shutdown
echo MySQL shutdown requested
```

`C:\llm\rag\start_api.bat`
```bat
@echo off
cd /d "C:\llm\rag"
".venv\Scripts\python.exe" -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

`C:\llm\rag\reindex.bat`
```bat
@echo off
cd /d "C:\llm\rag"
set PYTHONUTF8=1
".venv\Scripts\python.exe" -c "from app.indexer import reindex_all; print(reindex_all())"
```

---

## [I] 뉴스 RSS 자동수집 + 매시간 스케줄  (★ 인터넷 필요)

> RSS 수집은 **인터넷 접속이 필요**합니다. 완전 폐쇄망에서는 동작하지 않으므로,
> 인터넷 되는 "수집용 PC"에서 이 절을 진행하세요. (완전 폐쇄망에서는 [사전] 안내대로
> 외부 자료를 파일로 반입해 `app.ingest_text` 로 색인하는 방식을 사용합니다.)

### I-1. 뉴스 테이블 + 쓰기 전용 계정 만들기 (cmd)
```bat
cd /d C:\llm\db
mysql-8.4.3-winx64\bin\mysql.exe -h 127.0.0.1 -u root -pCHANGE_ME_PASSWORD --default-character-set=utf8mb4 -e "USE OLLAMA_LLM; CREATE TABLE IF NOT EXISTS NEWS_RSS (NEWS_ID VARCHAR(64) PRIMARY KEY, TITLE VARCHAR(500), LINK VARCHAR(1000), CATEGORY VARCHAR(100), AUTHOR VARCHAR(100), PUB_DATE VARCHAR(64), SUMMARY TEXT, CONTENT MEDIUMTEXT, FETCHED_AT DATETIME DEFAULT CURRENT_TIMESTAMP, INDEXED_YN CHAR(1) DEFAULT 'N') DEFAULT CHARSET=utf8mb4; CREATE USER IF NOT EXISTS 'newswriter'@'localhost' IDENTIFIED BY 'CHANGE_ME_PASSWORD'; GRANT SELECT, INSERT, UPDATE ON OLLAMA_LLM.NEWS_RSS TO 'newswriter'@'localhost'; FLUSH PRIVILEGES;"
```

### I-2. 의존성 확인
`beautifulsoup4`, `truststore` 는 [E-2] requirements.txt 에 이미 포함되어 [E-4]에서 설치됩니다.
(사내 SSL검사 프록시가 있으면 `truststore` 가 Windows 인증서 저장소를 사용해 인증서 오류를 막아줍니다.)

### I-3. 1회 수동 실행으로 확인 (cmd)
```bat
cd /d C:\llm\rag
set PYTHONUTF8=1
.venv\Scripts\python.exe -m app.ingest_rss
```
`>>> DB 저장(신규): N 건`, `>>> 임베딩 색인(신규): N 건` 이 나오면 성공.

### I-4. 스케줄용 배치 — `C:\llm\rag\ingest_rss.bat` (메모장, **영문 · ANSI 저장**)
```bat
@echo off
REM News RSS ingest (auto-starts MySQL/Ollama if down, then ingests). Log: rag\ingest_rss.log
setlocal
set RAGDIR=C:\llm\rag
set VENV=%RAGDIR%\.venv\Scripts\python.exe
set MYSQLD=C:\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe
set MYINI=C:\llm\db\my.ini
set OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
set LOG=%RAGDIR%\ingest_rss.log
cd /d "%RAGDIR%"
powershell -NoProfile -Command "Add-Content -Path '%LOG%' -Value ('==== ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ====')"
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue)) { Start-Process '%MYSQLD%' -ArgumentList '--defaults-file=%MYINI%' -WindowStyle Hidden; for($i=0;$i -lt 20;$i++){ Start-Sleep 1; if(Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue){break} } }"
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process '%OLLAMA%' -ArgumentList 'serve' -WindowStyle Hidden; Start-Sleep 5 }"
set PYTHONUTF8=1
"%VENV%" -m app.ingest_rss >> "%LOG%" 2>&1
echo [exit %ERRORLEVEL%] >> "%LOG%"
endlocal
```

### I-5. 매시간 스케줄 등록 — 방법 ① PowerShell (권장, 관리자 불필요)
**PowerShell 창**에서 아래를 붙여넣기:
```powershell
$bat = "C:\llm\rag\ingest_rss.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "RAG_News_Ingest" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "edaily RSS 뉴스 수집 (매시간)" -Force
```
확인:
```powershell
Get-ScheduledTaskInfo -TaskName "RAG_News_Ingest" | Select-Object NextRunTime, LastTaskResult
Start-ScheduledTask -TaskName "RAG_News_Ingest"   # 지금 한 번 실행 테스트
```

### I-5. 매시간 스케줄 등록 — 방법 ② GUI (작업 스케줄러)
1. 시작 → "작업 스케줄러" 실행
2. 오른쪽 **작업 만들기**(기본 작업 아님)
3. [일반] 이름 `RAG_News_Ingest`, "사용자가 로그온할 때만 실행"
4. [트리거] 새로 만들기 → **매일**, 반복 간격 **1시간**, 기간 **무기한**
5. [동작] 새로 만들기 → 프로그램: `cmd.exe`, 인수 추가: `/c "C:\llm\rag\ingest_rss.bat"`
6. 확인 → 저장

### I-6. 로그 확인
```
C:\llm\rag\ingest_rss.log
```

---

## [J] 재부팅 후 기동 순서

1. **Ollama** — 보통 부팅 시 자동 실행됨. 아니면 `C:\llm\rag\ingest_rss.bat` 이나 Ollama 앱 실행.
2. **MySQL** — `C:\llm\start_db.bat` 더블클릭
3. **색인 확인**(선택) — `C:\llm\rag\reindex.bat`
4. **챗봇 API** — `C:\llm\rag\start_api.bat`
5. RSS 스케줄 작업은 등록돼 있으면 매시간 자동 실행(로그온 상태).

> MySQL을 항상 자동 기동하려면 서비스로 등록할 수도 있습니다(관리자 cmd):
> `C:\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe --install MySQL84 --defaults-file=C:\llm\db\my.ini`
> 후 `net start MySQL84`. (제거: `sc delete MySQL84`)

---

## [K] 문제 해결 & 주의사항

| 증상 | 원인/조치 |
|---|---|
| `.bat` 실행 시 `'…' is not recognized` | .bat에 한글이 들어감 → **영문/ANSI로 다시 저장**. (이 문서 .bat는 전부 영문) |
| 챗봇 답변에 한글 깨짐 | `.env`/`config.yaml`/`init.sql` 을 **UTF-8**로 저장했는지 확인. python 실행 시 `set PYTHONUTF8=1` |
| 기사 스크래핑 `CERTIFICATE_VERIFY_FAILED` | 사내 SSL검사 프록시 → `truststore` 설치 확인. 임시로 `.env`에 `RSS_INSECURE=1` 가능(검증 생략) |
| MySQL 기동 실패 | `C:\llm\db\mysql-error.log` 확인. 포트 3306 충돌 여부 확인 |
| 메모리 부족/느림 | Ollama(모델 ~3GB)+MySQL 동시구동은 16GB에서 빠듯. `config.yaml`의 `num_ctx=4096` 유지, `my.ini`의 `performance_schema=OFF` 유지 |
| Ollama 모델 안 보임 | `ollama list` 확인. 없으면 [B-3] `ollama create` 재실행 |

**보안**
- 기본 비밀번호(`CHANGE_ME_PASSWORD`)는 운영 배포 전 **반드시 변경**하고 `.env`도 함께 수정.
- DB는 `bind-address=127.0.0.1`(로컬 전용), API도 `127.0.0.1` 기본. 원격 노출 시 인증/프록시 필수.
- 색인 대상에는 **개인정보·결제정보가 없는** 테이블/뷰만 등록.
- 뉴스 등 외부 자료는 저작권이 있으므로 **사내 RAG 내부 활용**에 한정하고 사이트 이용약관을 준수.

---

## 부록 — 데이터 "학습"(색인) 갱신 방법
- **DB 데이터 변경 시**: `C:\llm\rag\reindex.bat` 실행 (또는 `POST /reindex`)
- **외부 문서(.txt/.md) 추가**: `.venv\Scripts\python.exe -m app.ingest_text C:\문서폴더`
- **뉴스 RSS**: [I]의 스케줄이 매시간 자동 수집·색인 (신규 기사만)
- 이 시스템은 모델 가중치를 바꾸지 않는 **RAG** 방식이라, 데이터가 바뀌면 색인만 다시 하면 됩니다.
