import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging

setup_logging()


def _enforce_prod_safety() -> None:
    """Refuse to boot in prod with foot-gun defaults still in place."""
    if settings.APP_ENV.lower() != "prod":
        return
    bad: list[str] = []
    if settings.JWT_SECRET in {"change-me-in-prod", "please-change-me-in-prod", ""}:
        bad.append("JWT_SECRET is still the default")
    if "industria:industria" in settings.DATABASE_URL:
        bad.append("DATABASE_URL still uses the default 'industria:industria' password")
    if settings.N8N_WEBHOOK_SECRET in {"change-me-webhook", "replace-me", ""}:
        bad.append("N8N_WEBHOOK_SECRET is still the default")
    if "*" in settings.CORS_ORIGINS:
        bad.append("CORS_ORIGINS=['*'] is open to the world")
    if bad:
        msg = (
            "Refusing to start in APP_ENV=prod with insecure defaults:\n  - "
            + "\n  - ".join(bad)
            + "\nFix these in your .env (use `openssl rand -hex 48` for secrets) "
              "or set APP_ENV=dev to acknowledge."
        )
        raise RuntimeError(msg)


_enforce_prod_safety()

app = FastAPI(
    title="IndustriaCRM API",
    version="0.1.0",
    description="Enterprise CRM + ERP + AI for project-based industrial engineering.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)
app.include_router(api_router, prefix="/api/v1")


@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["meta"])
async def readyz():
    return {"status": "ready"}
