# Chat Composer 视觉优化执行计划

## Goal

在不改变聊天行为和前后端契约的前提下，统一 Chat/Workspace 输入区的视觉系统：卡片容器、textarea、上传/引用/模型/发送/停止控件、焦点态与移动端尺寸。

## Global constraints

- 只修改前端视觉相关代码与对应测试/文档。
- 保留现有 class、事件和组件接口；不改 API、mock、store 或流式状态机。
- 遵守项目响应式不变量：手机端页面不横向溢出，主要操作命中区至少 44px。
- 不删除用户已有未提交改动；显式选择文件进行检查和暂存。

## Tasks

### 1. 建立 composer 视觉契约与回归断言

Files:

- `docs/superpowers/specs/2026-08-30-chat-composer-polish-design.md`
- `e2e/chat-mobile.spec.ts` 或新增 `e2e/composer-style.spec.ts`

Interfaces:

- 断言 `.composer` 的卡片边界/圆角/阴影、textarea 的透明内框、桌面控件高度与移动端布局。

TDD:

- 先补充可稳定读取 computed style 和几何尺寸的 E2E 断言。
- 在样式落地后运行，确认测试从红转绿；避免绑定脆弱的完整颜色字符串。

### 2. 统一 Chat 与 Workspace composer 样式

Files:

- `src/views/ChatView.vue`
- `src/components/workspace/WorkspaceShell.vue`
- 如确有必要才调整 `src/styles/tokens.css`

Interfaces:

- 保持 `AttachmentUploader`、`ModelPicker`、`el-input` 和按钮的现有 props/events 不变。
- 通过现有 scoped CSS 的 `:deep` 规则统一 Element Plus 子节点；为发送/停止按钮补充语义 class 仅用于样式。

Implementation:

- composer 采用卡片边框、圆角、轻阴影和 `focus-within` 外环。
- textarea 去除默认内框并增加留白。
- 上传/引用/模型/发送/停止统一桌面 36px 高、圆角和间距；模型名称桌面保留，窄屏按现有规则收起。
- Workspace leading controls 与 Chat uploader 对齐；chips 和字符计数调整间距。
- 保留拖拽、禁用、loading 和 reduced-motion 状态。

### 3. 响应式与无障碍验证

Files:

- `src/views/ChatView.vue`
- `src/components/workspace/WorkspaceShell.vue`
- `e2e/chat-mobile.spec.ts`

Checks:

- 390×844、800×900、1440×900 下无页面级横向溢出。
- 手机端 textarea 仍独占一行，操作区在其下方，按钮和上传标签至少 44px。
- 键盘 focus-visible 清晰，上传标签可聚焦；不以颜色作为唯一状态信息。

### 4. 完整验证与收尾审查

Commands:

- `npm run typecheck`
- `npm run lint:check`
- `npm run test:unit`
- `npm run build`
- `E2E_PORT=5199 npm run test:e2e -- e2e/chat-mobile.spec.ts e2e/chat-stream.spec.ts`

Review:

- 运行 review-test-simplify 的 Test/Review/Simplify gate。
- 检查 diff 只包含本次 composer 视觉改动、测试和文档；不触碰既有交接/回滚改动。
