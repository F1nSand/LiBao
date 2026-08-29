# 前端界面与样式系统优化实施计划

**Goal:** 在不改变 API 契约、单用户本地模式和核心交互语义的前提下，系统性修复移动端布局、主题对比度、键盘可达性和页面状态反馈，并统一全站视觉层级。

**Architecture:** 先把颜色、间距、控件尺寸、焦点和响应式规则收敛到全局令牌与布局壳，再逐层改造聊天/工作区、轨迹和管理页。桌面端保留高密度工作台；769–960px 使用 64px 导航轨道；≤768px 使用覆盖式导航抽屉，主内容始终占满视口。

**Audit basis:** 代码静态审查 + 1440×900、800×900、390×844 本地 mock 实机核验。390px 下 `/chat` 的 232px 侧栏将主区压缩至 158px，输入区内部宽度达到 278px，已确认发生布局挤压。

**Global Constraints:**
- 遵守 `../docs/02-frontend-design.md`、`../docs/03-api-contract.md`、`../docs/04-data-model.md`；不新增或修改后端协议。
- 保留深色侧栏、浅色内容区和 Element Plus，不启用 Element Plus 全局 dark。
- 保留消息活动区在回复气泡上方、逐轮封口、贴底跟随、轨迹选中/聚焦分离等既有语义。
- 正常文本对比度至少 4.5:1；大号文本和非文本 UI 至少 3:1。
- ≤768px 的主要触控目标最小 44×44px；桌面紧凑控件最小高度 32px。
- 动效仅使用 `transform`、`opacity` 和颜色/阴影属性；继续遵守 `prefers-reduced-motion`。
- 不覆盖用户现有的 `progress.md`、`.claude/`、`.playwright-mcp/`、`AGENTS.md` 改动。

---

## 审查结论与优先级

### P0

1. `/chat` 在手机宽度仍占用 232px 常驻侧栏，主内容和 composer 已实测溢出。
2. `--app-primary` 同时承担按钮填充、链接、文字和焦点色，多套主题对白色不满足 4.5:1；`--app-text-muted` 在浅色背景上也明显不足。
3. 全仓缺少统一 `:focus-visible`，会话、通知、知识库集合、消息展开、轨迹台账等主要操作存在鼠标专用交互。

### P1

1. 主题配置、静态令牌和 Element 覆盖存在多套真源及默认值漂移。
2. 管理页只折叠侧栏，页面 header、固定宽度筛选器、表格和弹窗没有 768/480px 响应式策略。
3. 会话切换、轨迹加载、列表错误和空数据状态混用；发送失败时草稿不可恢复。
4. 大量 10–12px 信息文字、30px 图标按钮和纯颜色状态表达降低可读性与触控可用性。

### P2

1. 硬编码 success/warning/error 色、间距、时长和弹窗宽度重复分散。
2. `transition: all` 可能意外动画布局属性。
3. 响应式 e2e 最窄只覆盖 800px，且把聊天页窄屏常驻侧栏固化为旧预期。

---

## Task 1: 建立可验证的视觉基线和语义设计令牌

**Files:**
- Modify: `src/styles/tokens.css:1`
- Modify: `src/styles/element-overrides.css:1`
- Modify: `src/styles/global.css:1`
- Modify: `src/styles/markdown.css:1`
- Modify: `src/theme/themes.ts:1`
- Modify: `src/theme/themes.spec.ts:1`
- Create: `src/styles/tokens.spec.ts`

**Interfaces:**
- Produces: CSS 变量 `--app-primary-fill`、`--app-on-primary`、`--app-link`、`--app-focus-ring`、`--app-success`、`--app-warning`、`--app-danger`、`--app-info`、`--app-text-tertiary`、`--app-text-disabled`、`--app-space-1..6`、`--app-control-sm/md/touch`、`--app-z-dropdown/modal/toast`。
- Produces: `ThemeDef.vars` 的完整语义色映射；`applyTheme(id: string): void` 仍为唯一运行时入口。
- Consumes: 现有 `THEMES`、`DEFAULT_THEME` 和 Element Plus CSS 变量。

