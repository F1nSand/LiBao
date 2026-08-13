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
- T4 完成：models 补全 tool_definition/task/run_log + __init__ 导出 9 实体；repositories(user/conversation/message/agent/run_log) + owner 过滤；冒烟通过（import + configure_mappers 9 表可解析，ruff clean）
- T5 完成：alembic.ini + async env.py（URL 注入自 app config）+ autogenerate 0001_init_schema；upgrade head / downgrade -1 / 再 upgrade 均干净 ✅
- T6 完成：seed.py 幂等（org 默认组织 + admin/dev/viewer + time_now 工具 enabled + 时间助手 published v1 含 prefix_hash）；psql 核对 UTF-8/哈希正确，双跑幂等 ✅
- T7 进行中：core/llm.py（ChatLiteLLM 封装）
- 环境备注：Docker Hub 国内不可达；本次用 daocloud 镜像一次性 pull + retag 到本地（未改 daemon.json）

## 恢复指引
重启后恢复：读本账本 → `git log` 确认提交 → 从 T4 剩余项继续。
