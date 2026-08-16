# Agent Backend · 通用 Agent 框架后端

M0（地基）+ M1（最小闭环）实现。Python 3.12 + FastAPI + LangGraph + LiteLLM + Postgres16(pgvector) + Redis。
对接兄弟目录 `FrontEnd/`（Vue3 管理工作台）的 `/api/v1` 契约。

## 快速启动

前置：Docker Desktop（提供 db/redis）、Python 3.12（uv 管理）、LLM 可用（DeepSeek key 或 Ollama，见 `.env`）。

### 一键启动（推荐）

| 方式 | 说明 |
|---|---|
| **双击 `start.cmd`** | 纯 Windows 批处理，无需 git-bash。自动打开「Agent Backend」「Agent Frontend」两个服务窗口，关闭即停 |
| `bash start.sh` | git-bash 下运行，所有服务共用一个窗口，Ctrl+C 全部停止 |

两者逻辑相同：db/redis 拉起（等待 healthy）→ `alembic upgrade head` + 幂等种子 → 后端 `:8000` → 前端 `:5173`（`VITE_USE_MOCK=false` 走真实后端）。已在运行的服务自动跳过。

### 手动分步

```bash
# 1. 基础设施（首次会拉镜像；国内网络用镜像一次性 pull+retag，见文末「环境备注」）
docker compose up -d db redis && docker compose ps          # 双 healthy

# 2. 依赖 + 迁移 + 种子（幂等）
uv sync
uv run alembic upgrade head
uv run python -m app.seed                                     # org + admin/dev/viewer + 内置工具 + 通用助手(单)

# 3. LLM 配置
cp .env.example .env        # 填 LLM_API_KEY（DeepSeek）；LLM_MODEL 需带提供方前缀，如 deepseek/deepseek-chat

# 4. 启动后端
uv run uvicorn app.api.main:app --port 8000
curl localhost:8000/api/v1/system/health                     # {code:0,...}

# 5. 前端闭环（mock 关闭走真实后端）
cd ../FrontEnd && VITE_USE_MOCK=false npm run dev            # http://localhost:5173
# admin/admin123 登录 → 发「现在几点？」→ 流式输出 + time_now 工具卡 → 刷新页面消息回放（单通用助手，无需选 Agent）
```

**前后端连接**：前端 vite dev（`VITE_USE_MOCK=false`）把 `/api` 代理到 `http://localhost:8000`；后端 CORS 已放行 `http://localhost:5173`。浏览器只开 `http://localhost:5173`。

测试：`uv run pytest tests/`（工具/编排/SSE 序列单测 + 需 DB 的集成测试，DB 不可达自动跳过）。

## 架构（docs 00 五层单向依赖）

```
API → 编排 → 服务 → 工具 → 存储   （禁止反向）
```

| 层 | 目录 | 关键文件 |
|---|---|---|
| API | `app/api/` | `main.py`(create_app+lifespan+中间件+异常信封)、`routers/`(auth/conversations/chat/system) |
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

## M2 已落地 + M2.5 已落地 + M3+ 接缝

### M2 核心闭环（已完成）
- 工具管理：`GET/POST /tools`、`GET/PUT/PATCH/DELETE /tools/{id}`、`POST /tools/{id}/test`、`GET /tools/search`；DB 元数据 + registry 执行实现按 name 绑定，启停同步桥（默认关闭原则实时生效）
- 中断/恢复：`require_confirm` 工具 → `interrupt()` → Task 行（waiting_confirm + pending_confirm）→ SSE `interrupt` 事件（带 task_id）→ `POST /tasks/{id}/resume`（`Accept: text/event-stream` 续流 / JSON 后台续跑）→ done/cancelled；拒绝分支卡片状态 `cancelled`
- 任务：`POST/GET /tasks`、`GET /tasks/{id}`、`POST cancel`（40902）、`GET /tasks/{id}/events`（回放+live-tail）；后台运行（asyncio.create_task，完整队列为 M4）
- 执行策略：失败静默重试（指数退避+抖动，`ToolSpec.max_retries`）+ 幂等去重（进程内缓存）+ 沙盒守卫
- 单通用 Agent + Subagent 派发：所有会话/任务固定「通用助手」（不再有 /agents 管理端点）；内置 `tl_dispatch_subagent` 工具派发 subagent（research/code_review/proposal_review，嵌套 LLM 循环 + 上下文隔离 + agent_switch 事件）

