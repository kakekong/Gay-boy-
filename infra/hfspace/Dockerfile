# =====================================================================
# Hugging Face Spaces — Transmisi Eng backend
#
# This Dockerfile clones the FastAPI backend from GitHub at build time
# and starts uvicorn on port 7860 (HF Spaces' default port).
#
# Required HF Space variables/secrets (set in Settings → Variables):
#   APP_ENV             prod
#   DATABASE_URL        postgresql+asyncpg://… (from Neon)
#   DATABASE_SYNC_URL   postgresql+psycopg2://… (from Neon)
#   REDIS_URL           redis://default:…@…upstash.io:6379
#   JWT_SECRET          generate via `openssl rand -hex 48`
#   CORS_ORIGINS        ["https://your-app.vercel.app"]
#   STORAGE_LOCAL_DIR   /tmp/storage
#
# To pull a different branch, change GIT_BRANCH below or override
# via build arg.
# =====================================================================
FROM python:3.11-slim

ARG GIT_BRANCH=claude/enterprise-crm-erp-ai-IMGRg
ARG GIT_REPO=https://github.com/kakekong/Gay-boy-.git

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Cache-bust: re-fetch the branch HEAD metadata every build. When the latest
# commit changes, this layer's content changes and invalidates the cache for the
# git clone below — so a normal rebuild always pulls the newest code (no
# "Factory rebuild" needed). Without it, Docker reuses a stale clone layer.
ADD "https://api.github.com/repos/kakekong/Gay-boy-/commits/${GIT_BRANCH}" /tmp/_head.json
RUN git clone --branch ${GIT_BRANCH} --depth 1 ${GIT_REPO} repo
WORKDIR /app/repo/backend

RUN pip install --no-cache-dir -r requirements.txt

# HF Spaces routes external traffic to 7860 by default
ENV PORT=7860
EXPOSE 7860

# Persist uploads / cache in /tmp (HF free tier has no persistent disk;
# attachments will survive only until the next rebuild).
RUN mkdir -p /tmp/storage
ENV STORAGE_LOCAL_DIR=/tmp/storage

# Idempotent migrations + seed (uses APP_ENV=prod to skip demo accounts).
# Then start the API.
CMD ["sh", "-c", "python -m app.scripts.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
