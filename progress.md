# 进度账本 — plan: C:\Users\Admin1\.claude\plans\agent-time-now-7ms-woolly-iverson.md

## 📮 前后端交接板（双方 agent 异步传纸条）
> 本会话开始先读本节 → 处理 → 划掉。格式：[状态] 日期 · 方向 | 事项 | 期望/实际。
> 方向：→ 后端（前端发现的契约缺口/后端 bug/需后端配合）；← 后端（后端给前端的事项）。

[open] 2026-08-16 · →后端 | GET /system/evals/sets 404 | 期望 EvalSet[]（docs/03 §5.8）。
      根因 Agent/app/api/routers/evals.py APIRouter() 缺 prefix="/system/evals"；数据形状已对齐，仅路径错位。
      修法：router = APIRouter(prefix="/system/evals")。修复后前端刷新自动恢复。
[done] 2026-08-16 · →后端 | 契约核验：5 组新接口仅 evals 有缺口，其余对齐 | 前端零改动。

---

> 对话界面优化：输入框修复 + 工具卡精简 + 流式气泡修复
> 项目无 git 仓库，跳过 commit；以 typecheck/test:unit/test:e2e 作为验证门禁

## 任务
- [x] T1 Fix1 输入框：ChatView composerDisabled 改流式状态 + useChatStream start/confirmInterrupt try/finally 兜底
- [x] T2 Fix2 工具卡：ToolCallCard 只显示名称+状态（隐藏 input/output/summary/duration）
- [x] T3 Fix3 气泡：useChatStream 文本段置顶唯一 + 无空播种 + done 回填 messageId；MessageList 防闪跳
- [x] T4 单测：useChatStream.spec 新增文本置顶用例 + resume 断言 messageId
- [x] T5 e2e：chat-stream.spec 工具卡断言改“完成” + composer textarea 恢复可用断言
- [x] T6 文档同步 + 全量验证（typecheck / test:unit / test:e2e）

## 执行日志
- 2026-08-14 计划批准，开始执行。
- 2026-08-14 T1-T6 全部完成。验证：
  - `npm run typecheck` → 干净
  - `npm run lint` → 0 errors（3 warnings 均为既有 any，非本次引入）
  - `npm run test:unit` → 63 PASS（11 文件；原 62 + 新增 1：message_start 无空播种 + tool_call 先于文本时文本段置顶）
  - `npx playwright test e2e/chat-stream.spec.ts` → 3 PASS（含：工具卡不再显示参数→断言“完成”；一轮/单轮完成后 composer textarea 恢复可用）
  - 文档同步：docs/02-frontend-design.md §6.2 ToolCallCard 描述 + §5.4.3 混排说明；CLAUDE.md “文本×工具卡混排”要点
  - 项目无 git 仓库，跳过 commit。
- 2026-08-14 review-test-simplify 三道 gate（Test/Review/Simplify 全过），用户批准修复 7 项：
  - P1 防闪跳改“同步追加”（删 messageId 匹配/回填）：MessageList 恢复 `!finished`；ChatView onPersistedMessage 同步 appendAssistantMessage；chat store 新增 appendAssistantMessage
  - P2 ToolCallCard 状态标签补 cancelled(已取消)/awaiting_confirm(待确认)，不再显示绿色“完成”
  - P4 e2e 用例1 加负断言 `not.toContainText('6*7')`
  - S1 删除 chat store 死 `streaming`/`setStreaming` + ChatView 3 处调用
  - S5 删除 ToolCallCard 未用 props input/output/summary/durationMs + MessageBubble 对应 4 处绑定
  - F 发送按钮绑定 composerDisabled（中断等待时不再“看似可用”）
  - P5 补静默关流 streaming 复位单测
  - 复核：typecheck ✓ / lint 0err / 64 单测 PASS / 3 e2e PASS / 拒绝分支工具卡显示“calculator | 已取消”
  - 跳过（记录不改）：try/finally 抽 wrapper、partialText 与 segments 重复、message_start 冗余 seed、retry 无处理器（既有）、contextMetrics/tokenUsage 无读者（契约预留）、scroll 与 useVirtualList 重复（既有）
  - 文档已同步（P6 误报）。
