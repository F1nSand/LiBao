# MCP 管理页、工具默认启用与搜索修复实施计划

**Goal:** 在 LiBao Web 设置组中新增独立 MCP 管理页，让未来注册的普通/MCP 工具默认启用，并修复 Agent 与 Web 工具搜索的多关键词漏匹配。

**Architecture:** 复用现有 MCP 后端注册/列表/删除接口，新增 `McpServer` 前端类型、MCP API 模块、Pinia store 和 `/mcp` 页面；工具页继续负责工具启停/测试，MCP 页只负责服务源生命周期。后端通过领域服务显式切换新工具的 enabled 状态，并通过无依赖的共享关键词评分函数同时服务 runtime `tool_search` 和 REST 工具搜索。

**Global Constraints:**

- 只影响未来通过领域服务注册的工具；不迁移或批量启用历史停用工具。
- MCP 页面只支持列表、新增、删除；不新增编辑或注册后的 MCP 服务启停接口。
- MCP 响应只返回 `header_names`，不得把 Authorization 或其他请求头值返回到 Web 端。
- MCP 工具启用状态必须同时落在 `tool_definitions.json` 和当前进程 registry；服务停用时 runtime 仍不可用。
- 保留工作区已有未提交修改；执行器只修改本计划列出的文件，不执行 reset、checkout、clean 或全量格式化。
- 不引入 Embedding、向量库、BM25 或新的生产依赖。

## Task 1: 后端注册默认启用与 MCP 凭据响应脱敏

**Files:**

- Modify: `apps/backend/app/services/tool.py:63-78,117-129` — 普通工具创建默认 `enabled=True`，若存在同名 runtime spec 则同步 `set_enabled`。
- Modify: `apps/backend/app/services/mcp.py:24-30,111-132` — MCP 工具行默认 `enabled=True`，注册 spec 后以 `row.enabled and server.enabled` 同步 runtime 状态，并导入 `set_enabled`。
- Modify: `apps/backend/app/services/serializers.py:142-153` — `serialize_mcp_server` 输出 `header_names`，移除 `headers`。
- Modify: `apps/backend/app/api/schemas/tools.py:1,44-50` — 更新“默认关闭”文档为领域服务新注册默认启用，保留 `McpRegisterRequest` 的现有字段。
- Modify: `apps/backend/app/storage/models/tool_definition.py:1-12` — 说明底层行模型仍保留低层默认值，领域注册入口负责新工具启用，避免误解行为契约。
- Modify: `apps/backend/app/services/mcp.py:1-7`、`apps/backend/app/services/tool.py:1-7` — 更新服务级注释中的默认关闭描述。
- Modify: `apps/backend/tests/test_tool_service.py:31-40,47-58` — 将普通工具默认值断言改为启用，并增加同名 runtime spec 创建后已启用的断言。
- Modify: `apps/backend/tests/test_mcp_api.py:1-8,58-87,126-137` — 更新 MCP 工具默认值断言，覆盖服务 `enable=False` 时行启用/runtime 不可用。
- Modify: `apps/backend/tests/test_mcp_api.py` — 增加带 `Authorization` 和另一个请求头的注册响应测试，断言 `header_names` 排序正确、响应没有 `headers`、工具行和 spec 均启用。

**Interfaces:**

- Consumes: `ToolService.create(db, user, req) -> ToolDefinition`、`McpService.register(db, user, req) -> dict[str, Any]`、`set_enabled(tool_id: str, enabled: bool) -> None`。
- Produces: 新注册普通工具和服务启用的 MCP 工具返回/持久化 `enabled=True`；`serialize_mcp_server` 返回 `header_names: list[str]`，不返回 `headers`。

- [ ] Step 1: 先更新测试 `test_create_tool_default_disabled` 为 `test_create_tool_default_enabled` 并断言 `data["enabled"] is True`；新增 MCP 测试断言 `res["server"]["header_names"] == ["Authorization", "X-Trace"]`、`"headers" not in res["server"]`、所有 `res["tools"][*]["enabled"] is True`，并在 `enable=False` 场景断言工具行启用但 `get(mcp_spec_id).enabled is False`。
- [ ] Step 2: 运行 `uv run pytest tests/test_mcp_api.py tests/test_tool_service.py -q`，预期现有默认关闭断言失败，且新增字段断言失败。
- [ ] Step 3: 在 `ToolService.create` 显式传入 `enabled=True`，commit 后若 `get_by_name(row.name)` 有 spec 则调用 `set_enabled(spec.id, True)`；在 `McpService.register` 显式传入 `enabled=True`，每次 `register(spec)` 后调用 `set_enabled(spec.id, row.enabled and server.enabled)`；将 MCP 序列化改为排序后的请求头名称。
- [ ] Step 4: 重新运行同一命令，预期所有普通工具/MCP 注册测试通过；再运行 `uv run pytest tests/test_mcp_sync.py -q`，确认启动同步继续遵守行启用状态、服务删除状态和服务停用状态。
- [ ] Step 5: 检查 `git diff -- apps/backend` 只包含本任务列出的默认值、同步和脱敏变更后，创建原子提交 `feat: enable newly registered tools by default`。

