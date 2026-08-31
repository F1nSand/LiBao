@echo off
setlocal
set "ROOT=%~dp0.."

pushd "%ROOT%\apps\backend"
uv run ruff check .
if errorlevel 1 goto :fail
uv run pytest tests/
if errorlevel 1 goto :fail
popd

pushd "%ROOT%\apps\frontend"
call npm.cmd run lint:check
if errorlevel 1 goto :fail_frontend
call npm.cmd run typecheck
if errorlevel 1 goto :fail_frontend
call npm.cmd run build
if errorlevel 1 goto :fail_frontend
call npm.cmd run test:unit
if errorlevel 1 goto :fail_frontend
call npm.cmd run test:e2e
if errorlevel 1 goto :fail_frontend
popd
echo All tests passed.
exit /b 0

:fail
popd
:fail_frontend
echo Tests failed.
exit /b 1
