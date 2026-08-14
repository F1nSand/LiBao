# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\docs\plans\2026-08-14-m25-core-loop.md

目标：M2.5 核心闭环 —— MCP client（stdio+HTTP 双传输，注册/列表/注销）+ tool_search 元工具 + 两段式 ACI 注入（渐进式披露）。前端 ToolsView 注册弹窗直接对接真实后端。**本轮不做**：Docker 沙盒、M4 队列、MCP 资源/提示原语（M3 接缝）。

全局约束：五层单向依赖 API→编排→服务→工具→存储；DB 为元数据事实源、registry 为可执行宿主；连接会话/熔断为唯一新增进程级内存态（文档化接缝）；信封契约；静态前缀字节稳定；同名遮蔽拒绝（I7）；默认关闭原则（MCP 工具注册即 enabled=false）；ruff（120 列，E/F/I/UP/B，ignore B008）；pytest-asyncio auto + `_db_reachable()` skipif。

## 任务清单
- [ ] T1 依赖 + Settings + 错误码 + mcp_servers 表（迁移 0002）
- [ ] T2 MCP 连接层（mcp_client.py：stdio/http 传输 + 命名派生 + 文本提取）
- [ ] T3 熔断器 + MCPManager（惰性连接/并发锁/熔断 60003）
- [ ] T4 MCP 服务层 + 路由（register/list/unregister + 遮蔽拒绝 40903）
- [ ] T5 启动重建（sync_registry_from_db 扩展）
- [ ] T6 tool_search 元工具 + 两段式 ACI 门控
- [ ] T7 端到端验证（真实 FastMCP + 熔断实测 + 真实 DeepSeek 两段式）
- [ ] T8 收尾 gate（ruff + 全量测试 + 前端验证 + review-test-simplify）

## 执行记录（M2.5）
（T1 起记录）

---

# 以下为 M1/M2 历史（已完成，勿重做）

# 进度账本 — plan: C:\Users\Admin1\.claude\plans\immutable-inventing-breeze.md

目标：M2 核心闭环 —— 工具管理（CRUD/test/search）+ require_confirm→interrupt→resume（task 实体+状态机+tasks 最小 API）+ 执行器重试/幂等 + Agent 版本化管理（POST/PUT/DELETE/publish/unpublish/invoke）。对接已完整实现的 FrontEnd 工具/任务/Agent 页。

全局约束：五层单向依赖 API→编排→服务→工具→存储；sessionless（幂等缓存/live-tail 为唯一内存态接缝）；trace_id 全链路；信封契约；resume 双轨（Accept 区分 SSE/JSON）；静态前缀字节稳定；错误码 40405/40903 新增、40402/40901/40902/60002 消费。

**本轮不做**（M2.5）：Docker 沙盒、MCP、tool_search 元工具、任务系统完整形态（M4）。

## M1 历史（已完成，勿重做）
T1-T13 + review-test-simplify gate 全部完成；start.cmd/start.sh 一键启动；git 到 aaa26a6 工作区干净。

## 任务清单（M2）
- [x] T1 错误码与配置（40405/40903 + task_confirm_ttl_hours=24）
- [x] T2 工具服务层（tool_definition repo + ToolService + tl_ id 派生 + registry set_enabled 同步桥）
- [x] T3 工具路由（/tools CRUD/test/search）
- [x] T4 执行器重试/幂等/沙盒守卫
- [x] T5 tool_execute 节点 require_confirm 分支 + finalize 透传 cancelled
- [x] T6 流式核心抽取（stream_core）+ chat 中断落任务 + resume_stream_events ★
- [x] T7 任务服务 + 后台运行器（task_run）+ 任务路由（双轨 resume + events 回放/live-tail）
- [x] T8 Agent 写接口 + 版本化 + invoke
- [x] T9 内置确认演示工具（tl_demo_notify）+ seed
- [x] T10 收尾 gate（ruff + 全量测试 ≥20 + README 接缝表 + 端到端验证）