### M2.5 核心闭环（本轮完成）
- **MCP client**：`POST /tools/mcp/register {name?, url_or_command, headers?, enable}`（stdio 命令 / http(s) URL 双传输，验证即注册）、`GET /tools/mcp`、`DELETE /tools/mcp/{server_id}`；远程工具 → `tool_definition` 行（`mcp_source="mcp:{server_id}"` + `mcp_tool_name` 原始名）+ registry spec（`mc_<server>_<tool>`），生命周期与内置工具完全一致（默认关闭/agent 勾选/confirm/幂等/超时复用）；同名遮蔽拒绝 40903（I7）；启动同步自动重建 spec
- **熔断（I7）**：`MCPManager` 按源计数，连续失败达 `mcp_breaker_threshold`（3）→ OPEN，冷却 `mcp_breaker_cooldown_s`（60）后 HALF_OPEN 放行一次；熔断中返回"MCP 源熔断中"，不静默使用
- **tool_search 元工具**：内置 `tl_tool_search`（常驻启用），返回匹配工具的名称+路由描述（不含 params_schema）；I4 降级（空→提示创建 / 检索挂→全量目录 / disabled→标注）
- **两段式 ACI 注入（渐进式披露）**：启用工具数 ≤ `aci_full_limit`（30）→ 全量 ACI（现状零变化）；超过 → `tool_search` 常驻 + tool_search 匹配选中（`selected_tool_names`，上限 5）注入 bind_tools（每轮重算，不跨轮缓存 active_tools）

### M3 核心闭环（本轮完成）
- **记忆**：`/memory/traces`（append-only 轨迹，chat 每轮落 user+assistant 各一条）、`/memory/longterm` CRUD（json_card/note，版本化只增 + 软删）、`/memory/longterm/{id}/versions`、`/memory/maintenance`（LLM 整理：重要性评分/合并/抽象，`_extract_json` 剥围栏）；**memory_inject 图节点**每轮注入 importance top-N 卡片（历史后/状态栏前渲染；user_id 缺失/桥未设静默跳过，注入永不击穿对话）
- **RAG**：`/kb/collections` CRUD、`/kb/collections/{id}/documents` 上传（txt/md，UTF-8 严格，内容入库零磁盘）、文档状态机 uploaded→chunking→indexing→indexed/failed/archived（后台 `process_document`：字符滑窗 512/64 → SiliconFlow Qwen3-Embedding-0.6B 向量化 → 批量插库）、`/kb/search` 混合检索（语义 HNSW cosine + BM25 tsvector/ts_rank + RRF k=60 融合，语义通道故障降级 bm25-only）、**kb_search 内置工具**（ContextVar org 上下文 + sessionmaker 桥，Agentic RAG 预留）
- **附件**：`/uploads`（multipart，20MB/40011、类型白名单/40012）、`/attachments/{id}` 二进制流、`/{id}/analysis` 轮询契约（uploaded→analyzing→ready/failed，60004）、图片 I2 视觉降级（"无法分析"完成态）、txt/md 提取、pdf/office 仅 metadata；**chat 消息 attachments 链路接通**（校验 40403 → 落库 → 附件回填 conversation_id/message_id）

