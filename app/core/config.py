"""应用配置（docs 01 §2 core/config.py）。

Pydantic Settings 从 .env 读取；get_settings() 为进程内单例。
本地单机化：.env 只放 API key / 模型项（无 DB/Redis/JWT 配置）。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- 通用 ----
    app_env: str = "dev"
    debug: bool = True
    base_url: str = "/api/v1"
    log_level: str = "INFO"

    # ---- 任务（M2 interrupt/resume）----
    # pending_confirm 载荷 TTL：过期后拒绝 resume（docs 01 §3.4 I8）
    task_confirm_ttl_hours: int = 24

    # ---- MCP（M2.5）----
    # 熔断（I7）：单源连续失败达阈值 → OPEN；冷却后 HALF_OPEN 放行一次
    mcp_breaker_threshold: int = 3
    mcp_breaker_cooldown_s: int = 60
    # 两段式 ACI 门控（docs 01 §7.1.1 A2）：启用工具数 ≤ 阈值 → 全量 ACI；超过 → tool_search + 选中注入
    aci_full_limit: int = 30

    # ---- 本地单机化（文件存储）----
    agent_data_dir: str = ".agent"  # 会话 JSONL / 记忆 md / 配置 json 根目录
    kb_root: str = "kb"  # KB 集合目录（index.json + documents/ + vectors.lance）
    frontend_dist: str = "frontend_dist"  # 前端构建产物（FastAPI 静态托管）

    # ---- LLM（LiteLLM）----
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek/deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = ""

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

    # ---- M3 附件（本地磁盘）----
    upload_dir: str = "uploads"
    max_upload_mb: int = 20

    # ---- fetch_url 内置工具（docs 07 RM-8）----
    fetch_url_denylist: list[str] = []  # 出站黑名单（默认空 = 全放行）；精确域名或 *.example.com 通配
    fetch_url_max_chars: int = 8000

    # ---- 工具结果摘要（executor._summarize）----
    # dict/list 输出 json 化后截断到此上限；str 输出原样透传不截断
    tool_result_max_chars: int = 8000

    # ---- M7-B 工作区 ----
    workspaces_root: str = "data/workspaces"  # 本地文件夹根（root_path 托管于此）
    command_review_model: str = ""  # Bash 命令语义审查模型（缺省复用主 LLM）

    # ---- M8 热点收集（GitHub）----
    github_token: str | None = None  # GitHub API token（.env GITHUB_TOKEN，缺省匿名 60 req/h 配额受限）
    github_proxy: str | None = None  # 访问 GitHub 的 HTTP 代理（如 http://127.0.0.1:7890），国内直连被墙时填
    github_mirror: str = "https://gh-proxy.com/"  # GitHub 镜像前缀（直连失败时匿名兜底；空串=禁用镜像）

    # ---- 时区（time_now 工具）----
    tz: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
