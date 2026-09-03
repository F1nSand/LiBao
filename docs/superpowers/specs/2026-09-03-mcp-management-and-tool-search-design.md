# MCP 管理页、工具默认启用与工具搜索修复设计

**状态：** 设计方向已获确认，等待规格审阅

## 背景

LiBao 当前把 MCP 注册表单放在工具页，Web 端没有独立的 MCP 服务源管理入口。后端已经提供 MCP 注册、列表和删除接口，因此本次只需补齐独立页面和前端领域状态，不扩展 MCP 编辑或服务启停接口。

工具启用行为目前采用“默认关闭”：普通工具注册和 MCP 工具发现都会持久化为 `enabled=false`，MCP runtime spec 注册后也保持关闭。用户要求以后新注册的普通工具和 MCP 工具默认启用，但不迁移或批量开启历史停用工具。

生产日志还显示 `tool_search` 收到多关键词查询 `apify 网页抓取爬虫 scrape crawler actor` 时返回空结果，但本地目录中存在大量包含 `apify`、`scrape`、`crawler` 或 `actor` 的工具。最小复现确认当前实现把整段查询作为单一子串：完整查询命中数为 0，单独查询 `apify` 命中数为 1。

## 目标

1. 在设置菜单中新增与“工具”同级的“MCP”页面。
2. MCP 页面支持服务源列表、新增和删除。
3. 以后新注册的普通工具默认启用。
4. 以后新注册的 MCP 所发现工具默认启用，并立即在当前 backend 进程中可供 Agent 发现和调用。
5. 修复 `tool_search` 对多关键词自然语言查询的漏匹配，同时保持结果确定性和现有两段式工具注入契约。

## 非目标

- 不新增 MCP 服务配置编辑接口。
- 不新增注册后的 MCP 服务启停接口。
- 不批量修改现有工具或现有 MCP 工具的启用状态。
- 不引入向量检索、Embedding、BM25 或新的搜索依赖。
- 不改变工具执行确认、沙箱、超时或并发策略。
- 不解决无 runtime handler 的自定义工具可执行性；本次只改变它们的持久化默认启用状态。

## 方案选择

采用独立 MCP 领域页面和独立 Pinia store。相比继续把 MCP 方法放在工具 store 中，这能让服务源的加载、注册、删除和错误状态不与工具列表耦合；相比把 MCP 放进 `SettingsView` 内部标签，它符合“与工具同级”的导航要求。

工具搜索采用无依赖的关键词 OR 匹配与确定性评分。相比仅修改提示词，它能从代码层保证日志中已复现的查询有效；相比语义检索，它不增加模型、索引或运行成本。

## Web 信息架构与交互

### 导航

- 新增路由 `/mcp`，名称 `mcp`，页面组件 `McpView.vue`。
- 设置菜单子项顺序为：设置、工具、MCP、技能、记忆、系统。
- `/mcp` 加入设置路由集合，使侧栏设置入口保持高亮。
- 使用现有图标映射中的 `Link` 作为 MCP 图标，不引入新图标依赖。

### MCP 页面

页面标题为“MCP”，副标题说明该页管理外部 MCP 服务源。列表每行显示：

- 名称；
- 传输类型（HTTP 或 stdio）；
- URL 或命令；
- 请求头名称，不显示请求头值；
- 已发现工具数量；
- 服务启用状态；
- 删除操作。

空状态提供“注册 MCP”操作；加载失败复用 `AsyncState` 的重试模式。删除前使用 `ElMessageBox` 确认，成功后刷新列表和工具列表，因为注销服务会同步移除其工具定义。

注册弹窗字段：

- 名称：可选；为空时沿用后端自动派生规则。
- 地址/命令：必填，可填写 HTTP(S) URL 或 stdio 命令。
- 请求头：可选的键值行，支持新增和删除多行；值使用密码输入控件，默认不明文展示。
- 启用：默认开启，沿用现有 `enable` 请求字段。关闭后注册的服务会显示为停用；由于本期不提供启停接口，用户只能删除后重新注册来改变该状态。

提交前删除键名或值为空的请求头行；地址/命令为空时在前端阻止提交。后端业务错误继续使用现有 HTTP 错误展示机制。注册成功后关闭弹窗、清空表单，并刷新 MCP 和工具列表。

### 工具页面

- 移除工具页头部的“注册 MCP”按钮。
- 移除工具页内部 MCP 注册状态、方法和弹窗。
- MCP 发现的工具继续出现在工具页，与普通工具共用启停和测试能力。

## 前端数据模型与 API

新增类型：

```ts
interface McpServer {
  id: string
  name: string
  transport: 'http' | 'stdio'
  url_or_command: string
  header_names: string[]
  enabled: boolean
  tool_count: number
  created_at: string
}

interface McpRegisterRequest {
  name?: string
  url_or_command: string
  headers?: Record<string, string>
  enable?: boolean
}

interface McpRegisterResult {
  server: McpServer
  tools: ToolDefinition[]
}
```

前端 API 提供 `listMcpServers()`、`registerMcp(body)` 和 `deleteMcpServer(id)`，分别调用现有 `GET /tools/mcp`、`POST /tools/mcp/register` 和 `DELETE /tools/mcp/{server_id}`。修正当前把注册响应错误声明为单个 `ToolDefinition` 的类型。

独立 `useMcpStore` 保存 `servers`、`status`、`errorMessage` 和 `submitting`，提供 `list`、`retry`、`register`、`remove`。工具 store 不再承担 MCP 注册，但页面注册和删除成功后显式调用 `useToolStore().list()` 同步工具页数据。

## 后端安全响应