- [ ] Step 1: 在 `themes.spec.ts` 增加每套主题必含语义变量、前景/背景对比度阈值、切换后 Element 变量同步的失败测试。
- [ ] Step 2: 在 `tokens.spec.ts` 读取 `tokens.css`，断言核心语义令牌存在、`--app-text-muted` 不再承担 disabled 语义、组件公共状态色不依赖未定义 fallback。
- [ ] Step 3: 运行 `npx vitest run src/theme/themes.spec.ts src/styles/tokens.spec.ts`，确认新增断言先失败。
- [ ] Step 4: 扩充令牌，并让 `themes.ts` 成为主题色唯一真源；静态 CSS 仅保留默认安全回退值。
- [ ] Step 5: 将 Markdown 链接、Element 主按钮/链接/焦点、全局状态色改用对应语义变量；把 `.el-button` 的 `transition: all` 收窄为颜色、阴影和 transform。
- [ ] Step 6: 运行上述单测和 `npm run typecheck`，确认通过。
- [ ] Step 7: Commit: `refactor(ui): unify semantic design tokens and theme contrast`

## Task 2: 重构应用壳与导航的三档响应式布局

**Files:**
- Modify: `src/constants/layout.ts:1`
- Modify: `src/App.vue:5`
- Modify: `src/components/layout/SidebarNav.vue:14`
- Modify: `src/components/business/ConversationList.vue:36`
- Modify: `src/router/routes.ts:1`
- Modify: `e2e/layout.spec.ts:4`
- Create: `e2e/mobile-shell.spec.ts`

**Interfaces:**
- Produces: `TABLET_LAYOUT_MQ = '(max-width: 960px)'`、`MOBILE_LAYOUT_MQ = '(max-width: 768px)'`。
- Produces: `SidebarNav` 的 `drawerOpen`/`closeDrawer` 行为；路由变化后自动关闭移动抽屉。
- Consumes: `useMediaQuery(query: string)`、`menuItems`、当前会话列表。

- [ ] Step 1: 修改 `layout.spec.ts` 的旧预期：800px 下所有页面使用 64px 导航轨道，不再为 `/chat` 保留 232px 例外。
- [ ] Step 2: 在 `mobile-shell.spec.ts` 增加 390×844 测试：主内容宽度等于视口宽度、抽屉覆盖而非挤压内容、遮罩可关闭、Escape 可关闭、路由跳转后关闭、焦点返回菜单按钮。
- [ ] Step 3: 运行 `npx playwright test e2e/layout.spec.ts e2e/mobile-shell.spec.ts`，确认新增场景失败。
- [ ] Step 4: 在 `App.vue` 增加移动顶部栏、菜单按钮、遮罩和 `main` 焦点目标；在 `SidebarNav.vue` 实现桌面常驻、平板轨道、移动抽屉三态。
- [ ] Step 5: 将导航项补成稳定可访问名称、`aria-current="page"`、移动抽屉标题和关闭按钮；把折叠宽度/抽屉宽度提升为令牌。
- [ ] Step 6: 为 960/768/480px 定义 `.app-page`、`.app-page-header` 和 header actions 的换行/间距规则；使用 `100dvh` 并处理移动安全区。
- [ ] Step 7: 运行两项 e2e、`npm run typecheck` 和 `npm run lint:check`。
- [ ] Step 8: Commit: `feat(ui): add adaptive navigation shell for tablet and mobile`

## Task 3: 优化聊天与工作区 composer、加载和失败恢复

**Files:**
- Modify: `src/views/ChatView.vue:42`
- Modify: `src/components/workspace/WorkspaceShell.vue:92`
- Modify: `src/components/business/AttachmentUploader.vue:1`
- Modify: `src/components/business/MessageList.vue:23`
- Modify: `src/stores/chat.ts:1`
- Modify: `src/stores/workspace.ts:1`
- Modify: `src/composables/useChatStream.ts:1`
- Modify: `e2e/chat-stream.spec.ts:1`
- Modify: `e2e/workspace.spec.ts:1`
- Create: `e2e/chat-mobile.spec.ts`

**Interfaces:**
- Produces: 明确的消息加载状态，切换会话时不显示上一会话内容。
- Produces: `AttachmentUploader` 向父组件返回 `{ id, name, size, status }`，composer 渲染可移除附件 chip。
- Produces: 流失败状态中的 `retry` 和 `restoreDraft` UI；不改变 SSE 请求或事件协议。
- Consumes: `StreamState.error`、现有 `start/stop/confirmInterrupt`、工作区文件引用。

