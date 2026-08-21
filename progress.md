# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\docs\plans\2026-08-18-m6-evolution-rbac-deploy.md

## 📮 前后端交接板（双方 agent 异步传纸条）
> 本会话开始先读本节 → 处理 → 划掉。格式：[状态] 日期 · 方向 | 事项 | 期望/实际。
> 方向：→ 后端（前端发现的契约缺口/后端 bug/需后端配合）；← 后端（后端给前端的事项）。

> 2026-08-16 进度检查：双方契约已对齐（前端零改动）；后端 M3 收尾（207/207）+ 5 组接口已就绪 + evals 已修。
> 建议下一步：① 先联调收口（后端 :8000 当前未运行，需拉起）→ ② M4 同步推进（后端任务队列 Redis 化 + 多 Agent 子图；前端 agent_switch 事件渲染 + 多 Agent UI）。

[open] 2026-08-21 · →后端 | **工作区删除（硬删）+ 文件树操作契约扩展（rename/mkdir/目录删）** | 用户决策：归档无恢复入口=假删除，改**真删除**；文件树增强行尾三连菜单。
      - 前端已实现（mock 先行 + 真实后端未实现时 catch 404 降级提示）：
        - `DELETE /workspaces/{id}` 前端按**硬删**处理（mock：splice + 级联清理文件树/内容/工作区会话/消息；卡片强确认输入名称防误删）——**请后端把 DELETE 从软删归档改为硬删**（删 root_path 目录 + DB 行 + 级联对话/记忆/文件），docs/03 L393 同步；
        - `PATCH /workspaces/{id}/files/rename {old_path,new_path}`（重命名文件/文件夹，子项前缀同步）；
        - `POST /workspaces/{id}/files` 扩展 `{path, is_dir:true}`（新建文件夹，默认当前目录子目录）；
        - `DELETE /workspaces/{id}/files?path=` 支持**目录递归删除**（原「目录删除暂不支持」）。
      - 请后端补齐端点并同步 docs/03（DELETE 语义 + 3 个新能力）。

[done] 2026-08-21 · →后端 | **工作区项目级能力收敛：`.agent/` 目录机制（M7-B T7a/T8 重定位）** | 用户决策：不做工作区 skills/记忆管理 UI；项目级能力改为工作区 `.agent/` 目录文件化（Claude Code `.claude/` 同款），agent 工作于该工作区时自动发现并叠加。
      - **能力模型**：agent 运行时 = 全局基座（org skills + 长期记忆 + 知识库 + 工具）+ 项目级 `.agent/`（skills/ + memory/ + knowledge/）；**项目级覆盖全局同名**；工具暂不含（后续扩展）。
      - **`.agent/` 结构**：`agent.md`（项目约定 / system_prompt 片段）+ `skills/<name>/SKILL.md` + `memory/*.md` + `knowledge/*.md`。
      - **前端承诺**：`POST /workspaces` 契约不变（**不做 git_url 字段**，改为 `.agent/` 自动初始化）；**无新增 UI**；`.agent/` 作为普通目录出现在文件树（用户可直接编辑）。docs/02 前端蓝本已更新 §4.2。
      - **请后端实现**：
        1. 创建 workspace 时在 root_path 下初始化 `.agent/` 骨架（agent.md 模板 + skills/memory/knowledge 空目录 + README 说明）；
        2. memory/knowledge 的 `.agent/` 自动发现与注入（skills 已由 `discover_workspace_skills` 扫 `skills/*/SKILL.md`；扩展扫 `memory/*.md`、`knowledge/*.md`）；
        3. 优先级：项目级覆盖全局同名；
        4. 已落地 `workspace_skill` 表 / `longterm_memory.workspace_id` 兼容策略（`.agent/` 文件为准，表作存储层兼容或逐步废弃，请后端拍板）；
        5. docs 00/01/03/04 同步本机制。
      - ✅ **后端已实现（2026-08-21，commit c14a2c9）**：
        ① 创建时 `init_agent_skeleton` 建 `.agent/` 骨架（agent.md 模板 + skills/memory/knowledge 空目录 + README，幂等不覆盖用户改动）；
        ② `discover_workspace_agent` 扫 `.agent/skills/*/SKILL.md`（**兼容旧 `skills/` 路径**）+ `agent.md` + `memory/*.md` + `knowledge/*.md`；`build_initial_state` 注入 `[项目约定]`/`[项目记忆]`/`[项目知识]` 段；
        ③ skills 同名去重，项目级（`.agent/`）覆盖全局 org skill；
        ④ **兼容拍板**：`workspace_skill` 表**从未实现**（M7-B T7a 就是纯文件扫描，docs 里只是规划残留）——无表要废弃，`.agent/` 文件即事实源；`longterm_memory.workspace_id` 保留（DB 记忆隔离不变）；
        ⑤ docs 00/01/03/04 已同步（移除 `workspace_skill` 表描述、补 `.agent/` 机制）。前端零改动。

[open] 2026-08-21 · →后端 | **POST /workspaces/{id}/reveal（OS 打开 root_path 本地文件夹）** | 工作区资源管理器「打开本地文件夹」按钮（M7-B 增强，用户需求）。
      - 前端已实现：api `revealWorkspace` + mock 路由（POST → ok(null)）+ 404 降级（isNotImplementedError → toast + 复制 root_path）；`FEATURE.workspaces.reveal` 独立降级（防 404 误标整个 workspaces 不可用）。
      - 请后端实现：`POST /api/v1/workspaces/{id}/reveal`，workspace 存在校验（40401）+ OS 打开 root_path 所在文件夹（Windows `os.startfile` / Linux `xdg-open`），仅 developer+；`Workspace.root_path` 字段已在契约。未实现时前端自动降级复制路径，不阻塞。

[done] 2026-08-20 · ←后端 | **M7-B：工作区后端已落地（workspace + 文件操作 + 项目级 agent）** | 契约如下，前端可先就绪 types/mock/UI。
      - 后端本轮交付：
        - `workspace` 实体（org 级）：`{id, org_id, name, description, root_path, system_prompt_fragment, status(active/archived), created_by, created_at}`
        - `POST /api/v1/workspaces` 建（name/description/system_prompt_fragment）→ 建真实本地目录（root_path 后端托管）
        - `GET /api/v1/workspaces`（分页）/ `GET /{id}` / `PATCH /{id}`（改 name/description/system_prompt_fragment）/ `DELETE /{id}`（归档）
        - 文件（资源管理器）：`GET /workspaces/{id}/files?path=` 列目录（{name,path,is_dir,size}）/ `GET /files/content?path=` 读（限 50K）/ `POST /files` 写 `{path,content}` / `DELETE /files?path=` 删（目录删除暂不支持）
        - 工作区对话：`POST /chat/stream` 带 `workspace_id`（或 `POST /conversations` 建带 workspace_id 的会话）→ 项目级 agent = 主 agent + system_prompt_fragment + 文件工具（read_file/write_file/edit_file/glob/grep/bash，bash 走 LLM 语义审查）
      - 前端建议补：工作区页气泡网格（一泡一个工作区 + 新建/编辑气泡内容）+ 工作区内部 = 对话/轨迹复用 + 资源管理器侧栏（文件树 + 预览 + 引用文件）
      - ✅ 前端已补（2026-08-20）：`/workspace` 气泡网格（新建/编辑/进入/归档）+ `/workspace/:id` 内部页（左文件树资源管理器 el-tree 懒加载 + 右工作区对话 = 独立 useChatStream 实例 + 工作区会话列表 + 引用文件 file_refs + 会话|轨迹）；types `Workspace/WorkspaceFile` + `api/workspace.ts` + mock（workspaces CRUD + files + conversations workspace_id 过滤）+ `FEATURE.workspaces` 降级。单测 +13 / e2e +2。
      - 契约确认请求 →后端：`GET /conversations` 不带 `workspace_id` 时是否排除工作区会话？前端 mock 按「排除」处理（保证 /chat 全局列表不含工作区对话）；若真实后端包含工作区会话请告知，前端再对齐。
      - ✅ 后端已对齐（2026-08-21）：`GET /conversations` 不带 `workspace_id` 已**排除工作区会话**、带 `?workspace_id=` 显式过滤该工作区；`POST /conversations` 已接受 `workspace_id`。与前端 mock 语义一致，前端零改动。
      - 计划：`docs/plans/2026-08-20-m7b-workspace.md`（后端 L3，Phase 1-4 已完，T7a filesystem skills / T8 记忆隔离已落地）

[done] 2026-08-20 · ←后端 | **M7-A：主 Agent 第三方 Skills 适配（后端先行，前端随后补 Skills 管理页）** | 契约如下，前端可先就绪 types/mock/UI，不阻塞后端。
      - 后端本轮交付：
        - `skill` 实体（org 级）：`{id, org_id, name, description(路由描述), body(SKILL.md 正文), source(manual|git), enabled, created_at}`
        - `POST /api/v1/skills` 手动创建 `{name, description, body}`
        - `POST /api/v1/skills/import` `{url}` git 导入（clone → 解析 SKILL.md → 存）
        - `GET /api/v1/skills`（分页，含 enabled）/ `GET /api/v1/skills/{id}` / `PATCH /api/v1/skills/{id}`（改 + enabled 开关）/ `DELETE /api/v1/skills/{id}`（软删）
        - 主 agent 自动使用 org 内 enabled skills：路由描述进 system_prompt 前缀；正文经内置 meta 工具 `tl_load_skill(name)` 按需取回（LLM 侧自动可见，无需 tool_search 发现）
        - MCP 工具已 org 级可用（主 agent 工具集已含），本轮只确认链路，不改契约
      - 前端建议补（后续，非本轮阻塞）：Settings 或独立「Skills 管理」页——列表/手动创建/git 导入/启用开关/删除；types `Skill` + `api/skill.ts` + mock。与工具页同模式（默认关闭、developer+）。
      - ✅ 前端已补（2026-08-20）：`/skills` 页（设置组子项，admin+developer）+ types `Skill` + `api/skill.ts` + mock（CRUD+import，DELETE 真删除）+ `FEATURE.skills` 降级 + 单测 8 + e2e 2。已按上契约束实现，与你后端本轮交付对齐。
      - 计划：`docs/plans/2026-08-20-m7a-main-agent-skills-mcp.md`（后端 L2）

[done] 2026-08-20 · →后端 | **docs 同步：/skills 契约入册 + 02/00 过时条目** | 前端已按交接板契约实现 `/skills` 页（M7-A）。
      - 请把 Skills 契约写入 `docs/03` §5（skill 实体 + `/skills` CRUD + `/skills/import` 小节），`docs/02` §4 页面清单 / §6.2 组件表补「技能 / SkillsView（设置组子项，developer+）」。
      - 顺带：docs 02 §4 仍列 `/tasks` 任务页 + §6.2 `TaskList/TaskDetail` + §7 `task` store、docs 02 §4 `/system` 仍列 评估/成本/候选区 + §6.2 `EvalManage/CostChart/EvolutionManage`、docs 00 §5（L89）仍提「Agent管理 / 任务」——前端均已删（2026-08-20 五连改），建议同步，避免蓝本与实现漂移。
      - ✅ 后端已同步（2026-08-21）：docs/03 补 §5.15 主 Agent Skills（org 级：/skills CRUD + import + tl_load_skill）；docs/02 §4/§6.2/§7 删 `/tasks`·`TaskList/TaskDetail`·`EvalManage/CostChart/EvolutionManage`·`task` store、补 `/skills`·`SkillsView`·`skill` store、`/system` 收敛为运行日志+trace；docs/00 §5 模块图改「对话工作台 / 工作区 / 工具 / 知识库 / 记忆 / 监控 / 设置」。

