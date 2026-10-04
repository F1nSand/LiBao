# LiBao 论文证据矩阵

更新时间：2026-09-17。本文档只记录当前工作树中能够追溯的事实；“待补”表示不能用设计文档或历史记录代替。

## 1. 代码事实

| 主题 | 可引用实现 | 可写结论 | 证据等级 |
| --- | --- | --- | --- |
| 主图编排 | `apps/backend/app/orchestration/graph.py:55-80` | 主流程由 `route`、`memory_inject`、`agent_execute`、`tool_execute`、`context_update`、`finalize` 组成；工具轮受 `max_steps` 守卫 | 代码 |
| 上下文构建 | `apps/backend/app/orchestration/context_builder.py:71-155` | 静态 system prompt、工具 ACI、历史消息、记忆/项目索引和状态栏分层构造；动态内容追加到尾部 | 代码 |
| 任务生命周期 | `apps/backend/app/services/task.py:31-149`；`apps/backend/app/api/routers/tasks.py:103-240` | 任务具有 pending/running/waiting_confirm/cancelled/done/failed 语义，并通过提交、取消、恢复和确认接口驱动 | 代码+接口 |
| SSE 回放 | `apps/backend/app/services/task_events.py:75-127`；`apps/backend/app/api/routers/tasks.py:32-100,146-168` | `task_seq` 跨连接单调递增，先读 JSONL 历史再 live-tail；`after_seq` 和 `Last-Event-ID` 支持断线续接 | 代码 |
| 事件脱敏 | `apps/backend/app/services/task_events.py:18-72` | 持久化事件只允许安全事件类型，并过滤 api_key、authorization、prompt、messages、base64 等字段 | 代码 |
| 任务恢复 | `apps/backend/app/orchestration/task_run.py:250-369`；`apps/backend/app/api/routers/tasks.py:184-240` | 普通运行、确认恢复与模型传输失败恢复分开处理；恢复路径以 checkpoint 继续，不重新提交原用户消息 | 代码+接口 |
| 工具治理 | `apps/backend/app/tools/registry.py:42-146`；`apps/backend/app/services/tool.py:37-198` | ToolSpec 统一描述工具元数据、启用态、确认、沙箱、幂等和并发；ACI 与执行守卫复用 `agent_can_use` | 代码 |
| MCP 注册 | `apps/backend/app/services/mcp.py:79-151` | MCP 注册先连接并 `list_tools`，再做工具名冲突检查，最后批量写入并注册运行时 spec | 代码 |
| MCP 运行时 | `apps/backend/app/tools/mcp_manager.py:34-175` | 连接按源由 owner-task 复用，请求串行入队；连接/协议失败进入熔断状态机 | 代码 |
| 本地工作区 | `apps/backend/app/services/workspace.py:70-116,259-417` | 文件引用经过规范化路径和二次校验；工作区目录按用户目录派生，文件操作限制在根目录 | 代码 |
| 发布入口 | `apps/backend/app/api/factory.py:17-49`；`scripts/release_builder.py:81-133` | 发布包由 FastAPI 同时托管 REST/SSE 和 SPA，不依赖 Nginx 或独立前端服务器 | 代码+脚本 |

## 2. 项目文档事实

| 主题 | 来源 | 可写结论 | 注意事项 |
| --- | --- | --- | --- |
| 产品定位 | `README.md:1-11` | LiBao 是本地优先通用 Agent Runtime 与 Web 工作台，默认回环地址、本地单用户 | 不写成公网多租户系统 |
| 架构分层 | `docs/architecture/overview.md`、`backend.md`、`frontend.md` | 浏览器—Vue/Vite—FastAPI—LangGraph—服务/工具—本地存储；前后端按职责分层 | 文档需与当前代码一致 |
| 数据布局 | `docs/architecture/data-model.md` | 业务数据使用 FileStore/JSONL，知识库/记忆使用 LanceDB/BM25，checkpoint、附件和工作区独立存放 | 不写 SQL 数据库 |
| API 契约 | `docs/api/contract.md`、`contracts/openapi.json` | REST 统一信封；SSE 事件至少有单调 seq；契约快照需与客户端同步 | 提交前重导出核对 |
| 发布边界 | `docs/operations/release.md` | 发布包排除开发工具、测试、文档、用户数据和密钥；发布前做测试、契约、secret scan、路径与启动冒烟 | 区分“要求”和“实际运行” |

