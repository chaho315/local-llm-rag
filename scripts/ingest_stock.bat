@echo off
REM =====================================================================
REM  Daily stock price ingest (scheduled 09:00). ASCII-only bat.
REM  Auto-starts MySQL/Ollama if down, then fetches prev-day stock prices.
REM  Log: rag\ingest_stock.log
REM =====================================================================
setlocal
set RAGDIR=C:\Users\user\Desktop\claude\llm\rag
set VENV=%RAGDIR%\.venv\Scripts\python.exe
set MYSQLD=C:\Users\user\Desktop\claude\llm\db\mysql-8.4.3-winx64\bin\mysqld.exe
set MYINI=C:\Users\user\Desktop\claude\llm\db\my.ini
set OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
set LOG=%RAGDIR%\ingest_stock.log

cd /d "%RAGDIR%"
powershell -NoProfile -Command "Add-Content -Path '%LOG%' -Value ('==== ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ====')"
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue)) { Start-Process '%MYSQLD%' -ArgumentList '--defaults-file=%MYINI%' -WindowStyle Hidden; for($i=0;$i -lt 20;$i++){ Start-Sleep 1; if(Get-NetTCPConnection -LocalPort 3306 -State Listen -EA SilentlyContinue){break} } }"
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process '%OLLAMA%' -ArgumentList 'serve' -WindowStyle Hidden; Start-Sleep 5 }"

set PYTHONUTF8=1
"%VENV%" -u -m app.ingest_stock >> "%LOG%" 2>&1
echo [exit %ERRORLEVEL%] >> "%LOG%"
endlocal
