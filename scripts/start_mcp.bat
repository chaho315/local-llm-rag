@echo off
REM 읽기전용 DB MCP 서버 실행 (stdio)
cd /d %~dp0
.venv\Scripts\python.exe db_mcp.py
