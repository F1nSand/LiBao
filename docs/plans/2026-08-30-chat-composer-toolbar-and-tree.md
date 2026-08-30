# Chat Composer 工具栏与文件树优化执行计划

**Goal:** 在不改变业务契约和消息交互的前提下，将 Chat/Workspace 输入区改为“上方输入、下方左右工具栏”，并确保长文件名不会挤出文件树行尾操作。

**Architecture:** 保留现有 ChatView、WorkspaceShell、AttachmentUploader、ResourceManager 的事件和 API 边界。通过共享 `src/styles/composer.css` 负责 composer 的布局与视觉，通过 AttachmentUploader 调整“+ 添加文件”入口及键盘语义；ResourceManager 只调整树行布局和操作按钮可用性。

**Global Constraints:**

- 只修改前端视觉、交互可达性、对应 E2E 测试和本轮文档；不改 API、mock、store、路由、后端契约。
- 保留现有 AttachmentUploader、ModelPicker、引用、发送、停止的 props、事件、状态和请求行为。
- 遵守项目响应式不变量：手机端页面不横向溢出，主要操作命中区至少 44px。
- 保留用户已有未提交改动，不使用 reset/checkout 覆盖无关文件；只检查和修改本计划列出的文件。
- 所有代码修改使用 `apply_patch`，验证命令必须在本轮实际运行后才能记录为通过。
- 不展示 composer 字符计数，但保留 `maxlength` 与发送前的输入/附件/引用校验。

---

## Task 1: 建立布局、按钮和文件树回归断言

**Files:**

- Modify: `e2e/composer-style.spec.ts`
- Modify: `e2e/workspace.spec.ts`

**Interfaces:**

- Consumes: 当前 `.composer-input`、`.composer-leading`、`.composer-actions`、`.upload-btn`、`.model-btn`、`.rm-node-name`、`.rm-more` DOM 约定。
- Produces: 供实现阶段验证的结构顺序、边框、hover、移动端尺寸与长名称操作栏几何断言。

- [ ] Step 1: 在 `composer-style.spec.ts` 中先添加 Chat/Workspace 的结构断言：textarea 位于 `.composer-input` 第一层，`.composer-toolbar` 位于第二层；Workspace leading 子元素按 `.uploader`、`.composer-divider`、引用按钮顺序；actions 子元素按 `.model-btn`、`.composer-submit`/`.composer-stop` 顺序。
- [ ] Step 2: 在同一文件添加 computed style 断言：`.composer .el-button`、`.composer .upload-btn` 的边框为 none；`.composer-divider` 可见；桌面和 390px 移动视口下控件高度分别不低于 36px 和 44px，composer `scrollWidth <= clientWidth`。
- [ ] Step 3: 在 `workspace.spec.ts` 文件树菜单用例中创建名称至少 80 个字符的文件，hover 对应行后读取 `.rm-node-name` 和 `.rm-more` 的矩形，断言名称发生收缩/省略、操作入口宽度至少 28px 且 `right <= row.right + 1`，然后点击入口确认菜单仍可打开。
- [ ] Step 4: 运行新增/修改的 E2E，确认实现前断言失败且失败原因仅为尚未实现的 DOM 结构或样式。

## Task 2: 重排 Chat 与 Workspace composer

**Files:**

- Modify: `src/views/ChatView.vue`
- Modify: `src/components/workspace/WorkspaceShell.vue`
- Modify: `src/styles/composer.css`

**Interfaces:**

- Consumes: `AttachmentUploader` 的 `add` 事件、`ModelPicker` 现有组件、`currentStream.streaming/cancelling` 状态与既有发送/停止 handlers。
- Produces: `.composer-input > .composer-textarea`、`.composer-input > .composer-toolbar`；toolbar 内 `.composer-leading` 与 `.composer-actions` 的稳定 DOM 顺序。

