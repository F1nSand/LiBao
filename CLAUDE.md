# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目是什么

Agent 平台（通用 Agent 运行时）的 **Web 前端工作台 / 管理控制台**：工作区/对话工作台、工具/知识库/记忆/系统监控/设置 9 页，**单用户本地模式**（无登录、无 RBAC，按《本地单机化改造方案.md》）。

**契约来源（必须遵守）**：父目录 `docs/02-frontend-design.md`（前端蓝本）、`docs/03-api-contract.md`（唯一协议依据）、`docs/04-data-model.md`（字段）。前后端完全分离，后端（FastAPI）尚未实现。

## 常用命令

```bash
npm run dev          # Vite dev server（默认启用内置 mock），http://localhost:5173
npm run build        # vue-tsc --noEmit && vite build
npm run typecheck    # vue-tsc --noEmit
npm run lint         # eslint . --fix
npm run test:unit    # vitest run（全部单测）
npx vitest run src/utils/sse-parser.spec.ts   # 跑单个单测
npm run test:e2e     # playwright test（首次先 npx playwright install chromium；自动以 --mode e2e 起 server）
npx playwright test e2e/chat-stream.spec.ts    # 跑单个 e2e
```

Mock 单用户（本地单机化）：固定 admin（无登录页/无多角色/无 Bearer）。

## 架构要点

**双层数据访问**：所有页面/组件只调 `src/api/*`（axios，`src/api/http.ts` 统一解包信封 `{code,message,data,trace_id}`、抛 `ApiError`；**单用户本地模式无登录/无 Bearer/无 401 跳转**）。SSE 用 `src/api/sse.ts`（fetch+ReadableStream，POST，不用 EventSource）。Mock 是 **Vite dev middleware**（`src/mock/plugin.ts` → `server.ts` 拦截 `/api/v1/*`，`apply:'serve'` 生产不打包），`VITE_USE_MOCK=false` 时走 Vite proxy / nginx 到真实后端。**改契约时两处都要同步**（api 模块 + mock server 路由）。

**SSE 流式核心**（难点）：
- `src/utils/sse-parser.ts`：`SseParser`（增量分帧）+ `SeqGuard`（seq 去重）+ `parseSseFrame`（容错丢帧）。
- `src/composables/useChatStream.ts`：状态机 `message_start→token→tool_call→tool_result(占位/回填)→…→done`；token 走 `utils/rAF.ts` 合并帧；`tool_result placeholder:true` 按 `job_ref` 定位卡片 + 看门狗超时；`interrupt` → `confirmInterrupt` → `POST /tasks/{id}/resume` 续流（复用 segments 不回滚）。**`confirmInterrupt` 缺 task_id 必须 fail-fast**，不得用 conversation_id 冒充。

**Markdown 安全管线**（`src/utils/markdown.ts`）：`markdown-it(GFM, html:false, hljs 高亮) → DOMPurify 白名单净化 → 后处理`（链接加 target/rel、任务列表补 `type=checkbox`）。LLM 输出视为不可信。流式期 `renderStreamingMarkdown` 渐进渲染（stable 渲染 + 末行 tail），`done` 后一次性 `renderMarkdown`。

**单通用 Agent（后端 M5 契约，前端已收敛）**：无 `/agents` API、无 Agents 页/菜单。chat/conversation/task 请求**均不带 `agent_id`**（固定用后端默认通用 Agent）；`Task.agent_id` / `Conversation.agent_id` 仍返回（= 默认 Agent id，仅展示）。subagent 由主 Agent 经内置工具 `tl_dispatch_subagent` 派发，前端渲染 `agent_switch` 事件即可（payload `{from_agent,to_agent,reason}` 不变）。`agent_control` 是 `ToolType` 合法值。

**Store 边界**（`src/stores/`）：只存客户端状态，不复制服务端全量；列表从 API 查。

**路由（无守卫）**：单用户本地模式已删登录页/角色过滤/`router/guard.ts`（所有路由直访，`/` 与 `/:pathMatch(.*)*` 重定向 `/chat`）；`createWebHistory()` 深链 fallback 由后端 FastAPI catch-all 承担（交接板）。

**类型**：`src/types/` 手工对齐 03/04，字段 **snake_case**；`SseEnvelope{id,seq,type,ts,payload}`。事件类型含监视器预留（`thinking` 等）与 mock 扩展 `notification`。

**设计令牌**：`src/styles/tokens.css`（深色侧栏 `--app-sidebar-bg:#1e1e2f`）+ `element-overrides.css`（主色 indigo `#6366f1`）。不启用 Element Plus 全局 dark（内容区保持浅色）。

## 关键易错点（踩过的坑）

