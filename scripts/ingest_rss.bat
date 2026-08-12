@echo off
REM =====================================================================
REM  News RSS ingest batch (called hourly by Windows Task Scheduler)
REM  - Auto-starts MySQL / Ollama if they are not running, then ingests
REM  - Log: rag\ingest_rss.log   (ASCII-only bat; Korean output goes to log via python UTF-8)
REM =====================================================================
setlocal
set RAGDIR=C:\Users\user\Desktop\claude\llm\rag
set VENV=%RAGDIR%\.venv\Scripts\python.exe
set MYSQLD=C:\Users\user\Desktop\claude\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe
set MYINI=C:\Users\user\Desktop\claude\llm\db\my.ini
set OLLAMA=C:\Users\user\AppData\Local\Programs\Ollama\ollama.exe
set LOG=%RAGDIR%\ingest_rss.log

cd /d "%RAGDIR%"
powershell -NoProfile -Command "Add-Content -Path '%LOG%' -Value ('==== ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ====')"

REM Start MySQL if port 3306 is not listening (wait up to 20s)
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue)) { Start-Process '%MYSQLD%' -ArgumentList '--defaults-file=%MYINI%' -WindowStyle Hidden; for($i=0;$i -lt 20;$i++){ Start-Sleep 1; if(Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue){break} } }"

REM Start Ollama if not responding (wait up to 10s)
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process '%OLLAMA%' -ArgumentList 'serve' -WindowStyle Hidden; for($i=0;$i -lt 10;$i++){ Start-Sleep 1; try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null; break } catch {} } }"

REM Run the ingestion
set PYTHONUTF8=1
REM Hourly run: index only the newest 300 unindexed (fast, recent news first).
REM The large backlog is drained by the nightly RAG_News_Backfill (uncapped).
set RSS_INDEX_MAX=300
"%VENV%" -u -m app.ingest_rss >> "%LOG%" 2>&1
echo [exit %ERRORLEVEL%] >> "%LOG%"
endlocal
