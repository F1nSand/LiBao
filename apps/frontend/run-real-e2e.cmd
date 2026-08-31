@echo off
setlocal
cd /d "%~dp0"
if "%E2E_BACKEND_URL%"=="" set "E2E_BACKEND_URL=http://127.0.0.1:8000"
call npx playwright test --config playwright.real.config.ts %*
