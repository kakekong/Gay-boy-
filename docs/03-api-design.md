# 03 — REST API Design

Base path: `/api/v1`
Auth: `Authorization: Bearer <JWT>` (issued by `/auth/login`).
All list endpoints support `?page`, `?page_size`, `?q`, `?sort`, plus module-specific filters.

---

## 3.1 Auth & users

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/login` | public | email + password → JWT |
| POST | `/auth/refresh` | any | refresh token |
| GET | `/auth/me` | any | current user |
| GET | `/users` | director, manager | list users |
| POST | `/users` | director | create user |
| PATCH | `/users/{id}` | director | edit / activate |

## 3.2 CRM — Customers

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/customers` | sales (own only), admin/manager/director (all) | filter: stage, industry, sales_pic |
| POST | `/customers` | sales, admin | sales auto-becomes `sales_pic`; admin edits go through approval |
| GET | `/customers/{id}` | scoped | |
| PATCH | `/customers/{id}` | sales (own), admin (with approval) | |
| POST | `/customers/{id}/stage` | sales (own) | move stage |
| GET | `/customers/{id}/activities` | scoped | |
| POST | `/customers/{id}/activities` | scoped | log call/meeting/note |
| GET | `/customers/{id}/reminders` | scoped | |
| POST | `/customers/{id}/reminders` | scoped | |

## 3.3 Quotation

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/quotations` | scoped | filter status, customer |
| POST | `/quotations` | sales, admin | creates `draft` |
| GET | `/quotations/{id}` | scoped | |
| PATCH | `/quotations/{id}` | sales (own draft) | |
| POST | `/quotations/{id}/version` | sales (own) | clone & bump version |
| POST | `/quotations/{id}/submit` | sales | runs discount rule → triggers approval if needed |
| POST | `/quotations/{id}/approve` | manager / director | based on rule level |
| POST | `/quotations/{id}/reject` | manager / director | |
| POST | `/quotations/{id}/send` | sales (after approved) | dispatch via WA/email; logs activity |
| POST | `/quotations/{id}/won` | sales | converts to `Project` |
| POST | `/quotations/{id}/lost` | sales | requires `lost_reason`; feeds Loss Analysis AI |
| GET | `/quotations/{id}/pdf` | scoped | rendered short or detailed |
| POST | `/quotations/auto` | sales | **AI Auto-Quotation** from structured form |

## 3.4 Approval engine

| Method | Path | Role | |
|---|---|---|---|
| GET | `/approvals` | manager, director | inbox |
| POST | `/approvals/{id}/approve` | based on `required_role` | |
| POST | `/approvals/{id}/reject` | based on `required_role` | |

## 3.5 Purchasing

```
POST /purchasing/pr            create PR
GET  /purchasing/pr            list
POST /purchasing/pr/{id}/rfq   spawn RFQ to suppliers
POST /purchasing/rfq/{id}/po   convert chosen RFQ line → supplier PO
POST /purchasing/po/{id}/gr    record goods receipt
POST /purchasing/po/{id}/qc    QC report
POST /purchasing/po/{id}/pay   trigger AP payment
GET  /suppliers                list / rated
POST /suppliers
```

## 3.6 Operation

```
GET  /projects                  filter status, customer
POST /projects                  usually auto-created from won quotation or parsed PO
GET  /projects/{id}
POST /projects/{id}/work-order
POST /projects/{id}/drawing     upload + start approval cycle
POST /drawings/{id}/approve     customer (signed link) or internal
POST /projects/{id}/delivery    create DO (supports split: `split_index`)
POST /delivery/{id}/track       update resi / courier
POST /delivery/{id}/delivered
```

## 3.7 Finance

```
POST /invoices                  type: dp | settlement | termin | tempo | single
POST /invoices/{id}/issue
POST /invoices/{id}/payment
GET  /ar/aging                  AR aging buckets
GET  /ap/aging
GET  /tax/report?period=...
POST /finance/reminders/run     cron — triggers WA reminders for upcoming/overdue invoices
```

## 3.8 KPI & dashboards

```
GET /kpi/sales?range=...        new leads, lead→quote, quote→win, revenue vs target, OTD, after-sales rate, repeat rate
GET /kpi/purchasing             lead time, QC pass, drawing approval time
GET /kpi/operation              OTD, defect rate
GET /kpi/finance                AR collection, reporting timeliness
GET /dashboard/executive        pipeline, forecast, top customers, lost-deal patterns
GET /dashboard/ai-command       at-risk deals, top actions, forecast vs reality, profit alerts, recommendations
```

## 3.9 AI endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/ai/lead-score/{customer_id}` | recompute lead score |
| GET  | `/ai/lead-score/{customer_id}` | latest score |
| POST | `/ai/deal-risk/scan` | recompute all open deals (cron) |
| GET  | `/ai/deal-risk` | list at-risk deals |
| POST | `/ai/assistant/suggest` | body: `{customer_id, intent}` → WA message / strategy |
| POST | `/ai/quotation/auto` | structured form → quotation draft |
| POST | `/ai/document/parse` | upload PDF/image/text → extract structured data |
| POST | `/ai/upsell/{customer_id}` | opportunity expansion suggestions |
| GET  | `/ai/loss-analysis/patterns` | discovered patterns |
| GET  | `/ai/coach/{user_id}` | personal coaching suggestions |
| POST | `/ai/kb/search` | semantic search company memory |
| POST | `/ai/kb/index` | index a document |
| GET  | `/ai/profit/{project_id}` | live margin breakdown |
| GET  | `/ai/supply-risk` | supplier risk dashboard |

## 3.10 Webhooks (n8n / WhatsApp)

```
POST /webhooks/whatsapp/inbound      ← n8n forwards WA message
POST /webhooks/whatsapp/status       ← delivery / read receipts
POST /webhooks/email/inbound         ← parsed emails
POST /webhooks/payment/inbound       ← bank/payment gateway
```

All webhooks require an `X-Webhook-Secret` header verified against `.env`.

## 3.11 Standard response envelope

```json
{
  "data": { ... },
  "meta": { "page": 1, "page_size": 20, "total": 134 },
  "errors": null
}
```

Errors:
```json
{
  "data": null,
  "errors": [{ "code": "FORBIDDEN", "message": "Sales cannot approve quotations" }]
}
```