- 2026-08-14 新任务：长会话滚轮上滚“抽搐滚不上去”。
  - 根因：MessageList 手写 useVirtualList 虚拟滚动测量反馈循环（实测高度→平均高度→startIndex→offsetY 漂移），上滚时内容与原生滚动互相拉扯。
  - 用户确认“去掉虚拟滚动”。修复：
    - MessageList 直接平铺渲染全部消息（每页≤50）+ `content-visibility: auto`/`contain-intrinsic-size: auto 120px`；稳定 key；保留吸底 watch
    - 删除 src/composables/useVirtualList.ts + useVirtualList.spec.ts（全局无引用）
    - 文档同步 docs/02-frontend-design.md（§5.3 / §5.4.4 / §6.2 / FD-5 / 目录）
  - 验证：typecheck ✓ / lint 0err / 62 单测 PASS（删 useVirtualList.spec 2 条）/ 3 e2e PASS / DOM 验证无 .virtual-spacer、6 条消息平铺渲染、上滚/中/底 scrollTop 稳定不回落。
  - 不做：消息分页排序（mock 第 1 页=最旧 50 条，若真实后端>50 且不排序则最新不在第 1 页，属独立问题留待跟进）。
- 2026-08-14 新 bug：流式完成后文本气泡消失、工具卡仍在。
  - 根因：上一轮 P1“同步追加”直接用 done 的 `message`；真实后端 done 时 `content` 可能未就绪（空），append 后 MessageBubble 只渲染有内容的工具卡 → 文本气泡消失。
  - 修复（src/views/ChatView.vue onPersistedMessage）：append 时 content 兜底 = `m.content 有值 ? m.content : stream.state.partialText`；同时不再 done 后 refreshMessages（page1 分页会截断长会话最新消息），服务端一致性改由重进会话/刷新同步。删除 store 已无用的 `refreshMessages`。
  - 验证：typecheck ✓ / lint 0err / 62 单测 PASS / 3 e2e PASS / mock 多轮 DOM 验证每轮文本+工具卡都在、不截断。
  - 说明：真实后端空 content 场景无法用 mock 直接复现（mock 恒有 content），兜底逻辑由 partialText 单测 + 代码审查保证。
- 2026-08-15 新功能：响应式侧边栏自动收回（窗口 <960px）。
  - 用户确认：主侧边栏收成 64px 图标栏；ChatView 会话列表面板也要能收回。
  - 改动：
    - 新增 `src/composables/useMediaQuery.ts`（响应式 matchMedia）+ `src/constants/layout.ts`（NARROW_LAYOUT_MQ='(max-width: 960px)'）
    - `SidebarNav.vue`：`collapsed = isNarrow || userCollapsed`；折叠按钮改切 userCollapsed 且窄屏隐藏
    - `ConversationList.vue`：新增 `collapsed` prop，宽度过渡收起（220→0）
    - `ChatView.vue`：`convOpen` + watch(isNarrow) 自动收回/恢复；顶栏 Fold/Expand 切换按钮；`:collapsed="!convOpen"`
  - 测试：新增 `useMediaQuery.spec.ts`（3 条）+ `e2e/layout.spec.ts`（视口缩放断言收回/展开）
  - 验证：typecheck ✓ / lint 0err / 65 单测 PASS / 10 e2e PASS（auth+guards+chat-stream+layout）
  - 文档：docs/02-frontend-design.md §4.1 补响应式说明。
  - 不做：更窄完全隐藏+汉堡抽屉、表格横向溢出、会话列表宽度拖动。