当前 `serialize_mcp_server` 会原样返回 `headers`，这会把 Authorization 值送到浏览器。MCP 服务响应改为 `header_names: sorted(s.headers.keys())`，不返回 `headers` 字段。注册请求仍接受完整 `headers` 并仅持久化在 LiBao 本地数据中；列表和注册响应都不得包含请求头值。

## 新注册工具默认启用

### 普通工具

`ToolService.create` 创建新行时显式设置 `enabled=True`。如果同名 runtime spec 已存在，例如注册一个平台内置工具的元数据行，则创建完成后同步调用 registry 的 `set_enabled(spec.id, True)`，保证持久化状态和当前进程一致。没有 runtime handler 的自定义工具仍只具有元数据，不在本次范围内补造执行实现。

### MCP 工具

`McpService.register` 为每个发现工具创建 `enabled=True` 的工具行。注册 `build_mcp_spec(...)` 返回的 spec 后，立即把 spec 启用状态同步为 `row.enabled and server.enabled`。因此默认启用的服务会立即提供其工具；显式以 `enable=false` 注册服务时，工具行仍保持默认启用，但 runtime spec 因服务停用而不可用，重启后的 `_sync_mcp_spec` 继续遵守同一有效性判断。

模型类和 repository 的底层默认值保持不变，避免未经过领域服务的内部创建路径发生隐式行为变化。用户要求只针对“注册”行为，因此默认值在 `ToolService` 和 `McpService` 边界显式表达。

## 工具搜索修复

`tool_search` 继续搜索 runtime registry，因为返回的工具名称会进入 `selected_tool_names` 并在下一轮绑定 ACI；把仅存在于持久化表但没有 runtime spec 的条目返回给 Agent 会产生不可执行结果。

查询处理规则：

1. `strip()` 并转小写。
2. 使用正则 `/[\s,，;；、|/]+/` 按连续空白和常见中英文分隔符拆分关键词。
3. 去除空词并保持首次出现顺序；不做停用词表或语言学分词。
4. 任一关键词出现在工具名称或描述中即构成匹配。
5. 排序使用四元组 `(完整查询命中名称, 完整查询命中描述, 名称关键词命中数, 名称或描述关键词命中总数)`，各项降序。
6. 分数相同时按工具 `id` 排序，保持测试和模型上下文稳定。
7. 空白查询返回空匹配和现有提示，不降级为全目录。

搜索结果结构、异常时全目录降级、disabled 标记和 `selected_names` 只选择 enabled 工具的行为保持不变。

该规则直接覆盖已复现查询：`apify 网页抓取爬虫 scrape crawler actor` 至少会因 `apify`、`scrape`、`crawler` 或 `actor` 命中已有 Apify 工具，并按相关度排序。

## Mock 行为

Mock server 增加 MCP 服务源内存集合，实现列表、注册和删除的同形响应。每次 Mock 注册创建两个关联工具：`mcp_${serverId}_search` 与 `mcp_${serverId}_fetch`，两者默认 `enabled=true`；普通工具 mock 注册也改为默认启用。Mock MCP 响应只返回 `header_names`，不回传请求头值。

## 错误处理

- MCP 连接、鉴权、名称冲突和工具名冲突继续由现有后端错误码负责。
- 页面保留当前列表，加载错误时显示错误状态和重试按钮。
- 注册失败时弹窗保持打开且保留输入，便于修正地址或请求头。
- 删除失败时不从前端列表做乐观移除；后端成功后再刷新。
- 请求头值不得写入前端日志、成功提示、列表 DOM 或后端序列化响应。

## 测试策略

### 后端

- 更新普通工具注册测试，断言新行默认启用，并验证同名 runtime spec 状态立即同步。
- 更新 MCP 注册测试，断言工具行、序列化结果和当前进程 spec 默认启用。
- 增加 `enable=false` 服务测试，断言工具行默认启用但 runtime spec 不可用。
- 增加 MCP 序列化测试，断言响应包含排序后的 `header_names` 且不包含 `headers` 或 Authorization 值。
- 增加多关键词工具搜索回归测试，复现日志查询并断言 Apify 工具命中。
- 增加相关度与稳定排序测试、空白查询测试，并保留现有单关键词、大小写、disabled 和降级测试。

### 前端

- 路由测试断言 `/mcp` 属于设置组且菜单顺序正确。
- MCP API 测试断言三个端点、请求体和响应类型映射正确。
- MCP store 测试覆盖加载成功、失败保留旧列表、重试、注册后刷新和删除后刷新。
- MCP 页面组件测试覆盖空状态、列表字段、请求头行构造、注册校验、敏感值不出现在列表 DOM、删除确认及失败保留。
- 工具页测试或静态断言确认不再包含 MCP 注册入口。
- Mock 端到端用例覆盖从 MCP 页面注册服务、看到工具数量、返回工具页看到默认启用工具、删除服务后关联工具消失。

## 验收标准

1. 设置菜单可进入独立 MCP 页面，工具页不再展示 MCP 注册按钮。
2. 用户可在 MCP 页面通过 URL 或 stdio 命令注册服务，支持带 Authorization 等任意请求头。
3. MCP 列表可重试、可删除，并显示准确工具数量；任何响应和页面都不出现请求头值。
4. 新注册普通工具返回 `enabled=true`。
5. 新注册且服务启用的 MCP 工具在持久化数据、API 响应和 runtime registry 中均为启用状态。
6. 历史停用工具状态保持不变。
7. 日志中已复现的多关键词 Apify 查询能返回已有 Apify 工具；单关键词和异常降级行为不回归。
8. 后端 MCP/工具搜索测试、前端单元测试、类型检查、构建和相关 mock E2E 全部通过。
