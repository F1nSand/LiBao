@echo off
setlocal

docker build -t libao-sandbox:py312-v1 -f docker/sandbox/Dockerfile docker/sandbox
if errorlevel 1 exit /b %errorlevel%
