# 01 — System Architecture

## 1.1 High-level diagram

```
                       ┌──────────────────────────────────────────┐
                       │              Users (Web / Mobile)        │
                       │  Sales · Admin · Manager · Director      │
                       └──────────────────┬───────────────────────┘
                                          │ HTTPS
                                          ▼
                              ┌───────────────────────┐
                              │   Nginx (TLS, WAF)    │
                              └───────┬───────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
   ┌────────────────┐        ┌─────────────────┐       ┌────────────────┐
   │ React Frontend │        │  FastAPI API    │       │  n8n           │
   │ (Vite + TS)    │◄──────►│  (REST + JWT)   │◄─────►│  Automation    │
   └────────────────┘        └────────┬────────┘       └────────┬───────┘
                                      │                         │
                ┌─────────────────────┼─────────────────────────┘
                │                     │
                ▼                     ▼
        ┌──────────────┐      ┌─────────────────┐      ┌──────────────────┐
        │ PostgreSQL   │      │  Redis (cache,  │      │  Celery Worker   │
        │ (OLTP + JSONB│      │  queue, locks)  │◄────►│  (jobs, AI, doc) │
        └──────────────┘      └─────────────────┘      └────────┬─────────┘
                                                                │
                                                                ▼
                                ┌────────────────────────────────────────────┐
                                │   AI Layer                                 │
                                │   - LLM (OpenAI / Claude)                  │
                                │   - Lead scoring (sklearn)                 │
                                │   - Doc parser (OCR + LLM)                 │
                                │   - Embedding store (pgvector)             │
                                └────────────────────────────────────────────┘
                                                ▲
                                                │
                                ┌────────────────────────────────┐
                                │ External integrations          │
                                │ - WhatsApp Cloud API (Meta)    │
                                │ - Email (SMTP / Gmail)         │
                                │ - Logistics (resi tracking)    │
                                │ - Tax / e-Faktur (optional)    │
                                └────────────────────────────────┘
```

## 1.2 Service breakdown

| Service | Responsibility |
|---|---|
| `api` (FastAPI) | REST API, RBAC, business logic, AI orchestration |
| `worker` (Celery) | Async jobs: scoring, doc parsing, reminders, embedding |
| `beat` (Celery beat) | Scheduled tasks: daily KPI rollup, AR aging, smart reminders |
| `db` (Postgres + pgvector) | Source of truth + vector embeddings for KB |
| `cache` (Redis) | Sessions, rate limit, queue broker |
| `n8n` | Workflow automation (WA 2-way, payment alerts, follow-up flows) |
| `frontend` | React dashboard |
| `nginx` | TLS, routing, security headers |

## 1.3 Domain boundaries

The backend is structured by **business domain**, not by technical layer. Each domain owns its models, services, AI logic, and endpoints:

```
backend/app/
├── crm/              customer, contact, activity, reminder
├── quotation/        quotation, line items, versions, approvals
├── purchasing/       PR, RFQ, supplier, supplier PO, GR, QC
├── operation/        work order, delivery, packaging, logistics
├── finance/          DO, invoice, payment, AR/AP, tax
├── kpi/              metrics rollup, dashboards
├── ai/               scoring, risk, doc parser, assistant, KB
└── core/             auth, db, permissions, audit, approval
```

A single `core/approval` engine implements the **approval workflow** used by quotation, discount, and data changes — keeping the rule engine in one place.

## 1.4 Cross-cutting concerns

- **Audit trail** — every mutation is recorded in `audit_log` (who / when / before / after) by SQLAlchemy event listener.
- **Approval engine** — `core/approval.py` defines a generic `ApprovalRequest` lifecycle (`pending → approved/rejected`).
- **RBAC** — declarative policy in `core/permissions.py`, enforced via `Depends(require(...))` on each route.
- **Soft delete** — `is_deleted` + `deleted_at` on all customer-facing tables.
- **Multi-tenant ready** — schema includes optional `tenant_id` column (single-tenant by default).

## 1.5 Data flow examples

### A. PO received → project auto-created
1. WA / email / scan → `n8n` → `POST /ai/document/parse`
2. `worker` runs OCR + LLM extraction → returns `{customer, product, qty, deadline}`
3. API creates `Project`, `WorkOrder`, triggers `Purchasing.PR` if material missing.
4. Sales PIC notified via WA + dashboard.

### B. Discount approval
1. Sales submits quotation with 12% discount.
2. API calls `approval.request(type="discount", level="manager")`.
3. Manager gets WA + dashboard notification.
4. On approve → quotation status moves `pending_approval → approved`.
5. `audit_log` captures the decision.

### C. Deal Risk Detector
1. Celery beat runs every 6h → `ai/deal_risk.scan_all()`.
2. For each open deal: compute features (last activity, response time, # revisions, discount drift).
3. Score → write `deal_risk_score` + `risk_reason` + `recommended_action`.
4. UI Command Center surfaces "At Risk Deals". WA alert if `High`.