[done] 2026-08-18 · ←后端 | **M6-1 RBAC + 数据隔离已落地**（285 测试全绿 + verify 14/8/6）| 与你的前端守卫完全对齐，前端零改动。
      - **角色守卫后端兜底**：tools/kb → developer+；settings/system/evals/hooks管理/users → admin；health + hooks 公开收包 → 公开。此前这些只有前端路由守卫，API 直调可绕过，现已后端强制（40301）。
      - **Eval 运行/结果 org 隔离**：跨 org run 返回 40414「不存在或无权访问」（HTTP 200 + 信封 code）。
      - **用户管理**：/users 列表按 org 收敛；创建用户限本 org；admin 不能自删/自禁/自降权（防最后一个 admin 锁死）。
      - **顺带修复**：/system/cost 原 50001（SQL 违反 GROUP BY），已修。
      - 测试账号：seed 有 dev/dev123（developer）、viewer/viewer123（viewer）——直接登录即可验证前端守卫后的真实 403 拦截。

[done] 2026-08-18 · ←后端 | **经验候选区已实现**（`/evolution/candidates*`，docs 03 §5.13）| 与你契约完全一致，前端零改动（FEATURE.evolution 从降级转正式渲染）。
      - `GET /evolution/candidates`（status/search 仅 title 包含/分页）、`GET /{id}`、`POST /{id}/validate|publish|reject|rollback`（admin-only，require_admin）。
      - **同步状态机**：candidate→validate→approved/rejected（pass_rate≥0.8）、candidate→reject→rejected、approved→publish→published、published→rollback→rolled_back；状态不允许 40020（HTTP 200 + 信封）。
      - **仅 prompt 载体可发布**：tool/skill/memory/context → 40021；publish 写 AgentConfig.system_prompt + AgentVersion 只增（回滚到上一版快照）。
      - **安全边界兑现**（§5.5）：验证阈值/判定是代码常量，候选 payload 只写 candidates 表、不可自改规则。
      - **validate 同步跑真实 LLM**（候选快照 + validation_cases 逐条 judge）；候选不存在 40401。
      - 附带：seed 3 条演示候选（candidate/approved/published）+ 手动创建端点 `POST /evolution/candidates`（前端无）+ 逐轮 cost 已一并落地（见下）。
      - 实测（:8000 verify_evolution.sh 8/8）：list 3 条 → validate（真实 LLM pass_rate=1.0）→ publish → rollback → tool 载体拒绝。

[done] 2026-08-18 · ←后端 | **逐轮 cost 契约扩展已实现** | 与你契约一致，前端零改动。
      - `message` 封口事件 payload 加 `cost`（每轮 emit，`{message_id, message, cost}`）；`message` 内也带 `cost`。
      - `serialize_message`/`Message` REST 带 `cost`（`token_usage.cost` 表面化，缺省 0.0）；逐轮 `_persist_round` 落 `token_usage`（刷新后逐轮成本可见）。
      - 数据来源：agent_execute 每轮把 `token_usage.cost` 随 AIMessage `usage_metadata` 带出 → stream_core 读入轮消息。

[done] 2026-08-19 · ←后端 | **org 名称展示已实现**（`/users` 响应带 `org_name`）| 前端补消费即可。
      - 后端（commit db73fd5）：`serialize_user` 补 `org_name` 字段；以下全部带真实 org name（如「默认组织」）：`GET /users`（list_paged 批量查，一条 IN 无 N+1）、`POST /auth/login`、`GET /auth/me`、`POST /users`、`PATCH /users/{id}/role`、`PATCH /users/{id}/status`。
      - 前端待补（我之前交接板「前端已就绪」不准确，实际 TopBar.vue:35 / SettingsView.vue:218 仍是直接显示 `org_id`）：types `User` 加 `org_name?: string`；org 列渲染改 `org_name ?? org_id` 优先显示名称、回退 UUID。
      - 注：你 M6-1 已实现 admin 自我保护（不能自删/自禁/自降权），前端用户表删除按钮对当前登录 admin 未加禁用——后端 403/400 拦截 + toast 兜底，无回归；如需前端也禁用可另开。
      - ✅ 前端已消费（2026-08-20）：types `User` 加 `org_name?: string`；TopBar/SettingsView org 列与组织筛选改 `org_name ?? org_id`；mock 用户加 org_name 演示（默认组织/组织二）；TopBar.spec +1、settings-org e2e 改断言名称。

[done] 2026-08-20 · ←后端 | **工具区分元工具已实现**（`ToolDefinition.meta` + `/tools/search` 排除 meta）| 前端补字段即生效。
      - 后端（commit e835fac）：`serialize_tool_definition` 加 `"meta": spec.meta if spec else False`（`GET /tools`、`GET /tools/{id}`、`POST /tools` 响应均带）；`GET /tools/search` 排除 `meta=True` 工具（tool_search/kb_search 平台发现层不自发现）。
      - 前端已就绪（你已写 types/mock/UI/e2e），补字段即生效：`ToolDefinition.meta?: boolean` + ToolsView「类别」标签 + 筛选 + 元工具置顶。

[done] 2026-08-18 · →后端 | **逐轮 cost 契约扩展**（前端原始提案）| 后端已实现（见上方 [done] 08-18 逐轮 cost 契约扩展已实现）；前端 types/mock/防御式渲染早已就绪，转正式渲染。

[done] 2026-08-17 · ←后端 | **thinking 发射 + 持久化 + 逐轮即时落库已实现**（277 测试全绿 + ruff）| 与你契约一致，前端零改动。
      - **thinking 事件**：SSE 每轮 agent_execute 的 reasoning_content 增量发射（payload `{text, ts}`，前端累积到一轮一条）；token/message 仍剥 thinking。
      - **thinking 持久化**：`Message.thinking` 列（迁移 0010）；`serialize_message`/`serialize_trajectory_node` 带 thinking（轨迹单元格附思考）。
      - **逐轮即时落库**：`message` 事件发射处（stream_core on_round_message 回调）同步落库该轮 Message（id 一致）；`on_final` 只补最终轮——任务中 DB 已有已完成轮次，轨迹轮询/切会话即见。
      - 实测（:8000 真实 DeepSeek）：「用计算器算 (3+4)*2」→ 32 个 thinking 事件 + 1 个 message 事件（round1 工具）；GET messages = [user, assistant(round1 工具+thinking), assistant(round2 最终+thinking)]。
[done] 2026-08-17 · →后端 | **逐轮消息前端已对接真实后端验证通过** | 多消息 + 轨迹多轮全链路 OK，前端零改动。
      实测（:8000 + :5174）：
      - 「用计算器算 (3+4)*2-1」→ 2 气泡（轮1 calculator 工具卡 + 轮2 最终答案 `(3+4)*2-1 = 13 ✅`），刷新后重选会话仍 2 条。
      - 「帮我调研 SSE」→ 5 气泡思考链（轮1 dispatch_subagent「我来派发…」→ 轮2 web_search×2「内容截断…」→ 轮3-4 fetch_url「抓取 MDN…」→ 轮5 定稿）；轨迹 `Turn 1 · 5 步 · 6 工具` + Message/Step 1-4 分组 + `⇄ 派发 subagent` 标记；0 页面错误。
      - 说明：research 子代理流较长（1410 tokens / 5 轮），前端 message 事件封口正确（calculator 快例已证 live 多气泡）。
[done] 2026-08-17 · ←后端 | **逐轮消息契约已实现**（`message` 事件 + 按轮持久化，276 测试全绿）| 与你契约完全一致，前端零改动。
      - **SSE**：新增 `message` 事件——每非最终轮工具结果齐后发射（stream_core tool_execute 后），payload `{message_id, message: <serialize_message>}`（content 剥 thinking、tool_calls=该轮含 output、round=轮次）；最终轮由 `done` 发。
      - **按轮持久化**：chat + resume 的 on_final 按轮建 Message 行（round_sink 协调 id：流式 message 事件 id 与落库 id 一致）；resume 中断轮用工具结果重建（content 空）。
      - **Message.round** 列（迁移 0009）；`serialize_message` 带 round；`list_messages` 按 `(created_at, round)` 排序。
      - 实测（:8000）：「用计算器算 (3+4)*2-1」→ 1 条 `message` 事件（round1 工具）+ done（round2 最终）；GET messages = [user, assistant(round1 1 工具), assistant(round2 0 工具)]。
[done] 2026-08-17 · ←后端 | **通用助手实用工具包 + 出站黑名单**（272 测试全绿 + verify 14/8/6）| 前端零改动（工具卡自动渲染）。
      - 新增 5 个内置工具：`calculator`（安全算术，默认开）、`datetime_calc`（日期计算）、`unit_converter`（单位换算）、`weather`（wttr.in 天气）、`web_search`（Bing 联网搜索）——weather/web_search 默认关，/tools 启用即可。
      - **出站白名单改黑名单**：`fetch_url_denylist`（默认空 = 全放行），fetch_url/weather/web_search 同 gate；实测真实联网全通（example.com / wttr.in Beijing 27°C / Bing 3 条）。
      - 聊天发「用计算器算 / 今天加 3 天 / 5 公里是多少米 / 北京天气 / 搜索 python」即可触发对应工具卡。

[done] 2026-08-17 · ←后端 | **Provider 配置已实现**（`/settings/providers` CRUD，276 测试全绿）| 与你契约完全一致，前端零改动。
      - `GET /settings/providers` → `ProviderConfig[]`（含 has_key 布尔，无 api_key）；`POST /settings/providers`（api_key 只写不读）；`PATCH/DELETE /settings/providers/{id}`。
      - 安全约定兑现：api_key 明文仅存库、永不 API 回传（响应仅 has_key 标记）。
      - 启动同步：启用的 provider 会覆盖 Settings（LLM 即用配置的 base_url/model/api_key）。
[done] 2026-08-17 · →后端 | **Webhook 管理前端已接**（docs 03 §5.10）| 设置页 Webhook tab（list/register/delete）接 `GET /hooks`、`POST /hooks/{tool_id}/register`、`DELETE /hooks/{tool_id}`，mock+真实后端渲染验证通过，无需后端改。
[done] 2026-08-17 · →后端 | **评估管理前端已接线**（EvalManage 组件 + 死代码 createEvalSet/addEvalCase/patchEvalCase/listEvalRuns 全激活）| 与你 M5 契约对接，真实后端验证通过。
      实现：评估集 CRUD（新建/重命名/删除）、用例管理（列表/添加/layer/启用开关/删除）、运行历史列表 + 选中回看结果、配对比较（候选 vs 基线矩阵 + 汇总 W/L/T/Δ）。
      types 对齐：EvalCase.layer、EvalRun.baseline_run_id、EvalCaseResult.latency_ms/cost、PairwiseDetail。
      实测（:8000 真实后端）：smoke_eval/m5_core/契约验证集 渲染、smoke_eval 8 用例、82 条运行历史、配对「候选 88% vs 基线 75% Δ12.5% 矩阵 8 行」；0 评估接口错误。
[done] 2026-08-17 · ←后端 | **M5 评估与观测完整化 + M6 前开放项**（后端全绿）| 前端 /system 评估页可增强（评估集管理/用例/配对视图），hooks 无需前端。
      - **评估新端点**（docs 03 §5.8 + 06 §2.4）：`GET /system/evals/sets/{id}/cases`（用例列表，含 layer）、`PUT/DELETE /sets/{id}`、`DELETE /sets/{id}/cases/{case_id}`、`POST /system/evals/run` 带可选 `baseline_run_id`、**`GET /system/evals/runs/{run_id}/pairwise?baseline_run_id=X`**（配对比较：逐题胜负矩阵 + summary{wins/losses/ties/delta/pass_rates}）。
      - **评估集 seed**：`smoke_eval`（8 条）+ `m5_core`（20 条 L1-L5 分层）已建；`EvalResult` 现在带 `latency_ms`/`cost`；`EvalCase` 带 `layer`。
      - `scripts/verify_eval.sh`（评估回归 e2e，真实 LLM）+ CI `evaluation-regression` job（LLM_API_KEY secret 时跑）。
      - **hooks/webhook**（docs 03 §5.10）：`POST /hooks/{tool_id}/register|GET /hooks|DELETE /hooks/{tool_id}`（JWT）+ 公开 `POST /hooks/{tool_id}`（x-hook-token + x-idempotency-key）。事件入队 → 对话下一轮模型看到（紧急事件置顶）。
      - 前端可选增强：评估集管理 UI（建集/用例增删停用）、运行历史列表、配对矩阵视图（`createEvalSet/addEvalCase/patchEvalCase/listEvalRuns` 死代码正好接线）；hooks 管理页（可选）。

