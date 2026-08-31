# 后端结构

兼容入口是 `apps/backend/app/api/main.py`，继续提供 `app.api.main:app` 和 `create_app()`。实际装配按职责拆分为：

- `app/api/factory.py`：创建 FastAPI 实例并挂载可选 SPA；
- `app/api/lifespan.py`：运行时初始化、恢复和后台任务生命周期；
- `app/api/middleware.py`：trace id、统一错误信封和异常处理；
- `app/api/router_registry.py`：集中注册 REST/SSE 路由。

| 目录 | 职责 |
|---|---|
| `app/api` | Router、请求 schema、依赖和 REST/SSE 传输层 |
| `app/orchestration` | LangGraph 主图、上下文、任务和流式事件 |
| `app/services` | 对话、任务、工作区、工具、记忆、知识库等业务服务 |
| `app/tools` | 内置工具、MCP、执行器和沙箱 |
| `app/storage` | FileStore、JSONL、模型、仓储和向量索引 |
| `app/core` | 配置、日志、错误、LLM、Embedding 和运行时基础设施 |

配置和数据默认使用 `~/.LiBao`。当前不提供公网多用户安全边界；扩展认证、租户和多实例能力前，不能改变这一运行定位。
