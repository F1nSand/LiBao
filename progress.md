# 进度账本 — plan: C:\Users\Admin1\.claude\plans\immutable-inventing-breeze.md

目标：M2 核心闭环 —— 工具管理（CRUD/test/search）+ require_confirm→interrupt→resume（task 实体+状态机+tasks 最小 API）+ 执行器重试/幂等 + Agent 版本化管理（POST/PUT/DELETE/publish/unpublish/invoke）。对接已完整实现的 FrontEnd 工具/任务/Agent 页。

全局约束：五层单向依赖 API→编排→服务→工具→存储；sessionless（幂等缓存/live-tail 为唯一内存态接缝）；trace_id 全链路；信封契约；resume 双轨（Accept 区分 SSE/JSON）；静态前缀字节稳定；错误码 40405/40903 新增、40402/40901/40902/60002 消费。

**本轮不做**（M2.5）：Docker 沙盒、MCP、tool_search 元工具、任务系统完整形态（M4）。

## M1 历史（已完成，勿重做）
T1-T13 + review-test-simplify gate 全部完成；start.cmd/start.sh 一键启动；git 到 aaa26a6 工作区干净。

## 任务清单
- [x] T1 错误码与配置（40405/40903 + task_confirm_ttl_hours=24）
- [x] T2 工具服务层（tool_definition repo + ToolService + tl_ id 派生 + registry set_enabled 同步桥）
- [x] T3 工具路由（/tools CRUD/test/search）
- [ ] T4 执行器重试/幂等/沙盒守卫
- [ ] T5 tool_execute 节点 require_confirm 分支 + finalize 透传 cancelled
- [ ] T6 流式核心抽取（stream_core）+ chat 中断落任务 + resume_stream_events ★
- [ ] T7 任务服务 + 后台运行器（task_run）+ 任务路由（双轨 resume + events 回放/live-tail）
- [ ] T8 Agent 写接口 + 版本化 + invoke
- [ ] T9 内置确认演示工具（tl_demo_notify）+ seed
- [ ] T10 收尾 gate（ruff + 全量测试 ≥20 + README 接缝表 + 端到端验证）

## 执行记录
- T1 完成：40405/40903 + task_confirm_ttl_hours=24 ✅
- T2 完成：ToolDefinitionRepository + ToolService（tl_ id 派生/默认关闭/启停同步桥/echo test）+ serialize_tool_definition + registry.set_enabled；pytest 6 项新测试 ✅
- T3 完成：/tools CRUD/test/search 路由（search 在 {tool_id} 前）+ main.py 注册；httpx 实测 CRUD/echo/真执行/搜索/ACI/40405 全过 ✅
- T4 进行中：执行器重试/幂等/沙盒守卫
