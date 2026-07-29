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
    # 15 minutes was too aggressive in real use — sales kept getting kicked
    # out mid-call. The frontend also auto-refreshes on 401, so this is the
    # outer ceiling, not the typical lifetime.
    JWT_ACCESS_TTL_MIN: int = 720          # 12 hours
    JWT_REFRESH_TTL_DAYS: int = 30

    # Environment ("dev" seeds demo users; "prod" refuses defaults)
    APP_ENV: str = "dev"

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

    # Storage. "local" writes to STORAGE_LOCAL_DIR; "s3" writes to any
    # S3-compatible bucket. For Cloudflare R2 set S3_ENDPOINT_URL to
    # https://<account-id>.r2.cloudflarestorage.com and leave S3_REGION as
    # "auto"; for real AWS S3 leave the endpoint unset and name the region.
    # Reads always follow the path stored on the row, so switching backends
    # does not strand files written under the previous one.
    STORAGE_BACKEND: str = "local"  # local | s3
    STORAGE_LOCAL_DIR: str = "/data/storage"
    S3_BUCKET: str | None = None
    S3_REGION: str | None = "auto"
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    # Misc
    DEFAULT_CURRENCY: str = "IDR"
    TIMEZONE: str = "Asia/Jakarta"

    # Discount thresholds (override per tenant if needed)
    DISCOUNT_AUTO_MAX: float = 5.0
    DISCOUNT_MANAGER_MAX: float = 15.0

    # When true, EVERY submitted quotation requires director approval —
    # the discount-tier auto-approve / manager-approve shortcuts are
    # disabled. Set to false to fall back to the tiered thresholds above.
    QUOTATION_ALWAYS_DIRECTOR_APPROVAL: bool = True

    # Fixed company token baked into every auto-generated quotation number,
    # e.g. "TSE" → QT-TSE-2026-0005. Sales can still override the full number
    # per-quotation when needed (see QuotationCreate.number).
    QUOTATION_COMPANY_TOKEN: str = "TSE"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
