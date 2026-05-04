# IndustriaCRM — Enterprise CRM + ERP + AI for Project-Based Engineering Companies

A production-ready scaffold of a unified CRM, ERP and AI Automation platform tailored for **project-based industrial engineering companies** (Mining, PLTU/Power Plant, Fertilizer, Sugar, Cement, Pulp & Paper, Food).

This is **not** a generic CRM. The whole architecture follows the actual sales cycle of a custom industrial product business:

> Lead → Presentation → Engineering → Quotation → Negotiation → PO → Drawing Approval → Purchasing → Delivery → Invoicing → Payment

---

## 1. What's inside

| Layer | Tech | Purpose |
|---|---|---|
| Backend API | **FastAPI (Python 3.11)** | REST API, RBAC, business logic, AI orchestration |
| Database | **PostgreSQL 15** | Transactional data, JSONB for flexible engineering specs |
| Cache / Queue | **Redis** | Sessions, rate limiting, Celery broker |
| Background workers | **Celery** | Reminders, scoring jobs, document parsing |
| Automation | **n8n** | WhatsApp 2-way sync, payment alerts, follow-up flows |
| AI layer | **OpenAI / LLM API** + scikit-learn | Lead scoring, deal risk, AI assistant, doc parsing |
| Frontend | **React 18 + Vite + TypeScript + TailwindCSS** | Modern dashboard UI |
| Auth | **JWT + role-based** (Sales / Admin / Manager / Director) | Approval workflows |
| Infra | **Docker Compose** | One-command local stack |

---

## 2. Modules

1. **CRM** — Customers, contacts, activity log, reminders, WhatsApp 2-way
2. **Quotation** — Standard + custom engineering, multi-version, approval workflow, discount rules
3. **Purchasing** — PR → RFQ → Supplier PO → Drawing → Inspection → GR → QC → Payment
4. **Operation** — Receiving, Warehousing, QC, Packaging, Delivery, Work Orders, split delivery, resi tracking
5. **Finance** — DO, Invoice, AR/AP, payment terms (DP, Tempo, Termin), tax report
6. **KPI & Analytics** — Sales / Purchasing / Operation / Finance KPIs
7. **Executive Dashboard** — Pipeline, forecast, lost deal analysis
8. **AI Command Center** — At-Risk Deals, Top Priority Actions, Forecast vs Reality, Profit Alerts

### AI sub-modules
- Lead Scoring AI
- Auto Quotation AI
- Sales AI Assistant (WA suggestions, closing strategy, stalled-deal detection)
- **Deal Risk Detector** — early warning system
- **Profit Intelligence Engine** — real-time margin per project
- **Smart Reminder Engine** — AI-timed follow-ups
- **Opportunity Expansion AI** — upsell engine
- **Document Intelligence** — parse PO PDF / image / WA / email
- **Loss Analysis AI** — win/lose pattern brain
- **Sales Performance AI Coach**
- **Auto Workflow Orchestrator**
- **Supply Risk Monitor**
- **Knowledge Base AI** — company memory

---

## 3. Quickstart

```bash
# 1. Configure
cp infra/.env.example .env

# 2. Boot the full stack (db, redis, api, frontend, n8n, worker)
docker compose -f infra/docker-compose.yml --env-file .env up -d

# 3. Seed initial roles, demo data
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed

# 4. Open
# API docs : http://localhost:8000/docs
# Frontend : http://localhost:5173
# n8n      : http://localhost:5678
```

Default users (after seed):

| Role | Email | Password |
|---|---|---|
| Director | director@demo.local | demo1234 |
| Manager | manager@demo.local | demo1234 |
| Sales | sales1@demo.local | demo1234 |
| Admin | admin@demo.local | demo1234 |

---

## 4. Documentation

| File | Topic |
|---|---|
| [`docs/01-architecture.md`](docs/01-architecture.md) | High-level architecture & service breakdown |
| [`docs/02-database-schema.md`](docs/02-database-schema.md) | Full ERD, tables, relations, key fields |
| [`docs/03-api-design.md`](docs/03-api-design.md) | REST endpoints per module |
| [`docs/04-uiux-design.md`](docs/04-uiux-design.md) | Page structure, key components |
| [`docs/05-automation-flows.md`](docs/05-automation-flows.md) | n8n workflows & triggers |
| [`docs/06-ai-logic-design.md`](docs/06-ai-logic-design.md) | Prompts, scoring models, message generation |
| [`docs/07-deployment.md`](docs/07-deployment.md) | Production deployment notes |

---

## 5. Repository layout

```
.
├── backend/        FastAPI app (API, services, AI, workers)
├── frontend/       React + Vite dashboard
├── n8n/            n8n workflow exports (WhatsApp, reminders, alerts)
├── infra/          Docker Compose, nginx, .env.example
├── docs/           System design documentation
└── README.md
```

---

## 6. Roles & permissions (summary)

| Capability | Sales | Admin | Manager | Director |
|---|---|---|---|---|
| See own customers | ✅ | ✅ | ✅ | ✅ |
| See all customers | ❌ | ✅ | ✅ | ✅ |
| Create quotation | ✅ | ✅ | ✅ | ✅ |
| Approve quotation | ❌ | ❌ | ✅ | ✅ |
| Discount ≤ 5% | auto | auto | auto | auto |
| Discount 5–15% | request | request | ✅ | ✅ |
| Discount > 15% | request | request | request | ✅ |
| Edit data (with approval) | ❌ | ✅ | ✅ | ✅ |
| Approve data changes | ❌ | ❌ | ✅ | ✅ |
| Full system access | ❌ | ❌ | ❌ | ✅ |

Implementation: [`backend/app/core/permissions.py`](backend/app/core/permissions.py)

---

## 7. License & ownership

Internal enterprise system. All rights reserved by the issuing organization.