- [ ] Step 1: 增加会话切换慢响应测试，断言旧消息立即隐藏并显示 `StreamSkeleton`，完成后只显示新会话消息。
- [ ] Step 2: 增加发送失败测试，断言错误原因靠近失败消息显示，用户可恢复草稿或用原请求重试。
- [ ] Step 3: 增加 390px composer 测试，断言 textarea 独占第一行、附件/模型/发送位于第二行、无内部横向溢出、textarea 最多 8 行后内部滚动。
- [ ] Step 4: 运行 `npx playwright test e2e/chat-stream.spec.ts e2e/workspace.spec.ts e2e/chat-mobile.spec.ts`，确认新增场景失败。
- [ ] Step 5: 为 chat/workspace store 增加按当前会话归属的 loading/error 展示状态；切换开始即清空视图绑定或显示缓存对应会话。
- [ ] Step 6: 重排两个 composer；在 ≤768px 使用两行布局、短模型标签和 44px 操作区，在桌面维持紧凑单行。
- [ ] Step 7: 增加附件 chip、上传中/失败/移除反馈；保留每条最多 10 个附件约束。
- [ ] Step 8: 增加失败原因、恢复草稿和重试入口，确保重试不会重复追加用户消息。
- [ ] Step 9: 运行相关 e2e、`npx vitest run src/composables/useChatStream.spec.ts src/stores/workspace.spec.ts`、typecheck 和 lint check。
- [ ] Step 10: Commit: `feat(chat): improve responsive composer and recoverable states`

## Task 4: 修复消息流、会话列表和通知的交互可达性

**Files:**
- Modify: `src/components/business/ConversationList.vue:36`
- Modify: `src/components/business/MessageList.vue:23`
- Modify: `src/components/business/MessageBubble.vue:147`
- Modify: `src/components/business/ToolCallCard.vue:42`
- Modify: `src/components/layout/NotificationPane.vue:14`
- Modify: `src/components/layout/SidebarNav.vue:44`
- Modify: `src/components/business/MessageBubble.spec.ts:1`
- Create: `src/components/business/ConversationList.spec.ts`
- Create: `src/components/business/MessageList.spec.ts`
- Create: `src/components/layout/NotificationPane.spec.ts`

**Interfaces:**
- Produces: 所有展开/选择操作均由原生 `button`/`a` 提供，并支持 Enter、Space 和 `:focus-visible`。
- Produces: `MessageList` 在 `pinned === false` 且内容增长时显示“有新内容 / 回到底部”按钮。
- Consumes: 现有 scroll position Map、`pinned` 逻辑和会话选择 action。

- [ ] Step 1: 为会话项、通知项、thinking 展开和工具调用展开增加角色、键盘触发、`aria-expanded`/`aria-current` 单测。
- [ ] Step 2: 为 MessageList 增加测试：用户离底后内容增长显示按钮，点击后回到底部并恢复贴底；未增长时不显示。
- [ ] Step 3: 运行新增 Vitest 测试并确认先失败。
- [ ] Step 4: 将可点击容器替换为原生交互元素，保留现有布局；为删除/更多等图标按钮提供可见或辅助名称和至少 32px 桌面命中区。
- [ ] Step 5: 实现回到底部按钮和流式新内容提示；不得改变既有“用户滚走不强拉回”的规则。
- [ ] Step 6: 使用语义字号/状态色替换消息活动区和通知区的 10–12px 魔法值与叠加 opacity。
- [ ] Step 7: 运行新增单测、现有 `MessageBubble.spec.ts`、`e2e/scroll.spec.ts` 和 `e2e/chat-stream.spec.ts`。
- [ ] Step 8: Commit: `fix(ui): make chat interactions keyboard accessible`

## Task 5: 提升轨迹界面的加载反馈、选中辨识和窄屏可用性

**Files:**
- Modify: `src/components/trajectory/TrajectoryPanel.vue:24`
- Modify: `src/components/trajectory/TrajectoryTimeline.vue:216`
- Modify: `src/components/trajectory/TrajectoryLedger.vue:112`
- Modify: `src/components/trajectory/TrajectoryDetailPanel.vue:101`
- Modify: `src/stores/trajectory.ts:1`
- Modify: `src/utils/trajectory.spec.ts:1`
- Modify: `e2e/trajectory.spec.ts:1`

**Interfaces:**
- Produces: `TrajectoryPanel` 区分 `initialLoading`、`refreshing`、`loadingEarlier`。
- Produces: 时间轴单元和台账行可键盘选择；分栏 separator 支持方向键按 16px 调宽并暴露 `aria-valuenow/min/max`。
- Consumes: 现有 `focusSet`、`selectedIndex`、240–720px 详情宽度和 2.5s live 轮询。

