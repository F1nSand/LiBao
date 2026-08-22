# Agent 平台 · Web 前端工作台

通用 Agent 平台的管理控制台（Vue 3 + Vite 5 + TypeScript + Pinia + Element Plus），
按 `docs/02-frontend-design.md`（前端蓝本）与 `docs/03-api-contract.md`（唯一协议依据）实现。

**功能**：对话工作台（SSE 流式 + 工具调用 + 中断确认）· 工作区 · 工具管理 · 技能 · 知识库 · 记忆 · 系统监控 · 设置（**单用户本地模式，无登录/无 RBAC**）。

## 快速开始

```bash
npm install
npm run dev          # http://localhost:5173，默认启用内置 Mock
```

单用户本地模式：固定 admin，无登录页、无多角色（`dev/dev123`、`viewer/viewer123` 已随 RBAC 删除）。

## 脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | Vite dev server（含内置 mock） |
| `npm run build` | `vue-tsc --noEmit && vite build`（生产构建） |
| `npm run typecheck` | 类型检查 |
| `npm run lint` | ESLint（flat）+ Prettier |
| `npm run test:unit` | Vitest 单测 |
| `npm run test:e2e` | Playwright e2e（自动以 `--mode e2e` 启动 dev） |
| `npm run preview` | 预览生产构建产物 |

## 内置 Mock 适配层

后端尚未实现时，前端按 03 契约走**真实调用**，由 Vite middleware 拦截 `/api/v1/*` 模拟：
REST 统一信封、SSE 事件流（`message_start → token → tool_call → tool_result(占位/回填) → interrupt → done`）。
可本地演示：流式打字、工具调用确认/拒绝、异步占位回填、任务事件回放、通知推送。

**环境变量**（`.env.*`）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `VITE_USE_MOCK` | `true` 启用 mock；`false` 走代理到后端 | dev 为 `true`，prod 为 `false` |
| `VITE_MOCK_FAST` | `1` 时 mock 的 SSE 延迟归零（e2e 确定性） | 空 |
| `VITE_API_PROXY` | `VITE_USE_MOCK=false` 时 `/api` 代理目标 | `http://localhost:8000` |

### 切换到真实后端

1. 本地联调：`VITE_USE_MOCK=false npm run dev`（或改 `.env.development`），`/api` 会代理到 `VITE_API_PROXY`。
2. 生产（本地单机化）：`.env.production` 已设 `VITE_USE_MOCK=false`；`npm run build` 产物由 FastAPI 静态托管（见根目录《本地单机化改造方案.md》），`/api/v1` 同源；后端需 SPA catch-all 支持深链刷新（交接板）。

## 流式渲染要点（docs/02 §5）

- SSE 用 `fetch + ReadableStream`（POST 支持 body），不用 EventSource（单用户模式无鉴权头）。
- 事件信封 `{id, seq, type, ts, payload}`，`seq` 单调递增去重。
- 流式期显示裸文本（打字机，rAF 合并帧），`done` 后一次性 Markdown 渲染。
- 渲染管线固定 `DOMPurify 白名单净化 → markdown-it(GFM) → highlight.js`，LLM 输出视为不可信内容。
- 工具调用：`tool_call` 建卡 → `tool_result placeholder:true` 显示"处理中" → 同 `job_ref` 回填；`interrupt` 触发确认弹窗 → `POST /tasks/{id}/resume` 续流。
- 刷新后消息从 `GET /conversations/{id}/messages` 拉取并渲染为 Markdown。

## 目录结构

```
src/
├── api/          # http.ts(信封) · sse.ts(fetch-SSE) · 各资源模块
├── mock/         # Vite middleware mock（plugin/server/db/stream/util）
├── stores/       # Pinia：chat/kb/memory/skill/system/tool/trajectory/workspace
├── router/       # 路由（无守卫，单用户直访）
├── views/        # 10 个视图（无登录页）
├── components/   # layout/ · common/（MarkdownRenderer/JsonViewer/StatusTag…）· business/
├── composables/  # useChatStream/useSSE/useTaskPoll/useVirtualList
├── types/        # 与 03/04 契约对齐的 TS 类型（snake_case）
├── utils/        # sse-parser/http-envelope/rAF/markdown/format
└── styles/       # 设计令牌 + Element Plus 覆盖 + markdown
```

## 测试

- 单测：`npm run test:unit`（SSE 解析、useChatStream 状态机、Markdown 渲染 XSS、http 信封、可用性降级等）。
- e2e：`npx playwright install chromium` 后 `npm run test:e2e`（直访 /chat → 流式 → 工具确认 → 中断拒绝 → 工作区/轨迹/滚动）。
