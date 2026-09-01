# Linux/macOS 本地运行

硬支持平台是 Linux；macOS 使用同一套 POSIX shell 入口，属于尽力兼容。要求 Python 3.12+、Node.js 20+、uv 和 npm。

在仓库根目录执行：

```sh
cp examples/settings.example.json ~/.LiBao/settings.json
# 只在 ~/.LiBao/settings.json 中填写本机 LLM/Embedding key
./scripts/bootstrap.sh
./scripts/dev.sh
```

DevPanel 会启动真实 FastAPI 和 Vite。开发浏览器访问 `http://127.0.0.1:5173`，Vite 的 `/api` 代理到本地后端 `127.0.0.1:8000`。所有服务只绑定回环地址，不支持公网或多用户部署。

常用检查和发布：

```sh
./scripts/test.sh
./scripts/build-release.sh --version 0.1.0
```

所有 `.sh` 文件的 executable bit 已纳入 Git；如果工作区丢失权限，可执行 `chmod +x scripts/*.sh apps/backend/start.sh`。端口可用 `LIBAO_BACKEND_PORT`、`LIBAO_FRONTEND_PORT`、`LIBAO_DEVPANEL_PORT` 修改。真实 E2E 的 `E2E_BACKEND_URL`、`E2E_FRONTEND_URL` 只接受 `http://127.0.0.1:<port>`。
