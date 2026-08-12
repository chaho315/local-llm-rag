@echo off
REM =====================================================================
REM  Nightly news backlog backfill (scheduled ~03:00). ASCII-only bat.
REM  Index-only mode: NO feed collection, just embed unindexed NEWS_RSS
REM  rows (INDEXED_YN='N') until the backlog is drained.
REM  Auto-starts MySQL/Ollama if down. Log: rag\backfill_news.log
REM =====================================================================
setlocal
set RAGDIR=C:\Users\user\Desktop\claude\llm\rag
set VENV=%RAGDIR%\.venv\Scripts\python.exe
set MYSQLD=C:\Users\user\Desktop\claude\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe
set MYINI=C:\Users\user\Desktop\claude\llm\db\my.ini
set OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
set LOG=%RAGDIR%\backfill_news.log

cd /d "%RAGDIR%"
powershell -NoProfile -Command "Add-Content -Path '%LOG%' -Value ('==== ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' backfill ====')"

REM Start MySQL if port 3306 is not listening (wait up to 20s)
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue)) { Start-Process '%MYSQLD%' -ArgumentList '--defaults-file=%MYINI%' -WindowStyle Hidden; for($i=0;$i -lt 20;$i++){ Start-Sleep 1; if(Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue){break} } }"

REM Start Ollama if not responding (wait up to 10s)
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process '%OLLAMA%' -ArgumentList 'serve' -WindowStyle Hidden; for($i=0;$i -lt 10;$i++){ Start-Sleep 1; try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null; break } catch {} } }"

REM Run backlog index-only backfill
set PYTHONUTF8=1
REM Backfill: drain the ENTIRE unindexed backlog (no cap).
set RSS_INDEX_MAX=0
"%VENV%" -u -m app.ingest_rss index >> "%LOG%" 2>&1
echo [exit %ERRORLEVEL%] >> "%LOG%"
endlocal
