# LiBao 无 Nginx 跨平台兼容实施计划

**Goal:** 删除 LiBao 的全部运行时 Nginx 依赖，使源码、开发链路和发布包在 Windows 与 Linux 上均可安装、测试和启动，并永久维持本地单用户产品边界。

**Architecture:** 开发环境继续由 Vite 在 `127.0.0.1:5173` 提供页面，并仅在关闭 Mock 时把同源相对路径 `/api` 代理到本地 FastAPI；这属于开发服务器能力，不是生产反向代理。发布环境只启动 FastAPI：它在 `127.0.0.1:8000` 提供 `/api/v1`、SSE 和 `backend/frontend_dist` 中的 SPA，因此不需要 Nginx、CORS、独立前端生产服务器或公网入口。

**Global Constraints:**

- Windows 和 Linux 都是必须通过 CI 的受支持平台；macOS 复用 POSIX 脚本但暂不作为强制 CI 门禁。
- 后端固定绑定 `127.0.0.1`，前端开发服务器固定绑定 `127.0.0.1`，不增加 `0.0.0.0` 默认值。
- 项目永久定位为本地个人单用户应用；保留固定 `admin`，不设计注册、登录、租户隔离、多用户权限或公网部署。
- 开发环境使用 Vite `/api` 代理；发布环境由 FastAPI 同源托管 SPA 和 API，不增加 CORS。
- Mock 仅用于单元测试和 Mock E2E；`scripts/dev.*` 与 DevPanel 默认连接真实本地后端。
- 保留 `app.api.main:app`、`create_app()`、REST 路由、SSE 事件字段和 `~/.LiBao` 数据格式。
- 保留当前工作树中 5 个未提交文件，不执行 `git reset --hard`、`git clean`、覆盖式还原或隐式丢弃：`.github/workflows/ci.yml`、`apps/backend/app/orchestration/chat_stream.py`、`apps/backend/app/orchestration/checkpointer.py`、`apps/backend/tests/test_chat_stream.py`、`apps/backend/tests/test_json_file_saver.py`。
- 本计划执行期间只修改本地工作树；未经用户再次明确授权，不 commit、push、更新 PR 或 merge。

---

## 已确认的现状

1. 跟踪中的 Nginx 只有 `deploy/nginx/nginx.conf` 和 `deploy/nginx/README.md`；没有 Nginx 安装脚本、服务、容器或系统服务。
2. `scripts/build-release.py` 和 CI 仍把 `deploy/nginx/nginx.conf` 当作发布包必需文件，删除目录时必须同步修改。
3. `apps/backend/app/api/factory.py` 已有 `SPAStaticFiles`，发布包也已把前端构建物复制到 `backend/frontend_dist`，因此 FastAPI 可以成为唯一生产入口。
4. 前端 Axios、SSE 和附件链接使用相对 `/api/v1`；后端没有 CORS。开发时必须保留 Vite 代理，否则 `:5173` 页面无法请求 `:8000`。
5. `Settings.frontend_dist` 当前是相对路径，是否托管 SPA 取决于启动时的当前工作目录。
6. 根脚本已成对提供 `.cmd`/`.sh`，但实现重复；CI 全部运行在 Ubuntu，不能证明 `.cmd`、`npm.cmd`、Windows 路径和发布包能工作。
7. `E2E_BACKEND_URL` 使用非 8000 端口时，Python runner 仍启动 8000，且未把该地址传给 Vite 的 `VITE_API_PROXY`。
8. 当前聊天恢复 WIP 只覆盖 `task is None`。真实 `/chat/stream` 总会创建 Task；`db.rollback()` 会重载 FileTable，使闭包中的旧 `conversation` 对象脱离存储表。
9. 当前 `JsonFileSaver.get_tuple()` WIP 可能让“失败后成功”的线程仍回退到历史错误之前，需要补契约测试后再定实现。
10. Security job 的首次错误已确认与 PR gitleaks token 有关；最新失败必须以 Actions step 日志为准，不能用宽泛 allowlist 或关闭扫描掩盖。

