@echo off
rem ============================================================
rem  Agent 开发面板启动（单窗口）：双击运行，浏览器自动打开面板
rem  四个服务（db/redis/backend/frontend）都在这一个界面里启停
rem  停止：关闭本窗口（同时回收后端/前端进程，容器保持运行）
rem ============================================================
cd /d "%~dp0"
echo ================================================
echo  Agent DevPanel  -  http://127.0.0.1:9100
echo  关闭本窗口 = 停止面板，并回收后端/前端进程
echo ================================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
  echo  [WARN] Docker 未运行，容器服务将无法启动（可稍后在面板里重试）
  echo.
)

uv run python -m devpanel.main --port 9100 %*
pause
