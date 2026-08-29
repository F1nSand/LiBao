# 进度账本 — plan: C:/Users/Admin1/Desktop/Agent/FrontEnd/docs/plans/2026-08-28-attachment-context-and-file-ref-fix.md

## 执行约定

- 本账本记录当前 FrontEnd 仓的执行状态；后端 Tasks 1–3 由后端 agent 在 `C:/Users/Admin1/Desktop/Agent/Agent` 自己的账本记录。
- 根目录 `progress.md` 是用户维护的前后端交接板，本轮只追加交接条目，不改写其历史内容。
- 每项只有在本轮实际运行验证命令并读取结果后才标记 complete。

## Tasks

- [complete] Task 1（后端）：契约与失败测试
- [complete] Task 2（后端）：统一来源准备、文档抽取与工作区安全读取
- [complete] Task 3（后端）：模型上下文注入与轻量引用持久化
- [complete] Task 4（前端）：请求、元数据与会话隔离失败测试
- [complete] Task 5（前端）：移除分析覆盖层并保留完整附件/引用状态
- [complete] Task 6（前端 mock）：附件与文件引用语义
- [in_progress] Task 7（联调）：真实后端、全量验证与收尾审查

## 记录

- 2026-08-28：建立账本；前端工作树已有用户未提交改动，保留不覆盖。
- 2026-08-28：Task 4 红测已运行：`npx vitest run src/components/business/AttachmentBubble.spec.ts src/components/workspace/WorkspaceShell.spec.ts`（提升权限；2 个断言按预期暴露元数据丢失与切会话不清理，AttachmentBubble spec 另有测试导入错误待修）。
- 2026-08-28：Task 4 complete；目标 Vitest（AttachmentBubble、WorkspaceFileRefPicker、WorkspaceShell、chat store、mock server）→ PASS；新增请求体、元数据、会话清理、picker 清选测试。
- 2026-08-28：Task 5 complete；`npm run typecheck` → PASS；`npm run test:unit` → PASS（39 files / 203 tests）；`npm run lint:check` → PASS（0 errors，3 个既有 any warnings）；`npm run build` → PASS。
- 2026-08-28：Task 6 complete；目标附件/工作区 E2E（E2E_PORT=5199）→ PASS（10/10）；全量 `npx playwright test --project=chromium`（E2E_PORT=5199）→ PASS（52/52）；`npx vitest run src/mock/server.spec.ts` → PASS（2 tests）。
- 2026-08-28：后端 Tasks 1–3 complete；后端提交 `b845ef9 feat(chat): inject document and workspace context`；目标 pytest → PASS（55 passed, 2 skipped）；`uv run ruff check` → PASS；`git diff --check b845ef9^ b845ef9` → PASS。
- 2026-08-28：Task 7 联调准备；新增 `e2e-real/backend.spec.ts` 的越界 `file_refs` 契约冒烟，待真实后端运行环境执行；前端与后端本地目标验证均已通过，收尾 gate 尚未执行。
- 2026-08-28：review gate 第一轮发现的工作区切换竞态、Picker 跨 workspace 节点、mock 分支/预算/校验和后端历史 hydrate/resume/缓存/TOCTOU 问题已修复；后端增量提交 `a441a50 fix(chat): isolate document context across resume turns`，目标 pytest → PASS（58 passed, 3 skipped），`uv run ruff check` → PASS。
- 2026-08-28：前端增量验证：定向 Vitest **23 passed**，完整 Vitest **39 files / 206 tests passed**；附件/工作区 E2E **11/11 passed**；typecheck、lint（0 errors，3 个既有 any warnings）、build 均通过。全量 E2E 将在最终前端变更收束后再跑一次。
- 2026-08-28：最终全量前端 E2E（E2E_PORT=5199）→ **53 passed**；真实后端 E2E → **3 passed, 1 blocked**：新增 file_refs 负向断言命中现有 8000 进程的旧 SSE 实现（返回 text/event-stream 而非 40015），其余健康、工作区 UI、真实 LLM 流均通过；需重启后端加载 a441a50 后重跑该用例。
- 2026-08-28：review-test-simplify gate：Test gate（Vitest/E2E/typecheck/build/lint）通过；Review gate 的 Important 问题已逐项修复并由后端 a441a50 覆盖回归；Simplify gate 收敛为共享 stopAll、工作区请求版本、Picker key 重建和 mock 单一来源预算 helper。剩余唯一外部阻塞是本机 8000 后端旧进程，非工作树代码失败。