---

## 执行前保护

**Files:**

- Create locally, keep ignored: `.migration-backup/no-nginx-cross-platform-wip.patch`
- Read only: the 5 modified files listed in Global Constraints

**Interfaces:**

- Consumes: current working-tree diff and current Git HEAD
- Produces: a recoverable patch snapshot; no tracked-file mutation

- [ ] Step 1: Run `git status --short --branch` and confirm only the known 5 tracked files are modified before implementation begins.
- [ ] Step 2: Save `git diff --binary` to `.migration-backup/no-nginx-cross-platform-wip.patch`; verify the patch contains all 5 paths.
- [ ] Step 3: Record the current HEAD SHA and latest failing CI run SHA in the executor progress ledger; do not edit this plan with transient run IDs.
- [ ] Step 4: Run `git diff --check`; line-ending warnings may be recorded, but whitespace errors must be fixed only in files touched by the implementation.
- [ ] Step 5: Do not commit or upload the snapshot.

---

## Task 1: 固化 FastAPI 作为唯一发布入口

**Files:**

- Modify: `apps/backend/app/core/config.py:15-16,79-85`
- Modify: `apps/backend/app/api/factory.py:17-47`
- Create: `apps/backend/tests/test_frontend_static_hosting.py`

**Interfaces:**

- Consumes: `Settings.frontend_dist: str`, `create_app() -> FastAPI`
- Produces: `_BACKEND_ROOT: Path`; default `frontend_dist == str(_BACKEND_ROOT / "frontend_dist")`; `SPAStaticFiles` remains the SPA fallback implementation

- [ ] Step 1: Add `test_default_frontend_dist_is_backend_relative_not_cwd_relative`. Point `config._LIB` at an empty temporary user-data directory, change the process cwd to a different temporary directory, construct `Settings()`, and assert `Path(settings.frontend_dist) == Path(config.__file__).resolve().parents[2] / "frontend_dist"`.
- [ ] Step 2: Add `test_fastapi_serves_spa_root_and_deep_routes`. Create a temporary dist containing `index.html` with sentinel `libao-spa` and `assets/app.js`, monkeypatch `factory.get_settings()` to return settings pointing at that dist, then assert `GET /` and `GET /workspace/demo` return the sentinel while `GET /assets/app.js` returns the asset.
- [ ] Step 3: Add `test_api_routes_are_not_swallowed_by_spa`. Using the same app, assert `GET /api/v1/system/health` returns JSON and does not contain `libao-spa`; assert a missing `/api/v1/not-present` route returns 404 rather than `index.html`.
- [ ] Step 4: Run the three tests and confirm the cwd-independence test fails before implementation.
- [ ] Step 5: Define `_BACKEND_ROOT = Path(__file__).resolve().parents[2]`, use its absolute `frontend_dist` default, and keep the existing router-before-root-mount order in `create_app()`.
- [ ] Step 6: Run `uv run pytest tests/test_frontend_static_hosting.py` from `apps/backend`, then run it again while the shell cwd is the repository root.
- [ ] Step 7: Record results in the progress ledger; do not commit.

---

## Task 2: 删除 Nginx 并加固发布包边界

**Files:**

- Delete: `deploy/nginx/nginx.conf`
- Delete: `deploy/nginx/README.md`
- Create: `scripts/__init__.py`
- Create: `scripts/release_builder.py`
- Modify: `scripts/build-release.py`
- Create: `tests/test_release_builder.py`
- Modify: `.github/workflows/ci.yml:92-117`

**Interfaces:**

- Consumes: `apps/frontend/dist`, `apps/backend`, `deploy/sandbox`, `LICENSE`, `examples/settings.example.json`
- Produces: `validate_version(version: str) -> str`; `release_paths(version: str) -> tuple[Path, Path]`; `build_release(version: str) -> tuple[Path, Path]`; thin CLI compatibility entry `scripts/build-release.py`

