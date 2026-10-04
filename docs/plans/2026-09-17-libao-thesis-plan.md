# LiBao 论文编写计划与证据矩阵

## 目标

基于当前 LiBao 工作树、项目文档、测试与既有开题报告附件，形成一份可继续补实验、补截图并提交导师审阅的中文本科毕业论文初稿；同时生成一份与附件版式一致的 DOCX。论文以“现成项目如何被重构为可验证的工程研究”为写作原则，所有系统事实必须能够追溯到代码、文档、测试或实际运行记录。

## 全局约束

1. 原参考文件 `C:\Users\Admin1\Desktop\开题报告-基于LLMAgent的二手车智能分析系统.docx` 只作为版式与结构参照，保持不改；其中二手车、MySQL、样本数量和价格分析等内容不得写入 LiBao 论文。
2. 当前工作树已有大量跨平台迁移和 MCP 管理改动，属于用户工作；论文工作只读这些改动，不执行 reset、clean、checkout、覆盖式还原或提交。
3. 论文事实源按优先级取：实际代码与测试 > `progress.md` 中可复核的验收记录 > `docs/` 项目文档 > 开题报告中的设计目标。设计目标不能伪装成已实现结果。
4. 不虚构真实模型调用、性能指标、用户数量、问卷结果、恢复成功率或实验截图。缺数据的地方使用“待补实验”标记，并附实验步骤与记录格式。
5. LiBao 的定位必须保持为本地优先、个人单用户、回环地址运行的 Agent Runtime 与 Web 工作台；不将其描述成公网多租户平台或通用生产 SaaS。

## 论文主问题与题目

建议题目：

> LiBao：本地优先通用 Agent Runtime 与 Web 工作台的设计与实现

副标题可保留开题报告中的：

> ——面向大语言模型智能体的工程化运行时研究

拟回答的核心问题：在大语言模型输出不确定、工具调用可能失败、长任务可能中断且本地数据需要受控的条件下，如何设计一个面向个人用户的通用 Agent Runtime，使任务执行、工具能力、上下文、事件流、恢复机制与跨平台交付具有可观察、可回放和可验证的工程闭环？

论文的贡献口径暂定为：

1. 提出并实现面向本地单用户场景的运行边界，将 API、SSE、SPA、运行数据和工作区约束在本机回环与用户目录内。
2. 设计任务状态、持久化业务事件、单调游标与检查点恢复协同机制，支持断线回放、取消、确认恢复和模型传输失败后的续跑。
3. 设计统一工具注册与执行治理模型，统一内置工具、自定义工具和 MCP 工具的元数据、启用态、授权、确认、沙箱、幂等和冲突处理。
4. 建立跨平台验证与单入口发布方案，以 Windows/Linux CI、契约快照、发布包冒烟和进程回收测试验证工程可交付性。

## 章节结构

### 第 1 章 绪论

说明 Agent 从单轮问答走向多轮任务、工具使用和长期上下文后出现的运行时问题；提出研究问题、研究内容、论文组织结构和本文贡献。避免只写产品宣传。

### 第 2 章 相关技术与研究现状

介绍 ReAct、Toolformer、函数调用、RAG、图式编排、MCP、SSE 与检查点等概念，并按“能力—运行时—本地边界—交付验证”比较相关工作。相关工作只用于提出工程缺口，不声称 LiBao 在模型算法上超过已有方法。

### 第 3 章 需求分析与系统总体设计

给出功能需求、非功能需求、系统边界、总体架构、模块依赖、开发/发布拓扑和数据目录。重点解释为什么开发环境使用 Vite `/api` 代理，而发布环境由 FastAPI 同时提供 REST、SSE 与 SPA。

### 第 4 章 Agent Runtime 与任务编排设计

描述 AgentState、LangGraph 主图、上下文构建、工具调用、记忆注入、状态迁移、任务后台执行、确认中断、取消、错误归一化、检查点与恢复。用一次任务的时序/状态转换作为本章主线。

### 第 5 章 工具、MCP 与本地能力治理

描述 ToolSpec、注册中心、ACI、授权谓词、启用态同步、工具搜索、MCP 注册验证、源内/跨源命名冲突、连接池与熔断，以及文件、工作区、沙箱和凭据脱敏边界。强调“能力可用”与“能力可执行”使用同一授权不变量。

### 第 6 章 Web 工作台与数据持久化实现

描述 Vue/TypeScript/Pinia/Vite 前端、对话视图、任务时间线、SSE 客户端、MCP/工具/知识库/记忆/工作区页面；说明 JSONL、文件目录、LanceDB/BM25、检查点、附件和工作区之间的职责分离。

### 第 7 章 跨平台交付与实验验证

分别给出功能、可靠性、安全边界、跨平台、发布包和端到端可用性验证。当前已有的测试通过记录作为已完成证据；真实 LLM E2E、延迟、恢复比例、资源开销和人工可用性仍需补测，不用猜测。

### 第 8 章 总结与展望

总结工程研究结论，说明局限：本地单用户、无公网认证与租户隔离、外部模型/MCP 依赖、缺少大规模性能实验和长期用户研究，并给出后续方向。

## 证据矩阵

