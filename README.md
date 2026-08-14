# Agent Backend · 通用 Agent 框架后端

M0（地基）+ M1（最小闭环）实现。Python 3.12 + FastAPI + LangGraph + LiteLLM + Postgres16(pgvector) + Redis。
对接兄弟目录 `FrontEnd/`（Vue3 管理工作台）的 `/api/v1` 契约。

## 快速启动

前置：Docker Desktop（提供 db/redis）、Python 3.12（uv 管理）、LLM 可用（DeepSeek key 或 Ollama，见 `.env`）。

### 一键启动（推荐）

```bash
bash start.sh            # git-bash；Windows 也可双击 start.cmd
```

自动完成：db/redis 拉起（等待 healthy）→ `alembic upgrade head` + 幂等种子 → 后端 `:8000` → 前端 `:5173`（`VITE_USE_MOCK=false` 走真实后端）。Ctrl+C 全部停止。已运行的服务会跳过。

### 手动分步

```bash
# 1. 基础设施（首次会拉镜像；国内网络用镜像一次性 pull+retag，见文末「环境备注」）
docker compose up -d db redis && docker compose ps          # 双 healthy

# 2. 依赖 + 迁移 + 种子（幂等）
uv sync
uv run alembic upgrade head
uv run python -m app.seed                                     # org + admin/dev/viewer + time_now + 时间助手

# 3. LLM 配置
cp .env.example .env        # 填 LLM_API_KEY（DeepSeek）；LLM_MODEL 需带提供方前缀，如 deepseek/deepseek-chat

# 4. 启动后端
uv run uvicorn app.api.main:app --port 8000
curl localhost:8000/api/v1/system/health                     # {code:0,...}

# 5. 前端闭环（mock 关闭走真实后端）
cd ../FrontEnd && VITE_USE_MOCK=false npm run dev            # http://localhost:5173
# admin/admin123 登录 → 选「时间助手」→ 发「现在几点？」→ 流式输出 + time_now 工具卡 → 刷新页面消息回放
```

**前后端连接**：前端 vite dev（`VITE_USE_MOCK=false`）把 `/api` 代理到 `http://localhost:8000`；后端 CORS 已放行 `http://localhost:5173`。浏览器只开 `http://localhost:5173`。

测试：`uv run pytest tests/`（工具/编排/SSE 序列单测 + 需 DB 的集成测试，DB 不可达自动跳过）。

## 架构（docs 00 五层单向依赖）

```
API → 编排 → 服务 → 工具 → 存储   （禁止反向）
```

| 层 | 目录 | 关键文件 |
|---|---|---|
| API | `app/api/` | `main.py`(create_app+lifespan+中间件+异常信封)、`routers/`(auth/conversations/agents/chat/system) |
| 编排 | `app/orchestration/` | `graph.py`(单主图)、`chat_stream.py`(★ SSE 桥)、`nodes/`、`checkpointer.py`、`context_builder.py` |
| 服务 | `app/services/` | `user.py`/`conversation.py`/`agent.py` + `serializers.py` |
| 工具 | `app/tools/` | `registry.py`(ToolSpec+aci)、`executor.py`、`sandbox.py`、`builtin/time_now.py` |
| 存储 | `app/storage/` | `db.py`、`base.py`、`models/`(9 实体)、`repositories/` |
| 横切 | `app/core/` | `config.py`/`security.py`(JWT+bcrypt)/`logging.py`(trace_id)/`llm.py`/`errors.py`/`events.py` |

## M1 关键机制

- **SSE 事件序列**（docs 03 §3）：`message_start → token* → tool_call → tool_result → status → done/error`；keepalive 15s；`seq` 单调。
- **Sessionless 持久化**：`conversation.id = LangGraph thread_id`；消息即日志（message-as-log），刷新/重启可完整回放；checkpoint 与业务同库。
- **静态前缀稳定**：system_prompt + 工具 ACI 字节稳定 → KV Cache 友好；`agent_version.prefix_hash` 作缓存键。
- **trace_id 全链路**：ASGI 中间件注入 → REST 信封/SSE 事件 → run_log 落库。

## M2+ 接缝（本轮未实现，架构已预留）

| 里程碑 | 已预留接缝 | 落地位置 |
|---|---|---|
| **M2 工具系统** | 工具 CRUD/沙箱/重试/interrupt-resume | `ToolSpec` 已含 sandbox/require_confirm/allowlist/idempotent；`tools/sandbox.py` none 之外抛 NotImplementedError；`tool_execute` 预留 require_confirm → interrupt |
| **M2 Agent 版本化** | `PUT /agents` 建新版本 + A/B/回滚 | `agent_versions` 表 + `prefix_hash` 已建 |
| **M3 记忆/RAG/附件** | 三层记忆、混合检索、附件管线、MinIO | `memory`/`kb_*`/`attachment` 实体在 docs 04 定义；本轮未建表 |
| **M4 任务/多 Agent** | 异步任务、SSE 订阅、多 Agent 模板 | `task`/`tool_definition`/`run_log` 表已建；`graph.py` route 节点预留多 Agent 挂载 |
| **M5 评估/日志** | 评估运行、span 树、成本统计 | `run_log` 扁平表已建；`/system/evals` 接口在 docs 03 §5.8 |
| **M6 RBAC/持续进化** | 完整权限、在线评估迭代 | `user.role` 已存字段；RBAC 约束在 `api/deps.py` |

其他：Redis 服务已起未用（M4 多实例 SSE 广播 / 任务队列）；CORS 已配 `localhost:5173`。

## 环境备注（Windows / 国内网络）

- **Docker Hub 国内不可达**：首次拉 `pgvector/pgvector:pg16`、`redis:7` 可用 `docker.m.daocloud.io` 前缀一次性 pull 后 retag 到本地（未改 daemon.json）。
- **Windows 事件循环**：psycopg async 需 SelectorEventLoop。`app/api/main.py` 已 patch `uvicorn.config.LOOP_FACTORIES["auto"/"asyncio"]` 指向 selector，`uvicorn app.api.main:app` 直接可跑。
- **LLM 模型前缀**：LiteLLM 模型 id 必须带提供方前缀（`deepseek/deepseek-chat`）；推理模型返回 content blocks，SSE 流式只取 text。