## Task 2: 修复 Agent 与 REST 工具搜索的多关键词匹配

**Files:**

- Create: `apps/backend/app/tools/search_utils.py` — 提供共享查询分词和匹配评分函数。
- Modify: `apps/backend/app/tools/builtin/tool_search.py:15-66` — 使用共享匹配器，保留 registry 目录、disabled 标记、空结果提示、异常全目录降级和 `selected_names` 契约。
- Modify: `apps/backend/app/storage/repositories/tool_definition.py:75-89` — REST `/tools/search` 使用同一关键词规则和相关度排序，而不是整句子串。
- Modify: `apps/backend/tests/test_tool_search.py:31-69` — 增加真实复现查询、评分排序和空白查询回归测试。
- Modify: `apps/backend/tests/test_tool_service.py:79-92` — 增加 REST 搜索多关键词命中测试，确保工具页和 Agent 搜索语义一致。

**Interfaces:**

- Produces: `tokenize_tool_query(query: str) -> list[str]`，按 `/[\s,，;；、|/]+/` 拆分、去重并保留顺序；`tool_match_score(name: str, description: str, query: str) -> tuple[int, int, int, int] | None`，无命中返回 `None`。
- Score contract: 四元组依次为完整查询命中名称、完整查询命中描述、名称命中关键词数、名称/描述命中关键词总数；按四元组降序、工具 id 升序排序。
- Consumers: `tool_search_handler(query: str) -> dict[str, Any]` 与 `ToolDefinitionRepository.search(org_id: uuid.UUID, q: str, limit: int = 20) -> list[ToolDefinition]`。

- [ ] Step 1: 在 `test_tool_search.py` 增加 `test_search_multi_keyword_query`：注册 `apify_actor`，描述包含 `网页抓取 crawler actor`，调用 `tool_search_handler("apify 网页抓取爬虫 scrape crawler actor")`，断言 `apify_actor` 在 matches 中；增加一个只命中 `apify` 的工具并断言多关键词命中数更高者排在前面；调用全空白查询断言 `matches == []`。
- [ ] Step 2: 在 `test_tool_service.py` 增加 `test_search_multi_keyword_case_insensitive`：创建名称 `apify_actor`、描述 `网页抓取 crawler` 的工具，调用 `ToolService.search(..., "apify 网页抓取 crawler")`，断言返回该工具；保留现有单词和 meta 排除断言。
- [ ] Step 3: 运行 `uv run pytest tests/test_tool_search.py tests/test_tool_service.py -q`，预期新测试因整句子串匹配失败。
- [ ] Step 4: 实现 `search_utils.py` 的分词、去重、四元组评分；`tool_search._search_catalog` 对每个 spec 调用评分函数，过滤 `None` 并把分数临时附着后排序再移除；repository 对行使用同一评分规则，按评分降序、创建时间降序和名称升序返回；空 query 直接返回空行列表。
- [ ] Step 5: 重新运行同一命令，预期多关键词、大小写、空结果、disabled、meta 排除和降级测试全部通过；再运行 `uv run pytest tests/test_mcp_api.py tests/test_mcp_sync.py -q`，确认 MCP 工具仍进入 registry 搜索目录。
- [ ] Step 6: 检查搜索 helper 没有新增运行时依赖且没有改变 `selected_names` 的 enabled 过滤后，创建原子提交 `fix: match tool searches by keywords`。

## Task 3: 补齐前端 MCP 数据契约与 API 模块

**Files:**