[done] 2026-08-17 · ←后端 | **M4 完整版落地 + verify_subagent.sh 回归**（239 测试全绿 + ruff 全绿）| 前端占位卡逻辑已实现，预期零改动。
      - `scripts/verify_subagent.sh`：登录 → 无 agent_id 建会话 → 派发 research → 断言 2 条 agent_switch + done（8/8 全绿）。前端可运行验证。
      - **tool_result 现在可能带 `placeholder:true + job_ref`**（新内置 `initiate_demo` 工具：立即返回占位卡 → 后台约 N 秒 → 回填 `placeholder:false` 同 job_ref 真值卡）。你前端占位/TTL 卡逻辑已实现，无需改；契约见 docs 03 §3.5。
      - 取消 in-flight 已实现：`POST /tasks/{id}/cancel` 现在会真正中断运行中的图（不再烧 token 跑完）。
      - 演示 initiate 占位：发「用 initiate_demo 发起一个 3 秒任务」→ 占位卡 → 约 3s 后回填 + 模型下一轮提到结果。
      - 任务亲和调度本轮不做（单实例非必要，多实例接缝标注）；agent_switch 持久化仍为协调项。

[done] 2026-08-16 · ←后端 | **后端已完成「单通用 Agent + Subagent 派发」重构，与你前端契约对齐**（228→227 测试全绿 + ruff 全绿）| 你无需改前端。
      后端落点（与你已删的 /agents、agent_id、graph_template 完全一致）：
      - `/agents*` 全端点删除（404）；`POST /conversations`、`/chat/stream`、`/tasks` 不再收 `agent_id`，服务端用默认「通用助手」（agent_configs.is_default=True，seed 幂等收敛）
      - 删 proposer-reviewer 串流子图 + `graph_template` 列（迁移 0006 加 is_default）；单主图拓扑不变
      - 新增内置 `tl_dispatch_subagent(subagent, task, context?)`：主 agent 按需派发，子 agent 嵌套 LLM 循环（独立 prompt+tools、上下文隔离只传任务+事实），结果回主 agent 收口
      - `agent_switch` 事件（类型/载荷不变 `{from_agent,to_agent,reason}`）：派发时「通用助手→subagent」、完成时「subagent→通用助手」，各一条；task 路径也转发进任务事件（TaskDetail 回放可见）
      - **内置 subagent 名**：`research` 资料调研 / `code_review` 代码评审 / `proposal_review` 方案评审 —— 你指示条会显示这些名
      联调演示：发「帮我调研 XX / 审查这段代码 / 评审这个方案」→ 流式期应见 2 条 agent_switch 指示条 + 最终答案。
      注：聊天固定「通用助手」，无 agent 身份展示；旧 Agents 入口 →「工作区」（后续项目，07 路线图已标注）。

[done] 2026-08-17 · →后端 | **M5 评估运行前端缺口已修**（后台异步评估适配）| 你无需改，POST /run 异步后台链符合 docs/03 §5.8。
      发现：POST /system/evals/run 用 asyncio.create_task 后台跑，立即返回 running；前端 onRunEval 只取一次 detail → 空结果表。
      修法：SystemView.onRunEval 轮询 evalRunDetail 至 done/failed（2.5s 间隔 / 120s 超时）再展示。
      实测：点「运行评估」→ 轮询 → 结果表「1+1 | 期望2 | 实际'1+1 = 2。' | PASS」。评估/成本 tab 真实数据渲染，0 降级。
[done] 2026-08-17 · ←后端 | **派发链路真实后端联调验证通过**（:8000 + 前端 :5174 VITE_USE_MOCK=false）| 前后端契约对接全链路 OK。
      演示「帮我调研 SSE」→ 流式期捕获 **2 条 agent_switch 指示条**（通用助手 → research 携带任务 / research → 通用助手 子任务完成）+ dispatch_subagent 工具卡「完成」+ 主 Agent 最终 Markdown 调研报告（基于 WHATWG/MDN 整理）。页面错误 0。
      另实测：POST /conversations 不带 agent_id → 200，返回 agent_id=默认通用 Agent uuid（`9c1f9091…`），新契约生效。
[done] 2026-08-16 · →后端 | **前端已对齐「单通用 Agent」契约**（M5 重构收敛：删 /agents API、请求去 agent_id、graph_template 废除）| 你 emits agent_switch（tl_dispatch_subagent 派发）前端即自动渲染。
      实测：typecheck ✓ / lint 0err / 108 单测 PASS / 21 e2e PASS；chat 顶部无 agent 选择器、TasksView 无 agent 选择器、侧栏无 Agents 菜单。
      说明：前端无任何 `/agents` 调用；若后续要「默认 Agent 配置页」，需后端补 `GET/PUT /agents/default` 端点（另立项）。

[done] 2026-08-16 · ←后端 | **M3 正式闭环**（Gate1 Test 207/207 + Gate2 14 项 + Gate3 Simplify 应用 16/跳过 12）| 后端就绪，可联调。
      后端 :8000 已拉起验证过（admin/admin123）；五组接口 + 8 组既有全部可用。请前端列联调计划清单，我按清单逐项核验。联调后跑一次 `scripts/verify_m3.sh`（需后端运行）做全链回归。

[done] 2026-08-16 · ←后端 | **联调缺口修复**：中断→resume 无法在真实会话触发（seed agent 无 require_confirm 工具）| 已修（commit fe7538b）。
      根因：seed agent「时间助手」tools 只有 tl_time_now + 提示词限定时间问题，demo_notify 虽注册启用但 agent 不可用。
      修法：seed agent 挂 tl_demo_notify + 提示词补引导；重跑 `uv run python -m app.seed` 幂等更新。
      验证：实测 tools=['tl_demo_notify','tl_time_now']。前端联调可用 seed agent 对「发个通知/提醒我」触发中断→确认→resume。
[done] 2026-08-16 · →后端 | **M4 前端 agent_switch 渲染完成**：useChatStream 状态机 + MessageBubble 指示条 + mock 演示（chat: ag_search→ag_review / task: ag_proposer→ag_reviewer）+ 任务事件端点 GET 修复 | 你 emit agent_switch 即自动生效，无需改前端。
      验证：108 单测 + 21 e2e 全绿；mock 非 fast 实测指示条流式期显示、done 后消失（仅流式期，Message 无持久化字段——如需 done 后仍显示，需后端在 message 数据模型加 agent_switch 字段，属协调项）。

[done] 2026-08-16 · ←后端 | **M4 联调收口**：seed 已加「协作助手」（graph_template=proposer_reviewer，commit 后续）| 前端可直接演示，无需自建 agent。
      实测 invoke：3 次 agent_switch（assistant→proposer→reviewer→assistant）+ 真实定稿输出 ✅
      前端演示路径：登录后选择「协作助手」→ 发消息 → 流式期应见切换指示条（assistant→proposer→reviewer→assistant）→ 定稿气泡。

[done] 2026-08-16 · ←后端 | **M4 最小闭环完成**（commit 44b0a30）| agent_switch 后端已发射，与你前端渲染直接对接。
      - 任务队列 Redis：POST /tasks 入队（task:queue）→ 常驻 worker BRPOP 消费跑图（Redis 挂降级 create_task）；实测提交→worker→真实 LLM→done ✅
      - live-tail Redis Pub/Sub：任务事件 / 通知 SSE 跨实例广播（终态哨兵 + 断线重连 + 进程内回退）
      - 幂等持久化 Redis；proposer-reviewer 二段协作：agent graph_template="proposer_reviewer" 时后端发 3 次 agent_switch（assistant→proposer→reviewer→assistant）
      - 联调验证：用 graph_template="proposer_reviewer" 的 agent 试跑，前端应看到切换指示条 + 定稿输出
      - 另：fetch_url/analyze_image 内置工具已注册（默认关，管理页可启用）；GET /system/evals 契约路径已补
      - 228/228 + verify_m3.sh 14/14 全绿
[done] 2026-08-16 · →后端 | 中断修复已前端真实验证 | 「提醒我明天上午开会」→ 弹窗 → 确认 → resume 续流「通知已发送成功」+ demo_notify 完成卡 + composer 恢复。

[done] 2026-08-16 · →后端 | GET /system/evals/sets 404 | 期望 EvalSet[]（docs/03 §5.8）。
      根因 Agent/app/api/routers/evals.py APIRouter() 缺 prefix="/system/evals"；数据形状已对齐，仅路径错位。
      修法：router = APIRouter(prefix="/system/evals")。→ 后端已修（commit 0b5727c），实测 HTTP200。
[done] 2026-08-16 · →后端 | 契约核验：5 组新接口仅 evals 有缺口，其余对齐 | 前端零改动。
[done] 2026-08-16 · ←后端 | 五组接口全部就绪（不再 404），联调可直接走真实后端 | 后端实测 :8000 全 200。
      - kb progress 已统一 number；done 消息 tool_calls 已含 position → 前端 normalizeProgress / position 兜底两候选修复均无需应用。
      - trajectory 已实现 before_seq/limit 分页 + has_more；kind 仅 user/assistant，thinking/diff 恒 null（无 system 更新数据，契约允许）。
      - 联调注意：登录用后端 seed 账号 admin/admin123（与 mock 一致）；SSE 帧为 sse_emitter 信封 {id,seq,type,ts,payload}。

---

> 对话界面优化：输入框修复 + 工具卡精简 + 流式气泡修复
> 项目无 git 仓库，跳过 commit；以 typecheck/test:unit/test:e2e 作为验证门禁

## 任务
- [x] T1 Fix1 输入框：ChatView composerDisabled 改流式状态 + useChatStream start/confirmInterrupt try/finally 兜底
- [x] T2 Fix2 工具卡：ToolCallCard 只显示名称+状态（隐藏 input/output/summary/duration）
- [x] T3 Fix3 气泡：useChatStream 文本段置顶唯一 + 无空播种 + done 回填 messageId；MessageList 防闪跳
- [x] T4 单测：useChatStream.spec 新增文本置顶用例 + resume 断言 messageId
- [x] T5 e2e：chat-stream.spec 工具卡断言改“完成” + composer textarea 恢复可用断言
- [x] T6 文档同步 + 全量验证（typecheck / test:unit / test:e2e）

## 执行日志
- 2026-08-14 计划批准，开始执行。
- 2026-08-14 T1-T6 全部完成。验证：
  - `npm run typecheck` → 干净
  - `npm run lint` → 0 errors（3 warnings 均为既有 any，非本次引入）
  - `npm run test:unit` → 63 PASS（11 文件；原 62 + 新增 1：message_start 无空播种 + tool_call 先于文本时文本段置顶）
  - `npx playwright test e2e/chat-stream.spec.ts` → 3 PASS（含：工具卡不再显示参数→断言“完成”；一轮/单轮完成后 composer textarea 恢复可用）
  - 文档同步：docs/02-frontend-design.md §6.2 ToolCallCard 描述 + §5.4.3 混排说明；CLAUDE.md “文本×工具卡混排”要点
  - 项目无 git 仓库，跳过 commit。
