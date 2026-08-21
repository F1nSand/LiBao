"""应用配置（docs 01 §2 core/config.py）。

Pydantic Settings 从 .env 读取；get_settings() 为进程内单例。
所有密钥/账号类配置只放环境变量或密钥管理，不入库、不入代码。
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 默认 JWT 密钥仅限本地开发；非 dev 环境必须用环境变量显式覆盖（防伪造 token 击穿租户隔离）
DEFAULT_JWT_SECRET = "dev-only-change-me-in-prod-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- 通用 ----
    app_env: str = "dev"
    debug: bool = True
    # SQLAlchemy echo 独立于 debug：debug=true 时不再全量刷引擎 SQL 日志（启动同步会打印数千条）。
    # 需调 SQL 时显式设 SQL_ECHO=true。
    sql_echo: bool = False
    base_url: str = "/api/v1"
    log_level: str = "INFO"

    # ---- 认证 ----
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 720

    # ---- 任务（M2 interrupt/resume）----
    # pending_confirm 载荷 TTL：过期后拒绝 resume（docs 01 §3.4 I8）
    task_confirm_ttl_hours: int = 24

    # ---- MCP（M2.5）----
    # 熔断（I7）：单源连续失败达阈值 → OPEN；冷却后 HALF_OPEN 放行一次
    mcp_breaker_threshold: int = 3
    mcp_breaker_cooldown_s: int = 60
    # 两段式 ACI 门控（docs 01 §7.1.1 A2）：启用工具数 ≤ 阈值 → 全量 ACI；超过 → tool_search + 选中注入
    aci_full_limit: int = 30

    # ---- 数据存储 ----
    # SQLAlchemy（asyncpg 驱动）
    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agent"
    # LangGraph checkpointer（psycopg 驱动，与业务同库）
    checkpoint_dsn: str = "postgresql://agent:agent@localhost:5432/agent"
    redis_url: str = "redis://localhost:6379/0"

    # ---- LLM（LiteLLM）----
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek/deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = ""

    # ---- M3 Embedding（SiliconFlow，OpenAI 兼容）----
    # Qwen/Qwen3-Embedding-0.6B，维度 1024（与迁移 0004 的 vector(1024) 一致，见 models/kb.py EMBED_DIM）
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
    memory_trace_limit: int = 100  # maintenance 读取轨迹上限

    # ---- M3 知识库 ----
    kb_max_chunks: int = 2000  # 单文档分块上限（防 20MB 文本爆 embedding 预算）

    # ---- M3 附件（本地磁盘 MVP，MinIO 为 M4 接缝）----
    upload_dir: str = "uploads"
    max_upload_mb: int = 20

    # ---- fetch_url 内置工具（docs 07 RM-8）----
    # 出站白名单（fail-closed）：["*"] 放通全部仅限开发；空列表 = 全拒
    fetch_url_denylist: list[str] = []  # 出站黑名单（默认空 = 全放行）；精确域名或 *.example.com 通配
    fetch_url_max_chars: int = 8000

    # ---- M7-B 工作区 ----
    workspaces_root: str = "data/workspaces"  # 本地文件夹根（root_path 托管于此；MVP 单节点共享）
    command_review_model: str = ""  # Bash 命令语义审查模型（缺省复用主 LLM）

    # ---- M8 热点收集（GitHub）----
    github_token: str | None = None  # GitHub API token（.env GITHUB_TOKEN，缺省匿名 60 req/h 配额受限）
    github_proxy: str | None = None  # 访问 GitHub 的 HTTP 代理（如 http://127.0.0.1:7890），国内直连被墙时填

    # ---- 跨域 ----
    cors_origins: list[str] = ["http://localhost:5173"]

    # ---- 时区（time_now 工具）----
    tz: str = "Asia/Shanghai"

    @property
    def sync_checkpoint_dsn(self) -> str:
        """checkpointer 用 psycopg 驱动，剥掉 SQLAlchemy 的 +asyncpg 前缀。"""
        return self.checkpoint_dsn.replace("+asyncpg", "")

    @model_validator(mode="after")
    def _guard_prod_jwt_secret(self) -> "Settings":
        if self.app_env != "dev" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise ValueError("非 dev 环境必须显式设置 JWT_SECRET（默认密钥仅限本地开发）")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
