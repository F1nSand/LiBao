@echo off
setlocal
set "ROOT=%~dp0.."
python "%ROOT%\scripts\bootstrap.py" %*
exit /b %ERRORLEVEL%