- 2026-08-14 review-test-simplify 三道 gate（Test/Review/Simplify 全过），用户批准修复 7 项：
  - P1 防闪跳改“同步追加”（删 messageId 匹配/回填）：MessageList 恢复 `!finished`；ChatView onPersistedMessage 同步 appendAssistantMessage；chat store 新增 appendAssistantMessage
  - P2 ToolCallCard 状态标签补 cancelled(已取消)/awaiting_confirm(待确认)，不再显示绿色“完成”
  - P4 e2e 用例1 加负断言 `not.toContainText('6*7')`
  - S1 删除 chat store 死 `streaming`/`setStreaming` + ChatView 3 处调用
  - S5 删除 ToolCallCard 未用 props input/output/summary/durationMs + MessageBubble 对应 4 处绑定
  - F 发送按钮绑定 composerDisabled（中断等待时不再“看似可用”）
  - P5 补静默关流 streaming 复位单测
  - 复核：typecheck ✓ / lint 0err / 64 单测 PASS / 3 e2e PASS / 拒绝分支工具卡显示“calculator | 已取消”
  - 跳过（记录不改）：try/finally 抽 wrapper、partialText 与 segments 重复、message_start 冗余 seed、retry 无处理器（既有）、contextMetrics/tokenUsage 无读者（契约预留）、scroll 与 useVirtualList 重复（既有）
  - 文档已同步（P6 误报）。
- 2026-08-14 新任务：长会话滚轮上滚“抽搐滚不上去”。
  - 根因：MessageList 手写 useVirtualList 虚拟滚动测量反馈循环（实测高度→平均高度→startIndex→offsetY 漂移），上滚时内容与原生滚动互相拉扯。
  - 用户确认“去掉虚拟滚动”。修复：
    - MessageList 直接平铺渲染全部消息（每页≤50）+ `content-visibility: auto`/`contain-intrinsic-size: auto 120px`；稳定 key；保留吸底 watch
    - 删除 src/composables/useVirtualList.ts + useVirtualList.spec.ts（全局无引用）
    - 文档同步 docs/02-frontend-design.md（§5.3 / §5.4.4 / §6.2 / FD-5 / 目录）
  - 验证：typecheck ✓ / lint 0err / 62 单测 PASS（删 useVirtualList.spec 2 条）/ 3 e2e PASS / DOM 验证无 .virtual-spacer、6 条消息平铺渲染、上滚/中/底 scrollTop 稳定不回落。
  - 不做：消息分页排序（mock 第 1 页=最旧 50 条，若真实后端>50 且不排序则最新不在第 1 页，属独立问题留待跟进）。
- 2026-08-14 新 bug：流式完成后文本气泡消失、工具卡仍在。
  - 根因：上一轮 P1“同步追加”直接用 done 的 `message`；真实后端 done 时 `content` 可能未就绪（空），append 后 MessageBubble 只渲染有内容的工具卡 → 文本气泡消失。
  - 修复（src/views/ChatView.vue onPersistedMessage）：append 时 content 兜底 = `m.content 有值 ? m.content : stream.state.partialText`；同时不再 done 后 refreshMessages（page1 分页会截断长会话最新消息），服务端一致性改由重进会话/刷新同步。删除 store 已无用的 `refreshMessages`。
  - 验证：typecheck ✓ / lint 0err / 62 单测 PASS / 3 e2e PASS / mock 多轮 DOM 验证每轮文本+工具卡都在、不截断。
  - 说明：真实后端空 content 场景无法用 mock 直接复现（mock 恒有 content），兜底逻辑由 partialText 单测 + 代码审查保证。
- 2026-08-15 新功能：响应式侧边栏自动收回（窗口 <960px）。
  - 用户确认：主侧边栏收成 64px 图标栏；ChatView 会话列表面板也要能收回。
  - 改动：
    - 新增 `src/composables/useMediaQuery.ts`（响应式 matchMedia）+ `src/constants/layout.ts`（NARROW_LAYOUT_MQ='(max-width: 960px)'）
    - `SidebarNav.vue`：`collapsed = isNarrow || userCollapsed`；折叠按钮改切 userCollapsed 且窄屏隐藏
    - `ConversationList.vue`：新增 `collapsed` prop，宽度过渡收起（220→0）
    - `ChatView.vue`：`convOpen` + watch(isNarrow) 自动收回/恢复；顶栏 Fold/Expand 切换按钮；`:collapsed="!convOpen"`
  - 测试：新增 `useMediaQuery.spec.ts`（3 条）+ `e2e/layout.spec.ts`（视口缩放断言收回/展开）
  - 验证：typecheck ✓ / lint 0err / 65 单测 PASS / 10 e2e PASS（auth+guards+chat-stream+layout）
  - 文档：docs/02-frontend-design.md §4.1 补响应式说明。
  - 不做：更窄完全隐藏+汉堡抽屉、表格横向溢出、会话列表宽度拖动。
- 2026-08-15 新功能：Agent 对话轨迹（Trajectory）查看页 — MVP。
  - 用户确认：新增接口 / 先做 MVP / 独立页 + Chat 入口。
  - 契约：新增 `GET /conversations/{id}/trajectory`（docs/03 §5.2.1），由 message+tool_calls 只读派生（docs/04 §3.2.1）。
  - 改动：
    - types/api.ts 加 TrajectoryToolCall/TrajectoryNode/TrajectoryDetail；api/trajectory.ts getTrajectory；api/index 导出
    - mock/server.ts 加 /conversations/:id/trajectory（空会话返回 200+空 nodes，不存在 404）
    - utils/trajectory.ts 折叠纯函数（Turn→Group→Cell，全局 #N、tool 按 position、空 content 省略、summary）；format.ts 加 formatTime
    - stores/trajectory.ts；router/routes.ts 加 /trajectory/:conversationId（隐藏菜单）；ChatView 加「轨迹」按钮
    - views/TrajectoryView.vue + components/trajectory/{TrajectoryTimeline,TrajectoryLedger,TrajectoryDetailPanel}.vue（时间轴 3 泳道 + sequence/duration 投影；台账分组/折叠/搜索/选中；详情标签页；可拖拽调宽）
  - 测试：utils/trajectory.spec.ts（10 条折叠规则）+ e2e/trajectory.spec.ts（深链 c_001/c_002、选中联动、搜索、返回）
  - 验证：typecheck ✓ / lint 0err / 75 单测 PASS / 12 e2e PASS / DOM 验证（3 泳道各 1 span、台账 3 行、详情入参、全部折叠、投影、Chat 轨迹按钮）
  - 文档：docs/03 §5.2.1 轨迹端点、docs/04 §3.2.1 只读派生模型、docs/02 §6.2/§6.3 组件与折叠规则。
  - 不做（记录）：框选/缩放/平移、time/actual 投影、diff、虚拟滚动、thinking/reasoning 展示（契约预留未落库）、compaction/steering/context。
- 2026-08-15 MVP → 完整版（用户要求"把mvp做成完整的"）：
  - 时间轴补全：`time`/`actual` 投影、滚轮缩放（以鼠标为锚）、右键拖拽平移、左键框选（选中区间首条）、点击空白选最近、双击/Esc 复位、搜索暗化非命中、aria-label
  - 台账：Cell 行 `content-visibility:auto` 屏外跳过渲染；选中行 `scrollIntoView` 滚动到可见区
  - 详情：tool 增加 `Schema` 标签（占位）；窄屏 <1100px 详情改浮层覆盖台账
  - 跨视图定位：`?focus=<toolCallId>` 深链自动选中并滚动
  - 文档：docs/02 §6.3 更新为完整交互说明
  - 测试：e2e 增 focus 深链 + 4 投影渲染；真机验证滚轮缩放/点击选中/框选/双击复位/点击空白选最近均生效
  - 验证：typecheck ✓ / lint 0err / 75 单测 PASS / 14 e2e PASS
  - 仍不做（数据模型无对应）：diff 标签（无 system 更新数据）、thinking/reasoning 展示（契约预留未落库）、compaction/steering/context 节点、时间轴"加载更早历史"按钮（轨迹接口一次返回全部）。
- 2026-08-15 清理遗留 dev server（5173-5177 全杀）+ 补齐数据模型缺失项（完整版）。
  - 契约：`TrajectoryNode.kind` 扩展 context/steering/compaction；新增 `thinking`/`diff` 字段；`TrajectoryDetail.has_more` + `?before_seq&limit` 分页（docs/03 §5.2.1、docs/04 §3.2.1）。
  - 折叠（utils/trajectory.ts）：context→当前 Turn contextCells（含 diff）；steering→开 Turn（userCell）；compaction→`Compaction <seq>` 组（compacted cell）；assistant 附 thinking；kindLane 泳道映射。
  - 新增 `utils/diff.ts`（行级 LCS 统一 diff，6 单测）。
  - mock（src/mock/trajectory.ts）：kind 映射 + c_001 注入 context(diff)/thinking/compaction；c_long 程序化长会话；before_seq/limit 分页 + has_more。
  - 组件：时间轴泳道 Input/Model/Tools + hasMore「…加载更早」按钮；台账渲染 contextCells；详情 思考/Diff 标签。
  - store/api：getTrajectory 分页参数；store.load/loadEarlier（prepend 累积）。
  - 验证：typecheck ✓ / lint 0err / 86 单测 PASS（含 5 新折叠用例 + 6 diff）/ 16 e2e PASS（含 context/compaction 渲染、c_long 加载更早、focus、4 投影）/ 真机 Diff 标签 + 思考标签 + 加载更早按钮均生效。
  - 清理：5173-5177 全部 dev server 已杀。
- 2026-08-15 布局重构（会话列表并入主侧边栏 + 设置子侧栏 + Chat 会话|轨迹切换）。
  - 用户确认：设置子栏=主侧栏右侧窄条；原 /settings 保留为子项；对话页窄屏保持展开。
  - 改动：
    - routes.ts：menuItems 层级化（设置带 children）+ SETTINGS_ROUTES/isSettingsRoute
    - 新增 SettingsSubNav.vue（176px 窄子栏，按角色过滤）；SidebarNav 重写（logo+折叠顶部、Agents/对话、会话列表区、知识库/设置底部）
    - App.vue 接设置子栏（flex 子元素，不遮挡）
    - ConversationList 深色侧栏化 + 自包含 store/router（select/create 导航 /chat）
    - 新增 TrajectoryPanel.vue（从 TrajectoryView 抽出工作区），TrajectoryView 改为复用
    - ChatView：去会话面板/Fold/跳页按钮；加 会话|轨迹 radio，轨迹内嵌 TrajectoryPanel
  - 关键修复：guard 刷新竞态（App onMounted hydrate 在途时 status=loading，守卫跳过 hydrate → 角色页刷新误跳 /chat；用 roleFromToken 兜底）。chat store 加 selectionToken（侧栏选会话才复位流式，创建会话不误杀）。
  - 测试：routes.spec（isSettingsRoute + 层级）；重写 guards/layout；新增 restructure.spec（会话|轨迹切换、侧栏新建导航、设置子栏）
  - 验证：typecheck ✓ / lint 0err / 89 单测 PASS / 20 e2e PASS / 真机布局验证（侧栏顺序、子栏 x=232 不重叠、轨迹内嵌 composer 隐藏）
  - 文档：docs/02 §4.1 布局图更新；tokens.css 加 --app-settings-subnav-width。
