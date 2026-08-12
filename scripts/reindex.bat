@echo off
REM DB를 다시 읽어 벡터 색인 갱신 (데이터 변경 후 실행)
cd /d %~dp0
.venv\Scripts\python.exe -c "from app.indexer import reindex_all; print(reindex_all())"
