@echo off
rem 一键启动（Windows 双击）。实际逻辑在 start.sh，经 git-bash 执行。
chcp 65001 >nul
cd /d "%~dp0"
where bash >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 git-bash（bash），请用 Git Bash 运行 start.sh
  pause
  exit /b 1
)
bash ./start.sh
pause