- 2026-08-15 UI 细化：设置气泡卡片 + 会话列表浅色框 + 主题配色切换器（用户三项优化）。
  - 设置子侧栏 → 气泡卡片：删除 SettingsSubNav.vue；SidebarNav 的「设置」按钮包 el-popover（right-start，172px），内容=设置组子项（/settings 的 children 按 canAccess 过滤），点子项跳转+气泡自动关；App.vue 恢复 `<SidebarNav/>`；isSettingsRoute 做按钮高亮。
  - 会话列表浅色框：tokens.css 加 `--app-sidebar-conv-bg:#26263a`；ConversationList `.conv-list` 用该变量 + 圆角（深侧栏 + 浅框一深一浅）。
  - 主题系统：新增 src/theme/themes.ts（ThemeDef + solidTheme 生成器 + 撞色手写 var 集 + hexMix/lighten/darken；applyTheme 写 :root、getStoredTheme/setStoredTheme localStorage key agent.theme、DEFAULT indigo）；9 套=6 纯色（靛蓝/墨蓝/翠绿/紫罗兰/赭橙/绯红，conv-bg=lighten(sidebar,0.06)）+3 撞色（黑白/浅红×浅蓝/红黄）。
  - ThemeSwitcher.vue（TopBar 通知左侧短袖按钮 + 气泡色块）→ TopBar.vue 插在 NotificationBell 前；main.ts mount 前 applyTheme(getStoredTheme()) 防闪色。
  - 清理：tokens.css 删残留 --app-settings-subnav-width（SettingsSubNav 已删，无引用）。
  - 测试：新增 themes.spec.ts（9 主题 id 唯一/必需 var/纯色 conv-bg≠bg/applyTheme+默认 stored）；e2e 更新 guards（`.settings-subnav`→`.settings-popover .sub-item`）、restructure（子侧栏→气泡：点开 5 项→点子项跳转）；新增 theme.spec.ts（短袖→翠绿→主色#22c55e+localStorage→刷新保留）。
  - 验证：typecheck ✓ / lint 0err / 93 单测 PASS / 21 e2e PASS。
  - 文档：docs/02 §4.1 布局图去设置子栏改气泡卡片 + 会话列表浅框 + TopBar 主题切换；§3 工程结构加 theme/；§6.2 加 ThemeSwitcher 行；新增 §6.4 主题系统（9 套表 + 实现 + 测试）。
- 2026-08-15 L1 微调：工作流分级（全局 CLAUDE.md + FrontEnd 末行同步）。
  - 三档流程入全局 CLAUDE.md（L1 微小/跳计划仅简易笔记+快速 Test+豁免 Simplify；L2 常规/轻量计划+完整流程；L3 大型/强制三段不可简化）+ 升级规则（深度超定档就地升级）+ 验证纪律（开发跑子集、收尾全量；影响面核查 grep+全量 tsc）。FrontEnd CLAUDE.md 末行指向三档模型。无代码改动，无需构建。
- 2026-08-16 前端接真实后端（纯前端，后端由另一 agent 推进，不动后端代码）。
  - 计划：C:\Users\Admin1\.claude\plans\sleepy-humming-sparrow.md（L2）
  - 决策：dev 保持 mock 默认；缺失接口前端优雅降级；Provider 表单暂缓。
  - 判别信号：真实后端未注册路由 → HTTP 404（非信封）；业务 404xx → HTTP 200+信封，不重叠 → 纯 404 检测不误伤。mock 全实现 → 永不触发。
  - 阶段 1 检测打标地基、阶段 2 SSE 防护、阶段 3 页面降级（trajectory/通知铃铛/用户 tab/系统 tab）。阶段 4 契约对齐验证待后端 :8000 可用（检查时未响应）。
  - 执行：
    - 阶段 1：availability.ts（FEATURE + featureForUrl/mark/isUnavailable/reset，模块 ref 单一事实源）+ http-envelope isNotImplementedError（HTTP 404 = 端点未实现，信封 404xx 仅显式「未实现」标记才打标）+ http.ts request(url,promise) 签名 + guarded fail-fast 短路（创建请求前拦截）+ http.spec 5 新用例。
    - 阶段 2：sse.ts openSseStream 404 打标；useSSE onError 未实现短路不重连；sse.spec 2 新用例。
    - 阶段 3：trajectory store notImplemented getter + load/loadEarlier 短路；TrajectoryPanel 空态分支；NotificationBell unavailable computed 隐藏铃铛 + 条件启 SSE；SettingsView 用户 tab catch + EmptyState（Provider 不动）；system store 3 per-feature getter + 吞未实现；SystemView 3 tab 空态。
    - 验证：typecheck ✓ / lint 0err（3 既有 any 警告）/ 100 单测 PASS（+7：http 5 + sse 2）/ 21 e2e PASS（mock 零影响）。
    - Review 门（feature-dev:code-reviewer）发现 2 项已修：
      - A 功能组粒度过粗：拆分 FEATURE（notificationsStream 独立于 notifications、systemTrace 独立于 systemLogs），子路由 404 不再折叠同组可用功能；FEATURE_ROUTES 更具体优先。sse.spec 断言同步更新。
      - B 降级路径 unhandled rejection：TraceTimeline 补 unavailable/loadFailed 状态 + swallowNotImplemented；SystemView onRunEval 包降级；SettingsView 4 个写操作包降级（deleteUser 成功返回 null，用 ===undefined 判未实现）。
    - Simplify 门（Reuse+Simplification）应用：合并 request(url,thunk)+删 fail-fast 死 toast 分支+一次算 feature；availability 加 isUrlUnavailable/markUnavailableForUrl 收敛三处路由映射；http-envelope 加 swallowNotImplemented 收敛 4 处 catch 惯用法；trajectory getter 改名 unavailable + guard 复用 reset；NotificationBell getToken hoist。跳过（记录）：SystemView 模板缩进未重排（功能正确、lint 干净）。
    - 新增 availability.spec（7 用例：路由映射优先级/URL 级封装/reset/Pinia getter 反应式）。
    - 最终 gate：typecheck ✓ / lint 0err / **107 单测 PASS**（+7 availability）/ 21 e2e PASS。
    - 阶段 4（契约对齐 + kb progress/tool_calls.position 归一化）待后端 :8000 运行后联调，当前未做臆测改动。

## 联调准备（2026-08-16 存档，阶段 4 执行清单）
- 前置：后端 :8000 运行；登录用**后端 seed 账号**（mock 的 admin/admin123 不适用）。
- 启动：`VITE_USE_MOCK=false npm run dev`（Vite proxy → :8000，无 rewrite）。
- 逐页核对（后端已有的 8 组）：登录/me/401 跳转；会话列表/新建/详情/分页；Chat SSE 发送→token→工具卡→done + 中断→确认→resume（interrupt 带 task_id）；任务提交/列表/取消/恢复/事件；Agent CRUD/发布/版本/试跑；工具列表/注册/开关/测试/搜索/MCP；KB 集合/上传/分块状态/重索引/混合检索；记忆列表/整理；附件上传→attachment_id→分析。
- 确认降级生效（后端缺失的 5 组）：轨迹页/内嵌面板空态、通知铃铛隐藏、设置用户 tab 空态、系统 3 tab 空态、trace 抽屉提示。
- 两个候选修复（实测确认偏差才做）：`src/api/kb.ts` normalizeProgress（后端 progress 可能字符串/布尔）；`src/api/chat.ts` tool_calls.position 兜底。
- 只改前端，不动 Agent/ 目录。

### 契约核验（2026-08-16，真实后端 :8000 实测，admin/admin123，前后端联调前置）
- ✅ 已对齐（形状与 types/api.ts + api 模块一致，前端零改动）：
  - auth/me；trajectory（含 before_seq/limit 分页；节点带 thinking/diff/trace_id/tool_calls）
  - notifications：REST 分页 + PATCH read + SSE `GET /notifications/stream`（HTTP 200 text/event-stream）
  - users（GET/POST/PATCH/DELETE，admin 403 兜底）；system/logs（分页 + trace_id/level 过滤）；system/cost
  - kb：collections/documents（**裸数组**，前端 listDocuments 已对齐）/status；`progress=number`（实测 100）✓
  - messages：分页 {items,total,page,page_size}；`tool_calls[].position` 实测存在（0）✓；tasks/agents/tools 200
- 候选修复判定：kb `normalizeProgress`、`tool_calls.position` 兜底 **均不需要**（后端已返回 number / position，defer 判断正确）。
- 🔴 契约缺口（后端 bug，勿前端绕开）：`/system/evals/*` 全部 404。
  - 根因：`Agent/app/api/routers/evals.py` 的 `router = APIRouter()` **缺 `prefix="/system/evals"`**，路由实际注册到 `/api/v1/sets`、`/api/v1/runs`、`/api/v1/system/evals/run` 之外的位置。
  - 期望：`GET /system/evals/sets`（docs/03 §5.8 + api/system.ts）返回 `EvalSet[]`；实际 404。
  - 数据形状已对齐（/api/v1/runs 返回含 progress/pass_rate 的 EvalRun），仅路径前缀错位。
  - **后端修法**：`router = APIRouter(prefix="/system/evals")`（docstring 已写明该前缀）。
  - 修复前：前端 SystemView 评估 tab 走降级空态「后端暂未实现评估接口」（HTTP 404 判据）；修复后刷新自动恢复，无需改前端。
- 本轮无前端代码改动（门禁维持上一轮全绿：typecheck / 107 单测 / 21 e2e）。

### 联调执行（2026-08-16，真实后端 :8000 + 前端 :5174 VITE_USE_MOCK=false，Playwright 驱动）
- ✅ 登录 admin/admin123 → /chat；**8 页全部渲染真实数据、0 降级空态**（轨迹/通知/用户/系统 tab 均正常，降级机制休眠正确）
- ✅ 轨迹页（含 `?focus` 深链）真实数据渲染
- ✅ 聊天 SSE 流式：助手真实回复 + markdown 渲染 + composer 恢复可用
- ✅ verify_m3.sh 全链回归 **14/14**（KB 真实索引/混合检索/记忆/附件/清理）
- ✅ 控制台 pageerror 0；HTTP>=400 仅一次 `/tasks` 瞬时 404（Vite HMR 抖动，复测 3 次全 200，非真实问题）
- ⚠️ **中断→resume 未在真实会话触发**：真实 LLM 未调 require_confirm 工具（可能 agent 未启用 tl_demo_notify）。机制两侧均已各自验证（前端 mock e2e chat-stream + 后端 M2 interrupt→resume e2e），此条留**手动验证**。
- 手动验证项（脚本难覆盖，走清单）：KB 文件上传、评估运行（需评估集）、记忆 maintenance、用户 CRUD、MCP 注册、通知 SSE 实时推送、中断触发。

## 2026-08-16 M4 前端：agent_switch 事件渲染 + mock 演示（L2）
- 计划：C:\Users\Admin1\.claude\plans\sleepy-humming-sparrow.md
- Step 0 ✅ 后端中断修复验证：真实后端「提醒我明天上午开会」触发 tl_demo_notify → 中断弹窗 → 确认 → resume 续流（工具卡 demo_notify 完成 + 文本「通知已发送成功」+ composer 恢复）。后端 commit fe7538b 生效。
- Step 1 ✅ useChatStream：StreamSegment 加 `{kind:'agent';id;from;to;reason?}` + applyEvent `agent_switch` case（事件序混排 push）。
- Step 2 ✅ MessageBubble：Seg 联合加 agent 变体 + `.agent-switch` 指示条（`is-agent` 去气泡框弱化视觉）。
- Step 3 ✅ mock server 任务事件端点接受 GET（对齐契约/TaskDetail/真实后端，POST 保留兼容）。
- Step 4 ✅ mock 流插入 agent_switch 演示：buildChatScript 默认分支（ag_search→ag_review 检索结果复核）+ buildTaskEventsScript（ag_proposer→ag_reviewer 提案需审核）。
- Step 5 ✅ TaskDetail 事件回放 agent_switch 渲染 chip（from→to + reason），其余事件原样。
- Step 6 ✅ 单测 +1（agent_switch → segments agent 段 from/to/reason，streaming 不变）。
- Step 7 ⚠️ e2e agent 指示条断言**撤销**：指示条仅流式期显示（showStreamBubble=!finished），mock-fast 零延迟 done 后即消失 → 固有竞态。改 mock 非 fast 手动验证：流式期 `.agent-switch` 显示「ag_search → ag_review检索结果需复核」，done 后数量=0 ✓。状态机由单测覆盖。
- 验证：typecheck ✓ / lint 0err / 108 单测 PASS（+1）/ 21 e2e PASS。
- Review 门：feature-dev:code-reviewer 无 CONFIRMED 正确性问题。
- Simplify 门应用 4 项：复用 AgentSwitchPayload 类型（useChatStream/TaskDetail）；TaskDetail 事件项改 computed 一次性算（消 3 次 switchInfo 调用）；mock 事件路由改用 match() helper；msg-seg.is-agent 改裸词 agent。跳过（记录）：组件抽取/ mock helper（过度抽象）。
- 已知限制：agent_switch 仅流式期显示、done/刷新后消失（Message 无持久化字段，契约预留）。