### M3.5+ 接缝（下轮）
| 接缝 | 现状 | 落地位置 |
|---|---|---|
| **MinIO 对象存储** | 本地磁盘 `{upload_dir}/{attachment_id}`（MVP） | `services/attachment.py` → M4 加 MinIO/预签名 |
| **视觉模型（VLM）** | `analyze_image` 走 I2 降级文本（ready + reason=no_vision_model） | `storage/attachment_analysis.py::analyze_content` |
| **Cross-Encoder 重排序** | rerank_score 恒 null | `storage/repositories/kb.py::hybrid_search` |
| **对话自动记忆提取** | 仅手动卡片 + maintenance；context_update 自动提取未做 | `orchestration/nodes/context_update.py` |
| **PDF/Office 文本提取** | 仅 metadata（reason 标注） | `services/attachment.py`；引入 pypdf 即可 |
| **Docker 沙盒** | executor 对 `sandbox != none` 返回"暂未实现" | `tools/sandbox.py`（SandboxLevel 已备） |
| **MCP 会话复用** ✅ M4 完整版 | owner-task 池（连接 cancel scope 常驻 owner 任务，规避跨请求复用报错）+ 请求队列串行；stdio 免每次起子进程 | `tools/mcp_manager.py` |
| **MCP 资源/提示原语** | 只映射工具（E2） | 资源→RAG 数据源、提示→Skill 库（M6） |
| **幂等持久化** | 进程内缓存（TTL 1h/1024 条），重启丢失 | `tools/executor.py` `_idem_cache` → M4 换 Redis |
| **live-tail 多实例** | 单进程订阅表 | `services/task.py` `_tails` → M4 Redis 广播 |
| **max_concurrency** ✅ M4 完整版 | 进程内 per-spec Semaphore 已强制（executor 幂等后包重试循环；默认 10） | `tools/executor.py` `_semaphore` |
| **多确认** | 每节点每轮只确认第一个 require_confirm 工具 | `nodes/tool_execute.py` `confirmed_once` |
| **任务取消 in-flight** ✅ M4 完整版 | `task_worker._RUNNING` 注册表 + `POST /tasks/{id}/cancel` `fut.cancel()` 真正中断运行中的图 | `orchestration/task_worker.py` |
| **Webhook/事件触发（docs 03 §5.10）** | 4 端点（hooks CRUD + 事件接收）未实现 | `api/routers/hooks.py`（后续） |
| **事件安全点/裁决器** ✅ M4 完整版最小闭环 | 进程内收件箱 + route 轮边界排空 + 规则裁决（regular 进 context；urgent/light 预留）；`initiate_demo` 占位→回填工具已落地 | `services/events.py` + `nodes/route.py` + `builtin/initiate_demo.py` |
| **任务亲和调度** | 单实例 MVP 下 worker 天然单消费者（BRPOP）；多实例需实例 id + task:claim + per-instance 队列 | 本轮不做，接缝标注（docs 05） |
| **agent_switch 持久化** | 纯流式事件，Message 无持久化字段 | 协调项（前端 done 后指示条消失）；需则加 message JSONB 列 |
| **占位 TTL 看门狗** | `initiate_*` 占位→回填已落地，TTL 超时置失败未做 | `placeholder_events`（task 表）+ 定时器（后续） |
| **M5 评估/日志** | `run_log` 扁平表已建（type 含 retrieval/memory） | `/system/evals` 在 docs 03 §5.8 |
| **M6 RBAC/进化** | `user.role` 已存 | `api/deps.py` |

其他：Redis 服务已起未用（M4 多实例 SSE 广播 / 任务队列）；CORS 已配 `localhost:5173`。

## 环境备注（Windows / 国内网络）

- **Docker Hub 国内不可达**：首次拉 `pgvector/pgvector:pg16`、`redis:7` 可用 `docker.m.daocloud.io` 前缀一次性 pull 后 retag 到本地（未改 daemon.json）。
- **Windows 事件循环**：psycopg async 需 SelectorEventLoop。`app/api/main.py` 已 patch `uvicorn.config.LOOP_FACTORIES["auto"/"asyncio"]` 指向 selector，`uvicorn app.api.main:app` 直接可跑。
- **LLM 模型前缀**：LiteLLM 模型 id 必须带提供方前缀（`deepseek/deepseek-chat`）；推理模型返回 content blocks，SSE 流式只取 text。
