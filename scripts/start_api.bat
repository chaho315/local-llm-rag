@echo off
REM 사내 챗봇 API 서버 실행 (http://127.0.0.1:8000, 문서: /docs)
cd /d %~dp0
.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