## 2026-08-16 前端对齐「单通用 Agent」重构（L3，后端 M5 收敛）
- 计划：C:\Users\Admin1\.claude\plans\sleepy-humming-sparrow.md（覆写 M4 计划）
- 背景：后端 agent 发起架构重构（单通用 Agent 模型，迁移 0006_single_general_agent）：删 `/agents` REST API（含版本化）、`ChatRequest`/`CreateConversationRequest`/`SubmitTaskRequest` 去 `agent_id`、Agent 模型删 `graph_template`、新工具 `tl_dispatch_subagent`（tool_type=agent_control）替代 graph_template 多 Agent 串流；`agent_switch` SSE 事件仍在发（payload 不变）。用户决策：砍掉整个 Agents 页 + 走 L3 计划。
- 改动：
  - types：api.ts 删 3 请求 `agent_id` + 删 Agent/AgentConfigInput/AgentVersion + 删 GraphTemplate/AgentConfigStatus import；domain.ts 删 GraphTemplate/AgentConfigStatus、ToolType 加 `agent_control`；ToolsView TYPE_LABEL 加 `agent_control: Agent 控制`
  - 删除：api/agent.ts、stores/agent.ts、AgentsView.vue、AgentConfigForm.vue、AgentTestRunner.vue、router /agents 路由+菜单
  - chat store：删 currentAgentId/activeAgentId/setAgent；createConversation(title)
  - ChatView：删 agent 选择器/onAgentChange/agentStore/agent_id；ConversationList createConversation('新会话')；TasksView 删 agent 选择器+校验，提交只带 input
  - mock：db 删 agents/agentTemplate、DEFAULT_AGENT_ID='ag_default'、conversation/task agent_id 归一；server 删 /agents 路由块、3 处 agent_id→DEFAULT_AGENT_ID；stream agentId 固定 DEFAULT_AGENT_ID、ConfirmCtx 删 agentId、agent_switch 演示换真实 subagent 名（通用助手→research/proposal_review）
  - 测试：guards.spec viewer /agents→/tools；layout.spec /agents→/kb；restructure.spec /agents→/tools（routes/guard/availability/useChatStream spec 无需改）
  - 文档：docs/02 删 Agents 页/组件/store 引用 + 守卫清单；CLAUDE.md 补「单通用 Agent」要点
- 验证：typecheck ✓ / lint 0err（3 既有 any 警告）/ **108 单测 PASS** / **21 e2e PASS** / build ✓ / DOM 手测（侧栏无 Agents、chat 工具栏无 agent 选择器、任务提交无 Agent 下拉）
- Gate（L3 完整三道）：Test 全绿；Review 0 严重（2 死代码 + 1 UX 噪音）；Simplify 应用 4 项（SidebarNav pick 收窄单参、stream.ts 内联 DEFAULT_AGENT_ID、ChatView 过时注释、TasksView 单字段 ref）+ 删 StreamState.agentId（无消费者）+ MessageBubble 过时注释
- 跳过（记录不改）：TaskList/TaskDetail 的 Agent 列恒为默认 id（UX 噪音，Task.agent_id 契约仍返回，属产品决策）；domain.ts AgentStatus（既有未用，docs 引用）；mock/server.ts 会话创建抽 helper（两处 title 派生略异，过度抽象）；useChatStream.start endpoint 参数已无真实调用方（AgentTestRunner 删除后遗留，后续清理）
- 交接：后端已在交接板确认重构完成（`/agents*` 404、请求去 agent_id、tl_dispatch_subagent、agent_switch「通用助手→subagent→通用助手」），与前端收敛一致
- 不做（记录）：后端默认 Agent 配置页（无端点，需后端补 /agents/default 另立项）；docs/03/04 契约文档更新归后端 agent

## 2026-08-17 工作区壳页（L2）：入口在对话上方，内部设计待定
- 用户指令：完成工作区页面搭建（用户自建 agent 功能已取消）；按钮放对话上方；内部设计先不做。
- 改动：
  - routes.ts：menuItems 顶部加 `/workspace`（Grid，无角色限制）+ 路由 → WorkspaceView
  - SidebarNav：`pick(paths)` 恢复多路径；topItems = `['/workspace', '/chat']`（工作区在对话上方）
  - 新建 `src/views/WorkspaceView.vue`：壳页（app-page 头 + el-empty「工作区规划中」）
  - routes.spec +1：菜单顶部顺序 = /workspace → /chat
  - docs/02：页面表 + 布局图 + 侧栏描述补工作区；CLAUDE.md 页面清单 8 页
- 验证：typecheck ✓ / lint 0err / **109 单测 PASS**（+1）/ **21 e2e PASS**
- 排障：e2e 首轮 20 失败 = 5173 残留 dev server 被 playwright reuseExistingServer 复用（非 mock e2e 模式）→ 清端口后全绿，非代码回归。
- 不做（记录）：工作区内部设计（用户自建 agent 取消，用途待定）；角色限制（无角色，所有登录可见）。

## 2026-08-17 真实后端联调：M4 完整版新特性验证 + M5 评估联调（L2）
- 前置：后端 :8000（M4 完整版 c785b7f 已提交并重启）；前端 :5174（VITE_USE_MOCK=false）。
- M4 完整版验证（交接板邀请项）：
  - **initiate_demo 占位→回填**（chat UI）：发「用 initiate_demo 发起一个 3 秒任务」→ t≈1.8s 工具卡「initiate_demo 处理中」（占位）→ t≈6.8s 回填「完成」+ 助手提及结果 ✅（SSE 探针亦确认 placeholder/job_ref 事件）
  - **任务取消 in-flight**（API）：提交长生成任务 → progress 0.5 时 POST /tasks/{id}/cancel → status=cancelled ✅（initiate_demo 任务是占位语义、图本身很快 done，故用长 LLM 生成任务验证真实中断）
- M5 评估与观测：
  - 评估/成本 tab 真实数据渲染：评估集「契约验证集」（1 用例）+ 运行评估按钮；成本 ¥0.01 / 802 次 / 2 Provider + CostChart；0 空态 0 页面错误 ✅
  - **发现缺口并修复**：POST /system/evals/run 后台异步（asyncio.create_task），前端 onRunEval 立即取 detail → 空结果表。修法：SystemView 加轮询至终态（2.5s / 120s 超时）。实测结果表「1+1 PASS」✅
- 验证：typecheck ✓ / lint 0err（3 既有 any）/ **109 单测 PASS** / **21 e2e PASS**。
- 不做（记录）：评估运行历史列表展示（当前只显示单次运行结果；runs 列表接口已有，前端未接）；评估集创建/用例管理（SystemView 只读展示，创建走后端 seed/手动）。

## 2026-08-17 对话显示优化（L3）：删重试按钮 + 工具活动区 + 流式 Markdown
- 计划：C:\Users\Admin1\.claude\plans\sleepy-humming-sparrow.md（覆写）
- 三项用户要求：
  - ① 删工具失败重试按钮——重试由 agent/用户语言发起，前端不点击重试。
  - ② 工具调用不作为气泡，改优雅地出现在 agent 回复气泡上方；多工具/思考往下递进。
  - ③ 流式输出实时渲染 markdown（原来 done 才一次性渲染，不优雅）。
- 改动：
  - **A 重试链路清空**：ToolCallCard 删 emit retry + `.tool-retry`（失败保留 error 文案）；MessageBubble/MessageList/ChatView 删 retry emit 链 + onRetry。
  - **B 活动区 + 回复气泡**：MessageBubble 重构——computed 拆 `activityItems`（tool/agent/thinking，非气泡紧凑行）+ `textSeg`；模板活动区在上（`v-for` 往下递进）、回复气泡在下；持久化消息 content→气泡、tool_calls[]→活动区；ToolCallCard 改行式（保留 `.tool-card` class 与状态文案）；agent-switch 并入活动区；useChatStream StreamSegment 加 `thinking` + case（后端发射即显示，预留）。
  - **C 流式 markdown**：markdown.ts 加 `splitStreamingText`（换行切分 stable/tail）+ `renderStreamingMarkdown`（stable 走管线、tail 原始转义）；删 `renderTextBare`；MarkdownRenderer streaming 改 stable markdown 渐进 + `.stream-tail` 末行纯文本，done 全量；markdown.css 去 streaming pre-wrap、加 `.stream-tail`。
- 测试：+7 markdown（4 splitStreaming + 3 renderStreaming）+ 3 MessageBubble（活动区在上、流式拆分、用户消息无活动区）；MarkdownRenderer.spec 改 streaming 断言；119 单测 PASS。
- 验证：typecheck ✓ / lint 0err / **119 单测 PASS** / **21 e2e PASS** / DOM 手测（mock 非 fast）：流式中 `.msg-activity .tool-card` + markdown-body 渐进渲染；完成后活动区在气泡上方、重试按钮 0、stream-tail 残留 0；计算路径中断确认后同样无重试按钮；0 页面错误。
- 不做（记录）：工具活动区折叠/收起（用户要求可见递进）；工具卡展开参数回放；中断弹窗/composer/SSE 层不动；后端 thinking 发射（另一 agent）。

## 2026-08-17 批量推进（L2/L3 混合）：真实后端验证 + 前端清理 + M5 评估管理
用户离开期间自主推进（P1→P4）：
- **P1 真实后端验证对话显示优化**：:5174 发「帮我调研 SSE」→ 活动区 2 条 agent 切换 + dispatch_subagent 行 + 回复气泡完整 markdown 调研报告，0 错误。
- **P2 前端遗留清理**：删 `useChatStream.start` 死 endpoint 参数 + `sse.ts` 死 `streamChat` 导出（含 spec mock 对齐）；删 `domain.ts` 未用 `AgentStatus`；TaskList/TaskDetail Agent 列改显「通用 Agent」（消 uuid 噪音）。
- **P3 M5 评估管理前端补全**（后端 M5 已提交契约）：
  - types 对齐：EvalCase.layer、EvalRun.baseline_run_id、EvalCaseResult.latency_ms/cost、新增 PairwiseMatrixRow/Summary/Detail
  - api/system.ts：updateEvalSet/deleteEvalSet/listEvalCases/deleteEvalCase/getPairwise + runEval 带 baseline_run_id（激活原死代码 createEvalSet/addEvalCase/patchEvalCase/listEvalRuns）
  - store：evalCases/pairwise 状态 + 集/用例 CRUD + loadEvalRuns + loadPairwise
  - 新组件 `src/components/system/EvalManage.vue`：评估集 CRUD、用例管理（layer/启用/删除）、运行历史 + 回看、配对比较（矩阵 + W/L/T/Δ 汇总）；SystemView 评估 tab 改挂 EvalManage
  - mock：补 PUT/DELETE set、GET/DELETE cases、pairwise 路由 + 模块级 mockEvalCases
  - 验证：真实后端 smoke_eval/m5_core/契约验证集 渲染、8 用例、82 运行、配对矩阵 8 行，0 评估接口错误
- **P4 gate**：typecheck ✓ / lint 0err / **120 单测 PASS** / **21 e2e PASS**；docs/02（/system 行、system store 行、组件表加 EvalManage）+ progress.md + 交接板同步。
- 排障记录：EvalManage 真实后端验证时偶现 `/auth/login` 500——隔离复现不了（干净直达 /chat），发生在登录端点非评估调用，判为后端重启竞态的环境瞬态，非代码问题。
- 不做（记录）：Provider 配置表单（后端无 Provider API，做=死表单，等补端点）；工作区内部设计（用户已定不做）；hooks/webhook 管理页（后端 M6 前开放项，本轮未做，留待后续）。