- 2026-08-15 新功能：Agent 对话轨迹（Trajectory）查看页 — MVP。
  - 用户确认：新增接口 / 先做 MVP / 独立页 + Chat 入口。
  - 契约：新增 `GET /conversations/{id}/trajectory`（docs/03 §5.2.1），由 message+tool_calls 只读派生（docs/04 §3.2.1）。
  - 改动：
    - types/api.ts 加 TrajectoryToolCall/TrajectoryNode/TrajectoryDetail；api/trajectory.ts getTrajectory；api/index 导出
    - mock/server.ts 加 /conversations/:id/trajectory（空会话返回 200+空 nodes，不存在 404）
    - utils/trajectory.ts 折叠纯函数（Turn→Group→Cell，全局 #N、tool 按 position、空 content 省略、summary）；format.ts 加 formatTime
    - stores/trajectory.ts；router/routes.ts 加 /trajectory/:conversationId（隐藏菜单）；ChatView 加「轨迹」按钮
    - views/TrajectoryView.vue + components/trajectory/{TrajectoryTimeline,TrajectoryLedger,TrajectoryDetailPanel}.vue（时间轴 3 泳道 + sequence/duration 投影；台账分组/折叠/搜索/选中；详情标签页；可拖拽调宽）
  - 测试：utils/trajectory.spec.ts（10 条折叠规则）+ e2e/trajectory.spec.ts（深链 c_001/c_002、选中联动、搜索、返回）
  - 验证：typecheck ✓ / lint 0err / 75 单测 PASS / 12 e2e PASS / DOM 验证（3 泳道各 1 span、台账 3 行、详情入参、全部折叠、投影、Chat 轨迹按钮）
  - 文档：docs/03 §5.2.1 轨迹端点、docs/04 §3.2.1 只读派生模型、docs/02 §6.2/§6.3 组件与折叠规则。
  - 不做（记录）：框选/缩放/平移、time/actual 投影、diff、虚拟滚动、thinking/reasoning 展示（契约预留未落库）、compaction/steering/context。
- 2026-08-15 MVP → 完整版（用户要求"把mvp做成完整的"）：
  - 时间轴补全：`time`/`actual` 投影、滚轮缩放（以鼠标为锚）、右键拖拽平移、左键框选（选中区间首条）、点击空白选最近、双击/Esc 复位、搜索暗化非命中、aria-label
  - 台账：Cell 行 `content-visibility:auto` 屏外跳过渲染；选中行 `scrollIntoView` 滚动到可见区
  - 详情：tool 增加 `Schema` 标签（占位）；窄屏 <1100px 详情改浮层覆盖台账
  - 跨视图定位：`?focus=<toolCallId>` 深链自动选中并滚动
  - 文档：docs/02 §6.3 更新为完整交互说明
  - 测试：e2e 增 focus 深链 + 4 投影渲染；真机验证滚轮缩放/点击选中/框选/双击复位/点击空白选最近均生效
  - 验证：typecheck ✓ / lint 0err / 75 单测 PASS / 14 e2e PASS
  - 仍不做（数据模型无对应）：diff 标签（无 system 更新数据）、thinking/reasoning 展示（契约预留未落库）、compaction/steering/context 节点、时间轴"加载更早历史"按钮（轨迹接口一次返回全部）。
- 2026-08-15 清理遗留 dev server（5173-5177 全杀）+ 补齐数据模型缺失项（完整版）。
  - 契约：`TrajectoryNode.kind` 扩展 context/steering/compaction；新增 `thinking`/`diff` 字段；`TrajectoryDetail.has_more` + `?before_seq&limit` 分页（docs/03 §5.2.1、docs/04 §3.2.1）。
  - 折叠（utils/trajectory.ts）：context→当前 Turn contextCells（含 diff）；steering→开 Turn（userCell）；compaction→`Compaction <seq>` 组（compacted cell）；assistant 附 thinking；kindLane 泳道映射。
  - 新增 `utils/diff.ts`（行级 LCS 统一 diff，6 单测）。
  - mock（src/mock/trajectory.ts）：kind 映射 + c_001 注入 context(diff)/thinking/compaction；c_long 程序化长会话；before_seq/limit 分页 + has_more。
  - 组件：时间轴泳道 Input/Model/Tools + hasMore「…加载更早」按钮；台账渲染 contextCells；详情 思考/Diff 标签。
  - store/api：getTrajectory 分页参数；store.load/loadEarlier（prepend 累积）。
  - 验证：typecheck ✓ / lint 0err / 86 单测 PASS（含 5 新折叠用例 + 6 diff）/ 16 e2e PASS（含 context/compaction 渲染、c_long 加载更早、focus、4 投影）/ 真机 Diff 标签 + 思考标签 + 加载更早按钮均生效。
  - 清理：5173-5177 全部 dev server 已杀。