- [ ] Step 1: 将 Chat composer 的 textarea 移到 `.composer-input` 第一层，在下方新增 `.composer-toolbar`；将 `AttachmentUploader` 放入左侧 `.composer-leading`，将 ModelPicker 与发送/停止按钮保留在右侧 `.composer-actions`。
- [ ] Step 2: 将 Workspace composer 按相同结构重排；左侧 `.composer-leading` 内按上传入口、`.composer-divider`、引用按钮排列，右侧只保留 ModelPicker 与发送/停止按钮。
- [ ] Step 3: 在共享 CSS 中把 `.composer-input` 改为纵向布局；新增 toolbar 左右分组、浅色 `|` 分隔符、无边框普通按钮 hover 背景、无边框语义按钮样式；保留 textarea、拖拽、disabled、loading、focus-visible 和 reduced-motion 规则。
- [ ] Step 4: 运行 `npx playwright test e2e/composer-style.spec.ts e2e/workspace.spec.ts`，确认布局/样式/原有工作区交互通过。

## Task 3: 将上传入口变为可访问的“+ 添加文件”

**Files:**

- Modify: `src/components/business/AttachmentUploader.vue`
- Modify: `e2e/composer-style.spec.ts`

**Interfaces:**

- Consumes: `doUpload(file: File)`、`uploadAttachment`、`add` emit 和 `defineExpose({ upload })`，接口签名不变。
- Produces: `.upload-btn` 的 `+` 图标、`aria-label="添加文件"`、键盘 Enter/Space 触发文件选择，现有上传进度和拖拽行为不变。

- [ ] Step 1: 在上传入口 E2E 中断言 accessible name 为“添加文件”，并断言 `+` 图标入口位于 toolbar 左侧。
- [ ] Step 2: 为 hidden input 增加模板 ref；增加只处理 Enter/Space 的键盘 handler，让 label 获得 `role="button"`、`tabindex="0"` 和清晰 aria 文案。
- [ ] Step 3: 将 Paperclip 图标和“上传附件”提示改为 Plus 图标和“添加文件（≤20MB）”，不修改上传 API、校验、进度或 emit。
- [ ] Step 4: 运行 `npx playwright test e2e/composer-style.spec.ts e2e/attachment-context.spec.ts`，确认入口文案、附件上传上下文和已有行为通过。

## Task 4: 固定文件树行尾操作栏

**Files:**

- Modify: `src/components/workspace/ResourceManager.vue`
- Modify: `e2e/workspace.spec.ts`

**Interfaces:**

- Consumes: Element Plus `el-tree` scoped slot、`el-dropdown` command 分派和现有 `onMenu(cmd, data)`。
- Produces: 可键盘操作的 `.rm-more` button、稳定的固定宽度操作栏、名称省略和不溢出行的 CSS。

- [ ] Step 1: 将更多操作 slot 从不可聚焦的 span 改为 `type="button"`、`aria-label="更多操作"` 的 button，保留 `@click.stop`、dropdown menu 和 command 行为。
- [ ] Step 2: 为 tree content、node、name 与 dropdown 根节点补充 `min-width: 0`、`overflow: hidden` 和固定 action rail；为 `.rm-more` 设置 28px 固定宽高、居中、无边框透明背景、hover/focus-visible 状态。
- [ ] Step 3: 运行 `npx playwright test e2e/workspace.spec.ts`，确认超长文件名下菜单仍可打开，既有新建/重命名/删除流程通过。

## Task 5: 完整验证与收尾审查

**Files:**

- Modify: `docs/plans/2026-08-30-chat-composer-toolbar-and-tree.progress.md`

**Interfaces:**

- Consumes: Task 1–4 的实现和验证结果。
- Produces: 本轮独立进度账本、完整命令结果与未解决的既有问题记录。

- [ ] Step 1: 运行 `npm run typecheck`。
- [ ] Step 2: 运行 `npm run lint:check`。
- [ ] Step 3: 运行 `npx vitest run --no-file-parallelism`，必要时单独运行受影响组件测试。
- [ ] Step 4: 运行 `npm run build`。
- [ ] Step 5: 运行 `E2E_PORT=5199 npm run test:e2e -- e2e/composer-style.spec.ts e2e/chat-mobile.spec.ts e2e/chat-stream.spec.ts e2e/attachment-context.spec.ts e2e/workspace.spec.ts`；PowerShell 下使用 `$env:E2E_PORT='5199'; npm run test:e2e -- ...`。
- [ ] Step 6: 执行 `git diff --check`，人工审查 diff 仅覆盖本轮列出的前端文件、测试与文档；记录任何既有并发 Vitest/构建 warning，不擅自扩大范围修复。