- [ ] Step 1: 增加首次进入只请求一次、首次显示骨架、live 刷新不清空内容、加载更早按钮显示 loading 的测试。
- [ ] Step 2: 增加键盘测试：时间轴 Enter/Space 选择、台账上下键移动、separator 左右键调宽；焦点始终可见。
- [ ] Step 3: 增加 800px/390px 断言：详情覆盖层不导致页面横向溢出，泳道和台账标签保留缩写/图标，语义不只依赖颜色。
- [ ] Step 4: 运行 `npx playwright test e2e/trajectory.spec.ts` 并确认新增场景失败。
- [ ] Step 5: 合并重复 immediate watcher；保留当前选中/搜索/折叠的 live 刷新语义。
- [ ] Step 6: 增加骨架、轻量刷新指示和按钮 loading；清晰区分 hover、selected、focused 和 dimmed 样式。
- [ ] Step 7: 补齐时间轴、台账和分隔条的原生/ARIA 语义及焦点样式；将 10px 关键文本提升到可读字号。
- [ ] Step 8: 运行 trajectory e2e、相关 Vitest、typecheck 和 lint check。
- [ ] Step 9: Commit: `feat(trajectory): improve loading focus and responsive states`

## Task 6: 统一管理页容器、表格、表单与状态组件

**Files:**
- Modify: `src/styles/global.css:31`
- Modify: `src/styles/element-overrides.css:1`
- Modify: `src/components/common/EmptyState.vue:1`
- Modify: `src/components/common/PaginationPanel.vue:1`
- Create: `src/components/common/AsyncState.vue`
- Create: `src/components/common/ResponsiveDialog.vue`
- Create: `src/components/common/AsyncState.spec.ts`
- Modify: `src/stores/tool.ts:1`
- Modify: `src/stores/kb.ts:1`
- Modify: `src/stores/memory.ts:1`
- Modify: `src/stores/system.ts:1`

**Interfaces:**
- Produces: `AsyncState` props `{ status, errorMessage, emptyText }` 和 `retry` emit，覆盖 `idle/loading/success-empty/success/error/unavailable`。
- Produces: `ResponsiveDialog` 接收桌面 `width`，实际宽度为 `min(width, calc(100vw - 24px))`。
- Produces: 管理页列表 store 的 `status`、`errorMessage` 和 `retry()`；现有数据数组和 API action 签名保持不变。

- [ ] Step 1: 为 AsyncState 增加 loading、空、错误、不可用和 retry emit 的组件测试。
- [ ] Step 2: 为四个 store 增加失败不伪装为空列表、重试可恢复、切换筛选清理旧错误的单测。
- [ ] Step 3: 运行新增单测并确认先失败。
- [ ] Step 4: 实现公共异步状态组件和响应式 dialog 包装；统一页面 card、header、filter bar、table wrapper 的间距与断点规则。
- [ ] Step 5: 将列表状态收敛到统一状态机；错误必须显示原因和重试，空态提供下一步操作。
- [ ] Step 6: 统一表单提交期间 loading/disabled、字段旁错误、首错聚焦和失败保留输入；不引入新的表单依赖。
- [ ] Step 7: 运行新增单测、全量 store 单测、typecheck 和 lint check。
- [ ] Step 8: Commit: `refactor(ui): standardize admin page states and responsive primitives`

## Task 7: 逐页落地管理台响应式与键盘优化

**Files:**
- Modify: `src/views/WorkspaceView.vue:28`
- Modify: `src/components/workspace/WorkspaceCard.vue:45`
- Modify: `src/views/KbView.vue:57`
- Modify: `src/views/ToolsView.vue:45`
- Modify: `src/components/business/ToolTestModal.vue:12`
- Modify: `src/views/SkillsView.vue:1`
- Modify: `src/views/MemoryView.vue:25`
- Modify: `src/components/business/MemoryCardList.vue:17`
- Modify: `src/views/SystemView.vue:46`
- Modify: `src/components/business/TraceTimeline.vue:54`
- Modify: `src/views/SettingsView.vue:102`
- Modify: `src/components/layout/ThemePane.vue:1`
- Modify: `src/components/layout/NotificationPane.vue:14`
- Modify: `e2e/kb.spec.ts:1`
- Modify: `e2e/tools-meta.spec.ts:1`
- Modify: `e2e/skills.spec.ts:1`
- Modify: `e2e/theme.spec.ts:1`
- Create: `e2e/admin-responsive.spec.ts`
- Create: `e2e/admin-keyboard.spec.ts`

**Interfaces:**
- Consumes: Task 1 的语义令牌、Task 2 的断点、Task 6 的 `AsyncState`/`ResponsiveDialog`。
- Produces: 所有管理页在 390/800/1440px 无页面级横向溢出；宽表格仅在自己的 table wrapper 内滚动。