- 2026-08-15 布局重构（会话列表并入主侧边栏 + 设置子侧栏 + Chat 会话|轨迹切换）。
  - 用户确认：设置子栏=主侧栏右侧窄条；原 /settings 保留为子项；对话页窄屏保持展开。
  - 改动：
    - routes.ts：menuItems 层级化（设置带 children）+ SETTINGS_ROUTES/isSettingsRoute
    - 新增 SettingsSubNav.vue（176px 窄子栏，按角色过滤）；SidebarNav 重写（logo+折叠顶部、Agents/对话、会话列表区、知识库/设置底部）
    - App.vue 接设置子栏（flex 子元素，不遮挡）
    - ConversationList 深色侧栏化 + 自包含 store/router（select/create 导航 /chat）
    - 新增 TrajectoryPanel.vue（从 TrajectoryView 抽出工作区），TrajectoryView 改为复用
    - ChatView：去会话面板/Fold/跳页按钮；加 会话|轨迹 radio，轨迹内嵌 TrajectoryPanel
  - 关键修复：guard 刷新竞态（App onMounted hydrate 在途时 status=loading，守卫跳过 hydrate → 角色页刷新误跳 /chat；用 roleFromToken 兜底）。chat store 加 selectionToken（侧栏选会话才复位流式，创建会话不误杀）。
  - 测试：routes.spec（isSettingsRoute + 层级）；重写 guards/layout；新增 restructure.spec（会话|轨迹切换、侧栏新建导航、设置子栏）
  - 验证：typecheck ✓ / lint 0err / 89 单测 PASS / 20 e2e PASS / 真机布局验证（侧栏顺序、子栏 x=232 不重叠、轨迹内嵌 composer 隐藏）
  - 文档：docs/02 §4.1 布局图更新；tokens.css 加 --app-settings-subnav-width。
- 2026-08-15 UI 细化：设置气泡卡片 + 会话列表浅色框 + 主题配色切换器（用户三项优化）。
  - 设置子侧栏 → 气泡卡片：删除 SettingsSubNav.vue；SidebarNav 的「设置」按钮包 el-popover（right-start，172px），内容=设置组子项（/settings 的 children 按 canAccess 过滤），点子项跳转+气泡自动关；App.vue 恢复 `<SidebarNav/>`；isSettingsRoute 做按钮高亮。
  - 会话列表浅色框：tokens.css 加 `--app-sidebar-conv-bg:#26263a`；ConversationList `.conv-list` 用该变量 + 圆角（深侧栏 + 浅框一深一浅）。
  - 主题系统：新增 src/theme/themes.ts（ThemeDef + solidTheme 生成器 + 撞色手写 var 集 + hexMix/lighten/darken；applyTheme 写 :root、getStoredTheme/setStoredTheme localStorage key agent.theme、DEFAULT indigo）；9 套=6 纯色（靛蓝/墨蓝/翠绿/紫罗兰/赭橙/绯红，conv-bg=lighten(sidebar,0.06)）+3 撞色（黑白/浅红×浅蓝/红黄）。
  - ThemeSwitcher.vue（TopBar 通知左侧短袖按钮 + 气泡色块）→ TopBar.vue 插在 NotificationBell 前；main.ts mount 前 applyTheme(getStoredTheme()) 防闪色。
  - 清理：tokens.css 删残留 --app-settings-subnav-width（SettingsSubNav 已删，无引用）。
  - 测试：新增 themes.spec.ts（9 主题 id 唯一/必需 var/纯色 conv-bg≠bg/applyTheme+默认 stored）；e2e 更新 guards（`.settings-subnav`→`.settings-popover .sub-item`）、restructure（子侧栏→气泡：点开 5 项→点子项跳转）；新增 theme.spec.ts（短袖→翠绿→主色#22c55e+localStorage→刷新保留）。
  - 验证：typecheck ✓ / lint 0err / 93 单测 PASS / 21 e2e PASS。
  - 文档：docs/02 §4.1 布局图去设置子栏改气泡卡片 + 会话列表浅框 + TopBar 主题切换；§3 工程结构加 theme/；§6.2 加 ThemeSwitcher 行；新增 §6.4 主题系统（9 套表 + 实现 + 测试）。