- [ ] Step 1: Add `test_validate_version_accepts_release_names` for `0.1.0`, `ci-Windows`, and `smoke_posix.1`; require exact return of the accepted string.
- [ ] Step 2: Add parameterized `test_validate_version_rejects_path_escape` for `""`, `".."`, `"../escape"`, `"..\\escape"`, `"/tmp/x"`, `"C:\\temp"`, a leading dot, whitespace, and a value longer than 64 characters; each must raise `ValueError` before any filesystem deletion.
- [ ] Step 3: Add `test_release_paths_stay_strictly_under_artifacts`. Monkeypatch `ARTIFACTS` to a temp directory, call `release_paths("smoke")`, and assert both resolved parents remain under the resolved artifacts directory.
- [ ] Step 4: Add `test_release_layout_requires_spa_and_runtime_launcher_without_nginx`. Build against temporary source trees with subprocess and copy operations stubbed; assert required files include `backend/frontend_dist/index.html`, `backend/scripts/check_backend_runtime.py`, and `backend/scripts/start_backend.py`, and no member path begins with `deploy/nginx/`.
- [ ] Step 5: Run `PYTHONPATH=. uv run --project apps/backend pytest tests/test_release_builder.py` and confirm the tests fail because the testable functions do not yet exist; all root-level Python test commands must preserve `PYTHONPATH=.`.
- [ ] Step 6: Move the current implementation into `scripts/release_builder.py`. Validate versions with `^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$`, verify resolved stage/archive paths remain under `ARTIFACTS.resolve()`, and only then permit `rmtree()` or `unlink()`.
- [ ] Step 7: Make `scripts/build-release.py` a thin `from release_builder import main` import-and-exit wrapper (the script directory is `sys.path[0]` when invoked directly), while tests import `scripts.release_builder`; preserve all existing `.cmd`/`.sh` public entry points.
- [ ] Step 8: Remove the Nginx copy and required-file checks. Keep `backend/frontend_dist`, `deploy/sandbox`, `backend/scripts/check_backend_runtime.py`, `backend/scripts/start_backend.py`, README, LICENSE, settings example, manifest and ZIP.
- [ ] Step 9: Delete both tracked Nginx files. Do not edit `highlight.js` syntax definitions or ignored historical bundles; they are not deployment dependencies.
- [ ] Step 10: Update the release archive assertion in `.github/workflows/ci.yml`: require SPA and runtime checker, reject any `deploy/nginx/` member, and keep all existing forbidden-data checks.
- [ ] Step 11: Run the release-builder tests and `python scripts/build-release.py --version plan-smoke`; inspect the generated ZIP member list and assert it contains no Nginx path.
- [ ] Step 12: Record results in the progress ledger; do not commit.

---

## Task 3: 让 Windows 与 POSIX 启动/测试脚本共享实现

**Files:**

- Create: `scripts/bootstrap.py`
- Create: `scripts/run_checks.py`
- Create: `apps/backend/scripts/start_backend.py`
- Modify: `scripts/bootstrap.cmd`
- Modify: `scripts/bootstrap.sh`
- Modify: `scripts/test.cmd`
- Modify: `scripts/test.sh`
- Modify: `apps/backend/start.cmd`
- Modify: `apps/backend/start.sh`
- Create: `tests/test_cross_platform_scripts.py`

**Interfaces:**

- Produces: `scripts.bootstrap.main() -> int`; `scripts.run_checks.main() -> int`; `start_backend.backend_url(port: int) -> str`; `start_backend.main(argv: Sequence[str] | None = None) -> int`
- CLI contract: `LIBAO_BACKEND_PORT` defaults to `8000`; host is always `127.0.0.1`; a foreign/stale/legacy process is reported and never killed automatically

