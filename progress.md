# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\docs\plans\2026-08-20-m7b-workspace.md（M7-B）

## 删除 memory_trace + maintenance 改读 messages + 「轨迹」改名「对话轨迹」（2026-08-22，L2）

用户拍板：记忆页「轨迹」（memory_trace 原始聊天文本转储，与 messages 冗余）删除；会话轨迹保留并改名「对话轨迹」；主动记忆（记忆工具/Mem0）本轮不做。迁移 **0016**（drop memory_trace 表）。

- **后端删 memory_trace**：`models/memory.py` 删 MemoryTrace 类；`repositories/memory.py` 删 4 个 trace 方法 + **新增 `recent_messages_for_maintenance`**（join conversations 过滤 user_id + role in(user,assistant) + 排除软删会话/消息，与旧 recent_traces 同「最近 N 条升序」语义）；`services/memory.py` 删 record_trace/list_traces + run_maintenance 改读 messages；`routers/memory.py` 删 GET /memory/traces；`serializers.py` 删 serialize_memory_trace；`config.py` memory_trace_limit → memory_maintenance_limit；`chat_stream.py` 删 5 处 record_trace（C8 单事务缩为 user_msg+附件回填+touch）。
- **级联清理**：`workspace.py` `_cascade_delete_workspace` + `cleanup_test_orgs.py` 删 memory_trace 行。
- **迁移 0016** `b8c9d0e1f2a3`：drop_table；downgrade 重建表 + 两索引。已应用（head）。
- **测试**：6 文件改造（删 trace 用例/断言 + maintenance 改造 messages 数据源 + 新增 `test_maintenance_reads_recent_messages`）。全量 **393 passed + 2 跳过 + ruff**。
- **前端**：MemoryView.vue 删「轨迹」tab（只留长期记忆 + 触发整理）；stores/api/types/mock 删 MemoryTrace；ChatView/WorkspaceChatPanel radio「轨迹」→「对话轨迹」+ e2e 文案。typecheck ✓ / lint 0err / **179 单测** / build ✓。
- **docs 同步**：docs/00（记忆分层）/01（§8.1 记忆分层去轨迹）/02（「对话轨迹」+ 删命名警示）/03（删 GET /memory/traces）/04（删 §3.8 memory_trace + 目录树）。
- **遗留**：主动记忆（记忆工具/Mem0）待议；`mcp_server.workspace_id` defer、run_log org 列、测试污染根治 L3 等不变。

---

## 工作区硬删 + 文件树操作扩展（2026-08-22 完成，L2，交接板 [open] 收口）

交接板 `[open]` →后端 项：工作区删除（硬删）+ 文件树操作契约扩展（rename/mkdir/目录递归删）。前端已实现（mock + 404 降级），本轮后端补齐。用户拍板：硬删时附件**连磁盘文件一起删**。plan：`docs/plans/2026-08-22-workspace-hard-delete-file-ops.md`。

