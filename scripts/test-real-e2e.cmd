@echo off
setlocal
set "ROOT=%~dp0.."
python "%ROOT%\scripts\test-real-e2e.py" %*
exit /b %ERRORLEVEL%
