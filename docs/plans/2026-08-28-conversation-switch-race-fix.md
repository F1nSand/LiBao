# 会话快速切换与跳转竞态修复计划

**Goal:** 会话点击后立即更新选中态并进入 `/chat`，消息请求在后台完成；快速执行 A→B 或 A→B→A 时始终以最后一次点击为准，不出现无响应、旧消息回写、加载态提前结束或错误串到当前会话。

**Architecture:** 将“选择会话/路由跳转”与“加载消息”解耦：用户意图同步落地，路由跳转不等待网络；消息加载使用单调递增的请求版本实现 latest-wins，只有当前版本能提交 `currentMessages`、`messagesError` 和 `messagesLoading`。工作区内嵌会话复用相同守卫语义，不修改 API 或 SSE 契约。

**Diagnosis basis:** 静态调用链审查 + 本地普通开发模式复现。由 `/kb` 点击侧栏会话时，`ConversationList.onSelect` 先 `await chat.selectConversation(id)`，而后者又等待 `GET /conversations/{id}/messages`；`router.push('/chat')` 因此被消息网络请求阻塞。实测一次从点击到进入 `/chat` 约 3.3 秒，期间界面表现为卡顿/无反应。

**Global Constraints:**
- 不修改 `docs/03-api-contract.md`、消息分页字段、SSE 事件或 mock 路由契约。
- 保留 `currentId` 变化后 `useChatStream.setConversation(id)` 的多会话流隔离；切换会话不得停止其它会话的后台流。
- 保留“切换开始立即清空旧消息并显示骨架”的既有交互，以及 MessageList 的贴底跟随和按会话滚动位置恢复。
- 过期请求的成功、失败和 `finally` 都不得改写最新请求的消息、错误或 loading 状态。
- 不依赖请求实际完成顺序；正确性由客户端请求版本保证。可选的 HTTP 取消只能作为资源优化，不能成为唯一竞态保护。
- 不覆盖用户现有的 `progress.md`、`.claude/`、`.playwright-mcp/`、`AGENTS.md` 或其它无关改动。

---

## 根因与影响范围

### 根因 1：路由跳转被消息加载串行阻塞（已复现）

`src/components/business/ConversationList.vue:17` 的 `onSelect` 先等待 `chat.selectConversation(id)`，再执行 `router.push('/chat')`；`src/stores/chat.ts:48` 的 `selectConversation` 又等待 `loadMessages`。因此用户在知识库、工具、设置等非聊天页点击会话后，URL 和主内容区都要等消息接口返回才变化。连续点击会并发启动多个处理器，每个处理器都在各自请求完成后才尝试跳转，造成“卡一下、没有跳转”的直接体验。

### 根因 2：响应守卫无法覆盖 A→B→A（代码级确认）

`src/stores/chat.ts:60` 只检查 `id === currentId`。当请求顺序为 A1→B2→A3 时，若旧的 A1 在回到 A 后完成，它仍满足 ID 检查，会覆盖 A3 的结果；A1 的 `finally` 还可能把 A3 正在使用的 `messagesLoading` 提前设为 `false`。错误分支存在同类问题。

`src/components/workspace/WorkspaceShell.vue:97` 使用相同的 ID-only 守卫，因此工作区内快速回切也有同样风险，虽然它没有跨路由阻塞问题。

### 非根因

- Vue Router 没有守卫或鉴权重定向，本问题不是路由表拒绝跳转。
- mock/后端最终能返回正确消息，单次等待后可进入聊天页，不是会话不存在。
- `ChatView` 已在 `currentId` 改变时同步切换对应流上下文，SSE 多流隔离不是本次卡顿来源。

---

## Task 1: 先建立可稳定复现两类竞态的回归测试

**Files:**
- Create: `src/stores/chat.spec.ts`
- Modify: `src/components/business/ConversationList.spec.ts`
- Modify: `e2e/chat-mobile.spec.ts`

**Interfaces:**
- Consumes: `useChatStore.selectConversation(id)`、`useChatStore.loadMessages(id, page?)`、`ConversationList.onSelect(id)`。
- Produces: “路由不等待消息请求”和“最后一次选择获胜”的测试不变量。

