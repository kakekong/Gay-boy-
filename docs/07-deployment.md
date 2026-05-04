# 07 — Deployment & Operations

## 7.1 Local development

```bash
cp infra/.env.example .env
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed
```

Services:
- API → http://localhost:8000 (`/docs` for Swagger)
- Frontend → http://localhost:5173
- n8n → http://localhost:5678
- Postgres → localhost:5432
- Redis → localhost:6379

## 7.2 Production (single-server)

- Reverse proxy: **nginx** with TLS (Let's Encrypt).
- Backend: gunicorn + uvicorn workers (`-w 4 -k uvicorn.workers.UvicornWorker`).
- Postgres: managed (RDS / Cloud SQL) recommended; daily backups.
- Object storage: S3 / Spaces for PDFs, drawings, attachments (`storage` adapter in `core/storage.py`).
- Secrets: AWS Secrets Manager / Doppler / .env on host.
- Monitoring: OpenTelemetry → Grafana / Datadog. Sentry for errors.

## 7.3 Production (multi-service)

| Service | Recommended placement |
|---|---|
| API | Kubernetes / ECS, 2+ replicas |
| Worker / Beat | dedicated pod, single beat |
| n8n | dedicated VM (stateful, with its own pg) |
| Postgres | managed |
| Redis | managed |
| Frontend | static — Cloudflare Pages / Netlify / S3+CloudFront |

## 7.4 Environment variables

See [`infra/.env.example`](../infra/.env.example) for the canonical list. Highlights:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | postgres URL (must support pgvector) |
| `REDIS_URL` | redis URL |
| `JWT_SECRET` | sign access tokens |
| `OPENAI_API_KEY` | LLM provider |
| `WA_PROVIDER` | `meta_cloud` (default) |
| `WA_TOKEN`, `WA_PHONE_ID` | WhatsApp Cloud creds |
| `N8N_WEBHOOK_SECRET` | shared secret, n8n ↔ API |
| `AI_BUDGET_IDR_MONTH` | LLM monthly cost cap |

## 7.5 Backups & DR

- Postgres: nightly base backup + WAL archive (PITR).
- Object storage: versioning enabled.
- Restore drill quarterly.
- n8n: export workflows weekly to git.

## 7.6 Security

- TLS 1.2+ only.
- HSTS, CSP, X-Frame-Options on nginx.
- Argon2 password hashing.
- JWT short TTL (15m) + refresh (7d).
- Rate limit on auth + AI endpoints (Redis token bucket).
- Webhook HMAC verification (n8n, payment, WA).
- Audit log immutable (append-only; nightly checksum).
- Field-level encryption for `customers.email`, `customers.phone` if regulated.

## 7.7 Observability

- `/healthz` and `/readyz` endpoints.
- Structured JSON logs, trace_id propagation.
- AI cost dashboard: aggregates `ai_call_log`.
- Slow query log enabled in Postgres.
