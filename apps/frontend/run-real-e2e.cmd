@echo off
setlocal
cd /d "%~dp0"
if "%E2E_BACKEND_URL%"=="" set "E2E_BACKEND_URL=http://127.0.0.1:8000"
set "VITE_API_PROXY=%E2E_BACKEND_URL%"
set "VITE_USE_MOCK=false"
call npx playwright test --config playwright.real.config.ts %*
exit /b %ERRORLEVEL%
