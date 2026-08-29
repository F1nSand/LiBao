@echo off
setlocal EnableExtensions
rem ============================================================
rem  Agent Platform one-click start (local single-machine)
rem  backend(:8000) only; frontend built into frontend_dist/ (static hosted)
rem  Stop: close the "Agent Backend" window
rem ============================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
set "BE_URL=http://127.0.0.1:8000/api/v1/system/health"

echo ================================================
echo  Agent Platform - local single-machine start
echo ================================================

rem ---- 1. deps (first run) ----
if not exist "%ROOT%.venv" (
  echo [1/3] first run: uv sync...
  call uv sync || goto :fail
) else (
  echo [1/3] deps ready
)

rem ---- 2. backend ----
echo [2/3] backend :8000
if /I "%~1"=="restart" (
  echo   restart requested: checking current project instance
  for /f "delims=" %%S in ('uv run python scripts/check_backend_runtime.py "%BE_URL%" 2^>nul') do set "RUNTIME_STATE=%%S"
  if /I "!RUNTIME_STATE!"=="current" (
    echo   backend belongs to this project and is current; no restart needed
    goto :done
  )
  echo   state=!RUNTIME_STATE!; close the verified "Agent Backend" window, then run start.cmd again
  goto :done
)
curl -sf "%BE_URL%" >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%S in ('uv run python scripts/check_backend_runtime.py "%BE_URL%" 2^>nul') do set "RUNTIME_STATE=%%S"
  if /I "!RUNTIME_STATE!"=="current" echo   backend already running (current project/runtime), skip
  if /I not "!RUNTIME_STATE!"=="current" echo   backend state=!RUNTIME_STATE!; no automatic reuse, inspect/restart explicitly
  goto :done
)
start "Agent Backend" cmd /k "cd /d %ROOT% && uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000"
set /a W=0
:wait_be
curl -sf "%BE_URL%" >nul 2>&1
if not errorlevel 1 goto :be_ok
set /a W+=1
if !W! GEQ 30 goto :be_ok
timeout /t 2 /nobreak >nul
goto :wait_be
:be_ok
echo   backend ready

:done
echo.
echo ================================================
echo  All up:
echo    App   http://127.0.0.1:8000
echo    Stop: close the "Agent Backend" window
echo ================================================
pause
exit /b 0

:fail
echo [ERROR] step failed, check output above
pause
exit /b 1
