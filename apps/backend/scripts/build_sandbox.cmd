@echo off
setlocal

@set ROOT=%~dp0\..\..\..
docker build -t libao-sandbox:py312-v1 -f "%ROOT%\deploy\sandbox\Dockerfile" "%ROOT%\deploy\sandbox"
if errorlevel 1 exit /b %errorlevel%