- [ ] Step 1: Add `test_bootstrap_runs_uv_projects_and_npm_ci_in_repo_root`. Stub `subprocess.run`, assert ordered argv are `uv sync --project apps/backend`, `uv sync --project tools/devpanel`, and platform-resolved npm with `ci --prefix apps/frontend`; assert every cwd is the repository root and first nonzero exit code is returned.
- [ ] Step 2: Add `test_run_checks_uses_identical_check_list_on_windows_and_posix`. Feed executable names `npm.cmd` and `npm` through an injected resolver and assert both variants execute Ruff, backend pytest, frontend lint, typecheck, build, unit tests and Mock E2E in identical order.
- [ ] Step 3: Add `test_start_backend_rejects_non_loopback_host` and `test_start_backend_uses_environment_port`. Assert any host other than `127.0.0.1` is rejected and `LIBAO_BACKEND_PORT=18000` produces `http://127.0.0.1:18000/api/v1/system/health`.
- [ ] Step 4: Add `test_start_backend_never_reuses_foreign_or_stale_instance`. Stub `check_backend_runtime.check()` to return `foreign`, `stale`, and `legacy`; each must exit nonzero without calling Uvicorn. For `current`, exit zero; for `absent`, call Uvicorn exactly once.
- [ ] Step 5: Run `uv run --project apps/backend pytest tests/test_cross_platform_scripts.py` and confirm failure before shared runners exist.
- [ ] Step 6: Implement the three Python runners with `Path(__file__).resolve()` roots, argv lists rather than shell strings, `shutil.which("npm.cmd") or shutil.which("npm")`, and immediate propagation of subprocess exit codes.
- [ ] Step 7: Replace `bootstrap.cmd/.sh` and `test.cmd/.sh` bodies with thin wrappers that resolve the repository root and call the corresponding Python runner. Preserve `.cmd` CRLF and `.sh` LF/executable bits.
- [ ] Step 8: Replace backend `start.cmd/.sh` orchestration with thin wrappers around `uv run python scripts/start_backend.py`. Both platforms run the backend in the foreground and stop with Ctrl+C; remove the Windows-only extra `cmd /k` window and stale DevPanel wording from the release backend launcher.
- [ ] Step 9: Run `bash -n scripts/bootstrap.sh scripts/test.sh apps/backend/start.sh` on POSIX and invoke each `.cmd` through `cmd /d /c` in the Windows CI job.
- [ ] Step 10: Record results in the progress ledger; do not commit.

---

## Task 4: 保持 Vite 直连本地后端并统一 DevPanel 端口

**Files:**

- Modify: `apps/frontend/vite.config.ts:7-24`
- Modify: `apps/frontend/.env.example`
- Modify: `tools/devpanel/main.py:34-44,138-161,506-523`
- Create: `tests/test_devpanel_configuration.py`
- Modify: `tools/devpanel/README.md`

**Interfaces:**

- Consumes: `VITE_USE_MOCK`, `VITE_API_PROXY`, `LIBAO_BACKEND_PORT`, `LIBAO_FRONTEND_PORT`, `LIBAO_DEVPANEL_PORT`
- Produces: backend URL `http://127.0.0.1:<LIBAO_BACKEND_PORT>`; Vite `/api` proxy target equal to that URL; all three ports default to `8000`, `5173`, `9100`