- 2026-08-15 L1 微调：工作流分级（全局 CLAUDE.md + FrontEnd 末行同步）。
  - 三档流程入全局 CLAUDE.md（L1 微小/跳计划仅简易笔记+快速 Test+豁免 Simplify；L2 常规/轻量计划+完整流程；L3 大型/强制三段不可简化）+ 升级规则（深度超定档就地升级）+ 验证纪律（开发跑子集、收尾全量；影响面核查 grep+全量 tsc）。FrontEnd CLAUDE.md 末行指向三档模型。无代码改动，无需构建。
- 2026-08-16 前端接真实后端（纯前端，后端由另一 agent 推进，不动后端代码）。
  - 计划：C:\Users\Admin1\.claude\plans\sleepy-humming-sparrow.md（L2）
  - 决策：dev 保持 mock 默认；缺失接口前端优雅降级；Provider 表单暂缓。
  - 判别信号：真实后端未注册路由 → HTTP 404（非信封）；业务 404xx → HTTP 200+信封，不重叠 → 纯 404 检测不误伤。mock 全实现 → 永不触发。
  - 阶段 1 检测打标地基、阶段 2 SSE 防护、阶段 3 页面降级（trajectory/通知铃铛/用户 tab/系统 tab）。阶段 4 契约对齐验证待后端 :8000 可用（检查时未响应）。
  - 执行：
    - 阶段 1：availability.ts（FEATURE + featureForUrl/mark/isUnavailable/reset，模块 ref 单一事实源）+ http-envelope isNotImplementedError（HTTP 404 = 端点未实现，信封 404xx 仅显式「未实现」标记才打标）+ http.ts request(url,promise) 签名 + guarded fail-fast 短路（创建请求前拦截）+ http.spec 5 新用例。
    - 阶段 2：sse.ts openSseStream 404 打标；useSSE onError 未实现短路不重连；sse.spec 2 新用例。
    - 阶段 3：trajectory store notImplemented getter + load/loadEarlier 短路；TrajectoryPanel 空态分支；NotificationBell unavailable computed 隐藏铃铛 + 条件启 SSE；SettingsView 用户 tab catch + EmptyState（Provider 不动）；system store 3 per-feature getter + 吞未实现；SystemView 3 tab 空态。
    - 验证：typecheck ✓ / lint 0err（3 既有 any 警告）/ 100 单测 PASS（+7：http 5 + sse 2）/ 21 e2e PASS（mock 零影响）。
    - Review 门（feature-dev:code-reviewer）发现 2 项已修：
      - A 功能组粒度过粗：拆分 FEATURE（notificationsStream 独立于 notifications、systemTrace 独立于 systemLogs），子路由 404 不再折叠同组可用功能；FEATURE_ROUTES 更具体优先。sse.spec 断言同步更新。
      - B 降级路径 unhandled rejection：TraceTimeline 补 unavailable/loadFailed 状态 + swallowNotImplemented；SystemView onRunEval 包降级；SettingsView 4 个写操作包降级（deleteUser 成功返回 null，用 ===undefined 判未实现）。
    - Simplify 门（Reuse+Simplification）应用：合并 request(url,thunk)+删 fail-fast 死 toast 分支+一次算 feature；availability 加 isUrlUnavailable/markUnavailableForUrl 收敛三处路由映射；http-envelope 加 swallowNotImplemented 收敛 4 处 catch 惯用法；trajectory getter 改名 unavailable + guard 复用 reset；NotificationBell getToken hoist。跳过（记录）：SystemView 模板缩进未重排（功能正确、lint 干净）。
    - 新增 availability.spec（7 用例：路由映射优先级/URL 级封装/reset/Pinia getter 反应式）。
    - 最终 gate：typecheck ✓ / lint 0err / **107 单测 PASS**（+7 availability）/ 21 e2e PASS。
    - 阶段 4（契约对齐 + kb progress/tool_calls.position 归一化）待后端 :8000 运行后联调，当前未做臆测改动。

