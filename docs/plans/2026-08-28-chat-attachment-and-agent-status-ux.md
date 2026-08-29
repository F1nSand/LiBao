# 对话附件气泡与 Agent 运行状态优化计划

**目标：** 修复纯附件消息产生空文字气泡、重做文件附件卡片，并让停止操作真正取消 Agent 任务、实时显示可理解的运行阶段。

## 已确认根因与边界

- `MessageBubble.vue` 无条件渲染 `.user-text`；正文为空时仍产生深色背景。
- `AttachmentBubble.vue` 文件卡过小且没有可访问的预览/下载入口。
- `useChatStream.stop()` 只断开浏览器 SSE，不更新运行状态；真实后端断流后仍会继续运行并落库。
- 本轮“停止”指用户点击停止按钮，不等同于需要人工确认的 `interrupt`；二者分别显示“已中断”和“等待确认”。
- 工作区 `file_refs` chip 不重做，本轮视觉优化范围是上传附件卡。

## 1. 取消协议与流状态

### 后端

- 每次 `/chat/stream` 创建并置为 `running` 的 Task，`message_start.payload` 返回 `task_id`。
- 聊天 graph producer 注册到按 Task ID 管理的可取消运行表；复用现有 `POST /api/v1/tasks/{id}/cancel`。
- interrupt/resume 复用同一 Task，不能重复创建。
- cancel、done、failed 采用单向终态；`on_final` 在提交前重新检查 Task 未被取消，避免 cancel/done 竞态把 cancelled 覆盖为 done。
- 取消后不落库未封口的半段助手回复；前端当前页面保留已经流出的内容并停止流式光标。
- 取消失败保持 SSE 和原运行阶段，提示“中断失败，任务仍在运行”；`40902` 作为自然完成竞态处理。

### 前端

在 `StreamState` 增加标准化展示字段，保留原始 `status` 兼容既有消费者：

```ts
type AgentRunPhase =
  | 'idle' | 'starting' | 'running' | 'thinking' | 'tool' | 'delegating'
  | 'responding' | 'finalizing' | 'waiting_confirm' | 'cancelling'
  | 'cancelled' | 'done' | 'failed'

interface StreamState {
  phase: AgentRunPhase
  phaseDetail: string | null
  cancelling: boolean
}
```

事件映射：`starting` 正在启动、`running` 处理中、`thinking` 思考中、`tool` 正在调用工具、`delegating` 子 Agent 处理中、`responding` 生成回复、`finalizing` 整理回复、`waiting_confirm` 等待确认、`cancelling` 正在中断、`cancelled` 已中断、`done` 已完成、`failed` 运行失败。工具名/Agent 名最多展示 24 个字符，完整值放 `title`。

新增 `AgentRunStatus.vue`，Chat 和 Workspace 共用：工具栏中显示紧凑状态胶囊，运行阶段用 0.9s linear 环形点旋转，状态切换使用 160ms `var(--ease-out)` 淡入；终态静态显示。动效只使用 `transform/opacity`，精细指针 hover 才启用，`prefers-reduced-motion: reduce` 时关闭旋转与位移；组件提供 `role="status"`、`aria-live="polite"`。

## 2. 消息与附件视觉

- `.user-text` 只在 `message.content.trim()` 非空时渲染；纯图片、纯文件、纯引用不产生空气泡；空白正文同样不渲染。
- 文本与附件并存时保持附件在上、正文在下，间距 8px。
- 普通文件卡：桌面宽度 300px、最小高度 76px、44×44px 图标区、14px 文件名、12px 类型/大小信息、最多两行省略；整卡为可键盘聚焦链接，浏览器可预览的文件新页打开，其它格式自然下载，右侧显示打开/下载图标。
- 图片卡调整为 220×150px，并显示文件名；继续使用现有图片灯箱预览。
- 卡片使用现有主题令牌、圆角和阴影；hover 仅做 160ms、`translateY(-1px)` 的轻微反馈；移动端不得造成横向溢出。

## 3. 实施任务与文件责任

### Task 1：红测与交接