- **Mock 在 Node 侧运行**：`src/mock/*` 里不能用 `import.meta.env`（用插件 `configResolved` 注入 `setMockFast`）；token 编码用 `Buffer` 而非 `btoa`（btoa 对中文抛异常）。
- **InterruptConfirmDialog 不要从 `@close` 再 emit confirm**——按钮 emit 一次即可，否则二次 resume 导致助手消息重复落库。
- **e2e 依赖 mock 确定性**：playwright `webServer` 用 `--mode e2e`（`VITE_MOCK_FAST=1` 零延迟）；不要用 `reuseExistingServer` 复用普通 dev server。
- **助手消息 = 活动区 + 回复气泡**（docs/02 §5.4.3）：工具调用/agent 切换/思考进 `.msg-activity`（紧凑行非气泡，回复气泡**上方**往下递进），文本进 `.msg-text` 气泡。流式段按事件序拆分两区；持久化 `Message.tool_calls[].position` 分组。**工具失败无重试按钮**——重试由 agent/用户以语言发起，`ToolCallCard` 只保留错误文案。
- **流式 markdown 渐进渲染**（docs/02 §5.4.1）：`MarkdownRenderer` streaming 走 `renderStreamingMarkdown`（`splitStreamingText` 按换行切分：stable 渲染 + 末行 `.stream-tail` 纯文本）；done 全量。`stable` 仅在换行跨越时变化 → 解析天然节流。
- **逐轮消息封口**（docs/02 §5.4.3 / docs/03 §3）：`message` SSE 事件 = 一轮思考完成（追加 `onPersistedMessage` + `sealRound()` 复位段，**保留** taskId/conversationId/messageId 跨轮续用）；`done` = 最后一条。一轮 = 一条独立消息气泡。真实后端未实现该事件前仍是单气泡（无回归）。
- **会话滚动到底 + 贴底跟随**（MessageList）：`messages` **引用变化**（会话加载/切换/重选）强制滚动到底（`.msg-row` 用 `content-visibility` → `scrollHeight` 估算，需 `nextTick` + **双 rAF** + `setTimeout`）。**贴底跟随**：`scroll` 事件记录 `pinned`（±32px 内才算贴底），内容变化时**仅 pinned 才跟随**（`forceScrollBottom()`）——滚动在最下方自动追随新内容，滚走则不强制拉回（内容照常生成在下方）。
- **轨迹实时同步**（TrajectoryPanel）：`live` prop（= 会话流式活跃）→ 每 2.5s 轮询 `store.load`（不重置选中/搜索/折叠）；依赖后端按轮即时落库（否则轮询无新数据）。
- **轨迹页选中/聚焦语义分离**（TrajectoryTimeline/Panel/Ledger）：**拖选 = 聚焦区域**（框内不变、外部 `.focus-dim` 灰透明，甘特+台账同步）；**点击 = 单独选中**（高亮 + 轮次高光条）；点未聚焦部分 / 空白取消聚焦（Timeline `@empty` / Panel `onCellSelect` 里 `!focusSet.has(index)` 清空）。甘特缩放 = **鼠标锚定 + panX 钳制两端不逃逸**（左端可左移出屏不右移出视口、右端不左移出视口；最小缩放=内容铺满可视区）。**拖选命中坐标须减 44px 泳道标签列宽（`LABEL_W`）**，否则拖框与方块错位 44px；`fitScale` 的可视区宽要取真实 viewport（`.tj-lane-body.clientWidth` 需轨道固定为视口宽，若轨道=内容宽则 fit≈1 卡死缩不动）。
- **工具轮占位 + thinking 折叠**：`toolCallSummary(name, input)`（`utils/format.ts`）为无文本工具轮生成「调用 [工具]：入参」占位；`MessageBubble.partsFromMessage` 读 `Message.thinking` 加活动区 thinking 行（`isThinkingLong` → line-clamp 收起 + 展开/收起按钮）。`ChatView.onPersistedMessage` 须透传 `m.thinking`（否则持久化丢推理）。
- 消息持久化在 mock 的 `doneEvent`（最后一条）与 `sealEvent`（中间轮）里 push 到 `messages[conv]`；新会话（conversation_id=null）由 mock server 先注册 conversation。
- **mock 任务事件端点是 GET**（`/tasks/{id}/events`，契约 docs/03 §5.3 / 真实后端 / `TaskDetail.vue` 都是 GET）——改 mock 路由时不要只留 POST。
- **`agent_switch` 仅流式期显示**：`MessageBubble` 的 `.agent-switch` 指示条挂在 `showStreamBubble`（`!finished`）的流式气泡里，done 后被持久化消息替换即消失（`Message` 无持久化字段）。不要写依赖 done 后仍可见该指示条的 e2e 断言（mock-fast 下是竞态）。

## 工作流约定（本机全局）

按任务规模定档（详见全局 CLAUDE.md）：**L1** 微小改动 → 简易笔记 + 快速 Test（豁免 Simplify）；**L2** 常规功能 → 轻量计划 + 完整流程；**L3** 大型复杂 → 强制完整三段流程。多步骤功能仍走 `explore-planner` 出计划 → `executor-debugger` 按账本执行（`progress.md`）→ 收尾 `review-test-simplify` 三道 gate。
