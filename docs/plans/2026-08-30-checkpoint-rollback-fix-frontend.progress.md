# 进度账本 — plan: docs/plans/2026-08-30-checkpoint-rollback-fix-frontend.md

> 本轮使用独立账本，保留仓库已有的历史 `progress.md` 不覆盖。

## 任务状态

- [complete] Task 1：扩展 SSE 类型与 Checkpoint Anchor 回调（commit `ff87707`；`npm exec -- vitest run src/composables/useChatStream.spec.ts` → 35 passed）
- [complete] Task 2：幂等回填普通会话乐观用户消息（commit `c87ed6c`；`npm exec -- vitest run src/stores/chat.spec.ts src/composables/useChatStream.spec.ts` → 42 passed）
- [complete] Task 3：为 WorkspaceShell 接通同一回滚流程（commit `f71b0b0`；`npm exec -- vitest run src/components/workspace/WorkspaceShell.spec.ts` → 9 passed）
- [complete] Task 4：将文字回滚按钮改为复制/回滚图标操作栏（commit 待提交；`npm exec -- vitest run src/components/business/MessageBubble.spec.ts` → 19 passed）
- [in_progress] Task 5：修复 Mouseleave 残留并保留键盘/触屏可达性
- [pending] Task 6：同步 Mock 契约与双入口 E2E
- [pending] Task 7：前端交付门禁与构建同步

## 验证记录

- Task 1：红测新增 2 项失败；实现后 `npm exec -- vitest run src/composables/useChatStream.spec.ts` → PASS，35 passed。
- Task 2：红测新增 3 项失败；实现后 Chat store/SSE 定向测试 → PASS，42 passed。Pinia reactive proxy 导致一次 `toBe` 断言误报，改为行为字段断言后通过。
- Task 3：红测接线缺失项按预期失败；测试桩调整后实现 WorkspaceShell 接线，`WorkspaceShell.spec.ts` → PASS，9 passed。
- Task 4：红测新增 7 项失败；实现图标操作栏、复制成功/失败提示后 `MessageBubble.spec.ts` → PASS，19 passed。