- [ ] Step 1: Add `test_devpanel_defaults_to_loopback_real_backend`. Import DevPanel with a clean environment and assert backend/frontend commands bind `127.0.0.1`, frontend receives `VITE_USE_MOCK=false`, and `VITE_API_PROXY=http://127.0.0.1:8000`.
- [ ] Step 2: Add `test_devpanel_custom_ports_are_consistent`. Set ports to `18000`, `15173`, `19100`; assert commands, health URLs, browser URLs and proxy environment all use the matching values.
- [ ] Step 3: Add `test_devpanel_rejects_invalid_port_values` for zero, values above 65535 and non-numeric values; startup must fail with a clear configuration error before spawning a child.
- [ ] Step 4: Run the tests and confirm custom-port assertions fail.
- [ ] Step 5: Parse ports once in DevPanel through `read_port(name: str, default: int) -> int`, keep host fixed to `127.0.0.1`, and derive all commands/URLs from those values.
- [ ] Step 6: In `vite.config.ts`, give explicit process variables precedence over env files: `process.env.VITE_USE_MOCK ?? env.VITE_USE_MOCK` and `process.env.VITE_API_PROXY ?? env.VITE_API_PROXY ?? "http://127.0.0.1:8000"`. Keep relative `/api` and do not add CORS or an absolute API base to frontend source.
- [ ] Step 7: Keep only `VITE_USE_MOCK` and `VITE_API_PROXY` in the frontend `.env.example`; document those plus the three `LIBAO_*_PORT` variables in DevPanel README, including defaults and the statement that all addresses remain loopback-only.
- [ ] Step 8: Run DevPanel configuration tests plus frontend `npm run typecheck` and `npm run test:unit`.
- [ ] Step 9: Record results in the progress ledger; do not commit.

---

## Task 5: 修复真实 E2E 的跨平台端口与进程回收

**Files:**

- Create: `scripts/real_e2e.py`
- Modify: `scripts/test-real-e2e.py`
- Modify: `scripts/test-real-e2e.cmd`
- Modify: `scripts/test-real-e2e.sh`
- Modify: `apps/frontend/playwright.real.config.ts:10-25`
- Modify: `apps/frontend/run-real-e2e.cmd`
- Create: `tests/test_real_e2e_runner.py`

**Interfaces:**

- Produces: `parse_loopback_url(value: str, default_port: int) -> tuple[str, int, str]`; `run_real_e2e(argv: Sequence[str]) -> int`
- URL contract: `E2E_BACKEND_URL` and `E2E_FRONTEND_URL` must use `http://127.0.0.1:<port>`; auto-start never binds a remote or wildcard host

- [ ] Step 1: Add parameterized URL tests for default ports, custom ports, trailing slashes and rejection of `0.0.0.0`, non-loopback hosts, credentials, query strings and fragments.
- [ ] Step 2: Add `test_custom_backend_port_is_used_for_spawn_health_and_vite_proxy`. With `E2E_BACKEND_URL=http://127.0.0.1:18000`, stub Popen/health/npm and assert Uvicorn uses `--port 18000`, health probes use 18000, and child env contains `VITE_API_PROXY=http://127.0.0.1:18000` plus `VITE_USE_MOCK=false`.
- [ ] Step 3: Add `test_started_backend_is_stopped_on_startup_timeout_and_playwright_failure`. Force each failure and assert `stop_process()` is called exactly once only for a process owned by the runner.
- [ ] Step 4: Run the tests and confirm the current hard-coded 8000 behavior fails.
- [ ] Step 5: Move testable orchestration into `scripts/real_e2e.py`; keep `scripts/test-real-e2e.py` as a compatibility wrapper and keep `.cmd/.sh` as thin platform launchers.
- [ ] Step 6: Pass `VITE_API_PROXY` and `VITE_USE_MOCK=false` to Playwright's inherited web-server environment. Derive Vite port from the validated frontend URL and keep `reuseExistingServer: true`.
- [ ] Step 7: Run the unit tests, then run a no-LLM health/SPA setup check with ports 18000/15173. Keep full real-chat E2E manual because it requires the user's local LLM key.
- [ ] Step 8: Record results in the progress ledger; do not commit.

---

## Task 6: 修复 Linux 暴露的聊天失败恢复持久化问题

**Files:**

- Modify: `apps/backend/app/orchestration/chat_stream.py:391-408,512-550`
- Modify: `apps/backend/app/orchestration/checkpointer.py:210-310`
- Modify: `apps/backend/tests/test_chat_stream.py:528-580`
- Modify: `apps/backend/tests/test_json_file_saver.py:244-360`
- Modify: `apps/backend/tests/test_file_store.py`

