@echo off
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%"

echo [1/3] syncing backend dependencies
uv sync --project apps/backend
if errorlevel 1 goto :fail

echo [2/3] syncing DevPanel dependencies
uv sync --project tools/devpanel
if errorlevel 1 goto :fail

echo [3/3] installing frontend dependencies
call npm.cmd ci --prefix apps/frontend
if errorlevel 1 goto :fail

echo Bootstrap complete.
popd
exit /b 0

:fail
echo Bootstrap failed.
popd
exit /b 1
