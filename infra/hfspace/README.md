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
When you push new code to GitHub on the tracked branch, click
**Restart Space** in the HF UI to rebuild and pick it up.
