# n8n workflows

Import each JSON file into your n8n instance. They reference these credentials:

- `WHATSAPP_CLOUD` — Meta WhatsApp Cloud API token & phone-number ID
- `INDUSTRIA_API` — HTTP header credential carrying `X-Webhook-Secret = ${N8N_WEBHOOK_SECRET}`
  and `Authorization: Bearer <service-token>` for callbacks
- `IMAP_INBOX` — for inbound email parsing

Workflow files:

| File | Purpose |
|---|---|
| `01-wa-inbound.json` | WA Cloud webhook → POST /webhooks/whatsapp/inbound |
| `02-payment-reminders.json` | Cron → API list → WA template send |
| `03-doc-parse-pipeline.json` | IMAP / WA attachment → POST /ai/document/parse |
| `04-approval-fanout.json` | Subscribe to API approval-requested event → WA route |
| `05-quotation-followup.json` | T+3 unread quotation → suggest WA via /ai/assistant/suggest |
| `06-supply-risk-scan.json` | Weekly trigger → /ai/supply-risk → notify purchasing |

Each JSON below is a minimal stub representing the wired nodes; tune URLs,
credentials, and retry policy to your environment.
