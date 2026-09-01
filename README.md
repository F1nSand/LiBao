# LiBao

LiBao 是一个本地优先的通用 Agent Runtime 与 Web 工作台，包含 FastAPI/LangGraph 后端、Vue 3 前端和用于本地开发的 DevPanel。

## 当前支持边界

- Python 3.12+、Node.js 20+、uv、npm
- Windows、Linux、macOS 本地单用户运行
- 默认只绑定 `127.0.0.1`
- 配置与运行数据位于 `~/.LiBao`
- 当前版本不是公网多用户服务：认证、租户隔离和生产级审计尚未作为首发能力提供

## 快速开始

```text
复制 examples/settings.example.json 到 ~/.LiBao/settings.json，并填写 LLM API key
运行 scripts/bootstrap.cmd（Windows）或 scripts/bootstrap.sh（Linux/macOS）
运行 scripts/dev.cmd（Windows）或 scripts/dev.sh（Linux/macOS）
```

DevPanel 会启动真实后端 API、前端 Vite 服务并展示服务日志。开发时浏览器通过 Vite 的同源 `/api` 代理访问后端；不需要额外反向代理。默认地址：

- 开发 Web：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8000/docs>
- DevPanel：<http://127.0.0.1:9100>

发布包只启动 FastAPI：浏览器访问 <http://127.0.0.1:8000>，由后端同时提供 REST/SSE 和 SPA。

不使用 DevPanel 时，可分别进入 `apps/backend` 和 `apps/frontend` 按各自 README 启动。

## 仓库结构

```text
apps/backend/       FastAPI、LangGraph、工具、存储和后端测试
apps/frontend/      Vue 3、Pinia、Vite、Mock 和 Playwright 测试
tools/devpanel/     本地服务监管面板
contracts/          API 契约快照
deploy/             沙箱参考配置（不包含生产反向代理）
docs/               架构、API、测试和运行文档
scripts/            跨平台开发、测试和发布入口
```

## 测试

```text
scripts/test.cmd       Windows
scripts/test.sh        Linux/macOS
```

它们会运行后端 Ruff/pytest、前端 lint/typecheck/build/Vitest 和 Mock E2E。真实后端 E2E 需要本地配置 `~/.LiBao/settings.json`，不会在公共 CI 中自动执行。

正常开发使用真实本地后端；Mock 仅用于单测和 Mock E2E。`VITE_USE_MOCK`、`VITE_API_PROXY`、`E2E_PORT`、`E2E_BACKEND_URL` 的说明见 [测试指南](docs/development/testing.md)。

详细资料见 [文档目录](docs/README.md)、[架构总览](docs/architecture/overview.md) 和 [API 契约](docs/api/contract.md)。

## 安全

不要把 `~/.LiBao/settings.json`、上传文件、工作区数据或任何 API key 提交到 Git。漏洞请按 [SECURITY.md](SECURITY.md) 通过 GitHub Security Advisories 私下报告。

## 许可证

本项目采用 [MIT License](LICENSE)。
