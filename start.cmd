@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ============================================================
rem  Agent Platform one-click start (pure cmd, no bash needed)
rem  infra(db/redis) -> migrate/seed -> backend(:8000) -> frontend(:5173)
rem  Stop: close the "Agent Backend" / "Agent Frontend" windows
rem ============================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
set "FRONTEND=%ROOT%..\FrontEnd"
set "BE_URL=http://127.0.0.1:8000/api/v1/system/health"
set "FE_URL=http://127.0.0.1:5173/"

echo ================================================
echo  Agent Platform - one-click start
echo ================================================

rem ---- 1. infra ----
echo [1/4] infra db + redis
docker info >nul 2>&1
if errorlevel 1 (
  echo   [WARN] Docker not running, skip infra
  goto :migrate
)
docker compose -f "%ROOT%docker-compose.yml" up -d db redis >nul
set /a W=0
:wait_db
docker inspect -f "{{.State.Health.Status}}" agent-db 2>nul | findstr /c:"healthy" >nul
if not errorlevel 1 goto :db_ok
set /a W+=1
if !W! GEQ 30 (
  echo   [WARN] db not healthy, see 'docker compose ps'
  goto :migrate
)
timeout /t 2 /nobreak >nul
goto :wait_db
:db_ok
echo   db healthy

rem ---- 2. migrate + seed (idempotent) ----
:migrate
echo [2/4] alembic upgrade + seed (idempotent)
call uv run alembic upgrade head || goto :fail
call uv run python -m app.seed || goto :fail

rem ---- 3. backend ----
echo [3/4] backend :8000
curl -sf "%BE_URL%" >nul 2>&1
if not errorlevel 1 (
  echo   backend already running, skip
  goto :frontend
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

rem ---- 4. frontend ----
:frontend
echo [4/4] frontend :5173 (VITE_USE_MOCK=false -> real backend)
if not exist "%FRONTEND%node_modules" (
  echo   first run: npm install...
  pushd "%FRONTEND%"
  call npm install || goto :fail
  popd
)
curl -sf "%FE_URL%" >nul 2>&1
if not errorlevel 1 (
  echo   frontend already running, skip
  goto :done
)
rem NOTE: `set VAR=value&&` (no space) sets the value to exactly "false"; with a space
rem before && it becomes "false " (trailing space) which vite misreads as mock enabled.
start "Agent Frontend" cmd /k "cd /d %FRONTEND% && set VITE_USE_MOCK=false&&npm run dev"

:done
echo.
echo ================================================
echo  All up:
echo    Frontend  http://localhost:5173  (admin/admin123)
echo    Backend   http://localhost:8000/api/v1/system/health
echo    Stop: close the two service windows above
echo ================================================
pause
exit /b 0

:fail
echo [ERROR] step failed, check output above
pause
exit /b 1