- [ ] Step 1: 增加 390/800/1440px 页面矩阵：header actions 换行、筛选器全宽、知识库集合区改为上方横向选择/折叠区、弹窗不超出视口、表格滚动不推动页面。
- [ ] Step 2: 增加键盘矩阵：知识库集合、系统 trace、Trace 节点、设置 tabs 和主题 swatch 可通过 Tab/Enter/Space/方向键操作并显示焦点。
- [ ] Step 3: 运行新增 e2e 并确认先失败。
- [ ] Step 4: Workspace：卡片 grid 在 ≤480px 使用单列，卡片操作常显且命中区合格。
- [ ] Step 5: Knowledge Base：集合区在窄屏改为顶部区域；表格操作不被固定列遮挡；混合权重改为 `bm25 = 1 - semantic`，无结果与未执行状态分开。
- [ ] Step 6: Tools/Skills：筛选、表格、注册弹窗响应式；ToolTestModal 每次打开按 schema 重建值并按 boolean/number/string 渲染正确控件。
- [ ] Step 7: Memory：统一 importance 内部 0–1、UI 0–5 的转换；筛选器和卡片操作适配窄屏。
- [ ] Step 8: System：接入 `PaginationPanel`，补 loading/empty/error；trace 查看提供显式按钮或完整行键盘语义。
- [ ] Step 9: Settings：自定义标签改为 `tablist/tab/tabpanel` 语义；Provider 表单增加 required 规则、提交防重和响应式宽度；主题 swatch 显示对比安全的选中/焦点状态。
- [ ] Step 10: 运行新增 e2e、现有相关 e2e、typecheck 和 lint check。
- [ ] Step 11: Commit: `feat(ui): polish responsive and accessible admin pages`

## Task 8: 全量回归、视觉核验与文档同步

**Files:**
- Modify: `playwright.config.ts:9`
- Modify: `e2e/helpers.ts:1`
- Modify: `e2e/layout.spec.ts:1`
- Modify: `../docs/02-frontend-design.md:86`
- Modify: `AGENTS.md:1`

**Interfaces:**
- Produces: 确定性的 e2e server 配置，默认不复用普通 dev server；响应式矩阵固定为 390×844、800×900、1440×900。
- Consumes: Tasks 1–7 的组件与测试。

- [ ] Step 1: 将 Playwright server 调整为隔离 e2e mode；如保留复用能力，先以探针确认 `VITE_MOCK_FAST=1`，否则启动独立端口。
- [ ] Step 2: 运行 `npm run typecheck`、`npm run lint:check`、`npm run test:unit`、`npm run build`。
- [ ] Step 3: 运行 `npm run test:e2e`；对 390/800/1440px 的 `/chat`、`/workspace`、`/kb`、`/tools`、`/memory`、`/system`、`/settings` 做截图核验。
- [ ] Step 4: 手工键盘走查：侧栏/抽屉、会话列表、composer、消息展开、轨迹、管理页表格和所有弹窗；确认焦点顺序、焦点可见和 Escape 行为。
- [ ] Step 5: 手工主题走查九套配色，确认正文 4.5:1、非文本 3:1、浅色侧栏主题前景正确、状态不只依赖颜色。
- [ ] Step 6: 同步前端蓝本的三档导航、响应式页面、语义主题和可访问性约束；在 `AGENTS.md` 记录新的断点与测试不变量。
- [ ] Step 7: 使用 `review-test-simplify` 完成 Test / Review / Simplify 三道 gate，处理发现后再提交。
- [ ] Step 8: Commit: `docs(ui): record responsive and accessibility invariants`

---

## 验收标准

- 390×844、800×900、1440×900 下，所有主路由没有页面级横向滚动；表格若需横向滚动，只发生在表格容器内。
- 手机端侧栏为覆盖式抽屉，关闭后主内容宽度等于视口宽度；平板端为 64px 导航轨道。
- 聊天和工作区 composer 在手机端无挤压，textarea 最多 8 行，操作按钮命中区至少 44px。
- 九套主题的正常文本达到 4.5:1；主题切换、刷新持久化和 Element Plus 映射继续通过测试。
- 主要交互均可通过键盘完成，焦点可见；状态信息不只依赖颜色。
- 会话切换不泄露上一会话内容；加载、空、错误、不可用四类状态可辨识且错误可重试。
- 原有 SSE、逐轮消息、贴底跟随、轨迹聚焦/选中、工作区文件引用和 mock 契约测试无回归。

## 明确不在本轮范围

- 不新增暗色内容区或重做品牌视觉。
- 不修改后端 API、SSE 事件、领域字段或认证模式。
- 不引入新的 UI 框架、动画库或表单库。
- 不把桌面管理台整体放大为移动消费型 UI；44px 触控密度仅在 ≤768px 强制。
