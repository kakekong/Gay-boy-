---
title: Transmisi Eng API
emoji: 🏭
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Transmisi Eng — Backend

FastAPI backend for the Transmisi Eng CRM / ERP / AI system.

This Space pulls the code from GitHub at build time, so you don't push
the FastAPI source here — you only keep this `Dockerfile` and this
`README.md` in the Space repo.

## Live endpoints
- `GET  /healthz` → `{"status":"ok"}`
- `GET  /readyz`  → `{"status":"ready"}`
- `GET  /docs`    → OpenAPI / Swagger

## Required secrets
Set these in **Settings → Variables and secrets**:

| Key | Value |
|---|---|
| `APP_ENV` | `prod` |
| `DATABASE_URL` | `postgresql+asyncpg://…` (from Neon) |
| `DATABASE_SYNC_URL` | `postgresql+psycopg2://…` (from Neon) |
| `REDIS_URL` | `redis://default:…@…upstash.io:6379` |
| `JWT_SECRET` | `openssl rand -hex 48` |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` |
| `STORAGE_LOCAL_DIR` | `/tmp/storage` |

## Updating
The Dockerfile cache-busts the `git clone` against the branch HEAD, so after
you push to GitHub on the tracked branch, a normal **Rebuild** picks up the new
code (the clone layer invalidates when the latest commit changes).

If the API ever looks stuck on old code, use **Settings → Factory rebuild** to
force a no-cache build. Startup runs `python -m app.scripts.seed`, which applies
the idempotent DB migrations, so schema changes land automatically.

> ⚠️ The Space repo keeps only this `Dockerfile` + `README.md`. If you update
> the Dockerfile in the GitHub repo (`infra/hfspace/Dockerfile`), copy the
> change into the Space repo for it to take effect.