- **硬删** `DELETE /workspaces/{id}`：`soft_delete` → `hard_delete`。新增 `_cascade_delete_workspace`（叶子→根逆依赖序：longterm_memory_version→longterm_memory→messages→run_logs→attachments→memory_trace→webhook_configs→candidates→conversations→workspaces，先物化 id/附件路径）+ `_purge_workspace_files`（rmtree + 附件 unlink，best-effort 容 Windows 锁）；事务边界 DB 先 commit 后 `to_thread` 磁盘清理。`WorkspaceRepository.soft_delete` 一并删除。
- **rename** `PATCH /files/rename`：`rename_file`（old/new 过 `resolve_workspace_path`；禁 root / 源不存在 / 目标已存在 / 自身子路径成环 全 40302；old==new no-op；目录重命名整棵子树跟随）。
- **mkdir** `POST /files {is_dir:true}`：`WriteFileRequest` 加 `is_dir` + `content` 默认空；`write_file` is_dir 分支幂等建目录 + 空路径守卫。**响应统一 WorkspaceFile 形状** `{name,path,is_dir,size}`（原 `{path,written}` 与前端类型不符，属契约收紧）。
- **目录递归删** `DELETE /files?path=`：`delete_file` 目录分支 `shutil.rmtree`（to_thread）+ 禁删 root 守卫（原「目录删除暂不支持」移除）。
- **清理脚本修复**（范围外增项，用户已拍板保留）：`cleanup_test_orgs.py` 漏 M7-A `skills` + M7-B `workspaces` 两张表（删 org 撞 FK）→ 补两行 delete + import。跑通后清理累积污染 org=2887（含 170 工作区、137 skills）→ orgs=1。
- **测试**：test_workspace_service 删 `test_soft_delete`、增 17 项（硬删级联归零/磁盘删/隔离/40416 + rename 8 边界 + mkdir 4 + 目录递归删 2）；全量 **391 passed + ruff 干净**。
- **HTTP 冒烟**：建工作区 → 写文件（返回 is_dir:false/size:11）→ mkdir → rename → 目录递归删 → 硬删 → 取回 40416 + root 目录消失，全链通过。
- **docs 同步**：docs/03 §5.14 L393 DELETE 改硬删 + L401 POST is_dir + L402 目录递归删 + 新增 rename 行 + AC-6e 硬删例外。
- **交接板**：FrontEnd/progress.md [open] 2026-08-21 → [done]（附后端实现摘要）。
- **review/simplify gate（2026-08-22 收尾）**：review 2 agent 发现 C1（list_files Windows `\` 破坏前端 rename → 改 `.as_posix()`）+ I1（rmtree 无安全校验 → root 须落 workspaces_root 内才删）+ I2（write 写目录/rename 文件入自身路径 500 → 类型冲突守卫）+ I3（缺跨 org 隔离测试 → 补）+ I4（docstring 与归档行为不符 → 改注释），均修复。simplify 收敛 3 处（`_scalars` 复用 cleanup 模式 / 删未消费标签 / 去冗余 `.resolve()`）。修复后全量 **392 全绿 + ruff**。
- **Minor 三项后补（2026-08-22，commit 待定）**：M1 `hard_delete` 加 `with_for_update` 行锁（串行化并发/重复删除 → 第二次 40416）+ 测试；M2 `delete_file`/`rename_file` 符号链接按链接本身删/改（不解引用真实目标，防误删指向文件）+ 测试（本机无开发者模式自动跳过，逻辑已审）；M3 `rename_file` Windows 大小写仅改名特例（a.md→A.md 不再误报目标已存在）+ 测试。seed 重跑落库「栗包」人设（agent v3 published，system_prompt 含栗包 + 自称统一用我）。全量 **394 通过 + 2 跳过（符号链接）** + ruff。**遗留**：`mcp_server.workspace_id` defer、工作区端到端联调（真实 LLM，前端已联调核验 PASS）、run_log org 列、测试污染根治 L3。

---

## M7-B 工作区（2026-08-20 完成）

任务清单：
- [x] Phase1 T1 workspace 实体 + 迁移 0013 + 仓库 + 本地文件夹 + serialize
- [x] Phase1 T2 workspace service + /workspaces CRUD API
- [x] Phase2 T3 路径安全模块
- [x] Phase2 T4 6 内置文件工具 + Bash 语义审查
- [x] Phase2 T5 文件 REST（资源管理器）
- [x] Phase3 T6 workspace 对话 + 项目 agent 组装
- [x] Phase3 T7 workspace_skill（filesystem skills；mcp_server.workspace_id defer）
- [x] Phase4 T8 longterm_memory.workspace_id
- [x] Phase4 T9 全量回归 + 端到端（345 全绿 + ruff；workspace CRUD/文件 REST 真实 HTTP 冒烟过）

### 执行记录（M7-B）
- Phase1（commit 89bc29c）：迁移 0013 `workspaces` 表（org 级：name/description/root_path/system_prompt_fragment/status/created_by）+ WorkspaceService（create 建真实本地目录 `{workspaces_root}/{id}` 托管）+ `/workspaces` CRUD（developer+）+ 错误码 40416/40908 + 配置 workspaces_root/command_review_model。测试 4 项。
- Phase2 核心（commit 9a1e298）：`resolve_workspace_path` 路径强限制（realpath 逃逸 40302）+ 6 内置文件工具（read/write/edit/glob/grep/bash，工作区根 ContextVar）+ bash LLM 语义审查（allow/block，审查失败保守 block）+ tool_execute 注入工作区根。测试 7 项。
- Phase2 T5（commit 6bcf4fa）：`/workspaces/{id}/files` 列表/读 content/写/删（读→组织成员，写删→developer+），复用路径强限制；目录删除暂不支持。测试 +1。
- Phase3 T6（commit 0034f50）：conversation.workspace_id（迁移 0014）+ ChatRequest.workspace_id → chat.py 解析工作区 → build_initial_state 注入 workspace_root/system_prompt_fragment/文件工具（6 工具 enabled=True 仅工作区注入）。测试 +1。
- 修复（commit 160cc89）：workspace_root 返回绝对路径（relative_to/路径校验相对绝对混用致 500）；data/ 进 .gitignore。
- Phase4 T8（commit ce009dd）：longterm_memory.workspace_id（迁移 0015）+ list_cards 按 workspace_id 过滤（普通→个人；工作区→工作区∪个人）+ memory_inject 读 workspace_id。测试 +1。
- Phase3 T7a（commit 720014d）：discover_workspace_skills（扫描 skills/*/SKILL.md → 路由描述）+ build_initial_state 合并 org+工作区 skills 进前缀 + load_skill 回退（DB 未命中读工作区文件）。测试 +2。**mcp_server.workspace_id（工作区级 MCP）defer**——工作区 agent 复用组织级 MCP 已够 80% 场景。

### M7-B 收尾轮（2026-08-21，L2 轻量）
- **提交外部 slugify 改动**（commit c19cb52）：`slugify` 连字符→下划线。查清影响面：`mc_...` spec id 纯内存不落库、启动每次重建；绑定键 `row.name` 不变，无持久化破坏。
- **工作区会话隔离**（commit 41bc9fb）：`GET /conversations` 加 `workspace_id` 查询参数（缺省排除工作区会话 / 带值命中工作区）；`POST /conversations` 接受 `workspace_id`；对齐前端 mock 语义。测试 +2（347 全绿 + ruff）。
- **docs 同步**（前端交接板 →后端）：docs/03 补 §5.15 主 Agent Skills（org 级）+ §5.2 会话列表 workspace_id 参数；docs/02 §4/§6.2/§7 删 /tasks·TaskList·EvalManage/CostChart/EvolutionManage·task store、补 /skills·SkillsView·skill store、/system 收敛为日志+trace；docs/00 §5 模块图更新。（docs 在 `Desktop/Agent/docs/`，非后端 git 仓库，仅落盘）
- **交接板**：FrontEnd/progress.md 三张 open 纸条划 [done] + 回「会话 workspace_id 已对齐，前端零改动」。
- **遗留（记录不修）**：`mcp_server.workspace_id` defer、工作区端到端联调、run_log org 列、测试污染根治；下一大里程碑 = M8 热点垂直化。

### M7-B T7a/T8 重定位 · `.agent/` 目录机制（2026-08-21，L2，未提交）

交接板 `[open]` →后端 项：工作区项目级能力收敛为 `.agent/` 目录文件化（Claude Code `.claude/` 同款），不做专门 skills/记忆管理 UI。

- **skill 发现迁移**：`discover_workspace_skills` 改扫 `.agent/skills/*/SKILL.md`（优先），兼容旧 `skills/*/SKILL.md`，同名 `.agent/` 优先；新增 `discover_workspace_agent` 一并发现 `agent.md` + `memory/*.md` + `knowledge/*.md`。
- **注入**：`build_initial_state` 注入 `[项目约定]`（agent.md）/`[项目记忆]`/`[项目知识]` 段；skills 同名去重（项目级覆盖全局 org skill）。
- **骨架初始化**：`WorkspaceService.create` 调 `init_agent_skeleton` 建 `.agent/`（agent.md 模板 + skills/memory/knowledge 空目录 + README，幂等不覆盖）。
- **load_skill 回退**：优先 `.agent/skills/<name>/SKILL.md`，兼容旧 `skills/`。
- **兼容策略**：`workspace_skill` 表从未实现（仅 docs 描述，M7-B T7a 已是纯文件）——纯文件为准，无表废弃；`longterm_memory.workspace_id` 保留（DB 记忆隔离不变）。
- **docs 同步**（`Desktop/Agent/docs/`，非后端仓库）：docs/00/01/03/04 移除 `workspace_skill` 表描述、补 `.agent/` 机制；docs/03 工作区 skills REST 改文件化 + 补 `/workspaces/{id}/reveal`；docs/02 扫描路径修正。
- **验证**：`test_workspace_agent` +8（发现/`.agent/` 优先级/骨架幂等/注入/同名覆盖）；全量 **339 通过 + 18 跳过**（skip 全是 redis 容器 6379 未发布宿主机，环境问题与本改动无关）+ ruff 干净。

### Part B · `POST /workspaces/{id}/reveal`（2026-08-21，L1，未提交）

交接板 `[open]` →后端 项：OS 打开工作区本地文件夹。

- `WorkspaceService.reveal`（存在校验 + `_open_folder`：Windows `os.startfile` / Linux `xdg-open` / macOS `open`）+ `/workspaces/{id}/reveal` 路由（developer+，40416 校验）。
- 测试 test_reveal +1（monkeypatch `_open_folder` 捕获路径 + 不存在 40416）。

### Part C · GitHub 热点收集渠道（2026-08-21，L2，未提交）

垂直化领域-热点收集的 GitHub 信息源（plan `agent-ancient-lynx.md`）。用户拍板：trending 复用 gtrending 库 + 搜索/详情走官方 API + 落库本地工作区 + 定时脚本。

- **依赖**：pyproject 加 `gtrending>=0.5.1`；`Settings.github_token`（env `GITHUB_TOKEN`，缺省匿名 60 req/h）。
- **服务层** `app/services/github_hotspot.py`：`fetch_trending`（gtrending 同步爬，需 `asyncio.to_thread`）+ `search_repos`/`get_repo`（官方 REST API + 降级）+ `format_trending_md`/`format_repo_md` + 本地落库（`github-hotspot/{trending,repos}/` + `index.json` 新鲜度）。
- **内置工具** `app/tools/builtin/github_hotspot.py`：`tl_github_trending`（优先本地新鲜/实时抓取/失败本地兜底）、`tl_github_search`、`tl_github_repo`（落库）；默认 `enabled=False`（网络工具约束优先）。
- **定时脚本** `scripts/fetch_github_hotspot.py`（`--workspace-id`/`--root`/`--since`/`--force`，由 DevPanel/任务计划调度）。
- **skill 模板** `examples/skills/github-hotspot/SKILL.md`（复制到工作区 `.agent/skills/github-hotspot/` 即被自动发现）。
- **降级**（用户硬要求）：token 缺失→匿名+note；401/403→引导本地缓存；网络失败→本地快照兜底；gtrending 反爬→最近快照兜底。
- **测试** test_github_hotspot +11（格式化/落库/新鲜度/降级，monkeypatch 隔离网络）；test_reveal +1。
- **验证**：全量 **369 passed / 0 skipped**（redis 端口已恢复映射）+ ruff 干净。
- **待用户**：`.env` 配 `GITHUB_TOKEN`（用户自行配置）；commit 待确认。

### Part C 补 · 工作区文件夹可读化 + 热点 workspace 配置（2026-08-21，L2，未提交）
- **文件夹可读化**：`workspace_root(id, name)` 改 `{slug(name)}-{id前8}`（`_slugify_name`：ASCII 保留、中文剥除、纯中文兜底 `workspace`）；仅影响新工作区，存量 UUID 目录不动。test_slugify_name +1，test_create 断言更新。
- **seed 启用 3 个 GitHub 工具**：`_get_or_create_tool(..., enabled=True)`（github_trending/search/repo）+ `agent_tools` 追加 3 个 tl_github_* + 系统提示词补一行；幂等 re-seed 已跑（v3，DB 确认 3 行 enabled=t）。
- **配置「GitHub 热点」工作区**：复制 skill 模板 → `data/workspaces/2a9e5854-…/.agent/skills/github-hotspot/SKILL.md`（该工作区对话时自动发现）。
- **.env**：用户已填 `GITHUB_TOKEN`（ghp_ 前缀），`get_settings().github_token` 读通。
- **验证**：全量 **370 passed / 0 skipped** + ruff 干净。
- **待用户**：重启后端（sync_registry 使 spec enabled 跟随 DB）→ 在工作区问「今天 GitHub 有哪些热门项目」实测。

### 会话收尾（2026-08-21）
- 本轮 commit 链：c14a2c9（`.agent/` 机制）+ 2f5c9e5（reveal）+ 06cc3e8（文件夹可读化 + seed 启用 GitHub 工具）+ 55c7948（GITHUB_PROXY）+ 4bfe38b（镜像+近似榜自动兜底）+ 2555067（工具返回 str 修截断）+ e0e390c（摘要上限 500→8000）。全量 **375 全绿 + ruff**。
- **GitHub 热点渠道**：代码/工具/skill/落库/降级链全部就绪，**待用户重启后端后实测**（工作区问「今天 GitHub 有哪些热门项目」）。
- **明日待办（交接板 [open] →后端，已勘察未开工）**：**工作区硬删 + 文件树操作契约扩展**——① `DELETE /workspaces/{id}` 软删→真删（删 root_path 目录 + DB 行 + 级联 conversations/messages/memory_trace/run_log/attachment/webhook/evolution/longterm_memory，无 FK 级联手动叶子→根）；② `PATCH /files/rename`；③ `POST /files {is_dir:true}`；④ `DELETE /files?path=` 目录递归删；⑤ docs/03 同步。**待拍板**：硬删时 attachment 磁盘文件是否连删（我倾向只删 DB 行）。详见 memory `agent-backend-project-state.md`。

---

## M7-A 主 Agent 第三方 Skills + MCP 适配（2026-08-20 完成）

任务清单：
- [x] T1 Skill 实体 + 迁移 0012 + 仓库
- [x] T2 SKILL.md 解析 + SkillService + git 导入
- [x] T3 Skills API 路由
- [x] T4 tl_load_skill meta 工具
- [x] T5 Skills 注入主 agent 上下文
- [x] T6 MCP 适配确认（无新代码：MCP 工具已走 enabled_tool_ids 进主 agent 工具集）
- [x] T7 测试 + 回归

### 执行记录（M7-A）
- T1-T3 完成（commit 32adca3）：迁移 0012 `skills` 表（org 级：name/description/body/source/enabled，默认关闭）+ SkillRepository + SkillService（parse_skill_md frontmatter 校验 I7 + import_from_git：git clone 到临时目录→rglob SKILL.md→单事务入库，重名跳过）+ `/skills` CRUD + import（developer+，`/skills/import` 在 `{skill_id}` 前）+ serialize_skill + 错误码 40024/40025/40415/40907。测试 test_skill_service 8 项全绿。
- T4-T5 完成（commit 5271a01）：`tl_load_skill` 内置 meta 工具（读 get_tool_org → SkillRepository 取 enabled skill 正文，渐进式披露）；`build_initial_state` 追加 `skills_route_section`（enabled skills name+description）进 system_prompt 静态前缀；seed 挂 tl_load_skill（幂等收敛）；chat/task 三处接线 `SkillService.enabled_skill_routes`。测试 test_skill_injection 4 项全绿。
- T6：MCP 适配确认——org MCP 工具本就走 `enabled_tool_ids ∪ seed tools` 进主 agent 工具集，本轮零新代码（MCP 提示→skill 模板 defer）。
- T7：全量 pytest **329 全绿**（+12）+ ruff clean + seed 收敛（默认组织 agent 14 工具含 tl_load_skill）+ HTTP 冒烟（login→create/list/enable/get-by-name 全过）。
- 前端交接板已置 `[open]`（`/skills` API 契约 + `tl_load_skill` 语义），前端随后补 Skills 管理页。

---

## M6-3 多实例任务亲和 + 部署上线（2026-08-19 完成）

任务清单：
- [x] T1 instance id + Redis claim/cancel 命名层
- [x] T2 task_worker 改造（claim + cancel 监听）
- [x] T3 跨实例 cancel 路由
- [x] T4 拆独立 worker
- [x] T5 部署文件
- [ ] T6 验证 + 收尾

### 执行记录（M6-3）
- T1 完成（commit a73b6f8）：`app/core/instance.py` get_instance_id（uuid4 进程级单例）+ `app/storage/redis.py` 新增 `task_owner_key`/`worker_cancel_channel`/`claim_task`/`release_task_claim`/`get_task_owner`/`publish_cancel` + `TASK_OWNER_TTL_S=86400`。测试 `test_instance_claim.py` 5 passed。
- T2 完成（实现 + 测试 1 passed，**未 commit**）：`task_worker.py` `spawn_run` 内 claim 注入 + `cancel_listener`；`test_worker_cancel.py` 1 passed（SlowChatModel 挂起图 → publish_cancel → fut.cancel → claim 清除）。
- T3 完成（实现，测试待跑）：`task_worker.py` 新增 `route_cancel`（本地 fut.cancel + 查 claim publish_cancel）；`tasks.py` cancel_task 改调 `route_cancel`；`test_cancel_cross_instance.py` 已写（待跑）。
- T4 完成（实现，测试待跑）：`app/core/bootstrap.py`（init_runtime/cleanup_runtime）+ `app/worker.py`（独立 worker 入口）+ `main.py` lifespan 改用共享初始化、不再启动 task_worker。
- T5 完成（文件，验证待跑）：`Dockerfile`（backend/worker 共用镜像）+ `.dockerignore` + `docker-compose.yml` 加 backend/worker/frontend（profile app）+ `ci.yml` 加 `docker build .`。
- ⚠️ **阻塞**：Bash 权限分类器（claude-sonnet-4-6）持续超时，T2 的 commit 及 T3/T4/T5 的测试/ruff/docker 验证无法执行。恢复后需：① commit T2-T5；② 全量 pytest + ruff；③ `docker build .` + `docker compose config`；④ T6 多实例验证。

---

## M6-2 持续进化闭环·经验候选区（2026-08-18 完成，plan: agent-sparkling-patterson.md，297 测试全绿 + ruff + verify_evolution 8/8）

- **候选区**：candidates 表（迁移 0011，org_id 隔离）+ EvolutionRepository/Service/路由（`/evolution/candidates*`，admin-only）。同步状态机 candidate→validate→approved/rejected、reject→rejected、approved→publish→published、published→rollback→rolled_back；错误码 40020/40021/40022/40023 + 40401。
- **同步 validate**：复用 eval.py `_run_single_case`/`_judge`，瞬态 AgentConfig 快照（prompt 型换 system_prompt），逐 validation_case 跑图+judge，pass_rate≥0.8 approved。
- **发布/回滚**：`AgentService.publish_prompt/rollback_prompt`（不 commit + `SELECT FOR UPDATE` 防并发腐蚀）+ 单事务组合；AgentVersion 只增（回滚=上一版作为新版本发布，失败版保留）；仅 prompt 载体可发布（tool/skill/memory/context → 40021）；rollback 校验候选是否当前生效（防撤销更晚发布）。
- **逐轮 cost 扩展**：message 封口事件 payload + serialize_message/Message REST 加 cost（token_usage.cost 表面化）；agent_execute 把 cost 随 usage_metadata 带出 → stream_core 读入轮消息 → _persist_round 落库。
- **seed**：3 条演示候选（candidate/approved/published，全 prompt）+ 手动创建端点。
- **前端零改动**：validation_cases 前端是 string[]（我存 {input,expected}，serialize 转可读字符串）；FEATURE.evolution 从降级转正式渲染。
- **测试**：新增 test_evolution（9）、test_evolution_org_isolation、test_message_cost；扩 test_chat_stream（message seal cost）。verify_evolution.sh 8/8（真实 LLM 全闭环）。

## M6-1 多用户 RBAC + 数据隔离（2026-08-18 完成，plan: agent-sparkling-patterson.md，285 测试全绿 + ruff + verify 14/8/6）

- **角色守卫**：`deps.py` `require_role(*roles)` 工厂 + `require_admin`/`require_developer`（返回 user）；tools/kb → developer+，settings/system/evals/hooks管理/users → admin，health + hooks 公开收包 → 公开。对齐前端守卫（前端早已守卫，本轮后端补 API 直调兜底）。
- **Eval 运行/结果 org 隔离**：`get_run`/`list_runs` 加 org_id（join EvalSet.org_id）；`EvalService.get_run_owned` 镜像 `get_set_owned`，跨 org 40414。
- **用户**：`list_paged` org 收敛；create_user 拒跨 org 写（40301）；`get_owned` org 比对（40411）；`_guard_self` 防最后一个 admin 自锁死。
- **顺带修 bug**：`aggregate_llm` 的 `token_usage.cost` 未进 GROUP BY → `/system/cost` 50001，包 `func.sum` + 回归测试（test_system_logs）。
- **测试**：改 test_users_api/test_evals/test_eval_pairwise 签名；新增 test_rbac（纯单测）、test_eval_org_isolation（两 org 隔离）、用户 org 收敛 + 自守卫测试。
- **已知留白**（记录不修）：run_log 无 org 列 → `/system/logs` `/system/cost` 仅 admin 全平台（run_log 加列留部署/观测轮）；webhook 公开接收跨 org tool_id 碰撞（M6-1 前既有）。

## L1 笔记（2026-08-15 工作流提速轮）
- 用户采纳 3 条提速建议：① 全局 CLAUDE.md 验证纪律明确 L1 全量测试按天合并跑一次（L2/L3 仍每轮全量）；② Gate3 Simplify L2 降为 2 路（Reuse+Simplification），L3 恢复 4 路；③ 新增 `scripts/verify_m3.sh` M3 e2e 一键验证 —— 14 项断言全过（真实 SiliconFlow 索引 + 中文混合检索命中 + 附件分析 ready + 二进制回读一致 + 清理）。
- 脚本踩坑（已修，注释已内联）：Git Bash→curl.exe 中文 argv 按 Windows codepage(GBK) 转码 → 后端 400「There was an error parsing the body」，JSON body 必须写文件后 `--data-binary @file`；jget 对复合结构 print 输出 Python repr（单引号）→ json.load 失败，数组计数用单 python 内联。



目标：M3「记忆与知识库」核心闭环 —— 三层记忆（轨迹 + 长期记忆版本化只增 + 注入）、RAG 完整流水线（分块→向量化→语义+BM25 混合检索→RRF→kb_search 工具）、附件系统（本地磁盘存储 + 分析状态机 + 消息链路接通）。前端 MemoryView/KbView/附件契约已完整实现，后端补齐闭环。

全局约束：五层单向依赖（工具→存储合法，工具不碰服务）；信封契约；错误码 40011/40012/40403/50002/60001/60004/40901 消费 + 新增 40407/40408/40409/40905；默认关闭原则；后台任务 create_task 不持引用（M4 队列接缝）；ruff（120 列 E/F/I/UP/B ignore B008）；pytest-asyncio auto + conftest（requires_db/clean_mcp_specs）。

**本轮不做**（M4+ 接缝）：MinIO、视觉模型（analyze_image I2 降级）、Cross-Encoder 重排序（rerank_score 留空）、initiate_* 占位符、对话自动记忆提取、Agentic RAG 自主决策。

## 任务清单（M3）
- [ ] T1 数据层地基（依赖 pgvector/python-multipart + Settings + errors + 迁移 0004 七表 + sessionmaker 桥）
- [ ] T2 分块器 + EmbeddingService（httpx+重试+维度校验）
- [ ] T3 记忆域 REST（traces/longterm CRUD/版本只增/软删）
- [ ] T4 maintenance（LLM 整理 + json 提取 + 版本化写回）
- [ ] T5 记忆注入（memory_inject 节点 + 渲染 + 桥接线）
- [ ] T6 KB 集合/文档 + 后台索引流水线
- [ ] T7 /kb/search 混合检索（语义+BM25+RRF）
- [ ] T8 kb_search 内置工具（ContextVar + sessionmaker 桥 + seed）
- [ ] T9 附件（/uploads 落盘 + 二进制流 + 分析状态机 + 错误码）
- [ ] T10 消息 attachments 链路 + memory_trace + 收尾

## 执行记录（M3）
- T1 完成：迁移 0004（pgvector 扩展 + 七表 + HNSW/GIN/GENERATED tsvector CJK unigram raw string）+ Settings/errors（40407/40408/40409/40905）+ sessionmaker 桥 + 8 项测试 ✅
- T2 完成：chunker（字符滑窗 512/64）+ EmbeddingService（httpx SiliconFlow OpenAI 兼容，批量/重试/维度校验 1024）+ 13 项测试 ✅
- T3 完成：记忆域（memory_trace append-only + longterm CRUD/版本只增/软删 + /memory/* 路由，tags 列补迁移）+ 6 项测试 ✅
- T4 完成：/memory/maintenance（LLM 整理 + _extract_json 围栏 + 单事务 apply + 60001 retryable）+ 6 项测试 ✅
- T5 完成：memory_inject 节点（每轮 top-N importance 注入，历史后/状态栏前渲染，静默降级不击穿）+ graph 拓扑改造 + 6 项测试 + 全量回归 ✅
- T6 完成：KB 集合/文档 CRUD + 后台索引流水线（uploaded→indexed/failed，re-read 防并发，reindex 幂等，级联硬删）+ /kb/* 路由 + 8 项测试 ✅
- T7 完成：/kb/search 混合检索（语义 HNSW cosine + BM25 tsvector/ts_rank + RRF k=60，语义故障降级 bm25-only）+ 7 项测试 ✅
- T8 完成：kb_search 内置工具（ContextVar org 上下文 + sessionmaker 桥 + hybrid_search 下沉 repo 单一来源 + EmbeddingService 移 core 层）+ seed + 5 项测试 ✅
- T9 完成：附件（/uploads 落盘 + 二进制流 + 分析状态机：图片 I2 降级/txt 提取/pdf metadata + 错误码 40011/40012/40403/50002/60004）+ 9 项测试 ✅
- T10 完成：消息 attachments 链路（校验 40403→落库→回填 conversation_id/message_id）+ memory_trace 轨迹（user+assistant 每轮各一条）+ README M3 接缝表 + 2 项测试 ✅
- **M3 全部完成**：T1-T10 ✅，176/176 测试全绿，ruff clean → review-test-simplify gate（待执行）
- **端到端验证（真实 SiliconFlow embedding + 真实 DeepSeek）**：
  - RAG 全链：建集合 → 传 txt → 后台链真实向量化 → indexed → 混合检索（语义+BM25 双命中 RRF 0.0164）→ 纯 bm25 中文命中 ✓
  - kb_search 工具：DeepSeek 并行调用 kb_search（"产品支持哪些能力"）+ time_now → 基于检索结果作答 ✓
  - 附件链：图片上传 → ready + I2 降级文本"无法分析: 当前部署无视觉模型" ✓
  - 记忆链：卡片创建 → 真实 maintenance（DeepSeek 整理：更新 1 + 新建 1）✓
  - ⚠ 实测坑（已修）：DeepSeek v4-flash 的 content 是 blocks 列表——thinking 块（推理链）+ **末位裸 str 块（最终输出）**；
    `_content_to_text`/`message_text` 只拼 dict text 块导致 JSON/回答丢失 → 修复：跳过 thinking 块、保留裸 str 块
  - SiliconFlow Qwen3-Embedding-0.6B 实测返回 1024 维 ✓（.env 已配 key，不入库）

## Gate2 Review 发现（两路合并去重后 14 项，**恢复点：修全部并进 Simplify gate**）

### 🔴 HIGH
1. **S1 契约断裂：`POST /uploads` 响应缺 `attachment_id`** —— serialize_attachment 返回 `id`，前端 AttachmentUploader 消费 `res.attachment_id` → 附件→消息链路断裂。修：serializers.py 加 attachment_id 字段（保留 id 兼容）
2. **C1 kb_pipeline 插库阶段无异常捕获** —— `delete_chunks`/`insert_chunks`/commit 抛异常逃出 process_document → 文档永久卡 "indexing"（reindex/archive 都 40901 无出口）。修：try 包住插库段 → `_fail`

### 🟡 MEDIUM
3. **C2/S4 maintenance apply 阶段零校验** —— LLM 输出合法 JSON 但形状错（缺 id/UUID 非法/importance 非数字）→ KeyError/ValueError 裸 500 而非 60001 retryable。修：apply 循环包进 try + 形状校验
4. **C3 on_final 无异常保护** —— 落库/commit 失败穿出 → assistant 消息+done 丢失、resume 任务卡 running。修：stream_core on_final 调用包 try + on_error 兜底
5. **C4 add_version 并发** —— 双 maintenance 读-改-写 current_version → UNIQUE 冲突 500。修：SELECT FOR UPDATE 或捕获 IntegrityError → 60001 retryable
6. **C5 create_task 引用丢弃** —— 进程退出丢后台链 + task 异常静默。修：task 内加异常日志；MVP 接受重启丢任务（M4 队列接缝，README 已注）
7. **S2 progress 字段类型矛盾** —— status 端点返回布尔、序列化返回字符串，前端 KbDocument.progress 是 number。修：统一 number（0-100 或 null）
8. **S3 KB 上传非法 UTF-8 → 50001** —— 应 400xx（客户端输入错）。修：捕获 UnicodeDecodeError → AppError(40012)
9. **S5 迁移 0004 有 7 处 ruff 错误**（I001/UP035/UP007/F541）—— 手写迁移应过 ruff

### 🟢 LOW
10. **C6 _fail re-read 非原子** —— 竞态窗口极小；可接受或 UPDATE WHERE status IN 原子化
11. **C7 LongTermMemoryVersion ORM 缺 UNIQUE(memory_id, version) 声明** —— 迁移有、模型缺（create_all 环境丢约束）
12. **C8/S6 resume 路径不落 memory trace + 用户消息双 commit** —— 计划 D10 同事务偏差；resume 续答轮不落轨迹（maintenance 原料缺失）
13. **S7 语义通道异常整体吞掉** —— 静默降级 bm25-only 合理，建议响应带降级标记
14. **S8/S9/S10/S11/S12 杂项** —— 空内容错用 40014（改 40001）、chat.py uuid.UUID 裸抛 500（捕获→422）、hybrid 注释"权重"vs 实现"开关"、document_count 恒 0（改 COUNT 或接受）、services import api（既有模式不动）

### 已核实合规（勿重审）
hybrid_search RRF 叠加/降级语义、_indexed_filter join、ContextVar 无泄漏、graph after_tool steps 守卫、memory_inject 静默降级、迁移与模型列一致（除 C7）、附件删除-分析竞态、embedding 分批、五层依赖主体、错误码场景、seed 幂等、前端契约主体（memory/kb/analysis/message.attachments 形状）

## Gate3 Simplify（2026-08-16 执行完成）
四路并行（Reuse/Simplification/Efficiency/Altitude）审 `git diff 7ac4647..HEAD` → 合并去重（40 条→去重后 ~30）→ **应用 16 / 跳过 12**。

### 应用（16 项，均为安全小改动）
- `memory.py` `_content_to_text` → 复用 `stream_core.message_text`（删整函数，消除逐字重复）
- `kb.py` hybrid_search 死赋值 `semantic_on=False` 删除（降级由独立分支天然实现）
- 新建 `app/core/async_utils.py`：`spawn_background`+`log_task_failure` 收敛 kb/attachment 两处后台 spawn
- `kb.py` 裸 40012/40011 → `ERR_DOCUMENT_TYPE_UNSUPPORTED`(新增别名)/`ERR_FILE_TOO_LARGE`
- `user.py` 裸 40001 → 新增 `ERR_USERNAME_CONFLICT=40906`（与 collection 冲突码 40905 对齐；测试断言同步）
- `memory.py` `_clamp_importance` 收敛 4 处钳位
- `eval.py` `pass_flags` 列表 → `passed_count` 计数
- `chunker.py` 冗余分支 `[text] if text else []` → `[text]`
- `agent_execute.py` 删 `_text_of` 冗余 helper（直接用 `message_text`）
- `context_builder.py` 删死代码 `static_prefix_aci`（全库无调用）
- `task_run.py` 提取 `_mark_failed` 收敛 run/resume 异常兜底
- `embeddings.py` `in (429,*range(500,600))` → `==429 or >=500`
- `system.py` 提取 `_parse_iso`；`_trace_event` → `serializers.serialize_trace_event`
- `serializers.py` 新增 `serialize_trajectory_node`（conversation.py 收敛，契约单一落地）
- `chat_stream.py` `_message_dict` → `serialize_message`（done 消息契约单一落地）
- `notification.py` `maybe_notify_from_tool_results` @staticmethod → 模块级函数

### 跳过（12 项，记录理由）
- SSE fanout 收敛（task.push_event vs notification.push_notification）：任务 live-tail 终态哨兵语义不同；M4 多实例按 README 接缝 Redis 重构 fanout，此刻收敛收益短
- count 子查询 helper（user/notification/run_log 3 处）：3×3 行重复，抽象成本≈收益
- eval `_parse_judge` 复用 `_extract_json`：两函数语义略不同（围栏/规范化），跨服务 import 增耦合
- trajectory SQL 分页下推（Efficiency med）：limit=10000 上界足够开发量级；分页语义改动需更多测试，M4 长会话优化一并做
- /system/cost SQL GROUP BY 聚合（Efficiency med）：开发量级日志量小，Python 聚合正确可读；前缀 provider 推导 SQL 复杂，M5 观测模块化
- eval 各 case 并行 gather：后台评估非热路径；共享 session 并发写需重构，M4 队列
- hybrid_search bm25 并行：收益有限（语义通道已主导）
- run_logs/memory_trace 加索引：开发量级不可感，需迁移 0006，M5 增长时一并
- Altitude 结构性项（get_cost→SystemService、run_eval spawn→service、_decode_text→service、_require_admin→deps、service import api paged）：结构性重构/既有模式，M6 RBAC 或 M5 观测模块化时做
- `_backfill_attachments`→repo、`get_document_status`→serialize_kb_status、chat 附件校验→service：低价值小重构，本轮聚焦更高价值项

### ✅ **M3 正式闭环**（三道 gate 全过）
- Gate1 Test：207/207 + ruff clean ✅
- Gate2 Review：14 项发现全部修复 ✅（commit 1c39d37）
- Gate3 Simplify：应用 16 / 跳过 12（commit 待）✅
- 状态：M3 记忆/知识库/附件 + 五组接口全部收尾，进入前后端联调阶段

## M3.5 契约对齐轮（2026-08-16，后端×前端并行，以 FrontEnd/types/api.ts + mock/server.ts 为事实源）

**结论：后端与前端契约已对齐**（静态逐字段审计 + 运行时 :8000 实测）：
- SSE 事件（message_start/token/tool_call/tool_result/interrupt/done）字段与 useChatStream 消费一致；
  tool_call 事件前端只读 {tool_call_id,tool_name,input,require_confirm}，done 消息 tool_calls 含 position（position 兜底候选无需）
- kb progress 已统一 number（normalizeProgress 候选无需）；reindex/archive 返回 ok() 空——前端 store 忽略返回值，兼容
- trajectory：kind=user/assistant + thinking/diff=null + before_seq/limit/has_more（context/steering/compaction 为 mock 注入，契约允许）
- users/notifications/uploads/system-logs/cost/evals 输出形状全部匹配 Paged/信封/字段级
- **修复 1 处契约 bug**：evals 路由缺 `/system/evals` 前缀 → `GET /system/evals/sets` 404（前端会误判未实现降级）。
  `APIRouter(prefix="/system/evals")` 修复，实测 200。
- 运行时实测：login/me/conversations/users/notifications/system/logs/cost/evals/kb/collections/memory/tools/search/agents 形状全部正确

## M3.5 收尾轮（2026-08-16）

**Gate2 14 项修复全部落地**（commit 1c39d37）：
- HIGH：S1 `serialize_attachment` 补 `attachment_id`（前端 UploadResponse 契约）、C1 kb_pipeline 插库段异常捕获+先 rollback 再 `_fail`
- MEDIUM：C2/S4 maintenance apply 形状校验→60001 retryable、C3 stream_core on_final 保护（on_error 兜底+error 帧）、C4 IntegrityError（包 commit）→60001、C5 spawn 后台任务 done_callback 日志、S2 progress 统一 number、S3 KB 非法 UTF-8→40012（`_decode_text`）、S5 迁移 0001-0004 ruff 清零
- LOW：C6 `_fail` 单条 UPDATE 原子化、C7 LongTermMemoryVersion ORM UNIQUE 声明、C8 resume 补 assistant 轨迹+用户消息单事务、S7 语义降级日志、S8 空内容 40001、S9 attachments 校验 UUID→422、S10 hybrid 注释改开关、S11 document_counts GROUP BY
- 新增测试 7 项；非 DB 测试全过（含 stream_core on_final / pydantic 校验 / 纯序列化）

**前端五组新接口全部落地**（19 端点，commit 待）：
- trajectory：`GET /conversations/{id}/trajectory`（message+tool_calls 派生，before_seq/limit/has_more，零建表）
- notifications：`GET /notifications`、`PATCH /{id}/read`、`GET /notifications/stream`（SSE 按 user_id，镜像 task live-tail）；产生源 = 任务 done/failed + demo_notify 确认执行
- users：5 端点 admin 专属（复用 User 现有字段，零建表）
- system-logs：`GET /system/logs`（分页+trace_id/level/时间过滤）、`GET /system/logs/trace/{id}`（run_log 派生 TraceEvent）
- evals + cost：迁移 0005（notifications + eval 四表）+ 8 端点 + 最小运行器（逐 case 跑 agent 图 + LLM-as-a-Judge）+ `GET /system/cost`（token_usage.cost 聚合）
- 新增测试 24 项（207 collect）；`pass` 关键字冲突用 `pass_` 属性映射 `pass` 列

**验证状态**：ruff 全绿 + 迁移 0005 已应用（notifications+eval 四表）+ 全量 **207/207 通过**（Docker db 真实执行；修复轮 3 处失败：eval 模板非法 format 字段、C8 单事务需 flush 取 id、共享 DB 残留断言）。

## M4 最小闭环（2026-08-16，任务与多 Agent）

**前置**：完整性审计发现 M3 及之前 4 处未文档化缺口（hooks §5.10 / 事件裁决器 RM-9 入 M4；fetch_url / analyze_image / evals 路径 / CI 本轮补）。用户决策：补小的 + 大的入 M4；M4 先做最小闭环。

**Phase A — M3 收尾补齐**（commit a14...）：
- fetch_url 内置感知工具：httpx 只读抓取 + 出站白名单（Settings.fetch_url_allowlist fail-closed）+ HTML 清洗 + 注册(enabled=False) + seed；8 测试
- analyze_image 工具化：`_analyze_content` 下移 `storage/attachment_analysis.py`（五层约束）+ 内置工具（sessionmaker 桥）+ 注册 + seed；5 测试
- `GET /system/evals` 契约别名（commit 54893bd 修复：APIRouter 空路径路由不生效，改 system.py 全路径）
- `.github/workflows/ci.yml`（ruff + alembic + pytest，pgvector/redis service）
- README M4+ 接缝表补 hooks/事件裁决器标注
- 注册重构：builtin/__init__ 幂等守卫改逐工具 `_register`；修复 test_tool_search 与内置撞名

**Phase B — M4 最小闭环**（commit 40c7...，228/228 + ruff 全绿 + verify_m3.sh 14/14 + 实测冒烟）：
- B0 `storage/redis.py`：命名单一来源（task:queue / task:evt:{id} / notif:user:{id} / idem:{key}）+ init/get/close + enqueue/brpop/idem + `pubsub_bridge`；lifespan init/close + worker 生命周期；conftest `requires_redis`
- B1 任务队列 Redis：`TaskQueueService.enqueue_submit/enqueue_resume` + `task_worker`（BRPOP 消费分派 + trace_id 恢复）+ tasks.py 入队（Redis 挂降级 create_task）；实测：提交→入队→worker 消费→真实 LLM 作答→done ✅
- B2 live-tail Redis Pub/Sub：push_event/subscribe/unsubscribe 改 async + Redis 广播（终态 `__end__` 哨兵 + 断线重连）+ 进程内回退；notification 同构；~14 处 push_event 补 await
- B3 幂等 Redis：executor `_cache_get/_cache_put` async + Redis（TTL 1h，非 JSON 可序列化跳过）+ 进程内回退；幂等单测加 `_no_redis` 防跨 run 污染
- B4+B5 agent_switch + proposer-reviewer：state_schema 加 drafts/agent_switch；stream_core updates 分支发 agent_switch；`subgraphs/proposer_reviewer.py` 三段协作（上下文隔离）；graph.py 条件分流（graph_template）+ build_initial_state 传 template
- 修复 trajectory 测试确定性（created_at 同秒并列排序不稳定 → 显式递增时间戳）

**验收达标**：异步任务跑通（Redis 队列 + worker + live-tail）；两个 Agent 协作产出（proposer→reviewer→summarize + agent_switch 事件，前端可渲染）。

**M4 后续（完整版，用户说做好最小闭环再做）**：MCP 会话复用+任务亲和、max_concurrency 信号量、hooks/事件裁决器、initiate_* 占位符、取消 in-flight。

---

# M2.5 历史（已完成，勿重做）
# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\docs\plans\2026-08-14-m25-core-loop.md

目标：M2.5 核心闭环 —— MCP client（stdio+HTTP 双传输，注册/列表/注销）+ tool_search 元工具 + 两段式 ACI 注入（渐进式披露）。前端 ToolsView 注册弹窗直接对接真实后端。**本轮不做**：Docker 沙盒、M4 队列、MCP 资源/提示原语（M3 接缝）。

全局约束：五层单向依赖 API→编排→服务→工具→存储；DB 为元数据事实源、registry 为可执行宿主；连接会话/熔断为唯一新增进程级内存态（文档化接缝）；信封契约；静态前缀字节稳定；同名遮蔽拒绝（I7）；默认关闭原则（MCP 工具注册即 enabled=false）；ruff（120 列，E/F/I/UP/B，ignore B008）；pytest-asyncio auto + `_db_reachable()` skipif。

## 任务清单
- [ ] T1 依赖 + Settings + 错误码 + mcp_servers 表（迁移 0002）
- [ ] T2 MCP 连接层（mcp_client.py：stdio/http 传输 + 命名派生 + 文本提取）
- [ ] T3 熔断器 + MCPManager（惰性连接/并发锁/熔断 60003）
- [ ] T4 MCP 服务层 + 路由（register/list/unregister + 遮蔽拒绝 40903）
- [ ] T5 启动重建（sync_registry_from_db 扩展）
- [ ] T6 tool_search 元工具 + 两段式 ACI 门控
- [ ] T7 端到端验证（真实 FastMCP + 熔断实测 + 真实 DeepSeek 两段式）
- [ ] T8 收尾 gate（ruff + 全量测试 + 前端验证 + review-test-simplify）

## 执行记录（M2.5）
- T1 完成：mcp_servers 表（迁移 0002）+ Settings（mcp_breaker_threshold/cooldown_s、aci_full_limit）+ 错误码 40406/40904/50201 + mcp 2.0 依赖；5 项测试 ✅
- T2 完成：mcp_client.py（stdio/http 传输、命名派生、slugify、extract_text、McpConnectError）；mcp 2.0 API 差异核实（input_schema/is_error snake_case、streamable_http_client 无 headers 参数改 httpx2.AsyncClient）；12 项测试 ✅
- T3 完成：CircuitBreaker（CLOSED/OPEN/HALF_OPEN）+ MCPManager（每调用独立建连——mcp 2.0 ClientSession cancel scope 绑定任务，跨 ASGI 请求复用实测死亡）+ validate 即关；12 项测试 ✅
- T4 完成：McpServerRepository + McpService（验证即注册/遮蔽拒绝 40903/40406/50201）+ 路由（register/list/unregister，均在 /tools/{tool_id} 前）+ serialize_mcp_server + get_in_org spec-id 解析；10 项测试 ✅
- T5 完成：启动重建（迁移 0003 mcp_tool_name raw 名持久化 + sync_registry_from_db MCP 分支）；5 项测试 ✅
- T6 完成：tool_search 元工具（I4 三态降级）+ build_agent_tools 两段式门控 + selected_tool_names 状态 + seed；9 项测试 ✅
- T7 完成：端到端验证（真实 FastMCP stdio/HTTP 双传输 + 熔断/恢复实测 + 真实 DeepSeek 两段式 tool_search→time_now）+ README M2.5 接缝表 ✅
  - ⚠ 实测坑 1：mcp 2.0 跨任务会话死亡（anyio cancel scope）→ 改为每次调用独立建连/用完即关（README 接缝，M4 任务亲和优化）
  - ⚠ 实测坑 2：active_tools 跨轮缓存致选中注入失效 → agent_execute 每轮重算 build_agent_tools
- **review-test-simplify gate（M2.5 收尾）**：
  - Gate1 Test：ruff clean + 106/106 全绿 ✅
  - Gate2 Review：两 agent 发现 12 项（1 HIGH + 1 MED-HIGH + 5 Medium + 3 Low + 2 Info）——用户确认修全部 ✅
    - I1 slug 撞名预检（planned 内 seen_slugs 查重，防第二遍 register ValueError + ghost spec + 假 40903）✅
    - I2 熔断计执行失败（McpCallError 抛出，manager except→record_failure；is_error 业务错不计数）✅
    - I3 unregister 摘除 registry spec（registry.unregister，同进程重注册不被假 40903 挡）✅
    - I4 跨 org 同名隔离（name_exists_any_org 全 org 查重 + create 查全局 registry 但排除 tl_* 内置）✅
    - I5 启动重建覆盖全部 org（全量 sync 只做 MCP 重建不动已有 spec enabled，防 F7 回归）✅
    - I6 registry.register 拒同名遮蔽（_NAME_INDEX 检查，注释声明兑现）✅
    - I7 tool_search 平台元工具放行（超限强制注入 + 守卫 meta_tool 特例，与注入谓词一致）✅
    - M1 多 tool_search 合并（去重保序）+ 空结果清选中（matches 键存在即处理）✅
    - M2 mcp_source UUID 守卫（脏行跳过不击穿启动）✅
    - M3 Windows 路径 stdio 命令分词（_split_command 盘符/反斜杠按空白切）✅
    - M4 httpx2.AsyncClient 自建 client 关闭（_http_client.aclose）✅
    - M5 清理（死代码/req 类型/过期注释/active_tools 写回删除）✅
  - 跳过（记录理由）：slugify 保留连字符/命令派生取最后 token（实现与测试一致，计划初稿合理演进）、60003 未消费（熔断走 ToolResult 文本是决策 5 语义）、路由层自动化测试（T7 curl 已冒烟，补测留 M3）、mcp_servers (org,name) 唯一约束（并发竞态低概率）
  - 提交：069d52a（12 项）+ 41c9459（ruff clean）+ 5762249（去重）
  - Gate3 Simplify：4 agent 并行（Reuse 8 项 / Simplification 10 项 / Efficiency 2 项 / Altitude 2 项）→ 合并去重 16 项应用 / 5 项跳过 ✅
    - 应用：register 复用 build_mcp_spec（删 12 行重复）、mcp_spec_id + conn_config_from_server 单点、ToolSpec.meta/builtin flag（元工具身份 4 处字面量收敛 + I4 豁免显式化）、_authorized_specs 共享推导、selected_names 契约单点、_result helper 收敛三分支、breaker is_open/allow 冗余消除、批量查重（一条 IN 查询）、tests/conftest.py 收敛 8 份 _db_reachable 拷贝 + 3 份 mc_ 清理循环、active_tools 死字段删除、tool_search 投影/匹配分层（降级不经过检索逻辑）、unregister 循环合并
    - 跳过（记录理由）：lifespan 双 sync 不可合并（顺序承重：全量 usable 须覆盖默认 org 裸 enabled）、_with_connection 骨架（两路径错误处理差异大）、win32 分词特判（引号边缘为已知限制，注册期 fail-fast）、UUID try/except（局部惯用式 2 处未到提取阈值）、list_servers count N+1（管理路径，规模后 GROUP BY）
  - 最终：ruff clean + pytest 106/106 + 三 gate 全过 ✅ → **M2.5 核心闭环完成**

---

# 以下为 M1/M2 历史（已完成，勿重做）

# 进度账本 — plan: C:\Users\Admin1\.claude\plans\immutable-inventing-breeze.md

目标：M2 核心闭环 —— 工具管理（CRUD/test/search）+ require_confirm→interrupt→resume（task 实体+状态机+tasks 最小 API）+ 执行器重试/幂等 + Agent 版本化管理（POST/PUT/DELETE/publish/unpublish/invoke）。对接已完整实现的 FrontEnd 工具/任务/Agent 页。

全局约束：五层单向依赖 API→编排→服务→工具→存储；sessionless（幂等缓存/live-tail 为唯一内存态接缝）；trace_id 全链路；信封契约；resume 双轨（Accept 区分 SSE/JSON）；静态前缀字节稳定；错误码 40405/40903 新增、40402/40901/40902/60002 消费。

**本轮不做**（M2.5）：Docker 沙盒、MCP、tool_search 元工具、任务系统完整形态（M4）。

## M1 历史（已完成，勿重做）
T1-T13 + review-test-simplify gate 全部完成；start.cmd/start.sh 一键启动；git 到 aaa26a6 工作区干净。

## 任务清单（M2）
- [x] T1 错误码与配置（40405/40903 + task_confirm_ttl_hours=24）
- [x] T2 工具服务层（tool_definition repo + ToolService + tl_ id 派生 + registry set_enabled 同步桥）
- [x] T3 工具路由（/tools CRUD/test/search）
- [x] T4 执行器重试/幂等/沙盒守卫
- [x] T5 tool_execute 节点 require_confirm 分支 + finalize 透传 cancelled
- [x] T6 流式核心抽取（stream_core）+ chat 中断落任务 + resume_stream_events ★
- [x] T7 任务服务 + 后台运行器（task_run）+ 任务路由（双轨 resume + events 回放/live-tail）
- [x] T8 Agent 写接口 + 版本化 + invoke
- [x] T9 内置确认演示工具（tl_demo_notify）+ seed
- [x] T10 收尾 gate（ruff + 全量测试 ≥20 + README 接缝表 + 端到端验证）

## 执行记录（M2）
- T1 完成：40405/40903 + task_confirm_ttl_hours=24 ✅
- T2 完成：ToolDefinitionRepository + ToolService（tl_ id 派生/默认关闭/启停同步桥/echo test）+ serialize_tool_definition + registry.set_enabled；pytest 6 项新测试 ✅
- T3 完成：/tools CRUD/test/search 路由（search 在 {tool_id} 前）+ main.py 注册；httpx 实测 CRUD/echo/真执行/搜索/ACI/40405 全过 ✅
- T4 完成：executor 重试循环（指数退避+抖动，仅 handler 异常可重试）+ 幂等缓存（fingerprint/TTL/上限）+ 沙盒守卫 + ToolSpec.max_retries；pytest 8 项 ✅
- T5 完成：tool_execute require_confirm → interrupt(payload) → approved/denied 分支 + finalize 透传 status；图级测试 3 项（触发/续跑 done/拒绝 cancelled）✅；总测试 27 项
- T6 完成：stream_core.py 共享循环（tool_call.require_confirm 取自 spec / 跳过 cancelled tool_result / __interrupt__ 分支）+ chat_stream 重构 + resume_stream_events（UUID 转换/无会话守卫）；流层测试 3 项（中断落 Task/续流 done/拒绝 cancelled）+ chat_stream 帧序回归不变；总测试 30 项 ✅
- T7 完成：TaskService（状态机/live-tail/resume_precheck I8）+ TaskRepository + task_run.py 后台运行器 + /tasks 路由（双轨 resume + events 回放/live-tail，终态回放即关流）；pytest 5 项 ✅
- T8 完成：AgentService create/update/publish/unpublish/soft_delete/_snapshot（compute_prefix_hash）+ /agents 写路由 + invoke（agent_invoke_events 轻量路径）+ serialize_agent_version name；pytest 5 项 ✅；总测试 40 项
- T9 完成：tl_demo_notify（require_confirm=True, USER_COMMS）+ seed 泛化工具创建 + **修复 seed 缺 org 过滤**（测试数据污染导致 MultipleResultsFound）；种子双跑幂等 ✅；总测试 40 项
- T10 完成：README M2 接缝表 + 端到端验证（真实 DeepSeek）✅
  - 工具 CRUD/test/搜索、Agent 版本化 v1→v2→v3、任务提交→done、cancel 40902 全过
  - interrupt→resume 闭环：chat 流 message_start→tool_call→interrupt（带 task_id）→ resume 确认 → tool_result+token+done（任务 done）/ 拒绝 → 无 tool_result + 卡片 cancelled（任务 cancelled）✅
- ⚠ 深度坑（已修）：DeepSeek 推理模型（deepseek-v4-flash）多轮工具调用报 400 "reasoning_content must be passed back"——
  langchain-litellm 0.7.0 `_convert_message_to_dict` 丢 thinking 且不输出 reasoning_content，且 content 变字符串数组。
  → core/llm.py `_patch_reasoning_content_passthrough`（透传 reasoning_content + content 规范化为纯文本）；顺带 finalize 提取纯文本 content
- ⚠ 已修：task_run 图级异常（LLM 失败）→ stream_core 加 on_error 回调 → 任务置 failed（此前会永远卡 running）
- **M2 核心闭环全部完成**：T1-T10 ✅，40 项测试全绿 → review-test-simplify 收尾 gate：
  - Gate1 Test：40 项全过 ✅
  - Gate2 Review：两 agent 发现 11 项（4 Important + 3 Medium + 4 Low）——全部修复并验证 ✅
    - F1 JSON 轨 resume 读 pending_confirm.thread_id（此前 EmptyInputError→failed）✅
    - F2 time_now 去 idempotent（陈旧时间 bug）✅
    - F3 live-tail 订阅先于终态检查 + resume 推终态哨兵（events 流不挂死）✅
    - F4 runner 启动前重检 status==pending（取消竞态）✅
    - F5 resume_stream_events 加 on_error→failed ✅
    - F6 ToolService.update 同步运行时字段到 registry（patch_spec）✅
    - F7 lifespan DB→registry enabled 启动同步（停用不复活）✅
    - F8 thread 失效→40402 ✅ F9 版本序列化真实 graph_template/max_steps ✅
    - F10 resume on_final 重读任务防覆盖取消 ✅ F11 任务 input 提取 message 文本 ✅
  - 跳过（文档化接缝）：cancel 打断运行中图、同消息双确认、test 端点绕过确认、二次中断滞留原任务
  - 实测：JSON 轨 resume done + events 流即开即关 ✅；40 项测试全绿
  - Gate3 Simplify：4 agent 去重 11 项应用 / 4 项跳过（记录理由）✅
    - 应用：executor 缓存直返、共享 sse_emitter(core/events)、共享 build_initial_state + message_text(stream_core)、
      TaskService.resolve_resume_thread 单点解析、get_by_name O(1) 反向索引、agent flush 清理、resume 尾提交收敛、
      search 复用序列化、**ChatLiteLLM 子类替代全局 monkeypatch**（A2，实测多轮 DeepSeek 通过）
    - 跳过：values 模式（状态小+测试不耦合 checkpointer）、max_concurrency（计划设计延期）、
      DB 读时解析 registry（M2.5 重构）、终态处理器大重构（complete/fail 助手已缓解核心重复）
  - 最终：ruff clean + pytest 40/40 + 子类多轮验证 ✅ → M2 收尾完成
- **Bug 修复轮（2026-08-14 用户报告）**：
  1. 时间工具不可用：根因 = 启动同步全 org 遍历，32 个测试组织 enabled=false 行把 time_now 打成禁用
     → 修复 `sync_registry_from_db` 仅同步默认组织 + 清理 96 行测试污染 + 重跑种子；实测 chat 恢复 tool_call(time_now)→tool_result ✅
  2. 通知工具确认后执行结果不清：实为 time_now 禁用导致 invoke 只见 demo_notify（可调用与选中不符）；
     修复后通知助手 chat interrupt→resume 全闭环 tool_result(带结果)→done ✅
  3. 工具卡重试按钮无反应：前端 retry 事件无监听 → 接线 ToolCallCard→Bubble→List→ChatView，重试=重发最后一条用户消息；
     前端 vue-tsc 通过（FrontEnd 非 git 仓库，改动存盘）
  提交：947e0ec