## 3. 已验证测试记录

### 本轮重新执行

命令：

```text
cd apps/backend
uv run pytest tests/test_task_events.py tests/test_task_recovery.py tests/test_graph.py tests/test_graph_closeout.py tests/test_mcp_manager.py tests/test_mcp_sync.py tests/test_workspace_service.py tests/test_workspace_agent.py tests/test_chat_document_context.py -q
```

结果：`86 passed, 2 skipped, 2 warnings in 15.05s`。这组结果可支持任务事件、恢复、图编排、MCP 同步/管理、工作区和文档上下文等机制的回归测试存在；不能据此推出性能、恢复成功率或真实 LLM 质量结论。

同日重新执行完整测试：后端 `cd apps/backend && uv run pytest -q`，结果为 `779 passed, 4 skipped, 40 warnings in 110.14s`；前端 `cd apps/frontend && npm run test:unit -- --run`，结果为 52 个测试文件、313 项测试通过，耗时 56.32 秒。根目录直接运行 `uv run pytest -q` 因根环境没有可执行的 `pytest` 而无法启动，因此论文不将根目录测试写成本轮结果。

### 历史验收记录

`progress.md` 记录 2026-09-01 的一次完整验收：后端 `775 passed/4 skipped`，前端 Mock E2E `72 passed`，根目录测试 `45 passed`，OpenAPI 快照一致，Windows 发布包冒烟通过。由于当前工作树仍有大量迁移改动，论文中应写为“历史验收记录”，除非完稿前重新执行完整命令。

## 4. 开题报告附件可复用内容

附件 `.artifacts/libao-render-iter4-20260917/LiBao开题报告.pdf` 已按以下顺序形成内容：选题背景与意义、国内外研究现状、研究目标与内容、研究方法与技术路线、可行性分析、进度安排、预期成果与创新点、系统边界与口径声明、参考文献。其技术主线可继续用于论文绪论和总体设计，但开题报告的“计划/预期”段落要在论文中改写为“实现/验证”。

原参考附件 `.artifacts/reference-render-20260917/开题报告-基于LLMAgent的二手车智能分析系统.pdf` 只用于 A4 页面、封面、目录、标题、表格、正文和页脚页码样式。二手车数据、MySQL、样本规模、价格分析和其业务结论均不属于 LiBao 证据。

## 5. 网页攻略对写作流程的启发

以下资料用于抽取“代码到论文”的工作方法，不作为 LiBao 功能证据：

- [codex-academic-paper-skills](https://github.com/AAASS554/codex-academic-paper-skills)：先做 evidence map，逐条判断保留/改写/删除，再写章节、图表和 DOCX；强调真实截图和不虚构数字。
- [B站：用 Codex 做本科论文定稿](https://www.bilibili.com/video/BV1RjwyzTEYs/)：适用于软件工程/计算机本科论文的证据映射、草稿修订与素材保留。
- [B站：把代码练成论文](https://www.bilibili.com/video/BV17wgG6dENS/)：强调把已完成项目重新组织为问题、方法、实验和结论组成的研究故事。
- [Code-To-Paper](https://github.com/brkysbnc/Code-To-Paper)：展示代码索引、章节写作、文件/行号追踪和 faithfulness 检查的实验性流水线；只借鉴思想，不直接提交自动生成内容。
- [rrtools](https://github.com/benmarwick/rrtools)：提供研究项目、数据、分析脚本、图表和论文文件的可复现组织方式；LiBao 可借鉴其目录与证据管理思想。

## 6. 必须补齐的证据

1. 真实 LLM 配置下的完整任务截图、SSE 时间线和最终结果。
2. 模型超时、传输中断、工具异常、SSE 断开、进程重启、非法 checkpoint、重复恢复和并发提交的重复试验记录。
3. 首事件延迟、任务完成耗时、事件数量、checkpoint 大小、恢复耗时和恢复成功率。
4. Windows/Linux 相同场景的启动耗时、端口/进程回收结果和发布包大小。
5. 如果论文要声称易用性，必须有用户任务脚本和受试者数据；否则只写“流程可用性验证”。
6. 论文封面信息和学校最终格式要求。
