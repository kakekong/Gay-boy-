import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """On boot, make sure the DB schema exists.

    Creates any tables the running code knows about but the database is
    missing (e.g. ``entity_comments`` for the Discussion feature) so a fresh
    deploy or a Hugging Face Space rebuild "just works" without a separate
    ``python -m app.scripts.seed`` step. Idempotent — create_all only adds
    missing tables.

    Hardened against a HUNG database, not just a failing one: a TCP connect
    that neither succeeds nor errors (e.g. Neon mid-resume) used to block
    this forever, which kept the port closed and left the Space stuck on
    "Restarting" with an empty log. Now every attempt is capped at 90s,
    retried twice, and each step prints with flush so the container log
    always shows where boot is.
    """
    import asyncio

    from app.scripts.seed import ensure_schema

    for attempt in range(1, 4):
        print(f"[boot] database schema check (attempt {attempt}/3)…", flush=True)
        try:
            await asyncio.wait_for(ensure_schema(), timeout=90)
            print("[boot] schema ready — starting API.", flush=True)
            break
        except asyncio.TimeoutError:
            print(f"[boot] schema check timed out after 90s "
                  f"(attempt {attempt}/3) — database unreachable or hung.", flush=True)
        except Exception:
            logging.getLogger(__name__).exception("startup ensure_schema failed")
            print("[boot] schema check failed — starting API anyway "
                  "(see traceback above).", flush=True)
            break
    else:
        print("[boot] giving up on the schema check — starting API anyway; "
              "requests needing missing columns may error until the DB is back.",
              flush=True)

    # Web-push sweeper: delivers role-routed notifications to subscribed
    # devices even when no tab is open. Safe under multiple workers (a PG
    # advisory lock elects a single runner) and fully optional — with no
    # subscriptions it wakes, finds nothing, and sleeps.
    #
    # Its cadence is a database bill: every tick keeps a serverless Postgres
    # compute awake, so the interval is configurable and prints here — a
    # sweeper quietly running every 90 seconds is what emptied a month of
    # compute allowance and took the login screen down with it.
    sweeper_task = None
    try:
        from app.services.webpush import sweeper_loop
        sweeper_task = asyncio.create_task(sweeper_loop())
        if settings.WEBPUSH_SWEEP_SECONDS > 0:
            print(f"[boot] web-push sweeper started "
                  f"(every {settings.WEBPUSH_SWEEP_SECONDS}s, "
                  f"{settings.WEBPUSH_IDLE_SECONDS}s while nothing is "
                  f"subscribed).", flush=True)
        else:
            print("[boot] web-push sweeper off (WEBPUSH_SWEEP_SECONDS=0); "
                  "event-driven pushes still send.", flush=True)
    except Exception:
        logging.getLogger(__name__).exception("web-push sweeper failed to start")

    yield

    if sweeper_task:
        sweeper_task.cancel()


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
    title="Transmisi Eng API",
    version="0.1.0",
    description="Enterprise CRM + ERP + AI for project-based industrial engineering.",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
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
