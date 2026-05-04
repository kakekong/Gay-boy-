# 05 — Automation Flows (n8n)

n8n is the **automation control plane**. The FastAPI backend exposes webhooks; n8n owns scheduling, channel adapters (WhatsApp Cloud API, email, SMS), and human-readable flow definitions.

Workflows live in [`n8n/workflows/`](../n8n/workflows) as exported JSON. Below are the canonical flows.

---

## 5.1 WA-Inbound → CRM activity log

```
WhatsApp Cloud API webhook
       │
       ▼
[n8n] verify signature
       │
       ▼
[n8n] HTTP POST /api/v1/webhooks/whatsapp/inbound
       │  payload: { wa_id, from, text, media[], timestamp }
       ▼
[FastAPI]
  - find customer by phone
  - if found: insert activity{type:'whatsapp_in', direction:'inbound'}
  - else: stash in "unmatched_messages" + create reminder for sales
  - if message contains keywords ("PO", "purchase order", attachment) → enqueue doc-parse job
       │
       ▼
[FastAPI → Redis pubsub] → frontend live update
```

## 5.2 WA-Outbound (templated) — reminders & alerts

n8n triggers:
- payment due in T-3 / T-0 / T+3 / T+7 / T+14
- after-sales follow-up T+30 after delivered
- quotation follow-up T+3 after sent if no reply
- at-risk deal escalation (HIGH)

```
[Schedule / Webhook from API]
       │
       ▼
[n8n] fetch template from API: GET /api/v1/wa/templates/{key}
       │
       ▼
[n8n] WhatsApp Cloud API → send template message
       │
       ▼
[n8n] POST /api/v1/webhooks/whatsapp/status
   - record send + later delivery/read state on the activity row
```

## 5.3 Smart Reminder Engine flow

```
[Cron daily 06:00] (Celery beat)
       │
       ▼
[FastAPI] for each open reminder:
  - compute ai_optimal_at (per-customer responsiveness model)
  - rerank "Top Actions" per sales
       │
       ▼
[Frontend] AI Command Center → live "Top Priority Actions" list
       │
       ▼
[n8n WA flow] dispatches the WA messages exactly at ai_optimal_at
```

## 5.4 PO received → auto-orchestration

```
inbound channels:
  - email-inbox (n8n IMAP / Gmail trigger)
  - WA attachment
  - Manual upload
       │
       ▼
[n8n] POST /api/v1/ai/document/parse  (pdf/image base64)
       │
       ▼
[FastAPI worker]
  - OCR (tesseract or Vision LLM)
  - LLM extraction → {customer, po_number, items[], deadline, payment_terms}
  - if customer matches:
       create Project (status=new)
       create WorkOrder
       if items not in stock → create PurchaseRequest
       notify sales PIC + ops manager (WA + dashboard)
  - else:
       create review task for admin
```

## 5.5 Discount approval flow

```
Sales submits quotation (discount=12%)
       │
       ▼
[FastAPI] approval_engine.evaluate
   → required_role = manager
       │
       ▼
[FastAPI] insert approval_requests row → emit "approval.requested"
       │
       ▼
[n8n] route by required_role:
   - WA template to managers
   - dashboard notification (websocket)
       │
       ▼
Manager opens approval inbox → approve/reject
       │
       ▼
[FastAPI] update quotation.status, audit_log
       │
       ▼
[n8n] notify sales (WA) + record activity
```

## 5.6 Payment alert escalation

```
[Cron hourly]
       │
       ▼
[FastAPI] /finance/reminders/run
       │  for each invoice in (issued, partial) where due_date soon/past:
       ▼
[n8n] WA reminder to PIC keuangan customer
       │
       ▼ if T+7 still unpaid
[n8n] notify finance team
       │
       ▼ if T+14 still unpaid
[n8n] escalate to manager + flag deal as risk
       │
       ▼ if T+30
[n8n] escalate to director
```

## 5.7 Drawing approval cycle

```
Internal upload drawing rev N
   → /drawings/{id}/submit
       │
       ▼
[n8n] generate signed approval link (HMAC)
   → email + WA the customer with link
       │
       ▼
Customer clicks → mini approval page (no login, signed token)
   → /drawings/approve?token=...
       │
       ▼ on revision_requested
[n8n] WA back to engineering team + start SLA timer
```

## 5.8 Supplier risk monitor

```
[Cron weekly]
   → ai/supply_risk.scan()
   - update suppliers.rating, lead_time_days_avg, qc_fail_rate, price_volatility
   - if any metric breaches threshold → emit alert
       │
       ▼
[n8n] WA + dashboard alert to purchasing manager
```

## 5.9 KPI rollup

```
[Celery beat nightly 00:30]
   → kpi/rollup.py
   - sales kpis (per user, per period)
   - operation, purchasing, finance kpis
   - persist to kpi_snapshots table for fast dashboards
```

## 5.10 Workflow file index (planned)

| File | Description |
|---|---|
| `01-wa-inbound.json` | WA Cloud → API webhook |
| `02-wa-outbound-template.json` | Reusable subworkflow |
| `03-payment-reminders.json` | Cron-driven |
| `04-doc-parse-pipeline.json` | Email + WA attachment → parse |
| `05-approval-fanout.json` | Approval routed to managers/directors |
| `06-drawing-approval.json` | Customer-facing signed link |
| `07-supply-risk-scan.json` | Weekly supplier scoring |
| `08-followup-quotation.json` | T+3 follow-up if quotation unread |

The actual JSON exports live next to this doc; they are pre-stubbed and meant to be imported into n8n then connected to environment credentials.