## 联调准备（2026-08-16 存档，阶段 4 执行清单）
- 前置：后端 :8000 运行；登录用**后端 seed 账号**（mock 的 admin/admin123 不适用）。
- 启动：`VITE_USE_MOCK=false npm run dev`（Vite proxy → :8000，无 rewrite）。
- 逐页核对（后端已有的 8 组）：登录/me/401 跳转；会话列表/新建/详情/分页；Chat SSE 发送→token→工具卡→done + 中断→确认→resume（interrupt 带 task_id）；任务提交/列表/取消/恢复/事件；Agent CRUD/发布/版本/试跑；工具列表/注册/开关/测试/搜索/MCP；KB 集合/上传/分块状态/重索引/混合检索；记忆列表/整理；附件上传→attachment_id→分析。
- 确认降级生效（后端缺失的 5 组）：轨迹页/内嵌面板空态、通知铃铛隐藏、设置用户 tab 空态、系统 3 tab 空态、trace 抽屉提示。
- 两个候选修复（实测确认偏差才做）：`src/api/kb.ts` normalizeProgress（后端 progress 可能字符串/布尔）；`src/api/chat.ts` tool_calls.position 兜底。
- 只改前端，不动 Agent/ 目录。

### 契约核验（2026-08-16，真实后端 :8000 实测，admin/admin123，前后端联调前置）
- ✅ 已对齐（形状与 types/api.ts + api 模块一致，前端零改动）：
  - auth/me；trajectory（含 before_seq/limit 分页；节点带 thinking/diff/trace_id/tool_calls）
  - notifications：REST 分页 + PATCH read + SSE `GET /notifications/stream`（HTTP 200 text/event-stream）
  - users（GET/POST/PATCH/DELETE，admin 403 兜底）；system/logs（分页 + trace_id/level 过滤）；system/cost
  - kb：collections/documents（**裸数组**，前端 listDocuments 已对齐）/status；`progress=number`（实测 100）✓
  - messages：分页 {items,total,page,page_size}；`tool_calls[].position` 实测存在（0）✓；tasks/agents/tools 200
- 候选修复判定：kb `normalizeProgress`、`tool_calls.position` 兜底 **均不需要**（后端已返回 number / position，defer 判断正确）。
- 🔴 契约缺口（后端 bug，勿前端绕开）：`/system/evals/*` 全部 404。
  - 根因：`Agent/app/api/routers/evals.py` 的 `router = APIRouter()` **缺 `prefix="/system/evals"`**，路由实际注册到 `/api/v1/sets`、`/api/v1/runs`、`/api/v1/system/evals/run` 之外的位置。
  - 期望：`GET /system/evals/sets`（docs/03 §5.8 + api/system.ts）返回 `EvalSet[]`；实际 404。
  - 数据形状已对齐（/api/v1/runs 返回含 progress/pass_rate 的 EvalRun），仅路径前缀错位。
  - **后端修法**：`router = APIRouter(prefix="/system/evals")`（docstring 已写明该前缀）。
  - 修复前：前端 SystemView 评估 tab 走降级空态「后端暂未实现评估接口」（HTTP 404 判据）；修复后刷新自动恢复，无需改前端。
- 本轮无前端代码改动（门禁维持上一轮全绿：typecheck / 107 单测 / 21 e2e）。
