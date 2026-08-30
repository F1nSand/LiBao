# 进度账本 — plan: docs/plans/2026-08-30-checkpoint-rollback-fix-frontend.md

> 本轮使用独立账本，保留仓库已有的历史 `progress.md` 不覆盖。

## 任务状态

- [complete] Task 1：扩展 SSE 类型与 Checkpoint Anchor 回调（commit `ff87707`；`npm exec -- vitest run src/composables/useChatStream.spec.ts` → 35 passed）
- [complete] Task 2：幂等回填普通会话乐观用户消息（commit `c87ed6c`；`npm exec -- vitest run src/stores/chat.spec.ts src/composables/useChatStream.spec.ts` → 42 passed）
- [complete] Task 3：为 WorkspaceShell 接通同一回滚流程（commit `f71b0b0`；`npm exec -- vitest run src/components/workspace/WorkspaceShell.spec.ts` → 9 passed）
- [complete] Task 4：将文字回滚按钮改为复制/回滚图标操作栏（commit `8d59c3c`；`npm exec -- vitest run src/components/business/MessageBubble.spec.ts` → 19 passed）
- [complete] Task 5：修复 Mouseleave 残留并保留键盘/触屏可达性（commit `dceccd8`；组件 20 passed；Chromium E2E 3 passed）
- [complete] Task 6：同步 Mock 契约与双入口 E2E（commit `251816c`；mock 11 passed；checkpoint Chromium E2E 6 passed）
- [in_progress] Task 7：前端交付门禁与构建同步（源码门禁完成；`frontend_dist` 同步待归属确认）

## 验证记录

- Task 1：红测新增 2 项失败；实现后 `npm exec -- vitest run src/composables/useChatStream.spec.ts` → PASS，35 passed。
- Task 2：红测新增 3 项失败；实现后 Chat store/SSE 定向测试 → PASS，42 passed。Pinia reactive proxy 导致一次 `toBe` 断言误报，改为行为字段断言后通过。
- Task 3：红测接线缺失项按预期失败；测试桩调整后实现 WorkspaceShell 接线，`WorkspaceShell.spec.ts` → PASS，9 passed。
- Task 4：红测新增 7 项失败；实现图标操作栏、复制成功/失败提示后 `MessageBubble.spec.ts` → PASS，19 passed。
- Task 5：红测复现 mouseleave 的 `focus-within` 残留与触屏按钮尺寸失败；改用 `:has(:focus-visible)`、触屏常显和 44×44 命中区后，组件 → PASS，20 passed；`checkpoint-rollback.spec.ts` → PASS，3 passed。
- Task 6：红测复现普通会话/WorkspaceShell 首帧缺少 checkpoint；mock 将已落库用户消息锚点注入 `message_start`，完整 checkpoint E2E → PASS，6 passed；`server.spec.ts` → PASS，11 passed。
- Task 7 Test gate：`npm run typecheck` → PASS；`npm run test:unit` → 43 files / 273 tests passed；`npm run lint:check` → 0 errors（3 个既有 `no-explicit-any` warnings）；`npm run build` → PASS；`checkpoint-rollback.spec.ts` Chromium → 6 passed。
- Task 7 Review/Simplify gate：变更差异 `git diff --check` → PASS；未发现旧 `.rollback-trigger` 或本轮交互的鼠标 `:focus-within` 残留，契约字段与 mock/replay 路径已对齐；未发现需要修复的 correctness/security/performance 或不必要复杂度问题。
- Task 7 产物边界：后端 `frontend_dist` 在本轮开始前已有大量删除/新增未提交文件，后端计划要求不得手工覆盖；本轮未修改，待确认归属后再执行构建产物同步。
