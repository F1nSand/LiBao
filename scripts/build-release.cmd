@echo off
setlocal
set "ROOT=%~dp0.."
python "%ROOT%\scripts\build-release.py" %*
exit /b %ERRORLEVEL%
