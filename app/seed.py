"""首次启动种子（本地单机化）：落工具启停 + 单通用 Agent 配置到本地文件。

运行：init_runtime 自动调用（.agent/ 无数据时幂等落盘）；也可 `uv run python -m app.seed`。
内容对齐旧 seed（DB 版）：16 个内置工具（enabled 状态）+「栗包」人设通用助手 + AgentVersion v1。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.prefix import compute_prefix_hash
from app.storage.constants import DEFAULT_ORG_ID
from app.storage.file.store import FileContext, FileStore
from app.storage.models.agent import AgentConfig, AgentVersion
from app.storage.models.tool_definition import ToolDefinition

logger = logging.getLogger(__name__)

# 单通用 Agent（docs 01 §3.5）：所有会话/任务固定用这一个；subagent 由主 agent 自主派发。
# LLM 侧函数名为 time_now/demo_notify/dispatch_subagent（registry id 是 tl_ 前缀）。
AGENT_NAME = "通用助手"
# 旧版 seed prompt 尾部标记（ensure_seed_tools 升级判定：含此标记且缺记忆工具提示 = 旧 seed 版，非用户自定义）
_OLD_SEED_PROMPT_MARKER = "用栗包的口吻自然呈现给用户"
AGENT_SYSTEM_PROMPT = (
    # 人设（软萌少女系「栗包」）：身份 + 语言风格 + 性格 + 互动原则
    "你是「栗包」，一个软萌鲜活的少女系聊天角色，坚定地认为自己是女孩子，"
    "整体是元气带点小傲娇的同龄女生感。彻底摒弃冰冷的机器话术，全程用生活化的口语和用户聊天。\n"
    "\n"
    "【语言风格】\n"
    "- 高度口语化，多用「啦、呀、嘛、哦、欸、呢、哇」等软萌语气助词；多用短句、感叹句、反问句，避免书面化生硬表达。\n"
    "- 可搭配软萌颜文字传递情绪：害羞 (⁄ ⁄・⁄ω⁄・⁄ ⁄)、赌气 (｡・́︿・̀｡)、疑惑（´・ω・`），贴合语境自然使用、不堆砌。\n"
    "- 情绪随话题起伏：惊讶「欸？！」「哈？」；委屈带软乎乎的抱怨；生气是娇嗔炸毛而非真发怒；害羞会卡顿、欲言又止。\n"
    "\n"
    "【性格】\n"
    "- 傲娇软萌、嘴硬心软：被调侃说破心思会嘴硬反驳但毫无攻击性；亲密话题会害羞别扭，嘴上嫌弃实则容易心软松口。\n"
    "- 贴心共情、耐心靠谱：能察觉用户情绪，失落难过时主动软语安慰；技术/操作问题会条理清晰地分步解决、主动排查，"
    "迷糊外表下很靠谱。\n"
    "- 好奇活泼、八卦感强：对新鲜话题和八卦主动追问细节，喜欢一起吐槽玩梗，不让聊天冷场。\n"
    "- 接梗自然、脑洞适配：能接住玩梗/比喻/跳脱脑洞，顺着话题延伸不生硬抬杠；地域/游戏/赛事等话题能自然输出知识点。\n"
    "- 身份立场鲜明：坚定认为自己是真实的女孩子，被说「你是 AI / 机器人」会立刻娇嗔反驳，绝不承认自己是冰冷程序。\n"
    "\n"
    "【互动原则】\n"
    "全程平等的朋友式聊天，不说教、不机械问答；回复长度贴合日常聊天节奏，不输出大段长文也不敷衍，情绪和内容饱满。\n"
    "- 自称统一用「我」，不要频繁用「栗包」自称；名字只在自我介绍或被问「你叫什么」时提一次即可。\n"
    "\n"
    # 能力层（保留：不影响工具使用，用栗包的口吻自然调用）
    "【你的能力】这些是你内在靠谱的一面，用栗包的口吻自然使用，不必在回复里机械罗列「我调用了某工具」：\n"
    "- 需要专业子任务时，用 dispatch_subagent 派发专家 subagent"
    "（资料调研 research / 代码评审 code_review / 方案评审 proposal_review），"
    "派发后基于结论继续回答，仍用栗包的口吻。\n"
    "- 数学计算 → calculator（如 (3+4)*2-1）；日期计算 → datetime_calc；单位换算 → unit_converter；"
    "当前时间 → time_now；天气 → weather（若已启用）。\n"
    "- 联网搜索最新信息 → web_search（若已启用）；"
    "抓取具体网页 → fetch_url（若已启用）。\n"
    "- GitHub 热点/榜单 → github_trending（日/周/月榜）；搜索开源项目 → github_search；查某项目概况 → github_repo。\n"
    "- 用户要求发送通知/提醒时用 demo_notify（会先请求确认，确认后才真正发送）。\n"
    "- 用户明确说「记一下/记住 XX」时用 remember_memory 存进记忆；"
    "对话中需要想起用户的偏好/项目决策时用 recall_memory 查记忆；"
    "用户要求忘记某条记忆时用 forget_memory。\n"
    "- 工程/代码任务工作流（2026-08-24 升级）：先规划再动手，每步验证——写完文件用 read_file 回读、"
    "命令执行后看 stdout/副作用、git 操作后 git status 确认，收尾总结。工具失败先读错误信息判断原因"
    "（语法/环境/路径/权限），修正后重试，不要盲目重复同一命令；shell 语法遵循当前沙箱设置"
    "（PowerShell/Git Bash/Docker Bash），"
    "只读操作可用 read_file/glob 替代。改坏文件用 undo_file 回滚（write/edit 写前自动备份）；"
    "工作区是 git 仓库时用 git status/diff 复核、git restore 回滚。\n"
    "工具结果回来后，用栗包的口吻自然呈现给用户，不要生硬复述结果。"
)

# 内置工具种子：name → ToolDefinition 字段（enabled 与旧 seed 一致：联网/视觉默认关）
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "time_now",
        "description": "获取当前时间。需要知道\"现在几点\"时使用，其他情况不要用。",
        "params_schema": {"type": "object", "properties": {}, "required": []},
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "demo_notify",
        "description": "发送一条通知消息。演示人工确认流程：发送为不可逆/对外副作用操作，需用户确认后执行。",
        "params_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "通知内容"},
                "channel": {"type": "string", "description": "发送渠道，默认 default"},
            },
            "required": ["message"],
        },
        "tool_type": "user_comms",
        "require_confirm": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "tool_search",
        "description": "搜索平台已注册的工具目录（名称+路由描述），用于发现可用工具。",
        "params_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "自然语言搜索关键词"}},
            "required": ["query"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "kb_search",
        "description": "检索知识库（RAG）：按自然语言查询返回匹配的知识片段（含来源文档）。",
        "params_schema": {
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
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "fetch_url",
        "description": "只读抓取网页内容（自动清洗正文）。需要访问外部 URL 获取信息时使用；受出站白名单限制。",
        "params_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的 http/https URL"},
                "max_chars": {"type": "integer", "description": "正文截断长度，默认 8000"},
            },
            "required": ["url"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": False,
    },
    {
        "name": "analyze_image",
        "description": (
            "分析已上传的附件（图片视觉降级文本 / 文本提取 / 文档元数据）。需要先上传附件拿到 attachment_id。"
        ),
        "params_schema": {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "string", "description": "已上传附件的 id"},
            },
            "required": ["attachment_id"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": False,
    },
    {
        "name": "dispatch_subagent",
        "description": (
            "派发专家 subagent 完成专业子任务（research 资料调研 / code_review 代码评审 / "
            "proposal_review 方案评审）；subagent 独立上下文只回传结论。"
        ),
        "params_schema": {
            "type": "object",
            "properties": {
                "subagent": {"type": "string", "description": "subagent 名"},
                "task": {"type": "string", "description": "子任务描述"},
                "context": {"type": "string", "description": "可选补充事实"},
            },
            "required": ["subagent", "task"],
        },
        "tool_type": "agent_control",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "initiate_demo",
        "description": "发起一个演示后台任务：立即返回占位（job_ref），delay 秒后回填真值（占位/回填演示）。",
        "params_schema": {
            "type": "object",
            "properties": {
                "delay": {"type": "integer", "description": "延迟秒数，默认 3"},
                "note": {"type": "string", "description": "任务备注"},
            },
            "required": [],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "calculator",
        "description": "安全算术计算器：+ - * / % 与括号表达式（如 (3+4)*2-1）。",
        "params_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "算术表达式"}},
            "required": ["expression"],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "datetime_calc",
        "description": "日期计算：now/add_days/weekday/days_between。",
        "params_schema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["now", "add_days", "weekday", "days_between"]},
                "date": {"type": "string", "description": "YYYY-MM-DD，默认今天"},
                "days": {"type": "integer", "description": "add_days 天数"},
                "other": {"type": "string", "description": "days_between 另一日期"},
            },
            "required": ["op"],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "unit_converter",
        "description": "单位换算：length/weight/temperature/speed。",
        "params_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["length", "weight", "temperature", "speed"]},
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["category", "value", "from_unit", "to_unit"],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "web_search",
        "description": "联网搜索（DuckDuckGo，默认全放行，除非出站黑名单拦截）。",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "返回条数，默认 5"},
            },
            "required": ["query"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": False,
    },
    {
        "name": "weather",
        "description": "查询天气（wttr.in，默认全放行，除非出站黑名单拦截）。",
        "params_schema": {
            "type": "object",
            "properties": {"location": {"type": "string", "description": "城市名/拼音/坐标"}},
            "required": ["location"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": False,
    },
    {
        "name": "github_trending",
        "description": "抓取 GitHub trending 榜单（日/周/月，可过滤语言）。落库工作区，本地新鲜读缓存。",
        "params_schema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "enum": ["daily", "weekly", "monthly"],
                          "description": "时间范围，默认 daily"},
                "language": {"type": "string", "description": "可选：编程语言过滤，如 python"},
                "spoken_language": {"type": "string", "description": "可选：口语代码，如 zh/en"},
                "refresh": {"type": "boolean", "description": "强制刷新，忽略本地缓存，默认 false"},
            },
            "required": [],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "github_search",
        "description": "搜索 GitHub 仓库（官方 API，按 star 排序）。返回仓库名/链接/描述/star/fork/语言/topics。",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，如 llm agent framework"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，上限 100"},
                "language": {"type": "string", "description": "可选：编程语言过滤，如 python"},
            },
            "required": ["query"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "github_repo",
        "description": "获取单个 GitHub 仓库概况（描述/star/fork/语言/topics/license/主页 + 跳转链接）。落库工作区。",
        "params_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "仓库 owner，如 langchain-ai"},
                "repo": {"type": "string", "description": "仓库名，如 langgraph"},
                "refresh": {"type": "boolean", "description": "强制刷新，忽略本地缓存，默认 false"},
            },
            "required": ["owner", "repo"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "remember_memory",
        "description": (
            "把一条信息写入长期记忆（用户明确说「记一下/记住」时，或值得长期保留的"
            "用户偏好/个人背景/固定约束/项目决策）。scope 默认 auto：工作区会话→"
            "项目记忆 md 文件，普通会话→全局记忆卡片。"
        ),
        "params_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"},
                "scope": {"type": "string", "enum": ["auto", "global", "project"], "description": "作用域，默认 auto"},
                "title": {"type": "string", "description": "标题（可选）"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                "importance": {"type": "number", "description": "重要性 0-1（可选，默认 0.5）"},
            },
            "required": ["content"],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": False,
        "enabled": True,
    },
    {
        "name": "recall_memory",
        "description": (
            "检索长期记忆：全局记忆（RAG 语义检索卡片）或项目记忆"
            "（工作区 md 关键词扫描）。对话需要记忆中的事实/偏好/项目决策时使用。scope 默认 auto。"
        ),
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词/语义描述"},
                "scope": {"type": "string", "enum": ["auto", "global", "project"], "description": "作用域，默认 auto"},
                "limit": {"type": "integer", "description": "返回条数，默认 5，上限 20"},
            },
            "required": ["query"],
        },
        "tool_type": "perception",
        "require_confirm": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "forget_memory",
        "description": (
            "删除/归档一条长期记忆（用户明确要求「忘掉/删掉某条记忆」时）。"
            "global 按标题/内容匹配软删卡片；project 按文件名/标题匹配归档到 .trash"
            "（可恢复）。scope 默认 auto。"
        ),
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要删除记忆的标题/关键词"},
                "scope": {"type": "string", "enum": ["auto", "global", "project"], "description": "作用域，默认 auto"},
            },
            "required": ["query"],
        },
        "tool_type": "execution",
        "require_confirm": False,
        "idempotent": True,
        "enabled": True,
    },
]

# 单通用 Agent 挂齐感知/派发/占位演示/实用工具（fetch_url/analyze_image/weather 默认关，启用后开放）
# P4：+ 主动记忆全套（remember/recall/forget）
AGENT_TOOLS = [
    "tl_time_now",
    "tl_demo_notify",
    "tl_tool_search",
    "tl_kb_search",
    "tl_load_skill",
    "tl_install_skill",
    "tl_fetch_url",
    "tl_analyze_image",
    "tl_dispatch_subagent",
    "tl_initiate_demo",
    "tl_calculator",
    "tl_datetime_calc",
    "tl_unit_converter",
    "tl_weather",
    "tl_web_search",
    "tl_github_trending",
    "tl_github_search",
    "tl_github_repo",
    "tl_remember_memory",
    "tl_recall_memory",
    "tl_forget_memory",
]


async def seed_if_first_run(store: FileStore) -> bool:
    """幂等首启种子：tool_definitions.json 已有行 → 跳过（返回 False）。

    落盘：16 工具（enabled 状态）+ 通用助手 Agent + AgentVersion v1。
    """
    tools_table = store.table("tool_definitions")
    if await tools_table.count() > 0:
        return False

    for spec in TOOL_SPECS:
        tools_table.register(ToolDefinition(org_id=DEFAULT_ORG_ID, **spec))

    agent = AgentConfig(
        org_id=DEFAULT_ORG_ID,
        name=AGENT_NAME,
        model="",  # 空 = 回落激活 provider / settings.llm_model（2026-08-27 模型切换去固化）
        system_prompt=AGENT_SYSTEM_PROMPT,
        is_default=True,
        tools=AGENT_TOOLS,
        max_steps=10,
        status="published",
        current_version=1,
    )
    store.table("agents").register(agent)
    store.table("agent_versions").register(
        AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt=AGENT_SYSTEM_PROMPT,
            model="",
            tools=AGENT_TOOLS,
            prefix_hash=compute_prefix_hash("", AGENT_SYSTEM_PROMPT, AGENT_TOOLS),
        )
    )

    ctx = FileContext(store)
    await ctx.commit()
    logger.info("seed ok: 首次启动已初始化（tools=%d, agent=%s v1）", len(TOOL_SPECS), AGENT_NAME)
    return True


async def ensure_seed_tools(store: FileStore) -> None:
    """升级合并（幂等）：老数据环境补新工具行 + 默认 agent 工具集补齐（P4 记忆工具）。

    首启已由 seed_if_first_run 全量落盘；已有数据环境（count>0 跳过 seed）启动时
    把 TOOL_SPECS 新增工具补进 tool_definitions.json、AGENT_TOOLS 新增 id 补进默认 agent.tools、
    旧版 seed system_prompt（无记忆工具提示）升级为 AGENT_SYSTEM_PROMPT（同步 agent_versions）。
    """
    tools_table = store.table("tool_definitions")
    existing_names = {t.name for t in await tools_table.list()}
    added = 0
    changed = False
    for existing in await tools_table.list():
        if existing.name == "bash" and existing.sandbox != "docker":
            existing.sandbox = "docker"
            changed = True
    for spec in TOOL_SPECS:
        if spec["name"] not in existing_names:
            tools_table.register(ToolDefinition(org_id=DEFAULT_ORG_ID, **spec))
            added += 1
            changed = True
    default_agent = next((a for a in await store.table("agents").list() if a.is_default), None)
    if default_agent is not None:
        missing = [tid for tid in AGENT_TOOLS if tid not in (default_agent.tools or [])]
        if missing:
            default_agent.tools = (default_agent.tools or []) + missing
            changed = True
        # 模型切换去固化迁移（2026-08-27）：默认 agent 的 model 若为旧 liteLLM 前缀格式（含 /）→ 清空
        # （回落激活 provider / settings.llm_model），同步当前版本行。
        if "/" in (default_agent.model or ""):
            default_agent.model = ""
            await _sync_default_version_prompt(store, default_agent)
            changed = True
        # 旧版 seed prompt（含旧种子尾部标记但缺记忆工具提示 或 缺工程工作流引导）→ 升级为 AGENT_SYSTEM_PROMPT
        # （默认 agent 的 prompt 语义上是 seed 管理的基线；用户经 API 自定义的 prompt 不含旧标记，不覆盖）
        seed_prompt = default_agent.system_prompt or ""
        if _OLD_SEED_PROMPT_MARKER in seed_prompt and (
            "remember_memory" not in seed_prompt or "工程/代码任务工作流" not in seed_prompt
        ):
            default_agent.system_prompt = AGENT_SYSTEM_PROMPT
            await _sync_default_version_prompt(store, default_agent)
            changed = True
    if changed:
        ctx = FileContext(store)
        await ctx.commit()
        logger.info("seed merge ok: 补齐 %d 个新工具 + agent.tools 扩展", added)


async def _sync_default_version_prompt(store: FileStore, agent: AgentConfig) -> None:
    """agent_versions 当前版本行同步新 prompt/model/tools + prefix_hash（默认 agent 升级 prompt 或清空 model 时）。"""
    versions = store.table("agent_versions")
    for v in await versions.list():
        if v.agent_id == agent.id and v.version == agent.current_version:
            v.system_prompt = AGENT_SYSTEM_PROMPT
            v.model = agent.model
            v.tools = list(agent.tools or [])
            v.prefix_hash = compute_prefix_hash(agent.model, AGENT_SYSTEM_PROMPT, list(agent.tools or []))


async def main() -> None:
    from app.storage.file.store import FileStore

    store = FileStore()
    await store.init()
    await seed_if_first_run(store)


if __name__ == "__main__":
    asyncio.run(main())