- Modify: `apps/frontend/src/types/api.ts:304-352` — 增加 `McpServer` 和 `McpRegisterResult`，将 `McpRegisterRequest` 扩展为包含可选 `name`。
- Create: `apps/frontend/src/api/mcp.ts` — 实现 `listMcpServers(): Promise<McpServer[]>`、`registerMcp(body: McpRegisterRequest): Promise<McpRegisterResult>`、`deleteMcpServer(id: string): Promise<null>`。
- Create: `apps/frontend/src/api/mcp.spec.ts` — 使用 `axios-mock-adapter` 覆盖三个 HTTP 方法、路径、请求体、信封解包和 `header_names` 响应。
- Modify: `apps/frontend/src/api/tool.ts:1-40` — 删除 MCP 注册 API 和错误的 `ToolDefinition` 响应类型，只保留工具 API。
- Modify: `apps/frontend/src/stores/tool.ts:1-68` — 删除 `registerMcp` action 和对应 import，保留工具列表刷新能力。
- Modify: `apps/frontend/src/stores/tool.spec.ts:1-18` — 删除 MCP API mock 条目，保持工具 store 测试只验证工具行为。

**Interfaces:**

- `McpServer`: `{ id: string; name: string; transport: 'http' | 'stdio'; url_or_command: string; header_names: string[]; enabled: boolean; tool_count: number; created_at: string }`。
- `McpRegisterRequest`: `{ name?: string; url_or_command: string; headers?: Record<string, string>; enable?: boolean }`。
- `McpRegisterResult`: `{ server: McpServer; tools: ToolDefinition[] }`。

- [ ] Step 1: 先添加 `mcp.spec.ts`，断言 `GET /tools/mcp`、`POST /tools/mcp/register` 和 `DELETE /tools/mcp/server-1` 的请求/响应，POST 请求包含 `name`、`url_or_command`、`headers` 和 `enable`。
- [ ] Step 2: 运行 `npm run test:unit -- --run src/api/mcp.spec.ts`，预期因模块和方法不存在而失败。
- [ ] Step 3: 添加类型和 API 函数，迁移工具 API/store 对 MCP 的引用。
- [ ] Step 4: 重新运行 MCP API 测试和 `npm run test:unit -- --run src/stores/tool.spec.ts`，预期通过。
- [ ] Step 5: 检查请求头值只存在于 POST 请求体类型中，列表类型只有 `header_names` 后，创建原子提交 `feat: add frontend MCP API contract`。

## Task 4: 新增独立 MCP Pinia store 与管理页面

**Files:**

- Create: `apps/frontend/src/stores/mcp.ts` — 提供 MCP 列表状态和 `list`、`retry`、`register`、`remove` actions。
- Create: `apps/frontend/src/stores/mcp.spec.ts` — 覆盖加载成功、失败保留旧列表、retry、注册刷新工具列表依赖、删除刷新列表。
- Create: `apps/frontend/src/views/McpView.vue` — 实现 MCP 列表、空/加载/错误状态、注册弹窗和删除确认。
- Create: `apps/frontend/src/views/McpView.spec.ts` — 覆盖列表字段、header_names 不渲染值、注册字段整理、空 URL 校验、注册失败保留输入、删除确认。
- Modify: `apps/frontend/src/views/ToolsView.vue:1-228` — 删除 MCP 状态、注册方法、MCP 弹窗和“注册 MCP”按钮；保留工具搜索、注册、启停、测试和删除。

**Interfaces:**

- Store state: `servers: McpServer[]`、`loading: boolean`、`status: 'idle' | 'loading' | 'success-empty' | 'success' | 'error'`、`errorMessage: string | null`、`submitting: boolean`。
- `register(body: McpRegisterRequest): Promise<McpRegisterResult>`：调用 API 注册后刷新 MCP 列表，并返回注册结果供页面提示。
- `remove(id: string): Promise<void>`：调用删除 API 成功后刷新 MCP 列表。
- 页面构造 headers：从动态键值行过滤空 key/空 value，生成 `Record<string, string>`；列表只读 `header_names`。

