# 进度账本 — plan: docs/plans/2026-09-03-mcp-management-search.md

## 本次执行范围

用户已确认继续执行已批准规格；本轮完成计划 Task 1、Task 3、Task 4、Task 5、Task 5.5 和 Task 6。Task 2（工具搜索）已在上一轮完成，不重复修改。

## 状态

- Task 1: complete（后端默认启用、MCP 响应脱敏；全量回归通过）
- Task 2: complete（上一轮已完成）
- Task 3: complete（前端 MCP 类型/API）
- Task 4: complete（MCP store/管理页）
- Task 5: complete（设置导航与 mock 生命周期）
- Task 5.5: complete（工具批量启停与原地更新）
- Task 6: complete（测试、构建、E2E、审查）
- Task 7: complete（工具页 MCP 分类、三类筛选与 E2E 验收）

## 已确认根因

- `tool_search` 将整段多关键词查询作为单一连续子串匹配。
- 当前本地数据含目标 MCP 工具；隔离复现中 `apify 爬取网页 crawl scrape` 返回 0 条，`apify` 返回 12 条。
- 现有 `tests/test_tool_search.py` 13 项全部通过，但只覆盖单关键词，没有多关键词回归用例。

## 验证记录

- 基线：`uv run pytest tests/test_tool_search.py -q` → PASS（13 passed），说明现有测试存在覆盖缺口。
- RED（Agent）：新增真实多关键词用例后单独运行 → FAIL，`matches` 为空。
- GREEN（Agent）：接入共享关键词匹配器后单独运行 → PASS（1 passed）。
- RED（REST）：新增 `ToolService.search` 多关键词用例后单独运行 → FAIL，返回空列表。
- GREEN（REST）：repository 接入共享匹配器后单独运行 → PASS（1 passed）。
- 搜索相关回归：`uv run pytest tests/test_tool_search.py tests/test_tool_service.py -q` → PASS（32 passed）。
- MCP 回归：`uv run pytest tests/test_mcp_api.py tests/test_mcp_sync.py -q` → PASS（20 passed）。
- 最终聚焦回归：四个受影响测试文件 → PASS（52 passed）。
- 后端全量回归：`uv run pytest -q` → PASS（778 passed, 4 skipped；40 条既有弃用告警）。
- 静态检查：本轮 5 个 Python 文件运行 Ruff → PASS。
- 差异检查：`git diff --check` → PASS（仅现有 Windows CRLF 提示）。
- 真实目录重放：此前返回空数组的 `apify ...`、`fetch_url ...`、`web search ...` 均返回目标工具；首项分别为 `firecrawl_firecrawl_scrape`、`fetch_url`、`web_search`。

## 收尾审查

- 保留 `selected_names` 对 `enabled` 的过滤，未改变工具可执行权限。
- Agent runtime 与 REST/Web 搜索共用无依赖匹配器，避免两处语义漂移。
- 空白查询返回空列表；无命中提示和异常时全目录降级保持不变。
- 当前环境无可调用的 `/verify`、`/code-review`、`/simplify` 命令；以 mock E2E、完整测试、Ruff、差异检查和人工 review 作为替代。审查修正了 MCP 默认启用注释与 mock 关联工具清理，未发现待处理问题。
- 提交尝试：`git add` 因当前环境 `.git/index` 只读而被拒绝；未创建提交，且未成功暂存任何文件。代码改动保留在工作区。
- Task 7 RED：`npm run test:unit -- --run src/utils/tool-category.spec.ts src/views/ToolsView.spec.ts` → 1 个组件断言失败，分类模块尚不存在。
- Task 7 GREEN：同一命令 → PASS（6 passed）。
- Task 7 E2E：`npm run test:e2e -- e2e/tools-meta.spec.ts`（E2E_PORT=5199）→ PASS（2 passed）。
- Task 7 全量前端单元：`npm run test:unit -- --reporter=dot` → PASS（52 files, 313 tests）。
- Task 7 收尾静态检查：`npm run typecheck`、`npm run lint:check`、`npm run build` → PASS；仅保留项目既有 warning。

## 本轮执行记录

- Task 1 RED：`uv run pytest tests/test_mcp_api.py tests/test_tool_service.py -q` → 6 failed, 26 passed。
- Task 1 GREEN：同一命令 → PASS（32 passed）。
- Task 1 同步回归：`uv run pytest tests/test_mcp_sync.py -q` → PASS（6 passed）。
- 前端聚焦回归：`npm run test:unit -- --run src/mock/server.spec.ts src/views/ToolsView.spec.ts src/views/McpView.spec.ts` → PASS（22 passed）。
- 前端全量单元：`npm run test:unit -- --reporter=dot` → PASS（51 files, 310 tests）。
- 前端静态检查：`npm run typecheck` → PASS；`npm run lint:check` → PASS（4 条既有 warning，无 error）。
- 后端完整回归：`uv run pytest -q` → PASS（779 passed, 4 skipped；40 条既有弃用告警）。
- 前端生产构建：`npm run build` → PASS（Vite build 完成；2 条依赖注释 warning）。
- mock E2E：`npm run test:e2e`（E2E_PORT=5199）→ PASS（74 passed）。
- MCP 分类实现后的全量 E2E：`npm run test:e2e`（E2E_PORT=5199）→ PASS（75 passed）。
- 收尾修正后差异检查：`git diff --check` → PASS（仅现有 Windows CRLF 提示）。
