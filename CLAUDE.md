# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目是什么

Agent 平台（通用 Agent 运行时）的 **Web 前端工作台 / 管理控制台**：对话工作台、Agent/任务/工具/知识库/记忆/系统监控/设置 8 页 + 登录，RBAC 三角色。

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

Mock 演示账号：`admin/admin123`（管理员）· `dev/dev123`（开发者）· `viewer/viewer123`（访客）。

## 架构要点

**双层数据访问**：所有页面/组件只调 `src/api/*`（axios，`src/api/http.ts` 统一解包信封 `{code,message,data,trace_id}`、抛 `ApiError`、401 跳登录）。SSE 用 `src/api/sse.ts`（fetch+ReadableStream，POST，不用 EventSource）。Mock 是 **Vite dev middleware**（`src/mock/plugin.ts` → `server.ts` 拦截 `/api/v1/*`，`apply:'serve'` 生产不打包），`VITE_USE_MOCK=false` 时走 Vite proxy / nginx 到真实后端。**改契约时两处都要同步**（api 模块 + mock server 路由）。

**SSE 流式核心**（难点）：
- `src/utils/sse-parser.ts`：`SseParser`（增量分帧）+ `SeqGuard`（seq 去重）+ `parseSseFrame`（容错丢帧）。
- `src/composables/useChatStream.ts`：状态机 `message_start→token→tool_call→tool_result(占位/回填)→…→done`；token 走 `utils/rAF.ts` 合并帧；`tool_result placeholder:true` 按 `job_ref` 定位卡片 + 看门狗超时；`interrupt` → `confirmInterrupt` → `POST /tasks/{id}/resume` 续流（复用 segments 不回滚）。**`confirmInterrupt` 缺 task_id 必须 fail-fast**，不得用 conversation_id 冒充。

**Markdown 安全管线**（`src/utils/markdown.ts`）：`markdown-it(GFM, html:false, hljs 高亮) → DOMPurify 白名单净化 → 后处理`（链接加 target/rel、任务列表补 `type=checkbox`）。LLM 输出视为不可信。流式期 `renderTextBare` 裸文本，`done` 后一次性 `renderMarkdown`。

**Store 边界**（`src/stores/`）：只存客户端状态，不复制服务端全量；列表从 API 查。Agent 列表单一数据源是 `agent` store（`chat` store 通过 `activeAgentId` getter 引用它，**不要**在 chat store 再存 agents）。

**路由守卫**（`src/router/guard.ts`）：`beforeEach` 先 `await hydrate()`（刷新后 token 回填）；`canAccess` 里**无 roles 限制的路由必须先返回 true 再判 role 是否为空**（否则 user 未加载时守卫死循环）。`/agents /tools /kb` → developer+；`/system /settings` → admin。

**类型**：`src/types/` 手工对齐 03/04，字段 **snake_case**；`SseEnvelope{id,seq,type,ts,payload}`。事件类型含监视器预留（`thinking` 等）与 mock 扩展 `notification`。

**设计令牌**：`src/styles/tokens.css`（深色侧栏 `--app-sidebar-bg:#1e1e2f`）+ `element-overrides.css`（主色 indigo `#6366f1`）。不启用 Element Plus 全局 dark（内容区保持浅色）。

## 关键易错点（踩过的坑）

- **Mock 在 Node 侧运行**：`src/mock/*` 里不能用 `import.meta.env`（用插件 `configResolved` 注入 `setMockFast`）；token 编码用 `Buffer` 而非 `btoa`（btoa 对中文抛异常）。
- **InterruptConfirmDialog 不要从 `@close` 再 emit confirm**——按钮 emit 一次即可，否则二次 resume 导致助手消息重复落库。
- **e2e 依赖 mock 确定性**：playwright `webServer` 用 `--mode e2e`（`VITE_MOCK_FAST=1` 零延迟）；不要用 `reuseExistingServer` 复用普通 dev server。
- **文本×工具卡混排**：流式期用 `StreamState.segments`（文本段唯一且置顶，工具卡在后）；刷新后从持久化 `Message.tool_calls[].position` 分组渲染（FD-12'，字符级插入点无法还原）。流式期与持久化布局一致（content 在前、tools 在后），done 后无跳位。
- 消息持久化在 mock 的 `doneEvent` 里 push 到 `messages[conv]`；新会话（conversation_id=null）由 mock server 先注册 conversation。

## 工作流约定（本机全局）

按任务规模定档（详见全局 CLAUDE.md）：**L1** 微小改动 → 简易笔记 + 快速 Test（豁免 Simplify）；**L2** 常规功能 → 轻量计划 + 完整流程；**L3** 大型复杂 → 强制完整三段流程。多步骤功能仍走 `explore-planner` 出计划 → `executor-debugger` 按账本执行（`progress.md`）→ 收尾 `review-test-simplify` 三道 gate。