## 执行记录（M2）
- T1 完成：40405/40903 + task_confirm_ttl_hours=24 ✅
- T2 完成：ToolDefinitionRepository + ToolService（tl_ id 派生/默认关闭/启停同步桥/echo test）+ serialize_tool_definition + registry.set_enabled；pytest 6 项新测试 ✅
- T3 完成：/tools CRUD/test/search 路由（search 在 {tool_id} 前）+ main.py 注册；httpx 实测 CRUD/echo/真执行/搜索/ACI/40405 全过 ✅
- T4 完成：executor 重试循环（指数退避+抖动，仅 handler 异常可重试）+ 幂等缓存（fingerprint/TTL/上限）+ 沙盒守卫 + ToolSpec.max_retries；pytest 8 项 ✅
- T5 完成：tool_execute require_confirm → interrupt(payload) → approved/denied 分支 + finalize 透传 status；图级测试 3 项（触发/续跑 done/拒绝 cancelled）✅；总测试 27 项
- T6 完成：stream_core.py 共享循环（tool_call.require_confirm 取自 spec / 跳过 cancelled tool_result / __interrupt__ 分支）+ chat_stream 重构 + resume_stream_events（UUID 转换/无会话守卫）；流层测试 3 项（中断落 Task/续流 done/拒绝 cancelled）+ chat_stream 帧序回归不变；总测试 30 项 ✅
- T7 完成：TaskService（状态机/live-tail/resume_precheck I8）+ TaskRepository + task_run.py 后台运行器 + /tasks 路由（双轨 resume + events 回放/live-tail，终态回放即关流）；pytest 5 项 ✅
- T8 完成：AgentService create/update/publish/unpublish/soft_delete/_snapshot（compute_prefix_hash）+ /agents 写路由 + invoke（agent_invoke_events 轻量路径）+ serialize_agent_version name；pytest 5 项 ✅；总测试 40 项
- T9 完成：tl_demo_notify（require_confirm=True, USER_COMMS）+ seed 泛化工具创建 + **修复 seed 缺 org 过滤**（测试数据污染导致 MultipleResultsFound）；种子双跑幂等 ✅；总测试 40 项
- T10 完成：README M2 接缝表 + 端到端验证（真实 DeepSeek）✅
  - 工具 CRUD/test/搜索、Agent 版本化 v1→v2→v3、任务提交→done、cancel 40902 全过
  - interrupt→resume 闭环：chat 流 message_start→tool_call→interrupt（带 task_id）→ resume 确认 → tool_result+token+done（任务 done）/ 拒绝 → 无 tool_result + 卡片 cancelled（任务 cancelled）✅
- ⚠ 深度坑（已修）：DeepSeek 推理模型（deepseek-v4-flash）多轮工具调用报 400 "reasoning_content must be passed back"——
  langchain-litellm 0.7.0 `_convert_message_to_dict` 丢 thinking 且不输出 reasoning_content，且 content 变字符串数组。
  → core/llm.py `_patch_reasoning_content_passthrough`（透传 reasoning_content + content 规范化为纯文本）；顺带 finalize 提取纯文本 content
- ⚠ 已修：task_run 图级异常（LLM 失败）→ stream_core 加 on_error 回调 → 任务置 failed（此前会永远卡 running）
- **M2 核心闭环全部完成**：T1-T10 ✅，40 项测试全绿 → review-test-simplify 收尾 gate：
  - Gate1 Test：40 项全过 ✅
  - Gate2 Review：两 agent 发现 11 项（4 Important + 3 Medium + 4 Low）——全部修复并验证 ✅
    - F1 JSON 轨 resume 读 pending_confirm.thread_id（此前 EmptyInputError→failed）✅
    - F2 time_now 去 idempotent（陈旧时间 bug）✅
    - F3 live-tail 订阅先于终态检查 + resume 推终态哨兵（events 流不挂死）✅
    - F4 runner 启动前重检 status==pending（取消竞态）✅
    - F5 resume_stream_events 加 on_error→failed ✅
    - F6 ToolService.update 同步运行时字段到 registry（patch_spec）✅
    - F7 lifespan DB→registry enabled 启动同步（停用不复活）✅
    - F8 thread 失效→40402 ✅ F9 版本序列化真实 graph_template/max_steps ✅
    - F10 resume on_final 重读任务防覆盖取消 ✅ F11 任务 input 提取 message 文本 ✅
  - 跳过（文档化接缝）：cancel 打断运行中图、同消息双确认、test 端点绕过确认、二次中断滞留原任务
  - 实测：JSON 轨 resume done + events 流即开即关 ✅；40 项测试全绿
  - Gate3 Simplify：4 agent 去重 11 项应用 / 4 项跳过（记录理由）✅
    - 应用：executor 缓存直返、共享 sse_emitter(core/events)、共享 build_initial_state + message_text(stream_core)、
      TaskService.resolve_resume_thread 单点解析、get_by_name O(1) 反向索引、agent flush 清理、resume 尾提交收敛、
      search 复用序列化、**ChatLiteLLM 子类替代全局 monkeypatch**（A2，实测多轮 DeepSeek 通过）
    - 跳过：values 模式（状态小+测试不耦合 checkpointer）、max_concurrency（计划设计延期）、
      DB 读时解析 registry（M2.5 重构）、终态处理器大重构（complete/fail 助手已缓解核心重复）
  - 最终：ruff clean + pytest 40/40 + 子类多轮验证 ✅ → M2 收尾完成
- **Bug 修复轮（2026-08-14 用户报告）**：
  1. 时间工具不可用：根因 = 启动同步全 org 遍历，32 个测试组织 enabled=false 行把 time_now 打成禁用
     → 修复 `sync_registry_from_db` 仅同步默认组织 + 清理 96 行测试污染 + 重跑种子；实测 chat 恢复 tool_call(time_now)→tool_result ✅
  2. 通知工具确认后执行结果不清：实为 time_now 禁用导致 invoke 只见 demo_notify（可调用与选中不符）；
     修复后通知助手 chat interrupt→resume 全闭环 tool_result(带结果)→done ✅
  3. 工具卡重试按钮无反应：前端 retry 事件无监听 → 接线 ToolCallCard→Bubble→List→ChatView，重试=重发最后一条用户消息；
     前端 vue-tsc 通过（FrontEnd 非 git 仓库，改动存盘）
  提交：947e0ec