- [ ] Step 1: 在 `mcp.spec.ts` 先 mock `@/api/mcp` 和 `@/stores/tool`，添加 store 测试：list 成功写入 servers；list 失败保留旧 servers；retry 再次调用 list；register 传递完整 headers 并触发 list；remove 成功后触发 list。
- [ ] Step 2: 运行 `npm run test:unit -- --run src/stores/mcp.spec.ts`，预期因 store 不存在而失败。
- [ ] Step 3: 实现 `useMcpStore`，再实现 `McpView.vue`：使用 `AsyncState`，表格渲染名称/transport/url_or_command/header_names/tool_count/enabled，注册弹窗提供名称、地址/命令、动态请求头键值行和默认开启的 enable，删除使用 `ElMessageBox.confirm`；注册/删除成功后调用 `useToolStore().list()`。
- [ ] Step 4: 为 `McpView.spec.ts` 添加测试：`header_names` 出现在 DOM；任意模拟 Authorization 值不出现在 DOM；空地址不调用 API；注册失败后弹窗和输入仍存在；删除确认取消不调用 API，确认后调用对应 id。
- [ ] Step 5: 运行 `npm run test:unit -- --run src/stores/mcp.spec.ts src/views/McpView.spec.ts`，修复组件 stub/异步等待直到全部通过；再运行工具页相关单测确保移除 MCP 入口后无旧引用。
- [ ] Step 6: 检查页面没有展示或记录 headers 值、没有增加服务编辑/启停按钮后，创建原子提交 `feat: add MCP management page`。

## Task 5: 接入设置导航并统一 Mock 行为

**Files:**

- Modify: `apps/frontend/src/router/routes.ts:15-36,65-75` — 在设置 children 和 `SETTINGS_ROUTES` 加入 `/mcp`，注册 `McpView` 路由。
- Modify: `apps/frontend/src/router/routes.spec.ts:20-24` — 断言设置子项顺序为 `/settings`、`/tools`、`/mcp`、`/skills`、`/memory`、`/system`。
- Modify: `apps/frontend/src/mock/db.ts:1-20,22-90` — 增加 `mcpServers` 内存集合，工具种子和普通工具注册默认启用。
- Modify: `apps/frontend/src/mock/server.ts:815-850` — 在 `/tools/:id` 之前实现 MCP GET/POST/DELETE；POST 从请求头只提取 `header_names`，创建两个关联默认启用工具 `mcp_${serverId}_search` 与 `mcp_${serverId}_fetch`；DELETE 删除服务和其关联工具。
- Modify: `apps/frontend/src/mock/server.spec.ts` — 覆盖 MCP 注册、列表、删除、工具默认启用和请求头值不进入响应。

**Interfaces:**

- Mock `GET /tools/mcp -> ApiEnvelope<McpServer[]>`。
- Mock `POST /tools/mcp/register -> ApiEnvelope<McpRegisterResult>`。
- Mock `DELETE /tools/mcp/:server_id -> ApiEnvelope<null>`。
- Mock `POST /tools -> ApiEnvelope<ToolDefinition>` 返回 `enabled: true`。

- [ ] Step 1: 先更新 `routes.spec.ts` 和新增 mock server 测试，断言 `/mcp` 菜单/路由与三个 MCP endpoint，预期因实现缺失失败。
- [ ] Step 2: 运行 `npm run test:unit -- --run src/router/routes.spec.ts src/mock/server.spec.ts`，记录失败断言。
- [ ] Step 3: 添加 `/mcp` 导航和路由；实现 mock MCP 服务源/工具关联生命周期，确保 POST 请求头的值不进入返回对象；将 mock 普通工具注册 enabled 改为 true。
- [ ] Step 4: 重新运行同一命令，预期路由与 Mock 测试通过；再运行 `npm run typecheck`，确认路由、类型、页面导入无误。
- [ ] Step 5: 检查 `/tools/mcp` 路由位于 `/tools/:id` 之前、删除操作不误删普通工具后，创建原子提交 `feat: expose MCP in settings navigation`。

## Task 5.5: 工具页批量启停与原地更新

**Files:**

- Modify: `apps/frontend/src/api/tool.ts:18-25` — 保持现有单工具 PATCH API，确保返回 `ToolDefinition` 被 store 消费。
- Modify: `apps/frontend/src/stores/tool.ts:1-68` — `toggle` 改为 PATCH 成功后原地替换目标行；新增 `toggleMany(ids, enabled)`，用 `Promise.allSettled` 汇总成功/失败，不调用 `list()`。
- Modify: `apps/frontend/src/stores/tool.spec.ts` — 覆盖单项原地更新、单项失败保留旧列表、批量全成功和部分失败。
- Modify: `apps/frontend/src/views/ToolsView.vue:1-228` — 增加表格选择列、批量操作栏、当前筛选切换清空选择、批量确认/结果提示和逐行忙碌状态；移除 MCP 注册入口后保持工具注册/测试/删除。
- Create: `apps/frontend/src/views/ToolsView.spec.ts` — 覆盖批量选择与调用、已有目标状态跳过、筛选清空选择和单项切换不触发列表刷新。

