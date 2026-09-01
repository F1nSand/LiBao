@echo off
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%\tools\devpanel"
uv run python main.py %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