**Interfaces:**

- Consumes: `chat_stream_events(..., task: Task | None)`, `FileContext.rollback()`, `JsonFileSaver.aget_run_bounds()`, `JsonFileSaver.aget_tuple()`
- Produces: `_bind_graph_run(target_conversation: Conversation | None = None) -> None`; failed Task persists its cursor on the fresh post-rollback Conversation in the same commit as Task failure

- [ ] Step 1: Extend the recovery test to create and pass a real Task. First model call raises; after rollback/commit, reload the conversation from the current FileTable and assert `graph_cursor_initialized is True`, `active_graph_checkpoint_id is None`, and Task status is `failed`; the second call must contain human-message batches `[["失败消息"], ["恢复消息"]]` with no replay.
- [ ] Step 2: Add `test_failed_then_successful_run_keeps_latest_success_checkpoint`. Persist a failed run followed by a successful run, call `aget_tuple()` without an explicit checkpoint ID, and assert it returns the successful run's latest checkpoint rather than an older pre-failure checkpoint.
- [ ] Step 3: Keep and run the existing/new run-bound tests for trailing checkpoints and dropped `code_checkpoint_id`; add `test_next_input_record_bounds_the_previous_run` so an error in a later input cannot contaminate the earlier run.
- [ ] Step 4: Add `test_rollback_detaches_old_row_and_fresh_row_persists`. Mutate a Conversation, rollback, mutate only the old object and commit, then assert a table reload does not contain that mutation; mutate the freshly re-read row and assert it survives reload.
- [ ] Step 5: Run the focused tests and confirm the real Task test and failed-then-successful latest test fail against the current WIP.
- [ ] Step 6: Change `_bind_graph_run` to write the supplied fresh Conversation. In `on_error`, seal the checkpoint, rollback, re-read the Conversation by ID, bind the graph run to that fresh row, then call `TaskService.set_failed()` so cursor and Task state are flushed together.
- [ ] Step 7: Restrict implicit `aget_tuple()` failure fallback to the latest run interval (from the last metadata `source=input` through the end). Historical errors before a later successful run must not affect implicit latest reads.
- [ ] Step 8: Run `uv run ruff check .` and all focused checkpoint/chat/FileStore tests, then run `uv run pytest tests/` from `apps/backend`.
- [ ] Step 9: Record results in the progress ledger; do not commit.

---

## Task 7: 建立 Windows/Linux CI 矩阵和可启动发布包冒烟

**Files:**

- Modify: `.github/workflows/ci.yml`
- Create: `scripts/smoke_release.py`
- Create: `tests/test_smoke_release.py`

**Interfaces:**

- Produces: `smoke_release(archive: Path) -> None`; CI matrices `backend[ubuntu,windows]`, `frontend[ubuntu,windows]`, `release[ubuntu,windows]`
- Release smoke contract: unzip to temp, isolate HOME/USERPROFILE, `uv sync --frozen`, start on a free loopback port, verify health, SPA root and SPA deep-route fallback, always stop owned process

