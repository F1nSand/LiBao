# 可切换 Shell 沙箱实施计划

**Goal:** 修复 Docker 挂载参数错误，并提供默认宿主 PowerShell 7、可选宿主 Git Bash、可选 Docker Bash 的可切换命令执行后端。

**Architecture:** 新增通用 `shell` 工具与持久化沙箱模式设置。宿主模式使用工作区相对 cwd、清洗环境、独立审查和进程树清理；Docker 模式保留强隔离。模式在每轮 Agent 状态中快照，设置切换不影响正在执行的调用。

**Global Constraints:**
- 默认模式为 `powershell`；不自动从一种后端回退到另一种后端。
- 新会话注入 `tl_shell`；保留 `tl_bash` 仅用于旧 checkpoint 兼容。
- 宿主命令必须经过规则分类；联网安装/远程脚本需人工确认；越界路径、凭据、系统级和全局安装始终拦截。
- 工作区临时运行目录为 `.agent/runtime/`；普通会话删除时清理 `cache/sessions/<conversation_id>`，TTL 继续兜底。
- Docker 不自动 pull，网络保持 none，挂载只允许当前工作区。
- 保留既有未提交用户修改，不为本计划执行 reset、checkout 或覆盖无关文件。

## Task 1: 修复 Docker 挂载并保留强隔离回归

**Files:** `app/tools/sandbox.py`, `tests/test_docker_sandbox.py`

- [x] 为读写挂载写失败测试：`--mount` 不得出现裸 `rw`；只读挂载必须使用合法 `readonly`。
- [x] 修正 argv 生成并保留 `--pull never`、`--network none`、唯一容器名和清理逻辑。
- [x] 运行 Docker 单测与 Ruff。

## Task 2: 增加宿主 Shell runner、策略闸门和审查客户端

**Files:** `app/tools/sandbox.py`, `app/tools/context.py`, `app/tools/registry.py`, `app/tools/executor.py`, `app/tools/builtin/file_ops.py`, `app/tools/builtin/__init__.py`, `app/orchestration/context_builder.py`, `app/orchestration/stream_core.py`, `app/orchestration/nodes/tool_execute.py`, `app/seed.py`

- [x] 新增 `WorkspaceCommand`、宿主 runner、受限环境、输出预算、超时/取消进程树清理。
- [x] 新增 `SandboxLevel.WORKSPACE` 与 `tl_shell`；PowerShell、Git Bash、Docker 三模式按运行上下文选择命令构建器。
- [x] 将工作区文件工具从 `tl_bash` 切换到 `tl_shell`，保留旧 `tl_bash` 兼容。
- [x] 抽取 PowerShell/Git Bash 规则分类和动态人工确认；executor 与图节点都不得绕过 block/confirm。
- [x] 将独立审查从 Git Bash/curl 改为 `httpx`，保留熔断和旧 `BASH_REVIEW_*` 配置兼容。
- [x] 模式写入 Agent 状态快照，ACI 描述与执行方言一致。

## Task 3: 持久化沙箱设置与 API

**Files:** `app/storage/models/sandbox_preference.py`, `app/storage/file/store.py`, `app/api/routers/settings.py`, `app/services/sandbox.py`, `app/core/bootstrap.py`, `app/core/errors.py`

- [x] 新增单例 `SandboxPreference` 表与 `GET/PATCH /settings/sandbox`。
- [x] 响应只返回三种后端可用状态、当前模式和审查配置状态，不返回密钥/endpoint。
- [x] 切换前探测对应运行时；不可用返回 `60006` 且不改变配置；切换后同步运行时默认值。

## Task 4: 普通会话目录清理

**Files:** `app/services/conversation.py`, `app/core/session_cache.py`, `tests/test_session_cache.py`, `tests/test_conversations.py`

- [x] 删除普通会话时安全清理其精确 session 目录。
- [x] 工作区会话不删除项目目录；清理失败不阻断会话删除，TTL 继续兜底。

## Task 5: 前端“沙箱”设置标签

**Files:** `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/views/SettingsView.vue`, `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/sandbox.ts`, `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/types/api.ts`, `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/mock/server.ts`

- [x] 新增 PowerShell/Git Bash/Docker 三选项，默认 PowerShell，展示可用性、语法和隔离级别。
- [x] 保存调用后端 API，处理不可用模式和失败回滚；更新键盘导航、mock 与类型。
- [x] 更新前端 `progress.md` 交接记录。

## Task 6: 验证与交付

- [x] 后端运行 Docker、Shell、executor、graph interrupt、session cleanup 及分组回归测试。
- [x] 运行 `ruff check app tests` 与 `git diff --check`。
- [x] 前端运行 typecheck、Vitest、lint、build。
- [x] Docker smoke 未执行（当前验证环境未确认 Docker daemon/image，设置页会显示不可用且不会自动降级）。
- [x] 更新根目录 `progress.md`，不提交无关用户修改。
