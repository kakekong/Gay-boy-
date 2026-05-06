# 07 — Deployment & Operations

> 🟢 **Looking for the easy step-by-step?** See [`INSTALL.md`](../INSTALL.md)
> at the project root — it's written for non-technical readers.
>
> This doc is the **technical reference**: production hardening, environment
> variables, observability, backups, scaling.

---

## 7.1 Two ways to run it

| Mode | Use when | Where |
|---|---|---|
| **Single-host Docker Compose** | < 50 users, 1 server | `infra/docker-compose.yml` |
| **Multi-service / Kubernetes** | High availability, > 50 users | adapt manifests below |

---

## 7.2 Local / single-host (Docker Compose)

### Bring it up
```bash
cp infra/.env.example .env
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

### Initialize schema + demo data (first time only)
```bash
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed
```

### Endpoints
| Endpoint | URL |
|---|---|
| Frontend | <http://localhost:5173> |
| API + Swagger | <http://localhost:8000/docs> |
| n8n editor | <http://localhost:5678> |
| Postgres | `localhost:5432` |
| Redis | `localhost:6379` |

### Common ops
```bash
# Tail logs
docker compose -f infra/docker-compose.yml logs -f api worker

# Restart one service after a code change
docker compose -f infra/docker-compose.yml restart api

# Run a one-off command
docker compose -f infra/docker-compose.yml exec api alembic revision --autogenerate -m "msg"