- 前端新增/修改 `MessageBubble.spec.ts`、`AttachmentBubble.spec.ts`、`AgentRunStatus.spec.ts`、`useChatStream.spec.ts`：覆盖空正文、卡片语义、阶段映射、停止状态。
- 后端新增聊天 Task 创建、producer 取消、cancel/done 竞态和取消后下一任务可运行的失败测试。
- 在 `progress.md` 追加后端交接版，内容见本计划末尾。

### Task 2：后端真实取消

- 修改 `app/api/routers/chat.py`、`app/orchestration/chat_stream.py`、`app/orchestration/stream_core.py`、`app/orchestration/task_worker.py`、Task service。
- 更新 `docs/03-api-contract.md`，补充 `message_start.task_id` 与聊天 Task 生命周期。
- mock 增加 cancel 路由和活动 Task 记录，保持 SSE 取消测试确定性。

### Task 3：前端状态胶囊与停止流程

- 修改 `src/composables/useChatStream.ts`：事件转 phase，`stop()` 异步单飞调用 cancel API，取消成功后清理本地流和活跃工具卡；`stopAll()` 保持卸载/切换专用的静默清理。
- 新增 `src/components/common/AgentRunStatus.vue`，替换 `ChatView.vue` 与 `WorkspaceShell.vue` 中的字符串 `StatusTag`。
- 补充老后端无 `task_id`、取消失败和 `40902` 竞态的兼容行为。

### Task 4：空泡与附件卡

- 修改 `src/components/business/MessageBubble.vue` 与 `src/components/business/AttachmentBubble.vue`，实现条件正文渲染、放大卡片、文件 URL、键盘操作、图片尺寸和 reduced-motion/hover 样式。
- 修改对应单测与 `e2e/attachment-context.spec.ts`；Chat/Workspace 两入口复用同一验收场景。

### Task 5：收尾

- 更新 `docs/02-frontend-design.md` 的附件卡与运行状态说明。
- 后端目标 pytest、全量 pytest、ruff；前端 typecheck、lint、unit、build、全量 E2E、真实后端 E2E。
- 运行 review-test-simplify 三道 gate，完成后将交接条目由 `[open]` 改为 `[done]` 并附提交与测试证据。

## 4. 验收场景

- 纯附件/图片/工作区引用消息无空深色气泡；文本+附件仍正常显示。
- 文件卡在 390×844、800×900、1440×900 下可读、可聚焦、可预览/下载且无页面横向滚动。
- SSE 依次产生 thinking、tool_call、token、finalizing 时状态文案同步变化；运行阶段有动效，完成/失败/等待确认/已中断静态。
- 点击停止立即显示“正在中断”，取消接口成功后显示“已中断”、停止按钮消失、发送恢复；后台不会继续生成迟到最终回复。
- 取消失败、无 task_id、取消与 done 竞争均不显示虚假的“已中断”。
- 已产生的半段回复当前页面保留且不显示流式光标；刷新只显示服务端已封口内容。
- reduced-motion 下不存在持续旋转或位移动效。

## 后端交接版（执行时追加到 progress.md）

> [done] 2026-08-28 · →后端 | **聊天停止升级为真实任务取消** | 已完成：每次 `/chat/stream` 创建并复用同一 Task，`message_start` 返回 `task_id`；聊天 graph producer 注册到可取消运行表，`POST /tasks/{id}/cancel` 真正中断图；取消与 done/failed 采用终态守卫，取消后不触发迟到 `on_final`；interrupt/resume 复用同一 `task_id`。验证：后端 Ruff 全绿，取消/聊天流定向回归 17 passed，后端全量 651 passed / 3 skipped；前端 typecheck、unit 40 files/214 tests、build、Playwright 55 tests 均通过。

## 已锁定选择

- 停止是真正取消，不增加二次确认。
- 取消成功显示“已中断”；已有半段回复保留在当前页面。
- 状态采用“阶段 + 当前动作”的紧凑胶囊，不建设详情弹层。
- 文件卡整卡可点击；图片灯箱、普通文件新页预览或下载。