| 论文论断 | 代码/文档证据 | 当前状态 | 论文写法 |
| --- | --- | --- | --- |
| 主图采用 route → memory_inject → agent_execute → tool_execute/context_update → finalize | `apps/backend/app/orchestration/graph.py` | 已实现且有单元测试 | 可写实现机制，配架构图 |
| 上下文分为静态 system、工具 ACI 与末尾动态块 | `apps/backend/app/orchestration/context_builder.py` | 已实现 | 可写设计原则和实现 |
| 任务支持 pending/running/waiting_confirm/cancelled/done/failed | `apps/backend/app/services/task.py`、`apps/backend/app/api/routers/tasks.py` | 已实现，需汇总测试用例 | 可写状态机，引用接口 |
| 事件跨连接使用 task_seq，SSE 单次连接另有 seq | `apps/backend/app/services/task_events.py`、`apps/backend/app/api/routers/tasks.py` | 已实现并有事件测试 | 可写回放/去重算法 |
| 事件日志做安全投影，不保存 API key、Authorization、提示词、消息和 base64 | `apps/backend/app/services/task_events.py` | 已实现，需补安全测试清单 | 可写安全机制，不能写成绝对安全 |
| 模型传输失败可从 checkpoint 续跑，避免重复提交原消息 | `apps/backend/app/orchestration/task_run.py`、`apps/backend/app/api/routers/tasks.py`、`test_task_recovery.py` | 已实现；恢复指标待实测 | 可写流程与故障注入结果 |
| 工具 ACI 与执行守卫共用 `agent_can_use` | `apps/backend/app/orchestration/context_builder.py`、`apps/backend/app/tools/registry.py` | 已实现 | 可写一致性不变量 |
| MCP 注册先连接并 list_tools，再整体检查冲突和落库 | `apps/backend/app/services/mcp.py` | 已实现；需整理 API 测试 | 可写两阶段注册策略 |
| MCP 连接按源复用 owner-task，并有熔断状态机 | `apps/backend/app/tools/mcp_manager.py` | 已实现；性能/并发数据待补 | 可写机制，性能只写实验实测值 |
| 工作区路径校验、二次 realpath/no-follow、文件引用限制 | `apps/backend/app/services/workspace.py`、`apps/backend/app/tools/filesystem.py` | 已实现，部分平台能力依赖环境 | 可写威胁边界和测试案例 |
| 发布环境单 FastAPI 提供 REST/SSE/SPA，无 Nginx | `apps/backend/app/api/factory.py`、`scripts/release_builder.py`、`docs/operations/release.md` | 已实现且有发布冒烟 | 可写拓扑与交付验证 |
| Windows/Linux CI 运行后端、前端、契约、secret scan、发布验证 | `.github/workflows/ci.yml`、`progress.md` | 已有配置与验收记录 | 可写验证矩阵；注明本地未运行的检查 |
| 项目已有 775 个后端测试、72 个 Mock E2E、45 个根目录测试通过 | `progress.md` | 有历史验收记录，需确认当前 HEAD/工作树对应关系 | 若不重新运行，写“最近一次验收记录”；不要写成当前即时结果 |

## 评估设计

### 功能测试

覆盖提交任务、流式事件、取消、确认恢复、模型传输失败恢复、内置/自定义/MCP 工具启停、工作区文件、知识库、记忆、附件和设置端点。记录用例总数、通过数、跳过数与失败原因。

### 可靠性测试

对模型超时、模型传输中断、工具异常、SSE 断开、进程重启、非法 checkpoint、重复 recover 和并发提交进行故障注入。至少记录：任务最终状态、最后持久化 task_seq、是否重复用户消息、是否恢复到正确 checkpoint、恢复耗时。

### 安全与边界测试

检查敏感字段不进入任务事件、前端 DOM、普通日志和发布包；检查工作区外路径、符号链接、越权工作区、非法压缩包路径和 release 目录穿越。报告“已验证边界”，不报告未经测试的“绝对安全”。

### 跨平台与发布测试

在 Windows 与 Linux 分别记录 Python/Node 版本、启动端口、健康检查、SPA 深层路由、进程退出与临时用户目录；核对发布包不含 tests/docs/mock/DevPanel/Nginx/node_modules/.venv/日志和用户数据。

### 待补实验数据

1. 至少一个真实 LLM 配置下的端到端任务截图和事件时间线。
2. 故障注入每种场景的重复次数、恢复成功率、重复消息数和耗时。
3. 常用任务的首事件延迟、完成耗时、事件数量、checkpoint 文件大小。
4. Windows/Linux 同一用例的启动耗时与发布包大小。
5. 如需写“易用性”，补充受试者数量、任务脚本、完成时间和主观反馈；否则只写可用性流程验证。
6. 封面中的姓名、学号、院系、专业、指导教师和日期。

## 输出物

1. `docs/thesis/libao-thesis-draft.md`：可审阅、可检索、含证据标记的中文论文初稿。
2. `docs/thesis/LiBao本科毕业论文初稿.docx`：基于附件版式生成的可视化文档，保留封面、目录、主体标题、表格和页码结构。
3. `docs/thesis/evidence-matrix.md`：论断到代码/测试/运行记录的追踪表，方便后续补实验。
4. `docs/thesis/figures/`：只放真实运行截图或由代码/数据生成的架构、时序、状态机图；不使用虚构界面或虚构指标。

## 写作门禁

- 每章至少有一个明确问题、一个设计决策和一个证据来源。
- “实现了”必须对应代码路径；“验证通过”必须对应测试或运行记录；“提升/降低/高效”必须有对照或定量数据。
- 参考文献中的 DOI、URL、标题、年份逐条核对；项目内文档用访问日期标注。
- DOCX 生成后使用文档渲染器逐页检查：封面字段、目录、标题层级、表格分页、代码/英文混排、页脚页码、空白页和溢出。
- 完稿前运行适用的 Test / Review / Simplify 收尾门禁，并保留渲染产物与证据矩阵。

