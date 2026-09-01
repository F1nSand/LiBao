# Windows 本地运行

要求：Python 3.12+、Node.js 20+、uv 和 npm。首次运行：

1. 创建 `%USERPROFILE%\.LiBao`。
2. 将 `examples/settings.example.json` 复制为 `%USERPROFILE%\.LiBao\settings.json`。
3. 只在该用户配置文件中填写 LLM/Embedding key。
4. 在仓库根目录运行 `scripts/bootstrap.cmd`。
5. 运行 `scripts/dev.cmd`，打开 DevPanel 后启动全部服务。DevPanel 启动真实后端和 Vite，前端 `/api` 通过 Vite 代理到后端。

后端默认监听 `127.0.0.1:8000`，前端默认监听 `127.0.0.1:5173`。不要把这些服务直接绑定到公网地址。

可用 `LIBAO_BACKEND_PORT`、`LIBAO_FRONTEND_PORT`、`LIBAO_DEVPANEL_PORT` 修改本地端口；主配置仍唯一来自 `%USERPROFILE%\.LiBao\settings.json`。
