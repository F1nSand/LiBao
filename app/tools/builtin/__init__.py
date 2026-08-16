"""内置工具注册。M1 tl_time_now / M2 tl_demo_notify / M2.5 tl_tool_search / M3 tl_kb_search /
M3.5 tl_fetch_url + tl_analyze_image（docs 07 RM-8 / docs 04 F4）/ M4.5 tl_dispatch_subagent（单主 Agent 派发）。"""
from __future__ import annotations

from app.tools.builtin import (
    analyze_image,
    demo_notify,
    dispatch_subagent,
    fetch_url,
    initiate_demo,
    kb_search,
    time_now,
    tool_search,
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
            ),
            params_schema={
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