**Interfaces:**

- Consumes: `toggleTool(id: string, enabled: boolean) -> Promise<ToolDefinition>`。
- Produces: `useToolStore().toggle(id: string, enabled: boolean) -> Promise<ToolDefinition>`；`toggleMany(ids: string[], enabled: boolean) -> Promise<{ succeeded: ToolDefinition[]; failed: Array<{ id: string; reason: unknown }> }>`。
- UI contract: 复选框只代表当前筛选结果；批量成功项以服务端返回对象替换，失败项保持原对象；启停操作不改变 store 的 `status/loading`。

- [ ] Step 1: 在 `tool.spec.ts` 先断言 `toggle` 成功后更新目标行且 `listTools` 未调用；在 `ToolsView.spec.ts` 添加批量按钮存在、选择两项调用两个 PATCH、已是目标状态的行跳过和部分失败汇总用例。
- [ ] Step 2: 运行 `npm run test:unit -- --run src/stores/tool.spec.ts src/views/ToolsView.spec.ts`，预期因原地更新、批量 action 和组件入口缺失而失败。
- [ ] Step 3: 实现 store 原地更新和 `toggleMany`；在 ToolsView 用 `el-table` selection、`selection-change` 和按 id 的 pending 集合接入批量操作；批量完成后清空选择。
- [ ] Step 4: 重新运行同一命令，确认全部成功、部分失败、取消确认和筛选切换场景通过；再运行工具页、路由、MCP 页面相关单测。
- [ ] Step 5: 检查启停路径没有调用 `list()`、没有乐观覆盖失败项、没有改变 `selected_names` 或后端权限语义后，创建原子提交 `feat: batch toggle tools without reload`。

## Task 6: 集成回归、用户验收与收尾审查

**Files:**

- Modify only if required by failing tests: files listed in Tasks 1–5.5.
- Test: `apps/backend/tests/test_mcp_api.py`, `apps/backend/tests/test_mcp_sync.py`, `apps/backend/tests/test_tool_search.py`, `apps/backend/tests/test_tool_service.py`, `apps/frontend/src/api/mcp.spec.ts`, `apps/frontend/src/stores/mcp.spec.ts`, `apps/frontend/src/views/McpView.spec.ts`, `apps/frontend/src/router/routes.spec.ts`, `apps/frontend/src/mock/server.spec.ts`, `apps/frontend/src/stores/tool.spec.ts`, `apps/frontend/src/views/ToolsView.spec.ts`.
- Ledger: `progress-mcp-management-search.md`，不覆盖已有的其他任务 `progress.md`。

**Interfaces:**

- Verification command set: backend `uv run pytest tests/test_mcp_api.py tests/test_mcp_sync.py tests/test_tool_search.py tests/test_tool_service.py -q`; frontend `npm run lint:check`、`npm run typecheck`、`npm run test:unit`、`npm run build`。
- Browser/mock acceptance: open `/mcp`; register a mock HTTP source with one Authorization header; assert the source row shows only `Authorization`, tool count is 2, the two tools appear enabled in `/tools`; delete source and assert the source and associated tools disappear.

- [ ] Step 1: 在 `progress-mcp-management-search.md` 建立账本，记录每个 Task 的测试命令、输出和提交 hash；先运行受影响测试的基线，保存失败或通过结果。
- [ ] Step 2: 按 Tasks 1–5.5 顺序执行红-绿测试，不跨任务混改；每个失败先定位根因，不能用放宽断言替代修复。
- [ ] Step 3: 运行 backend 聚焦测试和 frontend 全量 lint/typecheck/unit/build；若失败，按错误所在层（类型、Mock 路由、API、store、页面或后端服务）逐一修复并重跑最小测试。
- [ ] Step 4: 运行 mock E2E，核对 MCP 页面注册/列表/删除、工具默认启用、请求头值不出现在 DOM 和网络响应摘要中。
- [ ] Step 5: 做收尾 review：`git diff --check`；`git status --short` 确认未修改 Codex 配置、未批量改变历史工具状态、未把凭据写入仓库；人工检查 MCP 页面没有编辑/启停实现和搜索逻辑没有新增依赖。
- [ ] Step 6: 运行现有项目收尾 gate；如果仓库没有可调用的 `/verify`、`/code-review`、`/simplify` 命令，则以已执行的测试、diff 检查和人工 review 记录替代，并在账本中说明。
