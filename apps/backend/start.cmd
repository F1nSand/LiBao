@echo off
setlocal
cd /d "%~dp0"
uv run python scripts\start_backend.py %*
exit /b %ERRORLEVEL%