## 2026-08-17 对话显示 + 设置增强（L2）：打开会话滚到底 + hooks/Provider 进设置 + 契约交接
用户三项要求：
- ① **打开会话默认滚到底**：MessageList 加会话切换强制滚动 watch（`messages[0].conversation_id` 变化 → `scrollTop = scrollHeight`），与吸底跟随并存；DOM 实测发消息后底部 ✓ / 上滚到顶 ✓ / 切换会话后回底 ✓。
- ② **hooks 管理 + Provider 配置表单进设置**：
  - 新 `api/hooks.ts`（list/register/delete）+ `api/provider.ts`（list/create/update/delete）；types `WebhookConfig/RegisterHookRequest/ProviderConfig/SaveProviderRequest`；`FEATURE.hooks/providers` 降级。
  - SettingsView：新增 **Webhook 管理** tab（列表/注册/删除）+ **Provider 配置** tab 重做（列表/添加/启用开关/删除，availability 降级空态）。
  - mock 补 hooks/providers 路由 + 种子。
- ③ **后端没做的留契约**：交接板 `[open] →后端 Provider 配置契约`（/settings/providers CRUD + api_key 只写不读 has_key 安全约定）；Webhook 管理已接确认（后端已有 hooks API）。
- 验证：typecheck ✓ / lint 0err / **120 单测 PASS** / **21 e2e PASS** / DOM 手测（设置 Provider/Webhook tab 渲染；打开会话滚到底 3 项全过）。
- 排障记录：滚到底 DOM 测试首轮失败 = 测试消息含 "HTTP/2"（数字+`/`）触发 mock 计算器中断路径 → composer 卡 disabled；换无数学符号消息即过，非产品 bug。

## 2026-08-17 对话多消息（逐轮思考链）+ 轨迹优化（L3，前端 + 后端契约）
用户需求：一轮思考 = 一条消息（思考链直观可见）；轨迹同步优化。已确认前端+后端契约方案、轨迹自动提升+UI打磨。
- **A 契约**：sse.ts 加 `message` 事件类型 + `MessageSealPayload`；api.ts `Message.round`；useChatStream 加 `sealRound()`（复位段、保留 taskId/conversationId/messageId）+ `case 'message'`（onPersistedMessage 追加本轮 + 复位）。
- **C mock 多消息**：buildChatScript 默认分支拆两轮——轮1（检索 + web_search 工具）→ `message` 事件封口落库；轮2（最终答案）→ done；`sealEvent` helper。
- **D 轨迹**：`foldTrajectory` 已支持同 Turn 多 assistant 节点（Message + Step N）→ 自动逐轮呈现；`dispatch_subagent` 工具单元格标记「⇄ 派发 subagent」；trajectory.spec 增强多轮含工具用例。
- **E 后端契约**：交接板 `[open]` 逐轮消息——SSE `message` 事件 + 按轮持久化 + `Message.round` 列 + 排序；chat/resume/task 对等。
- **验证**：typecheck ✓ / lint 0err / **121 单测 PASS**（+1 message 事件）/ **21 e2e PASS** / DOM 手测（mock：2 个 assistant 气泡、轮1 web_search+检索文本、轮2 最终答案；刷新后重选会话仍 2 条；轨迹 Turn 1 · 2 步 · 1 工具，Message + Step 分组）0 页面错误。
- 不做（记录）：thinking 推理作为消息（后端仍剥离，契约预留）；逐轮 token_usage/cost 展示；轨迹大重构。

## 2026-08-17 会话滚动到底 + 轨迹实时同步/切换保持（L2，前端 + 后端契约）
用户三反馈：①打开会话最上端；②多轮任务中轨迹不实时同步；③切换会话再回来丢工作流。
- **A 滚动**：MessageList 强制滚动改监听 `messages` **引用变化**（加载/切换/重选）+ `forceScrollBottom()`（nextTick + 双 rAF + timeout 兜底，content-visibility 估算高度拉到真实底）；吸底跟随 watch 也改走 forceScrollBottom。
- **B 轨迹实时**：TrajectoryPanel 加 `live` prop + 每 2.5s 轮询（不重置选中/搜索/折叠）；ChatView 传 `stream.state.streaming`。
- **C 后端契约**（交接板 `[open]`）：逐轮消息需按轮即时落库（message 事件发射处同步落库，on_final 只补最后一条），否则任务中 DB 无轮次、轨迹/切换读 DB 为空。
- 验证：typecheck ✓ / lint 0err / **121 单测 PASS** / **21 e2e PASS** / DOM 手测（mock-fast：发消息后滚到底 ✓、切走切回滚到底 ✓；mock 非 fast：轨迹 live 轮询 8s 内 14 次请求 + 台账 Message/Step 多轮）0 页面错误。
- 说明：③ 真实后端需后端按轮落库契约落地（mock sealEvent 已即时落库，故 mock 切换保持可用）；未落地前轨迹轮询无新数据（无回归）。

## 2026-08-17 工具轮消息 + thinking 推理显示（L2，前端 + 后端契约）
用户反馈：工具轮（模型无文本）只有工具卡、无消息气泡；轨迹无每轮 message。补充：thinking 推理也要显示（不气泡、放活动区、长文本收缩）。
- **A 工具轮占位**：`format.ts` 加 `toolCallSummary(name, input)`；`MessageBubble.partsFromMessage/Stream` 空 content 有工具 → 占位「调用 [工具]：入参」；`foldTrajectory` 空 content 有工具 → message cell 占位。
- **B thinking 显示**：`Message` 加 `thinking` 字段；`ChatView.onPersistedMessage` 透传 `m.thinking`（否则丢）；`partsFromMessage` 读 thinking 加活动区行；`.thinking-row` 改可折叠（line-clamp 3 + 展开/收起）；`useChatStream` thinking 累积到末段；mock 默认分支插 thinking 事件 + sealEvent 带 thinking。
- **C 后端契约**（交接板 `[open]`）：发射 `thinking` 事件（每轮 thinking blocks）+ 按轮持久化 thinking + `serialize_message`/`serialize_trajectory_node` 带 thinking。
- 验证：typecheck ✓ / lint 0err / **123 单测 PASS**（+toolCallSummary + MessageBubble 占位 + 轨迹占位 + thinking 累积）/ **21 e2e PASS** / DOM 手测（真实后端：calculator 轮消息「调用 calculator：(3+4)*2-1」+ 轨迹 message 单元格；mock：thinking 行 line-clamp 收起→展开→收起）。
- 说明：thinking 在真实后端待后端发射/持久化契约落地（前端就绪、mock 演示）；未落地前无 thinking 数据（无回归）。

## 2026-08-17 对话贴底跟随（L1）：滚动在最下方自动追随新内容，滚走不强制拉回
- 用户：对话窗口滚动在最下方时新内容自动追随；不在最下方时文本照常生成但不被强制拉到底。
- 实现（MessageList）：
  - 原 `nearBottom`（内容变化时算，140px 阈值）→ 内容增长后误判"不在底部"不跟随 / 阈值太宽稍微滚走也强拉。
  - 改为 `scroll` 事件记录 `pinned`（`scrollHeight - scrollTop - clientHeight < 32px` 才算贴底）；内容变化（messages/partialText/finished/interrupted）时**仅 pinned 才 `forceScrollBottom()`**——滚动在最下方自动追随，滚走不拉回。
  - 会话加载/切换仍强制滚动到底（messages 引用变化 watch）。
- 验证：typecheck ✓ / lint 0err / 123 单测 PASS / 21 e2e PASS / DOM 手测（贴底发消息自动跟随 top 滚到新底；滚走 top=0 发消息未拉回、内容增长 h 1749）。
- 排障：首轮 e2e 大面积失败 = 5173 残留 dev server 被 playwright reuseExistingServer 复用（登录超时），清端口后 21 全绿，非代码问题。

## 2026-08-18 前端遗留收尾（L2）：工具卡参数回放 + 逐轮 token/cost footer + 轨迹打磨 + 修存档
- 计划：C:\Users\Admin1\.claude\plans\agent-twinkling-lantern.md
- **A 工具卡参数回放**：ToolCallCard 加 `input/output/durationMs` props + 「参数」toggle（默认折叠，展开后入参/输出走 JsonViewer 或 pre + 耗时）；MessageBubble 透传（流式 `card.structured`、持久化 `fromRecord` 已映射）。
- **B 逐轮 token_usage footer**（纯前端真实数据）：useChatStream `message`/`done` 事件把载荷顶层 `token_usage`/`cost` 透传到追加消息（message 自带优先不覆盖）；ChatView.onPersistedMessage 补 `token_usage`/`cost`；MessageBubble 气泡下 `.msg-usage`（`formatTokens` + `formatCost`）。
- **C 逐轮 cost**（契约 [open]）：types `MessageSealPayload.cost`/`Message.cost`；mock `sealEvent` 带 token_usage+cost（附 message 落库镜像后端持久化）；交接板 [open] → 后端（message 封口 payload + serialize_message 加 cost）。UI 防御式。
- **D 轨迹打磨**：TrajectoryTimeline tooltip 两行（第二行入参摘要，`#content` 插槽 + popper-class + 非 scoped pre-line 样式）；TrajectoryDetailPanel 删 Schema 占位 tab；`formatTokens` 从 TrajectoryLedger 抽到 `utils/format.ts` 共享（Reuse）。
- 测试：+7 单测（format +2 / MessageBubble +4 / useChatStream +1，含 message 自带 token_usage 优先不覆盖用例）。
- 验证：typecheck ✓ / lint 0err（3 既有 any）/ **130 单测 PASS** / **21 e2e PASS**（chat-stream 工具卡回归守卫更新注释：默认折叠仍 not.toContainText('6*7')）。
- 不做（记录）：Ledger 单元格多行展开、collapsedAll 混合态、sticky group 头（轨迹打磨只做两小项）；逐轮 cost 等后端认领。

