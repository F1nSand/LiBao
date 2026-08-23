"""内置工具注册。M1 tl_time_now / M2 tl_demo_notify / M2.5 tl_tool_search / M3 tl_kb_search /
M3.5 tl_fetch_url + tl_analyze_image（docs 07 RM-8 / docs 04 F4）/ M4.5 tl_dispatch_subagent（单主 Agent 派发）/
P4 tl_remember_memory + tl_recall_memory + tl_forget_memory（主动记忆全套）。"""

from __future__ import annotations

from app.tools.builtin import (
    analyze_image,
    calculator,
    datetime_calc,
    demo_notify,
    dispatch_subagent,
    fetch_url,
    file_ops,
    github_hotspot,
    initiate_demo,
    kb_search,
    load_skill,
    memory_tool,
    time_now,
    tool_search,
    unit_converter,
    weather,
    web_search,
)
from app.tools.registry import SandboxLevel, ToolSpec, ToolType, get, register


def _register(spec: ToolSpec) -> None:
    """幂等注册单个内置工具（重复调用不遮蔽，registry.register 本身仍拒同名覆盖）。"""
    if get(spec.id) is None:
        register(spec)


def register_builtin_tools() -> None:
    _register(
        ToolSpec(
            id="tl_time_now",
            name="time_now",
            description=(
                "获取当前时间。需要知道\"现在几点\"或当前日期时使用，返回 iso/local/tz。"
                "反例：不要用它回答历史日期或无关问题。"
            ),
            params_schema={"type": "object", "properties": {}, "required": []},
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,  # 时间查询不可去重（缓存会返回陈旧时间）
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=time_now.handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_demo_notify",
            name="demo_notify",
            description=(
                "发送一条通知消息。用于演示人工确认流程；发送为不可逆/对外副作用操作，"
                "需要用户确认后才真正执行。反例：不要用它回答时间或无关问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "通知内容"},
                    "channel": {"type": "string", "description": "发送渠道，默认 default"},
                },
                "required": ["message"],
            },
            tool_type=ToolType.USER_COMMS,
            enabled=True,
            require_confirm=True,
            idempotent=True,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=demo_notify.handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_tool_search",
            name="tool_search",
            description=(
                "搜索平台已注册的工具目录，返回匹配工具的名称与路由描述（何时用/何时别用），"
                "不含参数 schema。需要确定某个任务可用什么工具时先搜索再选择。"
                "反例：不要用它执行任务或回答非工具发现问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "自然语言搜索关键词"}},
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=tool_search.tool_search_handler,
            meta=True,  # 平台元工具：超限模式常驻注入 + 执行守卫放行（与编排两处谓词单一来源）
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_kb_search",
            name="kb_search",
            description=(
                "检索知识库（RAG）：按自然语言查询返回匹配的知识片段（含来源文档）。"
                "需要依据知识库内容回答时使用。反例：不要用它回答与知识库无关的问题。"
            ),            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自然语言检索问题"},
                    "collection_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "限定集合 id 列表；空 = 全部集合",
                    },
                    "top_k": {"type": "integer", "description": "返回条数，默认 5，上限 10"},
                    "semantic": {"type": "boolean", "description": "是否启用语义通道，默认 true"},
                    "bm25": {"type": "boolean", "description": "是否启用关键词通道，默认 true"},
                },
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=30000,
            handler=kb_search.kb_search_handler,
            meta=True,  # 平台元工具：RAG 检索始终对 LLM 可见（超限模式常驻注入，同 tool_search）
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_load_skill",
            name="load_skill",
            description=(
                "加载指定 skill 的完整操作步骤（正文）。当需要某 skill 的详细流程/步骤时，"
                "按 skill 名调用此工具取回正文（skill 名见 system_prompt 中「可用 Skills」列表）。"
                "反例：不要用它执行动作或回答与 skill 无关的问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "skill 名称（见 system_prompt 中可用 Skills 列表）"},
                },
                "required": ["name"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=load_skill.load_skill_handler,
            meta=True,  # 平台元工具：skill 正文加载始终对 LLM 可见（渐进式披露，docs 01 §4.2.1）
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_fetch_url",
            name="fetch_url",
            description=(
                "只读抓取网页内容（自动清洗正文）。需要访问外部 URL 获取信息时使用；"
                "受出站白名单限制。反例：不要用它执行写入/下载文件/访问白名单外域名。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要抓取的 http/https URL"},
                    "max_chars": {"type": "integer", "description": "正文截断长度，默认 8000，上限 20000"},
                },
                "required": ["url"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 默认关闭：管理员显式启用后才向 LLM 开放
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=fetch_url.handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_analyze_image",
            name="analyze_image",
            description=(
                "分析已上传的附件（按附件 id 返回分析结果：图片视觉降级文本 / 文本提取 / 文档元数据）。"
                "需要对已上传附件做内容理解时使用。反例：不要凭空调用，必须先上传附件拿到 attachment_id。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "string", "description": "已上传附件的 id（POST /uploads 返回）"},
                },
                "required": ["attachment_id"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 默认关闭
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=10000,
            handler=analyze_image.analyze_image_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_web_search",
            name="web_search",
            description=(
                "联网搜索：关键词 → 搜索结果列表（标题/链接/摘要）。需要获取最新网上信息、"
                "查找资料时使用；配合 fetch_url 打开具体页面。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回条数，默认 5，上限 10"},
                },
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 默认关闭：网络工具，管理员显式启用（出站默认全放行，除非黑名单）
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=20000,
            handler=web_search.web_search_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_weather",
            name="weather",
            description=(
                "查询天气：城市名/拼音/坐标 → 当前温度/天气/湿度/风。需要知道某地天气时使用。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名/拼音/坐标，如 Beijing 或 上海"},
                },
                "required": ["location"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 默认关闭：网络工具，管理员显式启用（出站默认全放行，除非黑名单）
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=weather.weather_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_calculator",
            name="calculator",
            description=(
                "安全算术计算器：计算 + - * / % 与括号表达式（如 (3+4)*2-1）。"
                "需要精确数学计算时使用。反例：不要用于日期/单位换算（用 datetime_calc/unit_converter）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "算术表达式（数字与 + - * / % 括号）"},
                },
                "required": ["expression"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=calculator.calculator_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_datetime_calc",
            name="datetime_calc",
            description=(
                "日期/时间计算：now（当前日期时间）、add_days（加/减天数）、weekday（星期几）、"
                "days_between（两日期间隔天数）。需要日期计算时使用。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["now", "add_days", "weekday", "days_between"]},
                    "date": {"type": "string", "description": "基准日期 YYYY-MM-DD，默认今天"},
                    "days": {"type": "integer", "description": "add_days 的天数（负数为减）"},
                    "other": {"type": "string", "description": "days_between 的另一日期"},
                },
                "required": ["op"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=datetime_calc.datetime_calc_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_unit_converter",
            name="unit_converter",
            description=(
                "单位换算：长度(length)/重量(weight)/温度(temperature)/速度(speed)。"
                "需要单位换算时使用（如 5 公里是多少米）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["length", "weight", "temperature", "speed"]},
                    "value": {"type": "number", "description": "数值"},
                    "from_unit": {
                        "type": "string",
                        "description": "源单位（m/km/cm/mm/mi/ft/in；kg/g/t/lb/oz；C/F/K；m/s/km/h/mph/kn）",
                    },
                    "to_unit": {"type": "string", "description": "目标单位"},
                },
                "required": ["category", "value", "from_unit", "to_unit"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=unit_converter.unit_converter_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_initiate_demo",
            name="initiate_demo",
            description=(
                "发起一个演示后台任务并立即返回占位（placeholder:true + job_ref，前端显示「处理中」），"
                "delay 秒后完成后台任务，回填真值 + 事件备注。适合演示工具级异步占位/回填流程。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "delay": {"type": "integer", "description": "后台任务延迟秒数，默认 3"},
                    "note": {"type": "string", "description": "任务备注（回填时展示）"},
                },
                "required": [],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,  # 后台任务有副作用不可去重
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,  # 立即返回占位，不阻塞
            handler=initiate_demo.initiate_demo_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_dispatch_subagent",
            name="dispatch_subagent",
            description=(
                "派发专家 subagent 完成专业子任务（subagent 有独立提示词与工具，只做该子任务，结论回传）。"
                "可选 subagent：资料调研 research（检索知识库/抓取网页汇总）、代码评审 code_review（审查代码）、"
                "方案评审 proposal_review（批判性评审方案）。需要专业分工时使用；派发后基于其结论继续回答。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "subagent": {
                        "type": "string",
                        "enum": ["research", "code_review", "proposal_review"],
                        "description": "要派发的 subagent 名称",
                    },
                    "task": {
                        "type": "string",
                        "description": "子任务描述（含足够上下文，subagent 上下文隔离只收此任务）",
                    },
                    "context": {
                        "type": "string",
                        "description": "可选：补充事实/文件路径等（默认任务文本已含则省略）",
                    },
                },
                "required": ["subagent", "task"],
            },
            tool_type=ToolType.AGENT_CONTROL,
            enabled=True,
            require_confirm=False,
            idempotent=False,  # 子任务执行有副作用不可去重
            sandbox=SandboxLevel.NONE,
            timeout_ms=180000,  # 嵌套 LLM 循环需放大（默认 30s 会掐断子循环）
            max_concurrency=2,
            handler=dispatch_subagent.dispatch_subagent_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_read_file",
            name="read_file",
            description=(
                "读取工作区内文件内容（路径相对工作区根）。需要查看项目文件内容时使用。"
                "反例：不要用它访问工作区外路径。"
            ),
            params_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对工作区根的文件路径"}},
                "required": ["path"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=file_ops.read_file_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_write_file",
            name="write_file",
            description=(
                "写/覆盖工作区内文件（路径相对工作区根，父目录自动创建）。需要创建或修改项目文件时使用。"
                "反例：不要用它写工作区外路径。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区根的文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=file_ops.write_file_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_edit_file",
            name="edit_file",
            description=(
                "编辑工作区内文件：把首次出现的 old_str 替换为 new_str（最稳妥的定向修改）。"
                "需要精确修改文件某处时使用。反例：不要用于整文件重写（用 write_file）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区根的文件路径"},
                    "old_str": {"type": "string", "description": "要替换的原文片段"},
                    "new_str": {"type": "string", "description": "替换后的新片段"},
                },
                "required": ["path", "old_str", "new_str"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=file_ops.edit_file_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_glob",
            name="glob",
            description=(
                "按文件名/通配模式搜索工作区内文件（如 '**/*.py'）。需要定位文件时使用。"
                "反例：不要用它搜索文件内容（用 grep）。"
            ),
            params_schema={
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "通配模式，如 *.py 或 **/*.md"}},
                "required": ["pattern"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=10000,
            handler=file_ops.glob_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_grep",
            name="grep",
            description=(
                "按内容搜索工作区内文件（正则/字面量，返回命中文件+行号+文本）。需要找含某内容的代码/文本时使用。"
                "反例：不要用它找文件名（用 glob）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则或字面量"},
                    "path": {"type": "string", "description": "可选：限定搜索的目录/文件（相对工作区根）"},
                },
                "required": ["pattern"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=file_ops.grep_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_bash",
            name="bash",
            description=(
                "在工作区目录内执行 shell 命令（先经语义审查，破坏性/越权/外传命令会被拦截）。"
                "需要跑脚本/构建/装依赖等无法用文件工具完成的动作时使用。反例：不要用它读写文件（用 read/write_file）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "cwd": {"type": "string", "description": "可选：相对工作区根的工作目录，缺省工作区根"},
                },
                "required": ["command"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,  # 语义审查是动态闸门（非静态确认）
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=130000,
            handler=file_ops.bash_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_github_trending",
            name="github_trending",
            description=(
                "抓取 GitHub trending 榜单（日/周/月榜，可过滤编程语言）。需要了解 GitHub 热门项目/热点时使用；"
                "结果自动落库到工作区 github-hotspot/，本地新鲜（<24h）时直接读回缓存。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                        "description": "时间范围，默认 daily",
                    },
                    "language": {"type": "string", "description": "可选：编程语言过滤，如 python"},
                    "spoken_language": {"type": "string", "description": "可选：口语代码，如 zh/en"},
                    "refresh": {"type": "boolean", "description": "强制刷新，忽略本地缓存，默认 false"},
                },
                "required": [],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 网络工具，默认关闭（约束优先，管理员显式启用）
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=30000,
            handler=github_hotspot.tl_github_trending_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_github_search",
            name="github_search",
            description=(
                "搜索 GitHub 仓库（官方 API，按 star 排序）。需要查找某个项目/领域有哪些开源仓库时使用；"
                "返回仓库名/链接/描述/star/fork/语言/topics（html_url 即跳转链接）。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如 llm agent framework"},
                    "limit": {"type": "integer", "description": "返回条数，默认 10，上限 100"},
                    "language": {"type": "string", "description": "可选：编程语言过滤，如 python"},
                },
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 网络工具，默认关闭
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=20000,
            handler=github_hotspot.tl_github_search_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_github_repo",
            name="github_repo",
            description=(
                "获取单个 GitHub 仓库概况（官方 API）：描述/star/fork/issues/语言/topics/license/主页 + 跳转链接。"
                "需要了解某个具体项目时使用；结果自动落库到工作区 github-hotspot/repos/。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "仓库 owner，如 langchain-ai"},
                    "repo": {"type": "string", "description": "仓库名，如 langgraph"},
                    "refresh": {"type": "boolean", "description": "强制刷新，忽略本地缓存，默认 false"},
                },
                "required": ["owner", "repo"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=False,  # 网络工具，默认关闭
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=20000,
            handler=github_hotspot.tl_github_repo_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_remember_memory",
            name="remember_memory",
            description=(
                "把一条信息写入长期记忆。用户明确说「记一下/记住」时，或对话中出现值得长期保留的"
                "用户偏好/个人背景/固定约束/项目决策。scope 默认 auto（工作区会话→项目记忆 md 文件，"
                "普通会话→全局记忆卡片）。反例：不要用它回答时间或无关问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记住的内容（用户表达的事实/决策）"},
                    "scope": {
                        "type": "string", "enum": ["auto", "global", "project"],
                        "description": "作用域，默认 auto",
                    },
                    "title": {"type": "string", "description": "标题（可选，默认取内容开头）"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                    "importance": {"type": "number", "description": "重要性 0-1（可选，默认 0.5）"},
                },
                "required": ["content"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,  # 可恢复（软删/版本化），不需确认
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=memory_tool.remember_memory_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_recall_memory",
            name="recall_memory",
            description=(
                "检索长期记忆：全局记忆（RAG 语义检索卡片，query 越贴近记忆内容越准）或项目记忆"
                "（工作区 md 关键词扫描）。对话需要记忆中的事实/偏好/项目决策时使用——自动注入"
                "未命中但你认为相关时主动查。scope 默认 auto。反例：不要用它搜索 KB 知识库或网页。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词/语义描述"},
                    "scope": {
                        "type": "string", "enum": ["auto", "global", "project"],
                        "description": "作用域，默认 auto",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认 5，上限 20"},
                },
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=True,  # 检索可去重
            sandbox=SandboxLevel.NONE,
            timeout_ms=15000,
            handler=memory_tool.recall_memory_handler,
            builtin=True,
        )
    )
    _register(
        ToolSpec(
            id="tl_forget_memory",
            name="forget_memory",
            description=(
                "删除/归档一条长期记忆。用户明确要求「忘掉/删掉某条记忆」时使用：global 按标题/内容"
                "匹配软删卡片（可恢复）；project 按文件名/标题匹配归档到 .trash（不硬删）。"
                "scope 默认 auto。反例：不要用它清理会话消息或 KB 文档。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要删除记忆的标题/关键词"},
                    "scope": {
                        "type": "string", "enum": ["auto", "global", "project"],
                        "description": "作用域，默认 auto",
                    },
                },
                "required": ["query"],
            },
            tool_type=ToolType.EXECUTION,
            enabled=True,
            require_confirm=False,  # 软删/归档可恢复
            idempotent=True,  # 重复删除无害（匹配不到则 0 条）
            sandbox=SandboxLevel.NONE,
            timeout_ms=10000,
            handler=memory_tool.forget_memory_handler,
            builtin=True,
        )
    )
