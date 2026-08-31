@echo off
rem ============================================================
rem  Agent DevPanel launcher (single window)
rem  Double-click to run: browser opens the panel automatically.
rem  Two services (backend/frontend) are started and stopped
rem  from this one screen.
rem  To stop: close this window - backend/frontend processes are
rem  reclaimed.
rem ============================================================
cd /d "%~dp0"
echo ================================================
echo  Agent DevPanel  -  http://127.0.0.1:9100
echo  Close this window = stop panel + reclaim services
echo ================================================
echo.

uv run python main.py --port 9100 %*
pause
