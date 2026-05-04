from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized configuration. Values come from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://industria:industria@db:5432/industriacrm"
    DATABASE_SYNC_URL: str = "postgresql+psycopg2://industria:industria@db:5432/industriacrm"

    # Cache / queue
    REDIS_URL: str = "redis://cache:6379/0"

    # Auth
    JWT_SECRET: str = Field(default="change-me-in-prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MIN: int = 15
    JWT_REFRESH_TTL_DAYS: int = 7

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # AI / LLM
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-large"
    AI_BUDGET_IDR_MONTH: int = 5_000_000  # cap

    # WhatsApp
    WA_PROVIDER: str = "meta_cloud"
    WA_TOKEN: str | None = None
    WA_PHONE_ID: str | None = None

    # Webhook secret (n8n shared)
    N8N_WEBHOOK_SECRET: str = "change-me-webhook"

    # Storage
    STORAGE_BACKEND: str = "local"  # local | s3
    STORAGE_LOCAL_DIR: str = "/data/storage"
    S3_BUCKET: str | None = None
    S3_REGION: str | None = None

    # Misc
    DEFAULT_CURRENCY: str = "IDR"
    TIMEZONE: str = "Asia/Jakarta"

    # Discount thresholds (override per tenant if needed)
    DISCOUNT_AUTO_MAX: float = 5.0
    DISCOUNT_MANAGER_MAX: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
