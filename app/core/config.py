"""应用配置（docs 01 §2 core/config.py）。

Pydantic Settings 从 settings.json（~/.LiBao，主）与 .env（后备）读取；get_settings() 进程内单例。
2026-08-25：数据目录从项目根迁到用户全局 ~/.LiBao（对齐 Claude Code ~/.claude；打包后源码只读、数据全在用户目录）。
"""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# 用户全局数据根（2026-08-25：会话/记忆/配置/工作区/知识库/附件全在此，源码只读后数据不随代码更新丢失）
_LIB = str(Path.home() / ".LiBao")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """配置优先级（2026-08-25）：显式传参（init）> ~/.LiBao/settings.json（用户全局，主）> .env（后备）。

        settings.json 用字段名（snake_case，如 llm_api_key）；.env 用大写 env 名（LLM_API_KEY）。
        源码只读后 .env 不可写，用户改 ~/.LiBao/settings.json。
        """
        lib_json = Path(_LIB) / "settings.json"
        if lib_json.is_file():
            return (init_settings, JsonConfigSettingsSource(settings_cls, json_file=lib_json), dotenv_settings)
        return (init_settings, dotenv_settings)

    # ---- 通用 ----
    app_env: str = "dev"
    debug: bool = True
    base_url: str = "/api/v1"
    log_level: str = "INFO"

    # ---- 任务（M2 interrupt/resume）----
    # pending_confirm 载荷 TTL：过期后拒绝 resume（docs 01 §3.4 I8）
    task_confirm_ttl_hours: int = 24

    # ---- Docker 沙箱（仅 tl_bash；不自动拉取、不宿主回退）----
    sandbox_docker_cli: str = "docker"
    sandbox_docker_image: str = "libao-sandbox:py312-v1"
    sandbox_docker_memory: str = "512m"
    sandbox_docker_cpus: str = "1"
    sandbox_docker_pids_limit: int = Field(default=128, gt=0)
    sandbox_docker_tmpfs_mb: int = Field(default=64, gt=0)

    @field_validator("sandbox_docker_memory")
    @classmethod
    def _validate_docker_memory(cls, value: str) -> str:
        if not re.fullmatch(r"[1-9]\d*(?:\.\d+)?(?:b|k|m|g|t)?", value.strip().lower()):
            raise ValueError("sandbox_docker_memory 必须是正的 Docker 内存值，例如 512m")
        return value

    @field_validator("sandbox_docker_cpus")
    @classmethod
    def _validate_docker_cpus(cls, value: str) -> str:
        try:
            if float(value) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("sandbox_docker_cpus 必须是正数") from exc
        return value

    # ---- MCP（M2.5）----
    # 熔断（I7）：单源连续失败达阈值 → OPEN；冷却后 HALF_OPEN 放行一次
    mcp_breaker_threshold: int = 3
    mcp_breaker_cooldown_s: int = 60
    # 两段式 ACI 门控（docs 01 §7.1.1 A2）：启用工具数 ≤ 阈值 → 全量 ACI；超过 → tool_search + 选中注入
    aci_full_limit: int = 30

    # ---- 用户全局数据目录（~/.LiBao，对齐 ~/.claude）----
    agent_data_dir: str = _LIB  # 会话 JSONL / 记忆 md / 配置 json 根目录
    kb_root: str = f"{_LIB}/kb"  # KB 集合目录（index.json + documents/ + vectors.lance）
    cache_dir: str = f"{_LIB}/cache"  # 临时会话工作区（非工作区对话的文件落地；可 TTL 清理）
    cache_ttl_days: int = 7  # 临时会话工作区保留天数（超过即后台清理，见 core/session_cache.py）
    frontend_dist: str = "frontend_dist"  # 前端构建产物（FastAPI 静态托管，源码目录）

    # ---- LLM（纯 OpenAI 协议，2026-08-27）----
    # 模型名裸写（gpt-4o / deepseek-chat），base_url 为 OpenAI 兼容 base（ChatOpenAI 自动拼 /chat/completions）
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = ""
    # 视觉能力声明（多模态适配 2026-08-27）：激活 provider 的 capabilities 推导——
    # ["vision"]→True、其他非空→False、空/无激活 provider→None（回落 core/vision.py pattern 判定）
    llm_vision_declared: bool | None = None
    # 单轮图片总预算（原始字节 MB；b64 后请求体 ≈ ×1.33）：超限自动跳过并在消息注记声明被剔张数
    image_total_budget_mb: int = 20

    # ---- M3 Embedding（SiliconFlow，OpenAI 兼容）----
    # Qwen/Qwen3-Embedding-0.6B，维度 1024（与 LanceDB schema 一致，见 models/kb.py EMBED_DIM）
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str = ""
    embedding_batch_size: int = 32
    embedding_timeout_s: int = 60

    # ---- M3 Rerank（SiliconFlow，复用 embedding 的 base_url/api_key，同一家供应商）----
    rerank_model: str = "Qwen/Qwen3-Reranker-0.6B"

    # ---- M3 记忆 ----
    memory_inject_limit: int = 5  # 每轮注入卡片上限（docs 01 §8.2）
    memory_card_max_chars: int = 500  # 单卡片注入序列化上限
    memory_maintenance_limit: int = 100  # maintenance 读取最近 messages 上限
    # ---- 主动记忆（自动提取分支，docs 01 §8.3）----
    memory_extract_enabled: bool = True  # 对话流结束后台提取长期记忆总开关
    memory_extract_model: str = ""  # 提取判定模型（缺省复用主 LLM）

    # ---- M3 知识库 ----
    kb_max_chunks: int = 2000  # 单文档分块上限（防 20MB 文本爆 embedding 预算）

    # ---- M3 附件（本地磁盘，~/.LiBao/uploads）----
    upload_dir: str = f"{_LIB}/uploads"
    max_upload_mb: int = 20

    # ---- fetch_url 内置工具（docs 07 RM-8）----
    fetch_url_denylist: list[str] = []  # 出站黑名单（默认空 = 全放行）；精确域名或 *.example.com 通配
    fetch_url_max_chars: int = 8000

    # ---- 工具结果摘要（executor._summarize）----
    # dict/list 输出 json 化后截断到此上限；str 输出原样透传不截断
    tool_result_max_chars: int = 8000

    # ---- M7-B 工作区（~/.LiBao/workspaces）----
    workspaces_root: str = f"{_LIB}/workspaces"  # 本地文件夹根（root_path 托管于此）
    # 全局 skills 根目录（<root>/<name>/SKILL.md 自动发现；expanduser 解析——打包后为 ~/.LiBao/skills）
    skills_root: str = "~/.LiBao/skills"
    command_review_model: str = ""  # [deprecated 2026-08-25] 旧 litellm 审查通道已废弃，改用 BASH_REVIEW_* curl 通道

    # ---- Bash 语义审查（2026-08-25 独立 curl LLM 通道，docs 01 §7.8）----
    # 云端独立 key 直连（bash+curl 执行，与应用内主 LLM 通道解耦）；未配置 endpoint → 降级规则快速通道
    bash_review_enabled: bool = True  # 总开关（false = 完全走规则快速通道，不做 curl）
    bash_review_endpoint: str = ""  # 审查 LLM OpenAI 兼容 endpoint（必配才启用 curl 审查）
    bash_review_api_key: str = ""  # 独立 key（只进 .env；命令内容会外发到此 LLM）
    bash_review_model: str = ""  # 模型名（传入请求 body，多数 endpoint 需填）
    bash_review_timeout: int = 15  # curl --max-time（秒）
    bash_review_connect_timeout: int = 5  # curl --connect-timeout（秒）
    bash_review_proxy: str = ""  # 显式 HTTP 代理（curl 不读 Windows 系统代理，云端 endpoint 需配）
    bash_review_breaker_threshold: int = 3  # 熔断阈值：审查通道连续失败次数
    bash_review_breaker_cooldown_s: int = 60  # 熔断冷却期（秒），过后 HALF_OPEN 试水
    # 审查不可用时允许放行的最高风险档（low/medium/high；high 档默认 fail-close）
    bash_review_failopen_max_grade: str = "medium"

    # ---- M8 热点收集（GitHub）----
    github_token: str | None = None  # GitHub API token（.env GITHUB_TOKEN，缺省匿名 60 req/h 配额受限）
    github_proxy: str | None = None  # 访问 GitHub 的 HTTP 代理（如 http://127.0.0.1:7890），国内直连被墙时填
    github_mirror: str = "https://gh-proxy.com/"  # GitHub 镜像前缀（直连失败时匿名兜底；空串=禁用镜像）

    # ---- 时区（time_now 工具）----
    tz: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
