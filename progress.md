# 进度账本 — plan: C:\Users\Admin1\.claude\plans\agent-c-users-admin1-desktop-agent-docs-nested-charm.md

目标：在 Agent/ 目录从零搭建通用 Agent 框架后端，M0（地基）+ M1（最小闭环：单Agent对话+SSE流式+Postgres持久化+time_now 工具），对接现有 FrontEnd 契约。

全局约束：五层单向依赖 API→编排→服务→工具→存储；sessionless；静态前缀稳定；验证先于置信；trace_id 全链路；严格对齐 docs 03 契约。

前置条件：① Docker Desktop 用户手动安装（本机无 Docker）② Python 3.12（uv 安装）③ LLM 可用（DeepSeek key 或本地 Ollama，需支持工具调用）——执行中确认。

## 任务清单
- [x] T1 脚手架 + git（uv init + 依赖 + .gitignore/.env.example/app骨架）
- [x] T2 基础设施 docker-compose（db: pgvector/pg16 + redis:7；health 验证延至 T12，Docker 安装中）
- [x] T3 核心横切（config/security/logging/errors/events/envelope/deps）
- [ ] T4 存储层（db/base/ORM models/repositories）
- [ ] T5 Alembic 迁移（async env + 0001_init_schema）
- [ ] T6 种子数据（seed.py 幂等）
- [ ] T7 LLM 封装（core/llm.py）
- [ ] T8 工具层（registry/executor/sandbox/time_now）
- [ ] T9 编排层（state/graph/nodes/context_builder/checkpointer）
- [ ] T10 SSE 桥（orchestration/chat_stream.py）
- [ ] T11 API 层（routers + main.py + schemas）
- [ ] T12 集成验证（端到端验收）
- [ ] T13 README 记录 M2+ 接缝

## 执行记录
- T1 完成（commit：chore scaffold）
- T2 完成（docker-compose 已写；health 验证延至 T12，Docker 安装中）
- T3 完成（core 横切全通过）
- T4 进行中：base.py/db.py + models(org/user/conversation/message/agent) 已写并提交；**待续**：models/tool_definition.py、models/task.py、models/run_log.py、models/__init__.py、repositories/(user/conversation/agent/run_log) → 然后冒烟验证
- 暂停点：2026-08-13 用户重启电脑，进度已全部提交（T4 部分存档 commit: wip(T4) storage layer）

## 恢复指引
重启后恢复：读本账本 → `git log` 确认提交 → 从 T4 剩余项继续。