# Wipe & rebuild (DESTROYS DATA)
docker compose -f infra/docker-compose.yml down -v
```

---

## 7.3 Production checklist

Before going live, verify each item below.

### Identity & secrets
- [ ] `JWT_SECRET` is a fresh 48+ byte random string (`openssl rand -hex 48`)
- [ ] `POSTGRES_PASSWORD` rotated from default
- [ ] `N8N_WEBHOOK_SECRET` rotated from default
- [ ] `N8N_BASIC_AUTH_PASSWORD` rotated from default
- [ ] Demo users (`*@demo.local`) deleted or disabled
- [ ] Real users seeded with strong passwords (Argon2 hashed)
- [ ] Secrets stored outside the repo (Doppler / AWS SSM / Hashicorp Vault)

### Network
- [ ] Postgres port (5432) NOT exposed to the internet
- [ ] Redis port (6379) NOT exposed to the internet
- [ ] API only reachable through nginx (locked to 127.0.0.1:8000 in compose)
- [ ] n8n behind basic-auth and TLS
- [ ] CORS_ORIGINS narrowed to your real frontend hostname

### TLS & security headers
- [ ] Let's Encrypt certificate via certbot, auto-renew enabled
- [ ] HSTS header (1 year, includeSubDomains)
- [ ] CSP, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy
- [ ] Webhook signature verification active (`X-Webhook-Secret`)
- [ ] Rate limit on `/auth/login` and `/ai/*` (Redis token bucket)

### Backups & DR
- [ ] Postgres nightly base backup + WAL archiving (PITR)
- [ ] Object storage versioning on
- [ ] Restore drill performed
- [ ] n8n workflows exported to git weekly

### Observability
- [ ] OpenTelemetry traces flowing to Grafana / Datadog
- [ ] Sentry DSN configured for both API and frontend
- [ ] `/healthz` and `/readyz` monitored externally (UptimeRobot, Better Stack, etc.)
- [ ] AI cost dashboard + monthly budget alarm

---

## 7.4 Recommended infrastructure

### Single-host (5–20 users)
- 1× **2 vCPU / 4 GB RAM** VM (Hetzner CX22, DO $12, Lightsail, etc.)
- Managed Postgres (or pgvector container with daily backup)
- Cloudflare in front for caching + DDoS protection
- ~$15–25/month all-in

### Multi-service (> 20 users / HA)

| Component | Where |
|---|---|
| `api` | Kubernetes Deployment, 2+ replicas, HPA on CPU |
| `worker` | Deployment, 1–4 replicas |
| `beat` | StatefulSet **single replica** (must be exactly one) |
| `frontend` | Static — Cloudflare Pages / Netlify / S3 + CloudFront |
| `db` | Managed Postgres 15 with pgvector (RDS, Cloud SQL, Aiven) |
| `cache` | Managed Redis (ElastiCache, Upstash) |
| `n8n` | Single VM, persistent volume + its own Postgres |
| `object storage` | S3 / GCS / R2 with versioning |
| `ingress` | nginx-ingress / ALB with TLS termination |

### Resource sizing baseline

| Service | CPU | Memory |
|---|---|---|
| api (per replica) | 0.5 vCPU | 512 MB |
| worker | 0.5 vCPU | 512 MB |
| beat | 0.1 vCPU | 128 MB |
| db | 1 vCPU | 2 GB |
| cache | 0.1 vCPU | 256 MB |
| n8n | 0.5 vCPU | 512 MB |

---

## 7.5 Environment variables (canonical)

See [`infra/.env.example`](../infra/.env.example) for the full list. Highlights:

| Variable | Purpose | Example |
|---|---|---|
| `DATABASE_URL` | async Postgres URL (must support pgvector) | `postgresql+asyncpg://user:pass@db:5432/industriacrm` |
| `DATABASE_SYNC_URL` | sync URL (used by Alembic) | `postgresql+psycopg2://...` |
| `REDIS_URL` | Redis URL | `redis://cache:6379/0` |
| `JWT_SECRET` | sign access tokens | 48-byte random hex |
| `JWT_ACCESS_TTL_MIN` | access token TTL | `15` |
| `JWT_REFRESH_TTL_DAYS` | refresh token TTL | `7` |
| `OPENAI_API_KEY` | LLM provider | `sk-…` |
| `OPENAI_MODEL` | chat model | `gpt-4o-mini` |
| `OPENAI_EMBED_MODEL` | embedding model | `text-embedding-3-large` |
| `AI_BUDGET_IDR_MONTH` | monthly LLM cost cap | `5000000` |
| `WA_PROVIDER` | WhatsApp provider | `meta_cloud` |
| `WA_TOKEN`, `WA_PHONE_ID` | WhatsApp Cloud creds | from Meta dev portal |
| `N8N_WEBHOOK_SECRET` | shared secret n8n ↔ API | random hex |
| `STORAGE_BACKEND` | `local` or `s3` | `s3` |
| `S3_BUCKET`, `S3_REGION` | object storage | `industriacrm-prod`, `ap-southeast-1` |
| `DEFAULT_CURRENCY` | display currency | `IDR` |
| `TIMEZONE` | server timezone | `Asia/Jakarta` |
| `DISCOUNT_AUTO_MAX` | auto-approve threshold | `5` |
| `DISCOUNT_MANAGER_MAX` | manager threshold | `15` |
| `CORS_ORIGINS` | allowed frontend origins | `["https://crm.yourco.com"]` |

---

## 7.6 Backups & disaster recovery

### Postgres
```bash
# Nightly logical backup (cron 02:00)
docker compose -f infra/docker-compose.yml exec -T db \
  pg_dump -U industria industriacrm | gzip > "/backups/db-$(date +%F).sql.gz"

# Restore
gunzip -c db-2026-05-04.sql.gz | docker compose -f infra/docker-compose.yml exec -T db \
  psql -U industria industriacrm
```

For PITR (point-in-time recovery), use a managed Postgres or run pgBackRest.

### Object storage
Enable bucket versioning + lifecycle (move to cold storage after 90 days).

### n8n workflows
Schedule a weekly export of `/home/node/.n8n` and commit JSON to git.

### Restore drill
Quarterly: spin up a staging stack from latest backup, log in as Director,
verify customers/quotations/AR aging match production figures.

---

## 7.7 Security hardening

- **TLS only** (HTTP → HTTPS 301 in nginx).
- **Argon2** password hashing (already wired in `core/security.py`).
- **JWT short TTL** (15 min access, 7 day refresh) with rotation on refresh.
- **Rate limit** auth and AI endpoints via Redis (`slowapi` or custom middleware).
- **Webhook HMAC** verification for n8n, payment, WhatsApp inbound (already in `webhooks.py`).
- **Audit log immutable** — append-only, with nightly checksum job.
- **Field-level encryption** for `customers.email/phone` if regulated (Indonesia PDP Law).
- **Container hardening**: non-root user, read-only root filesystem, drop caps.
- **Image scanning**: Trivy in CI, fail on HIGH+ CVEs.
- **Dependabot / renovate** for ongoing patches.

---

## 7.8 Observability

### Health endpoints
| Path | Purpose |
|---|---|
| `/healthz` | liveness — process up |
| `/readyz` | readiness — DB & Redis reachable |

### Structured logs
- JSON logs via Loguru (`core/logging.py`)
- Include `trace_id`, `user_id`, `route`, `latency_ms`
- Ship to Loki / Cloudwatch / Datadog

### Metrics
- Add `prometheus-fastapi-instrumentator` for RED metrics
- Track AI cost: `ai_call_log` table, daily roll-up dashboard
- Slow query log enabled in Postgres (`log_min_duration_statement = 500`)

### Alerts
| Alert | Threshold |
|---|---|
| API 5xx rate | > 1% over 5 min |
| Login failures spike | > 50/min |
| AI monthly spend | > 80% of budget |
| Worker queue backlog | > 1000 tasks |
| Postgres connections | > 80% of max |
| Disk free | < 15% |

---

## 7.9 CI/CD

The included GitHub Actions (`.github/workflows/ci-deploy.yml`) runs on every
push to `main` and `claude/**`:

1. Backend: `ruff check` + `pytest`
2. Frontend: `npm run build`

For deployment, extend with:
- `docker buildx build --push` to your registry
- Apply migrations: `kubectl exec deploy/api -- alembic upgrade head`
- Rolling restart: `kubectl rollout restart deploy/api`
- Smoke test: hit `/readyz` and abort on failure

---

## 7.10 Upgrade procedure

```bash
# 1. Take a backup
./scripts/backup-db.sh

# 2. Pull new code
git pull --ff-only

# 3. Rebuild + restart
docker compose -f infra/docker-compose.yml --env-file .env up -d --build

# 4. Apply migrations
docker compose -f infra/docker-compose.yml exec api alembic upgrade head

# 5. Smoke check
curl -f https://crm.yourco.com/api/v1/healthz
```

If migrations fail, restore the backup and investigate before retrying — don't
edit migrations that have already been applied to production.
