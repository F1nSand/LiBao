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
    base_url: str = "/api/v1"
    log_level: str = "INFO"

    # ---- 认证 ----
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 720

    # ---- 任务（M2 interrupt/resume）----
    # pending_confirm 载荷 TTL：过期后拒绝 resume（docs 01 §3.4 I8）
    task_confirm_ttl_hours: int = 24

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
    llm_embed_model: str = "text-embedding-3-small"

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