- [ ] Step 1: 在 `ConversationList.spec.ts` 将模拟路由设为非 `/chat`，让 `chat.selectConversation` 返回一个未完成 Promise；点击会话后不释放 Promise，立即断言 `selectConversation('c2')` 与 `router.push('/chat')` 都已调用。该测试应先失败，证明当前跳转被 `await` 阻塞。
- [ ] Step 2: 在新建的 `chat.spec.ts` 使用真实 Pinia store、mock `@/api/chat.listMessages` 和三个可控 Promise，构造 A1→B2→A3；依次释放 A1、B2、A3，断言 A1/B2 均不能写入消息、错误或关闭 loading，最终只接受 A3。
- [ ] Step 3: 增加旧请求失败场景：A1→B2 后拒绝 A1，断言当前 B 不显示 A 的错误且 B2 完成前 `messagesLoading` 保持 `true`。
- [ ] Step 4: 在 `e2e/chat-mobile.spec.ts` 增加跨页面场景：从 `/kb` 点击一个会话，同时拦截并延迟其 messages 请求；请求尚未释放时即断言 URL 已为 `/chat`、对应会话已激活、旧消息不存在且骨架可见。
- [ ] Step 5: 增加快速 A→B 场景：分别拦截两个 messages 请求，让 B 先完成、A 后完成；最终断言 active 会话和消息都属于 B，A 的迟到响应不再改变页面。
- [ ] Step 6: 运行 `npx vitest run src/stores/chat.spec.ts src/components/business/ConversationList.spec.ts` 和 `npx playwright test e2e/chat-mobile.spec.ts`，确认新增用例按预期失败且失败点对应上述两条根因。
- [ ] Step 7: Commit: `test(chat): reproduce rapid conversation switch races`

## Task 2: 将全局会话选择改为即时跳转与 latest-wins 加载

**Files:**
- Modify: `src/components/business/ConversationList.vue:17`
- Modify: `src/stores/chat.ts:16`
- Modify: `src/views/ChatView.vue:264`
- Modify: `src/stores/chat.spec.ts`
- Modify: `src/components/business/ConversationList.spec.ts`

**Interfaces:**
- Produces: `messagesRequestVersion: number`（名称可按项目惯例微调），每次消息加载开始时递增。
- Keeps: `selectConversation(id: string): Promise<void>` 对调用方兼容，但其 Promise 不再决定何时路由；`loadMessages(id, page?)` 仍可用于当前会话重试。
- Removes: 未被任何消费方读取的 `selectionToken` 及其过时注释，避免与实际 `currentId` watcher 语义冲突。

- [ ] Step 1: 在 chat store 增加单调递增的消息请求版本；`loadMessages` 启动时捕获本次版本，并在 success/catch/finally 三个分支同时校验“版本仍为最新且 id 仍为 currentId”。
- [ ] Step 2: `selectConversation` 保持同步完成 `currentId`、清空 `currentMessages`、清空错误并启动 loading，再异步加载消息；创建/删除当前会话时递增版本以使在途请求失效。
- [ ] Step 3: 将 ChatView 的“重试加载”从再次调用 `selectConversation(currentId)` 改为 `loadMessages(currentId)`，避免重试被误认为一次新的用户切换并重复执行选择副作用。
- [ ] Step 4: 将 `ConversationList.onSelect` 改为非阻塞编排：先触发 `void chat.selectConversation(id)` 使选中态/骨架立即生效，再在当前不为 `/chat` 时立即 `void router.push('/chat')`；不得等待 messages 请求后再导航。
- [ ] Step 5: 对 `router.push` 的 rejected Promise 保持现有全局错误处理策略，不把消息请求失败与路由失败合并为同一错误态。
- [ ] Step 6: 运行 Task 1 的 Vitest 与 E2E，确认路由即时性、A→B、A→B→A、迟到错误和 loading 生命周期全部通过。
- [ ] Step 7: Commit: `fix(chat): make conversation switching latest-wins`

## Task 3: 为工作区会话补齐同等请求版本守卫

**Files:**
- Modify: `src/components/workspace/WorkspaceShell.vue:97`
- Create: `src/components/workspace/WorkspaceShell.spec.ts`