- [ ] Step 1: Add `test_smoke_release_checks_health_root_and_deep_route`. Stub archive extraction, subprocess and HTTP calls; assert the requested paths are `/api/v1/system/health`, `/`, and `/workspace/smoke`, and root/deep responses must contain HTML.
- [ ] Step 2: Add `test_smoke_release_always_stops_owned_process` for success, health timeout and malformed SPA responses.
- [ ] Step 3: Run these tests and confirm failure before the smoke module exists.
- [ ] Step 4: Implement `scripts/smoke_release.py` with stdlib ZIP/tempfile/urllib/subprocess. Allocate a free `127.0.0.1` port, set child `HOME` and `USERPROFILE` to the temporary home, and terminate the full owned process tree on both OSes.
- [ ] Step 5: Change backend and frontend jobs to `strategy.matrix.os: [ubuntu-latest, windows-latest]`. Use `npm` on Ubuntu and PowerShell-compatible commands on Windows without shell-built paths.
- [ ] Step 6: Keep Mock Playwright E2E on Ubuntu with Chromium and Linux dependencies; frontend build/typecheck/unit on Windows provides the platform gate without doubling browser-install cost.
- [ ] Step 7: Change release to an Ubuntu/Windows matrix. Build `libao-ci-${{ runner.os }}.zip`, run `python scripts/smoke_release.py <archive>`, and preserve archive-content checks without Nginx.
- [ ] Step 8: Add a POSIX syntax step on Ubuntu: `bash -n` for every tracked `.sh`. Add a Windows wrapper step that invokes `cmd /d /c` for noninteractive `--help`/validation paths and checks nonzero exit propagation.
- [ ] Step 9: Run root script tests, backend full tests, frontend lint/typecheck/build/unit, and a local release smoke before relying on GitHub runners.
- [ ] Step 10: Record results in the progress ledger; do not commit.

---

## Task 8: 修复 Security job，但不降低扫描强度

**Files:**

- Modify: `.github/workflows/ci.yml:9-12,69-77`
- Modify: `apps/backend/tests/test_file_ops.py`
- Modify: `apps/backend/tests/test_llm.py`
- Modify: `apps/backend/tests/test_provider.py`
- Modify: `apps/backend/tests/test_settings_upgrade.py`

**Interfaces:**

- Consumes: GitHub-provided `${{ github.token }}` and PR metadata
- Produces: independent `secret-scan` and PR-only `dependency-review` checks; no broad allowlist and no `continue-on-error`

- [ ] Step 1: Save the exact gitleaks failing step log, run SHA and event type in the executor ledger before editing the workflow; distinguish authentication failure from a finding.
- [ ] Step 2: Replace credential-shaped API-key test fixtures with explicit neutral values such as `test-review-key`, `test-provider-key` and `test-llm-key`; keep assertions that secrets never appear in command lines or serialized API responses.
- [ ] Step 3: Split gitleaks and dependency review into separate jobs so annotations identify the failing tool. Pass `GITHUB_TOKEN: ${{ github.token }}` to gitleaks and retain least-privilege `contents: read`/`pull-requests: read` permissions.
- [ ] Step 4: Do not add repository-wide regex/path allowlists. If gitleaks reports an actual non-test credential, stop execution, report the exact tracked path, and require credential rotation before continuing.
- [ ] Step 5: Run backend tests containing renamed fixtures and verify the secret scan against the complete tracked tree and PR range.
- [ ] Step 6: Record results in the progress ledger; do not commit.

---

## Task 9: 更新本地单用户、无 Nginx 文档契约

**Files:**

- Modify: `README.md:5-39`
- Modify: `SECURITY.md:3-17`
- Modify: `apps/backend/README.md`
- Modify: `apps/frontend/README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/overview.md:3-16`
- Modify: `docs/architecture/frontend.md:12-14`
- Modify: `docs/operations/release.md`
- Modify: `docs/operations/local-windows.md`
- Create: `docs/operations/local-linux.md`

**Interfaces:**

- Produces: one documented topology and one support policy; no alternate reverse-proxy/public deployment path

