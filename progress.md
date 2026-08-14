# 进度账本 — plan: C:\Users\Admin1\.claude\plans\agent-c-users-admin1-desktop-agent-docs-nested-charm.md

目标：在 Agent/ 目录从零搭建通用 Agent 框架后端，M0（地基）+ M1（最小闭环：单Agent对话+SSE流式+Postgres持久化+time_now 工具），对接现有 FrontEnd 契约。

全局约束：五层单向依赖 API→编排→服务→工具→存储；sessionless；静态前缀稳定；验证先于置信；trace_id 全链路；严格对齐 docs 03 契约。

前置条件：① Docker Desktop 用户手动安装（本机无 Docker）② Python 3.12（uv 安装）③ LLM 可用（DeepSeek key 或本地 Ollama，需支持工具调用）——执行中确认。

## 任务清单
- [x] T1 脚手架 + git（uv init + 依赖 + .gitignore/.env.example/app骨架）
- [x] T2 基础设施 docker-compose（db: pgvector/pg16 + redis:7；2026-08-13 已起容器双 healthy ✅）
- [x] T3 核心横切（config/security/logging/errors/events/envelope/deps）
- [x] T4 存储层（db/base/ORM models/repositories）
- [x] T5 Alembic 迁移（async env + 0001_init_schema）
- [x] T6 种子数据（seed.py 幂等）
- [x] T7 LLM 封装（core/llm.py）
- [x] T8 工具层（registry/executor/sandbox/time_now）
- [x] T9 编排层（state/graph/nodes/context_builder/checkpointer）
- [x] T10 SSE 桥（orchestration/chat_stream.py）
- [x] T11 API 层（routers + main.py + schemas）
- [x] T12 集成验证（端到端验收）
- [x] T13 README 记录 M2+ 接缝

## 执行记录
- T1 完成（commit：chore scaffold）
- T2 完成（docker-compose 已写；health 验证延至 T12，Docker 安装中）
- T3 完成（core 横切全通过）
- T4 完成：models 补全 tool_definition/task/run_log + __init__ 导出 9 实体；repositories(user/conversation/message/agent/run_log) + owner 过滤；冒烟通过（import + configure_mappers 9 表可解析，ruff clean）
- T5 完成：alembic.ini + async env.py（URL 注入自 app config）+ autogenerate 0001_init_schema；upgrade head / downgrade -1 / 再 upgrade 均干净 ✅
- T6 完成：seed.py 幂等（org 默认组织 + admin/dev/viewer + time_now 工具 enabled + 时间助手 published v1 含 prefix_hash）；psql 核对 UTF-8/哈希正确，双跑幂等 ✅
- T7 完成：LLMService.build_model → ChatLiteLLM；DeepSeek ainvoke 实测返回 ✅（用户 .env 填了 key；model 需带前缀 `deepseek/`，已从 `deepseek-v4-flash` 改为 `deepseek/deepseek-v4-flash`）
- T8 完成：registry(ToolSpec+aci/acis 按 id 排序) + executor(jsonschema→wait_for 超时→ToolResult) + sandbox(none/docker/microvm) + builtin tl_time_now；pytest 6 项全过 ✅
- T9 完成：state_schema + context_builder(compute_prefix_hash 与 seed 同算法) + 5 nodes + graph(build_graph) + checkpointer(PostgresCheckpointer/from_conn_string)；pytest 3 项全过（编译/mock 工具调用全程/前缀字节稳定）；真库 AsyncPostgresSaver + thread_id 走通，checkpoint 4 表已建 ✅
- ⚠ Windows 关键坑：psycopg async 需 SelectorEventLoop，而 Windows 默认 ProactorEventLoop → main.py 启动前必须 `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`（T11 落地）
- ⚠ LangGraph 节点 config 参数必须标注 `Optional[RunnableConfig]`（`RunnableConfig | None` 不被识别注入）；ruff UP045 已 noqa
- ⚠ deepseek-v4-flash 为推理模型，AIMessage.content 是 content blocks 列表（thinking + text）；T10 流式需只取 text 部分
- T10 完成：chat_stream.py（producer/queue + 15s keepalive + messages/updates/values 三模式映射 + 持久化用户/assistant 消息 + run_logs + last_message_at）；pytest 序列精确断言过 ✅；全部 10 项测试通过
- ⚠ LangGraph stream_mode="updates" 产出的是 {node: update} dict，不是 (node, update) 元组
- T11 完成：schemas + services(user/conversation/agent/serializers) + routers(auth/conversations/agents/chat/system) + main.py；uvicorn 实测：health/login(错码 40101 HTTP200)/me/agents/conversations CRUD(owner 隔离 40401、坏 agent 40404)/chat/stream 全过 ✅
- ⚠ Windows 双坑落地：uvicorn 用自身 loop 工厂忽略事件循环策略 → main.py 里 patch `uvicorn.config.LOOP_FACTORIES["auto"/"asyncio"]` 指向 SelectorEventLoop；`uvicorn app.api.main:app` 直接可跑
- ✅ M1 端到端实测：真实 DeepSeek 一次工具调用流式事件序列 = message_start→tool_call→tool_result→token*→status→done；双轮会话持久化 + 跨轮 resume（LLM 记得上一轮工具）+ run_logs 按 trace_id 落库
- T12 完成：端到端 1-8 项全过 ✅ —— 后端 1-7（compose healthy/alembic/seed/uvicorn+health/login+信封/conversations+SSE chat+重启持久化）+ **第 8 项前端闭环**（2026-08-14 Playwright 无头浏览器实测：登录 → 选时间助手 → 发"现在几点？"→ time_now 工具卡 + 真实 DeepSeek 流式回答 → 刷新 → 从会话列表点开消息回放 ✓）
- T13 完成：README.md（快速启动/架构/M1 机制/M2+ 接缝表/环境备注）
- 环境备注：Docker Hub 国内不可达；本次用 daocloud 镜像一次性 pull + retag 到本地（未改 daemon.json）
- **M1 全部任务完成** → review-test-simplify 收尾 gate：
  - Gate1 Test：pytest 10 项全过 ✅
  - Gate2 Review：两 agent 发现 9 项（多轮 tool_results/run_logs 残留 · 会话列表未序列化 · 401 非信封/坏 sub 500 · 登录未校验 enabled · 种子工具名 tl_time_now vs time_now · 工具越权执行 · JWT 默认密钥 · 孤儿会话 · keepalive 未 await）——全部修复并实测验证 ✅
  - Gate3 Simplify：4 agent 去重 6 项（create 复用已校验 agent 消除双查询 · agent_can_use 共享谓词 · compute_prefix_hash 抽 core/prefix.py · 版本快照赋值上提 · 轮次重置移 route_node · UUID 直比）；跳过 2 项（uvicorn LOOP_FACTORIES patch 为文档化运行命令所需；JWT validator 无漂移）
  - 最终回归：ruff clean + pytest 10/10 + E2E（conversations/chat/持久化/坏 agent 40404 无孤儿）✅

## 恢复指引
重启后恢复：读本账本 → `git log` 确认提交 → 从 T4 剩余项继续。
