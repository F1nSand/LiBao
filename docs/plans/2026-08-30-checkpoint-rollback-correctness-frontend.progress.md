# 进度账本 — plan: docs/plans/2026-08-30-checkpoint-rollback-correctness-frontend.md

> 本轮使用独立账本，保留仓库已有历史 `progress.md` 不覆盖。
> 旧 checkpoint 操作栏/首帧 anchor 提交是本轮的现有基线；本计划的 v2 契约消费、草稿恢复与模型选择优化仍按以下任务执行。

## 任务状态

- [completed] Task 1：冻结 API 类型和 Mock 契约
- [completed] Task 2：让默认 Both 成为真实选择并消除 Preview 竞态
- [completed] Task 3：统一草稿恢复和消息裁剪纯逻辑
- [completed] Task 4：普通会话应用权威草稿并清理流状态
- [completed] Task 5：WorkspaceShell 同步草稿、附件与文件引用
- [completed] Task 6：接通回滚操作的再次回滚和草稿保护
- [completed] Task 7：消除消息操作栏的隐藏占位
- [completed] Task 8：抽取共享 ModelPicker 并修复首次打开模型误显示
- [completed] Task 9：WorkspaceShell 接入模型选择并调整 composer 操作顺序
- [completed] Task 10：双入口端到端验收

## 执行记录

- 2026-08-30：用户批准前端修订计划；后端 `checkpoint-restore-v2` 仍由后端 Agent 管理，真实联调在后端契约就绪后执行。
- 2026-08-30：确认模型初始误显示根因：`ChatView.vue` 仅在首次打开 popover 时调用 `getActiveProvider()`，页面挂载时未加载 active provider。
- 2026-08-30：确认 WorkspaceShell 当前 composer 顺序为 `AttachmentUploader → textarea → 引用 → 停止/发送`，本轮目标为 `选择文件 → 引用` 左侧、`选择模型 → 停止/发送` 右侧。
- 2026-08-30：Task 1 完成：类型、restore preview/execute API、Mock v2 路由与 3 条契约单测已对齐；Mock 单测 14/14 通过。
- 2026-08-30：Task 2 完成：CheckpointRestoreDialog 默认 `both` 真实加载并可直接确认；请求版本、client_request_id、目标与模式均做过期响应隔离；对话框单测 4/4 通过。
- 2026-08-30：Task 3 完成：抽取消息裁剪、草稿转换、composer fingerprint 纯逻辑，并接入 ChatStore；相关单测 10/10 通过。
- 2026-08-30：Task 4 完成：普通会话按后端 `conversation.action` 应用权威草稿，回滚/撤销时清理流代次；useChatStream 单测 37/37 通过。
- 2026-08-30：Task 5 完成：WorkspaceShell 同步消息裁剪、正文、附件与 `file_refs`，不可用附件阻止发送并保留可移除状态；WorkspaceShell 单测 10/10 通过。
- 2026-08-30：Task 6 完成：接入 rollback operation-before 撤销入口，按指纹保护已编辑草稿，并在确认前禁止关闭/切换模式等竞态操作。
- 2026-08-30：Task 7 完成：消息操作栏改为不占用隐藏态布局空间，桌面保留 hover/focus，触屏命中区不小于 44px。
- 2026-08-30：Task 8 完成：抽取共享 ModelPicker；挂载即加载 active provider，期间显示 `加载中…`，显式空配置才显示 `未配置`，延迟响应不会覆盖用户切换。
- 2026-08-30：Task 9 完成：Workspace composer 调整为 `选择文件 → 引用 | 输入 | 选择模型 → 停止/发送`，复用 ModelPicker 并保留移动端两行布局。
- 2026-08-30：Task 10 完成：checkpoint restore E2E 8/8 通过；此前受影响的 model-picker/workspace/chat-mobile E2E 17/17 通过；完整单测最终 47 个文件、291/291 通过。
- 2026-08-30：质量修正：代码审查发现预览/执行期间“取消”按钮未同步禁用，已补齐禁用条件与测试；同时清除 ModelPicker 成功激活后的陈旧错误提示。
- 2026-08-30：提交前尝试 `git commit -S --signoff`，因本机 GPG 缺少 `F1nSand <391919054@qq.com>` 私钥而未创建提交；HEAD 保持不变，改动保留在 Git 暂存区。