- [ ] Step 1: Document development flow as `browser :5173 -> Vite /api proxy -> FastAPI :8000`, and release flow as `browser :8000 -> FastAPI API/SPA`.
- [ ] Step 2: Remove all operational claims that Nginx is optional, recommended or packaged. Describe `deploy/` as sandbox-only.
- [ ] Step 3: State explicitly in README and SECURITY that LiBao is permanently scoped to personal local use: fixed admin is intentional, services remain loopback-only, and no multi-user/public deployment roadmap is promised.
- [ ] Step 4: Document Windows/Linux hard CI support, macOS POSIX best effort, supported prerequisites, ports and environment variables.
- [ ] Step 5: Add Linux instructions using `./scripts/bootstrap.sh`, `./scripts/dev.sh`, `./scripts/test.sh` and `./scripts/build-release.sh`; state that executable bits are tracked.
- [ ] Step 6: Document that Mock is test-only in normal development, while DevPanel launches the real local backend and Vite proxy.
- [ ] Step 7: Run a tracked-source search for `nginx` excluding this historical plan and ignored/generated dependencies; every remaining operational reference must be removed. Do not remove syntax-highlighting library data.
- [ ] Step 8: Check every documented command from a repository-root working directory and at least one unrelated working directory.
- [ ] Step 9: Record results in the progress ledger; do not commit.

---

## Task 10: 全量验收和提交门禁

**Files:**

- Review only: all files changed by Tasks 1-9
- Generated and ignored: `.artifacts/release/libao-acceptance-*`

**Interfaces:**

- Produces: verified local working tree ready for user review; no remote mutation

- [ ] Step 1: Windows: run `scripts\\bootstrap.cmd`, `scripts\\test.cmd`, `scripts\\build-release.cmd --version acceptance-windows`, then smoke the generated ZIP with `python scripts/smoke_release.py`.
- [ ] Step 2: Linux/CI-equivalent: run `./scripts/bootstrap.sh`, `./scripts/test.sh`, `./scripts/build-release.sh --version acceptance-linux`, then run the same smoke tool.
- [ ] Step 3: Run custom-port real integration setup with `E2E_BACKEND_URL=http://127.0.0.1:18000` and `E2E_FRONTEND_URL=http://127.0.0.1:15173`; omit only the LLM-dependent chat assertion when no local key is available.
- [ ] Step 4: Verify release ZIP excludes `deploy/nginx/`, tests, docs, DevPanel, Mock, `.git`, virtual environments, node_modules, logs, user data and environment files.
- [ ] Step 5: Verify `git grep` contains no personal absolute path, legacy sibling path, operational Nginx reference, `0.0.0.0` default binding or credential-shaped test fixture.
- [ ] Step 6: Run `git diff --check`, inspect `git status --short`, and compare the final diff against `.migration-backup/no-nginx-cross-platform-wip.patch` to ensure the original 5-file WIP was intentionally integrated rather than lost.
- [ ] Step 7: Execute the `review-test-simplify` Test/Review/Simplify gates. Any Critical/Important finding returns to the owning task and reruns its focused and full tests.
- [ ] Step 8: Present the complete diff summary and local/CI-equivalent results to the user. Wait for explicit authorization before any commit, push, PR update or merge.

---

## 验收标准

- `deploy/nginx/` 不存在，发布 ZIP 和 CI required 集合均不含 Nginx。
- 开发时 Vite 通过 `/api` 连接本地 FastAPI；发布时只启动 FastAPI 即可同时访问 SPA、REST 和 SSE。
- 从任意工作目录启动后端，`frontend_dist` 都按后端目录解析。
- `scripts/*.cmd` 与 `scripts/*.sh` 调用共享 Python 实现，退出码、命令顺序和路径语义一致。
- Windows 与 Linux CI 均通过后端 Ruff/pytest、前端 lint/typecheck/build/unit 和发布包启动冒烟；Mock Playwright E2E 在 Ubuntu 通过。
- 自定义真实 E2E 端口同时作用于 Uvicorn、健康检查、Playwright 和 Vite 代理，runner 只清理自己启动的进程。
- 真实 Task 失败后 Conversation 游标、Task failed 状态和检查点边界持久化一致；下一次聊天不重放失败消息。
- gitleaks 和 dependency review 独立可诊断，测试假数据不模拟真实凭证格式，扫描不使用宽泛豁免。
- README 与 SECURITY 明确：固定 admin、仅 `127.0.0.1`、本地个人单用户、无公网/多用户目标。
- 未经用户授权，没有 commit、push、PR 更新或 merge。