**Interfaces:**
- Produces: 组件局部 `messageRequestVersion`，语义与 chat store 一致。
- Keeps: `WorkspaceConvList` 的 `select/create/delete` emits 和工作区 API 调用方式不变。

- [ ] Step 1: 在 `WorkspaceShell.spec.ts` mock `listMessages`，构造 A1→B2→A3 和旧请求失败场景，断言只有最新版本能提交消息、错误和 loading。
- [ ] Step 2: 在 `WorkspaceShell` 的 `selectConversation` 中递增并捕获局部请求版本；success/catch/finally 必须同时校验版本和 currentId。
- [ ] Step 3: 删除当前会话、切换 workspaceId 或组件卸载时使在途版本失效，避免旧工作区响应回写新上下文。
- [ ] Step 4: 将工作区“重试消息”抽为只重新执行当前消息加载，不重复 `stream.setConversation` 或其它会话选择副作用。
- [ ] Step 5: 运行 `npx vitest run src/components/workspace/WorkspaceShell.spec.ts` 和 `npx playwright test e2e/workspace.spec.ts`。
- [ ] Step 6: Commit: `fix(workspace): guard rapid conversation reloads`

## Task 4: 全量回归与收尾审查

**Files:**
- Modify only if findings require: `AGENTS.md`
- Modify only if implementation progress is tracked: `docs/plans/2026-08-28-conversation-switch-race-fix.progress.md`

**Interfaces:**
- Consumes: Tasks 1–3 的测试不变量。
- Produces: 可恢复执行账本与最终验证记录。

- [ ] Step 1: 使用 `executor-debugger` 按本计划执行，并在同目录 progress 文件记录每项状态、验证命令和偏差。
- [ ] Step 2: 运行 `npm run typecheck`、`npm run lint:check`、`npm run test:unit`、`npm run build`。
- [ ] Step 3: 运行 `npx playwright test e2e/chat-mobile.spec.ts e2e/scroll.spec.ts e2e/chat-stream.spec.ts e2e/workspace.spec.ts`，再运行 `npm run test:e2e`。
- [ ] Step 4: 在普通开发模式手工延迟 messages 请求，验证 `/kb`、`/tools`、`/settings` 点击会话都立即进入 `/chat`；在 `/chat` 和工作区各验证 A→B、A→B→A。
- [ ] Step 5: 检查流式中的 A 切到 B 再切回 A：A 的后台流仍在对应上下文继续，且迟到的历史消息请求不能覆盖流式期间已追加的当前消息。
- [ ] Step 6: 使用 `review-test-simplify` 完成 Test / Review / Simplify 三道 gate；重点审查所有 state commit 是否都有最新版本守卫，以及是否出现未处理 Promise 或重复请求。
- [ ] Step 7: 如新增了可长期复用的不变量，在 `AGENTS.md` 记录“会话选择即时生效、消息加载 latest-wins、禁止仅按 ID 防 A→B→A”的约束。
- [ ] Step 8: Commit: `docs(chat): record conversation switching invariants`

---

## 验收标准

- 从任意非聊天页点击会话，即使 messages 请求被延迟 5 秒，也应先进入 `/chat` 并立即显示目标会话选中态和加载骨架。
- 快速点击 A→B，最终 active 会话、消息、错误和 loading 全部属于 B；A 的迟到成功/失败不产生任何可见状态变更。
- 快速点击 A→B→A，旧 A1 不得冒充最新 A3；A3 完成前 loading 不提前消失。
- 切换开始后不闪现上一会话消息；最新请求失败时只显示当前会话错误并可重试。
- 工作区内嵌会话满足相同 latest-wins 语义。
- 正在流式输出的其它会话不被取消或串流，切回后仍显示该会话自己的流状态。
- typecheck、lint check、unit、build、目标 E2E 与全量 E2E 全部通过。

## 明确不在本轮范围

- 不改变会话 URL 结构或新增 query/route param。
- 不修改后端 messages API，不要求服务端支持取消请求。
- 不引入新的状态管理、请求缓存或路由库。
- 不重做会话列表视觉样式、分页策略或 SSE 生命周期。