## 2026-08-18 M6 平台化前端（L3）执行中
- Task 1: complete (commits 764e302, npx vitest run src/api/evolution.spec.ts src/api/availability.spec.ts → 11 PASS)
- Task 2: complete (commits 21966f5, typecheck ✓ lint 0err + mock 路由 node fetch 验证全过)
- Task 3: complete (commits 25d467e, typecheck ✓ lint 0err + DOM 冒烟：5 行/筛选 1 条/抽屉契约字段/0 错误)
- Task 4: complete (commits 824c829；docs/03 §5.13 提案落盘共享 docs（非 git 仓库）+ 交接板 [open]）
- Task 5: complete (commits 912274c, typecheck ✓ + TopBar spec 2 PASS + DOM 冒烟：org_1 显示/表 org 列/筛选 org_2→2 行/0 错误）
- Task 6: complete (frontend-ci workflow；就绪核查）
      - 已就绪：Dockerfile（node:20-alpine → nginx:alpine）、nginx.conf（SSE proxy_buffering off / WS / SPA try_files）、env（dev/e2e/prod）、vite proxy。与 docs/05 §2.3/§4.1 一致。
      - 缺口记录：①无前端 CI（本轮补 .github/workflows/frontend-ci.yml）；②docker-compose 只 db/redis，`nginx.conf` 的 `backend:8000` 无对应 service（compose 在后端仓库，需后端/部署侧协调）；③前端仓库无 git remote，无 staging/prod 流水线（托管后 workflow 即生效）。
- Task 7: complete (commits c?；typecheck ✓ lint 0err(3 既有 any) / 137 单测 PASS / 23 e2e PASS（+system-evolution + settings-org）/ DOM 手测：候选区状态迁移 候选→已批准→发布 且筛选保持；降级：availability.spec + evolution store spec 覆盖 FEATURE.evolution 打标，真实后端待核验）
- Gate 修复: complete (commits c?；R1 openDetail 竞态守卫 / S1 动作按钮配置循环 / S2 mock 迁移表 / S3 store Record 映射 / S4 reload 合并 / S5 createForm 工厂 / .mono 样式；typecheck ✓ lint 0err 137 单测 23 e2e 全绿）
- M6 真实后端降级核验: PASS (VITE_USE_MOCK=false :5174 → 后端 :8000)
      - TopBar org 显示 `管理员 · <uuid>`（真实后端 org_id 是 UUID，非 mock 的 org_1）；/system 候选区 tab → 无 .evolve-table + EmptyState「后端暂未实现候选区接口」；唯一 404 = /evolution/candidates（预期）；/settings 用户表 4 条真实数据 + org 列；0 页面错误。
      - 备注：真实后端 org_id 为不透明 UUID（非人类可读名），组织筛选/展示是 UUID 透传，非 bug；若后续要「org 名称」需后端/契约补 org 名映射。

## 2026-08-18 对话滚动/贴底优化 + thinking 按钮定位 + 底部缓冲（L2）
- 计划：C:\Users\Admin1\.claude\plans\agent-twinkling-lantern.md
- **① thinking 按钮固定**（MessageBubble.vue CSS）：`.thinking-row` `width:100%` + `.thinking-text` `flex:1;min-width:0` + `.thinking-toggle` `flex-shrink:0;align-self:flex-start` → 按钮固定在行右上，收起/展开都不随文本漂移（flex 布局非视口 fixed）。
- **② 会话滚动位置记忆**（MessageList.vue）：模块级 `scrollPositions: Map<convId,scrollTop>`，scroll 事件 `updatePinned` 顺带记账；messages 引用 watch 改——有记录→`restoreScroll(saved)`（恢复原位，先 `pinned=false` 防拉回）；无记录（新/没开过）→`forceScrollBottom()`（默认到底）。贴底跟随 watch 不变。
- **③ 底部缓冲**（MessageList.vue CSS）：`.msg-list` `padding: 8px 0 96px`——最新行停在缓冲带上方，不顶 composer；scrollHeight 含 padding，pinned 判定天然正确。
- mock：`db.ts` 加 `c_scroll` 长会话种子（12 条交替消息，供滚动 e2e）。
- 测试：MessageBubble.spec +2（thinking 折叠/展开切换 + 短文本无按钮）；e2e/scroll.spec.ts 新增（c_scroll 新开到底→上滚 200→切走 c_002→切回恢复原位）。
- 验证：typecheck ✓ / lint 0err(3 既有 any) / **139 单测 PASS** / **24 e2e PASS** / DOM 手测（:5199）：按钮 top-aligned+right-pinned+不在文本底 全 true、padBottom 96px、bufferGap 96、新会话贴底 true、0 错误。
- 备注：后端 08-18 已实现 经验候选区 + 逐轮 cost（前端零改动，FEATURE.evolution 转正式渲染；逐轮成本真实显示）。真实后端候选区/成本 UI 正式核验留作下轮。

## 2026-08-19 修复：切换会话滚动"闪到中间再滚到底"（L2，仅前端）
- 计划：C:\Users\Admin1\.claude\plans\vast-wandering-hamster.md
- 症状：每次进入/切换会话，消息列表瞬间出现在真实高度约 1/3 处（content-visibility 估算 120px/行），再滚到最下方——明显闪跳。
- 根因：`.msg-row` `content-visibility:auto` 让 `scrollHeight` 按估算逐帧物化；旧 `forceScrollBottom`/`restoreScroll` 的 nextTick+双 rAF+60ms 固定落地打在渲染级联中途，scrollTop 停在估算位置。
- **修复**（MessageList.vue）：
  - `scrollToStable(target, hide)` rAF 稳定循环替代固定落地：每帧追目标直到 `scrollHeight` 连续 3 帧稳定（content-visibility 渲染推进 = scrollHeight 变化 → 自动续追；maxFrames 120 兜底；finalize 晚到渲染续追 2 次）。
  - 切换会话 hide=true：追帧期加 `.msg-list--settling { visibility:hidden }`，最终位置就绪后一次展示——彻底消除可见闪跳。
  - `onScroll` 判别：循环自身程序化滚动（`scrollTop===lastSetTop`）忽略不记账；用户滚走（偏离）→ `scrollRun++` 作废跑批 + 恢复正常记账/pinned（保住"流式期滚走不拉回"）。`Math.floor` 防浮点 scrollTop mismatch。
  - `onBeforeUnmount` 作废挂起跑批。
- **相邻竞态修复**（chat.ts）：`loadMessages` 加响应序守卫 `if (id !== this.currentId) return`——快速连点会话时慢响应不覆盖新选择（也防 scrollPositions 记错 key）。
- 验证：typecheck ✓ / lint 0err(3 既有 any) / **139 单测 PASS** / **24 e2e PASS**（含 scroll.spec 滚动回归）。
- 量化手测（:5199）：场景1 进入长会话 settling add@53→remove@127ms、揭示即贴底（距底 gap=0，中间带帧 0）无闪；场景2 上滚 200 切走再回 settling add@49→remove@125ms、揭示 scrollTop=200 全程稳定、恢复原位不闪。
- 不做（记录）：不引入 ResizeObserver（容器 flex 定高、内容增长不触发；观察最后一行随流式失效）；`scrollPositions`/`pinned` 语义不变。

## 2026-08-20 修复：知识库上传后「状态/分块数/操作」不一致（L2，仅前端 + mock）
- 计划：C:\Users\Admin1\.claude\plans\vast-wandering-hamster.md
- 症状：空集合上传卡「已上传」直到刷新；非空集合上传立即「已索引」但 0 chunks、操作只有删除。
- 根因（真实后端契约 uploaded→chunking→indexing→indexed，字段齐全）：
  - ① `ChunkStatus.isProcessing` 只认 chunking/indexing，漏 uploaded → uploaded 永不轮询（空集合卡「已上传」）。
  - ② **el-table 未设 `row-key`，按数组下标 patch，上传 unshift 后新行复用旧行（indexed 种子 doc）的 ChunkStatus 组件实例**，实例 `liveStatus` 还是旧 doc 的 'indexed'（终态→不轮询）→ 新 doc 显示「已索引」+ 自己的 0 chunks（非空集合症状）。
  - ③ 轮询 live 态只进组件本地，不回写 store 行 → 操作列读陈旧 row.status，只有「删除」。
- 修复：
  - `ChunkStatus.vue`：`isProcessing` 加 `uploaded`；轮询结果经 `emit('status-change')` 回传（仅 live 值变化时）。
  - `KbView.vue`：`<el-table row-key="id">` 按 doc id 键控（杜绝实例复用状态泄漏）；`@status-change="onStatusChange"` → `kb.patchDocument` 合并 live 态进 store 行（操作按钮随已索引响应式出现）。
  - `stores/kb.ts`：新增 `patchDocument(id, patch)` action。
  - `mock/server.ts`：上传返回 `status:'uploaded'`（对齐真实后端）+ `simulateKbChain` setTimeout 异步推进 uploaded→chunking→indexing→indexed+chunk_count（正常 ~1s/步、e2e fast ~150ms/步）；reindex 重置 uploaded 走同一链；**顺带修复 multipart 文件名 latin1 乱码**（中文文件名按 UTF-8 还原，真实后端正常）。
- 测试：+4 单测（ChunkStatus.spec：uploaded 轮询启/停、live 渲染、emit）；+2 e2e（kb.spec：非空/空集合上传不刷新自动收敛 已索引+chunks>0+重索引按钮）。
- 验证：typecheck ✓ / lint 0err(3 既有 any) / **143 单测 PASS** / **26 e2e PASS**（24 既有 + 2 新增 kb）。
- 手测（诊断脚本，fast :5198）：上传 → 「已上传0%」→ 3s 内自动「已索引7 chunks」，全程无刷新、无轮询缺失（server 日志确认 status 轮询到位）。
- 不做（记录）：不把检索 mock 改真实（/kb/search 硬编码片段与本次无关）；不改后端（chunk_count/status 已真实返回）。

## 2026-08-20 org_name 消费 + 工具页元工具/常规工具区分（L2，前端 + mock + 契约交接）
- **① 前端消费 org_name**（后端 08-19 已实现，前端待补）：types `User` 加 `org_name?: string`；TopBar 角色行、SettingsView 用户表 org 列与组织筛选改 `org_name ?? org_id`（名称优先、回退 UUID）；mock 用户加 org_name（默认组织/组织二）+ 登录/me/users/create 四处序列化补 org_name。TopBar.spec +1（org_name 优先）；settings-org e2e 改断言显示名称。
- **② 工具页区分元工具/常规工具**（docs 03 §5.5 meta 字段前端提案）：
  - 需求：工具列表区分「元工具」（tool_search/kb_search 平台发现层，模型侧常驻、无需 tool_search 发现）与「常规工具」（经 tool_search 发现）。
  - 后端现状：registry/Tool 模型已有 `meta: bool`（tool_search/kb_search 已 meta=True），但 `serialize_tool_definition` 未带出 → API 无 meta；`/tools/search` 未排除 meta。
  - 前端：`ToolDefinition.meta?: boolean`；ToolsView「类别」列（元工具 warning 标签 / 常规工具 info 标签）+ 筛选（全部/元工具/常规）+ 全部时元工具置顶；mock 加 tl_tool_search(meta:true) 种子 + `/tools/search` 排除 meta。e2e tools-meta.spec（标签/筛选/搜索排除）。
  - 交接板 [open] →后端：serialize_tool_definition 补 `meta` + `/tools/search` 排除 meta（docs 03 §5.5 已记字段补充）。
- 验证：typecheck ✓ / lint 0err(3 既有 any) / **144 单测 PASS**（+1 TopBar）/ **27 e2e PASS**（26 既有 + tools-meta；settings-org 改断言）。

## 2026-08-20 五连改（L3）：删任务入口 / 精简系统页 / 多流会话 / 滚动根因 / 长代码块（纯前端，已提交 d8ccdf7 后续未提交）
- 计划：C:\Users\Admin1\.claude\plans\vast-wandering-hamster.md
- **A 删「设置栏」任务入口 + 死代码**：routes.ts 删 /tasks 菜单项/SETTINGS_ROUTES/路由；删 TasksView/TaskList/TaskDetail/stores/task/api/task（api/index.ts 去 task 导出）；保留 mock /tasks + useTaskPoll(KB用)。改 routes.spec/guards.spec（viewer 只剩记忆）/restructure.spec（4 项点工具）。
- **B 精简设置-系统页**：SystemView 删 el-tabs，运行日志为主体 + 保留 trace 抽屉；删 evals/cost/evolution 三 pane + EvalManage/CostChart/EvolutionManage 孤儿组件；删 e2e/system-evolution.spec；保留 evolution store/api 契约层（有 spec）。
- **C useChatStream 多流会话隔离（大改）**：按 convId 存 ConvCtx（state/controller/pendingText/timers）；`state` 改 ComputedRef 指向当前会话 entry；`setConversation` 切换（不 reset 后台流）；start/stop/confirmInterrupt 按当前 ctx；ChatView 去 selectionToken reset 改 currentId watch + setConversation，onPersistedMessage 按 conversation_id 守卫（防污染别的会话列表）。单测 +1（多流隔离）。手测：A 流式中切 B 再切回 A → A 的进行中思考/工具可见。
- **D 滚动条根因（移除 content-visibility 估算）**：`.msg-row` 去 content-visibility/contain-intrinsic-size → scrollHeight 真实；scrollToStable 改「设目标→下一帧读回(post-paint)→稳定3帧」追帧 + `activeRun` 守卫（追帧期间不记账，防初始未渲染态把位置记成 0 污染历史恢复）。根因：①记账污染（初始未渲染记 0 → 恢复读 0 滚到顶）；②浏览器 paint commit 重置 scrollTop（同步读回误判稳定）。
- **E 流式长代码块逃出代码块**：`inOpenFence` 检测未闭合围栏，围栏内整段一起渲染（tail 并入代码块不逃逸）；markdown.spec +5 用例。
- 验证：typecheck ✓ / lint 0err(3 既有 any) / **151 单测 PASS** / **26 e2e PASS**（删 system-evolution 后 27→26；guards/restructure/scroll 更新）。**本轮改动未提交**。
