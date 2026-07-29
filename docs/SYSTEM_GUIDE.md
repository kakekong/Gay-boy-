# Transmisi Eng — Complete System Guide

**Enterprise CRM + ERP for project-based industrial engineering**
Built for PT Transmisi Uplindo · live at `transmisisuplindo.com` · v0.2

This is the full reference for the system: what it is, how it is built, and — in detail — how every workflow inside it operates, from a customer's first inquiry to a closed, fully-paid project. It supersedes the v0.1 guide.

**How to read this document**
- New staff: read §1, §3 (your role's row), §14 (the happy path), then the in-app **Role Guide**.
- Managers/directors: §4–§10 are the heart — pipeline, pricing, quotations, orders, production, finance, approvals.
- Whoever operates the deployment: §2, §15, §16.

---

## 1. What the system is

Transmisi Eng is a single web application that runs the entire commercial and operational life of an engineering trading/fabrication business:

- **CRM** — customers, contacts (PICs), a staged deal pipeline, activities, follow-ups, reminders, WhatsApp deep-links.
- **Pre-sales pricing** — a price-request workflow where sales never invents a price: purchasing costs the items, the director sets the sell price.
- **Quotations** — generated from approved price requests, director-gated, exportable to PDF/Excel, revisable with a full version chain.
- **Order intake** — customer POs (regular and down-payment variants) that spawn projects.
- **Operations / ERP** — projects with a strict production pipeline, work orders, technical drawings, logistics & import documents, a three-leg shipping timeline, QC, delivery orders.
- **Finance** — invoices (DP and final), faktur pajak (Indonesian tax invoice), payment claims and verification, manual payment entry, AR aging, a transaction journal over a 109-account Indonesian chart of accounts, a printable financial-reports suite, payroll.
- **HR** — employee directory, personnel documents (KTP, contract, NPWP, BPJS), attendance with late tracking.
- **External portals** — a stripped-down customer portal (order status, drawing approval, payment claims) and supplier portal (assigned POs, drawing upload, ETA entry).
- **Communication** — internal chat (DMs + group channels) and discussion threads on deal documents, both with instant device notifications.
- **Cross-cutting** — role-scoped notifications (bell, banners with chime, device push), an approvals inbox, calendar, audit logging, custom roles, full English/Indonesian bilingual UI, installable as a phone app (PWA).

The design philosophy: **every consequential action is gated, scoped, and leaves a paper trail.** Sales can't invent prices; purchasing can't see customers; nobody below director can change a customer-visible date silently; every stage move, edit, and payment is either approved or audited.

---

## 2. Architecture & stack

### 2.1 Components

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript, TanStack Query, Tailwind CSS, Zustand, lucide-react | Vercel (auto-deploys on every push) |
| Backend | FastAPI (Python 3.11) + SQLAlchemy 2 async + Pydantic v2 | Hugging Face Space (Docker; clones the GitHub repo at build) |
| Database | PostgreSQL | Neon (serverless Postgres) |
| File storage | Local disk `/tmp/storage` on the Space (**ephemeral — wiped on rebuild**, see §16) | — |
| Push delivery | Web Push (VAPID) direct to each browser/phone | keys auto-generated, stored in the DB |

### 2.2 Repository layout

```
backend/
  app/
    api/v1/endpoints/   # one file per domain: customers, quotations, price_requests,
                        # customer_pos, operation, finance, financial_reports, ledger,
                        # payments, approvals, notifications, push, calendar, chat,
                        # comments, feedback, attachments, users, audit, ai, …
    core/               # config, db, deps (auth), permissions, approval engine,
                        # audit, stage_playbook, stage_tasks
    models/             # SQLAlchemy models (one file per domain)
    scripts/seed.py     # idempotent schema creation + column migrations, run on EVERY boot
    services/           # webpush, ledger posting, financial reports engine,
                        # numbering, quote import (Excel/PDF parsing), exports
  tests/                # in-process e2e suites (see §15)
frontend/
  public/               # PWA: manifest.webmanifest, sw.js (service worker), icons
  src/
    pages/              # one page component per route
    components/         # shared: AttachmentsSection, CommentThread, NotificationsBell, …
    layouts/Shell.tsx   # sidebar, topbar, role allowlists, bell, banners
    store/              # zustand stores: auth, lang (i18n), theme (dark mode)
docs/                   # this document + design docs + ROLE_GUIDES.md
```

### 2.3 Request flow

1. The browser (or installed phone app) loads the React app from Vercel.
2. Every API call goes to the Space's FastAPI under `/api/v1/...` with a JWT bearer token (12 h access token, 30-day refresh, argon2 password hashing).
3. FastAPI resolves the current user, applies role/scope guards per endpoint, talks to Neon via async SQLAlchemy, and returns JSON (errors in a uniform `{data, errors, meta}` envelope).
4. TanStack Query caches responses client-side and invalidates after mutations, so pages refresh without reloads.

### 2.4 Boot sequence (backend)

On every container start:
1. The Space Dockerfile runs `python -m app.scripts.seed` (best-effort), then `uvicorn app.main:app`.
2. The app's lifespan runs `ensure_schema()`: `create_all` for missing tables plus ~90 idempotent `ALTER TABLE … IF NOT EXISTS` migrations and forward-only data repairs, capped at 90 s × 3 attempts with loud `[boot]` log lines — a hung database delays boot instead of bricking it.
3. The **web-push sweeper** starts: a background loop that every ~90 seconds recomputes each user's notifications and pushes new high/medium-severity items to their subscribed devices (§10.3).
4. Prod-safety check: the app refuses to boot in `APP_ENV=prod` with default secrets or `CORS_ORIGINS=["*"]`.

**Deployment note:** the Space clones GitHub *at build time* — backend changes require a Space rebuild; the frontend deploys automatically via Vercel on every push.

### 2.5 The phone app (PWA)

The frontend is a Progressive Web App: `manifest.webmanifest` + a service worker (`sw.js`) that receives pushes and opens the right page on tap.

- **Android/desktop Chrome**: "Install app" from the browser menu.
- **iPhone**: Safari → Share → **Add to Home Screen**. On iOS, device notifications *only* work from the installed home-screen app (an Apple restriction), not from a Safari tab.
- Notifications arriving while the app is closed show as native OS notifications; tapping one opens the app at the linked page.

---

## 3. Roles & access model

Nine base roles. Internal roles are capped by a sidebar/route allowlist enforced in the UI *and* re-checked server-side on every endpoint.

| Role | Scope (pages) | One-line job |
|---|---|---|
| **Sales** | CRM, price requests, quotations, customer POs, projects (shell view), ops board (read-only), calendar, chat | Owns customers from first hello to signed PO; sees **only their own** customers |
| **Purchasing** | Price requests, purchasing/suppliers, purchase orders, inventory, projects (customer-blind), calendar, attendance, chat | Prices deals, raises supplier POs, books origin shipping — never sees customer identity |
| **Admin** | Projects, operation board, inventory, attendance, chat | Runs production: work orders, arrivals, delivery proofs. No CRM, no money pages |
| **Finance** | Finance, financial reports, estimated finance, payment verification, chart of accounts, recent ledgers, customer POs, projects, attendance, chat | Issues + approves invoices, gates DP POs, verifies/records payments |
| **HR** | Employees, attendance, chat | Personnel documents and attendance |
| **Manager** | Everything (oversight) | Clears manual stage moves + manager-tier changes; watches every queue |
| **Director** | Everything + Salary, PO Recap, All files, Users, KPI, Audit log, Feedback inbox | The approval authority for every deal document |
| **Customer** (portal) | Own quotations, projects, invoices, drawings, payment claims | External |
| **Supplier** (portal) | Own assigned POs, drawing upload, ETA entry | External |

**Custom roles** (director-built, Admin → Users): a named role = a display name + a *base tier* (the real security level) + a hand-picked page list from the page catalog. Use it for hybrid jobs ("Sales-admin" who also sees the ops board) without inventing new permission code — the base tier still governs what the API allows.

### 3.1 Information boundaries (deliberate)

- **Purchasing is customer-blind.** Projects render as "Order PRJ-…"; price requests hide the customer; the calendar, notifications and PO screens are scrubbed server-side. Purchasing prices *items*, not *customers*.
- **Sales is money/ops-blind.** On a project, sales sees only the customer-facing shell (header, pipeline, shipping timeline, drawings upload). Work orders, invoices, margins, supplier POs, QC internals and the ledger are hidden. Sales never sees procurement cost on a price request.
- **Internal note scrubbing.** Lines beginning with `[purchasing]`, `[director]`, etc. in price-request notes are a staff side-channel; they are stripped before sales sees the PR and before notes are copied to a customer-facing quotation.
- **Sales sees only its own records** — customers where they are the sales PIC, and the quotations/PRs/POs/projects of those customers. Enforced on every list *and* detail endpoint, not just hidden in the UI.

---

## 4. The deal pipeline (CRM)

Each customer carries a **stage**:
`lead → presentation → engineering → quotation → negotiation → po → drawing → purchasing → delivery → invoicing → payment → closed_won / closed_lost`

- **Forward moves are one stage at a time** (no skipping); backward moves are always allowed; `closed_lost` can be reached from anywhere.
- **Manual stage moves need approval.** Sales files a request (mandatory written reason + optional evidence files); a **manager or director** approves. Managers'/directors' own moves apply instantly.
- **Stage notes are permanent.** Clicking a *passed* stage on the pipeline stepper opens that stage's paper trail: every move into/out of it, the reason written at the time, who requested, who decided, and the decision note.
- **The fused pipeline** — deal documents advance the stage automatically, so sales never files a request for ground already covered:
  - quotation approved → stage `quotation`
  - Mark-Won approved → stage `negotiation`
  - customer PO approved → stage `po`
  - project progress mirrors the onward stages (`drawing`, `purchasing`, `delivery`, `invoicing`, `payment`, `closed_won`) — forward-only, never regressing.

### 4.1 Stage tasks (the playbook)

Entering a stage auto-spawns that stage's required checklist on the customer page (e.g. *lead*: "Make first contact", "Qualify need + budget"; *po*: "Collect signed PO", "Confirm payment terms"). Each task shows a hint, is owned by the right role, and can be ticked done, reopened, or annotated.

**Tasks carry no deadline by default.** A freshly spawned task is checklist-only — it does **not** appear on the calendar and does **not** generate notifications. Clicking **"+ Set deadline / note"** and picking a date is what enrolls it: from then on it shows on the calendar, warns 2 days before it's due, and escalates when overdue (red, counted in the director's team roll-up). This keeps the bell and calendar quiet unless a date was a deliberate commitment.

Task nags follow the owning role: deal chores → the owning sales rep; raise-PR / select-supplier → purchasing (customer-blind); drawing/delivery chores → admin; issue/send-invoice + payment follow-up → finance. Managers and the director see everything.

---

## 5. Pricing: the price request (PR)

Sales cannot type a price anywhere. The flow:

1. **Sales files a PR** on the customer page: line items (description, qty, UoM, spec) — no prices. Status `draft` → submit.
2. **Purchasing costs it**: procurement cost per line (entered per-unit or as line total; stored per-unit). It then goes to the director. Purchasing may attach an internal `[purchasing]` note.
3. **Director prices it**: sets the sell price per line (may correct costs), approves — or rejects with notes.
4. **Sales generates the quotation** from the approved PR — every unit price is the director's sell price, carried automatically.

Around the PR:
- **The PR number is editable at any stage** (unique, audited) — e.g. to mirror the customer's own RFQ number. Links are by id, so renames orphan nothing.
- **File uploads** ride on the PR (spec sheets, the customer's RFQ) so purchasing costs from source documents.
- **A discussion thread** (sales ↔ purchasing ↔ director) lives on the PR — and posting in it **pushes a device notification** to the other participants and the PR's stakeholders (§10.4).
- **Handoffs notify instantly**: submitting a PR pings purchasing; purchasing finishing costing pings the director; the director's decision pings the requesting sales rep — each as bell items and device pushes.
- Serialization is role-aware: purchasing never receives sell price or customer name; sales never receives cost.
- The PR links forward: PR → quotation → project, all clickable on each other's pages.

---

## 6. Quotations

### 6.1 Lifecycle

`draft → pending_approval → approved → (sent) → won / lost`, plus `rejected`, `cancelled`, and `superseded` (see revisions).

- **Creation**: sales only via *generate from approved PR* (direct creation returns 409 for sales). Director/manager/admin retain a direct-creation path for off-system negotiated deals. Numbers are auto-generated (`QT-TSE-YYYY-NNNN`) with an editable token, or fully custom — uniqueness enforced.
- **Submit**: every quotation requires **director approval** — there is no discount-based auto-approve. Submitting creates an approval request.
- **Unsubmit**: while pending, the owner (or director) can withdraw — the quote returns to draft and the pending request is deleted so a stale decision can't land.
- **Approval**: director approves/rejects (inline on the quote or in /approvals). Approval bumps the customer stage to `quotation`.
- **Editing rules**:
  - `draft` / `rejected`: fully editable by the owner or director.
  - `approved` / `sent`: pricing edits **queue a `quotation_edit` approval** — changes apply only when the director approves; the quote shows an "Edit awaiting director" chip meanwhile. Director edits apply instantly. `valid_until` and meta notes stay directly editable.
  - `pending_approval`: locked — unsubmit first.
  - PR-backed drafts: line prices are fixed by the approved PR.
- **Mark won**: sales' click files a `quotation_won` request to the director; approval flips the quote to Won, posts revenue to the ledger, and bumps the stage. **Won does not create a project — the customer PO does.**
- **Mark lost**: requires a written reason (feeds the Lost-deals report); blocked while a Mark-won request is pending and on won/closed quotes — the two outcomes are mutually exclusive, enforced in UI and API.
- **Exports**: PDF and Excel with the company header, PIC addressing and totals. **Every export writes an `export` activity** to the customer timeline (who, which quote, which format, when).
- **Quote import**: line items can be imported from an existing Excel/PDF quotation document instead of typed by hand.
- **Follow-ups**: logged on the quote; they route to the director for approval before being recorded; approved follow-ups can schedule the next reminder.

### 6.2 Revisions

"Post revision" on an approved/sent/rejected/lost quote clones it into a **new editable draft** numbered `<base>-R<n>` (version bumped, parent linked, items/prices/PR link copied). The revision walks the normal submit → director approval path. **When the revision is approved, the original flips to `superseded`** so only one version of the offer is ever live. One open revision at a time; the header shows the whole revision chain as links.

### 6.3 Ledger link

Winning (or posting) a quotation writes to the chart of accounts: Piutang Usaha ↑, Penjualan ↑, PPN Keluaran ↑ (11 % default), Diskon ↑ — visible in the Linked Accounts panel (hidden from sales) with per-quote account overrides and a reversal mechanism (reversal entries, never hard deletes).

---

## 7. Order intake: customer POs

Filed from the Won quotation's "Next step" card: attach the customer's PO file, pick which quoted items they actually ordered (with price edits if negotiated), set the PO number/date, and optionally tick **"This PO is a down payment"**.

### 7.1 Regular PO path
`pending_approval` → **director** approves → **project spawns** carrying PO number, date, value and ordered items. Rejection stores a reason shown inline on the quotation and customer page.

### 7.2 Down-payment (DP) path
1. Sales files the PO with the DP flag → status `pending_finance`. **Finance** (not the director) is pinged.
2. Finance reviews on the Customer PO page → **Finance approve DP** (or reject with a reason) → status `pending_sales_confirm`.
3. Finance issues the **DP invoice against the PO itself** — the project doesn't exist yet.
4. Finance approves the DP invoice with the faktur pajak number.
5. The customer pays; **sales clicks "Confirm deposit received"** — this spawns the project, and every invoice on the PO is re-linked to it.

The director still sees DP POs in the approvals feed for visibility; a decision there is DP-aware (it advances the DP state machine, never spawns the project early). All approval requests are closed on decision so duplicates can't spawn.

---

## 8. Projects & production

### 8.1 Project pipeline

`new → purchasing → drawing → drawing_approved → production → qc → packaging → invoiced → delivered → paid → closed`

- Advancement is **one stage at a time, forward-only**; boot-time repairs guarantee a Space restart can never regress a project's stage.
- **Every stage carries a "how to move on" guide.** The card under the stage chips names the exact action that advances the project, who may do it, where the button lives, and any hard prerequisite the API enforces (e.g. import documents must be director-approved before Confirm delivery). It follows the project's own stage by default; clicking any chip reads that stage's guide instead, so you can look ahead without changing anything.
- The project header links the whole traceability chain: customer → quotation → customer PO → **PR number** — all clickable (role-permitting).
- Only the **director can delete a project** (soft-delete; the PO/quotation/invoice history stays; the customer PO is unlinked for potential re-approval).
- Editable header dates are role-gated; **target delivery is the promise**, actual delivery the measured outcome — the gap drives on-time reporting and missed-deadline alerts to management.

### 8.2 Work orders (ops board)

Work orders progress through **Receiving → Warehousing → QC → Packaging → Delivery** on the Operation board.
- Only **purchasing, admin, director** create/advance WOs.
- WOs are **stage-gated to the project**: receiving/warehousing/QC WOs require `production`; packaging requires `qc`; delivery requires `packaging`.
- Sales sees the board read-only with WO codes, notes and buttons hidden.

### 8.3 Drawings

- Internal staff (purchasing/admin/manager/director) upload technical drawings; **sales can upload the customer's own drawing**; suppliers upload via their portal (mirrored to the project).
- Submitted drawings are approved internally (manager/director/admin) and/or by the customer on their portal. Drawing approval advances the project (`drawing → drawing_approved`).

### 8.4 Logistics & imports

For import orders, purchasing maintains the required import documents (invoice, packing list, B/L, PIB, …) per delivery mode on the project's logistics card — expected complete before goods land. Document scans go through a director check.

### 8.5 Shipping timeline (three legs)

Origin → our warehouse → customer's site; each leg has estimated + actual dates, shown identically on the customer portal.

Lane ownership:
- **Purchasing**: Est. + Actual *shipped-from-origin*, the import flag, origin location.
- **Admin**: Est. + Actual *arrival at our warehouse* and *at the customer*.
- **Manager / Director**: any field; director edits apply instantly.
- Any non-director date change is **queued for director approval** — these dates are customer-visible promises; the timeline updates only when approved.

### 8.6 QC and delivery

- Operations records the QC decision (pass/fail with findings). **Passing QC unlocks the final invoice + delivery order** (issued by finance).
- Admin uploads the **delivery proof** (POD/courier slip); the **director verifies** it; then delivery can be confirmed ("customer received") → `delivered`.

---

## 9. Finance

### 9.1 Invoices

- **Finance owns invoice issuing** (director as backstop). Two flavours:
  - **DP invoice** — issued from the *customer PO page* before any project exists; re-linked to the project at sales-confirm.
  - **Final invoice** — issued from the project page after QC passes, together with the delivery order.
- **Faktur pajak** is entered at the *approval* step, not at issue: Finance → Pending invoices → enter FP number + upload the FP file → Approve.
- Finance can **delete** a duplicate/mistaken invoice with its FP record — blocked once any payment is verified against it.

### 9.2 Payments — two paths, one outcome

1. **Portal claim**: the customer clicks "I paid this" on their portal, attaching proof → finance **verifies or rejects** (reason shown to the customer) on Payment verification.
2. **Manual entry**: finance opens the project's invoice card → **"Enter payment manually"**: amount (prefilled to outstanding), date, method, reference, notes, optional proof upload — recorded *and* verified in one stroke, audit-tagged "recorded by finance".

Both paths: create a Payment row, post cash-up/receivable-down to the journal (attributed to the customer's sales rep), recompute the invoice status (`partial` until covered), and **when fully paid, auto-advance the project `paid → closed`**.

### 9.3 The journal & chart of accounts

Every financial movement (quotation posting, payments, payroll) writes signed journal lines against the 109 pre-seeded Indonesian chart of accounts (admin/director can extend it). Reversals are matching journal entries, never deletes. **Recent ledgers** shows the live feed of the latest postings; the **Linked Accounts** panel on each quotation shows exactly which accounts that deal touches.

### 9.4 Financial reports suite

Printable, period-aware reports (Finance/management; sales never sees them):

| Report | Contents |
|---|---|
| **Transactions** | the raw journal for a period |
| **Cash** | cash in/out and running balance |
| **Profit & Loss** | revenue − COGS − expenses, by month/quarter/year |
| **Balance sheet** | assets / liabilities / equity as of a date |
| **Assets** / **Liabilities** | detail drill-downs |
| **By salesperson** | won revenue and cash collected per sales rep, with a per-rep drill-down |

Every report exports to **PDF and Excel**. A separate **Estimated finance** page projects expected cash from open deals; **AR aging** buckets receivables (current / 0-30 / 31-60 / 61-90 / 90+); a **tax report** covers PPN.

### 9.5 Payroll

Director-only: generate the monthly run → post to ledger → mark paid.

---

## 10. Approvals & notifications

### 10.1 The approvals engine

A single `ApprovalRequest` table (target type + id, requester, required role, reason, JSON payload, decision fields) drives every gate. Decisions enforce who may decide (director-required → director only; manager → manager or director; finance → finance or director) and apply the effect atomically: quotation status + stage bump, queued quotation edits, customer stage changes + checklist spawn, customer-PO project spawn (DP-aware), supplier-PO effects, revision superseding.

**Who approves what**

| Decision | Approver |
|---|---|
| Quotation submit, Mark-won, customer PO (regular), supplier PO, price-request pricing, shipping/delivery date changes, sales follow-ups, quotation edits | **Director only** |
| DP customer PO, faktur pajak, payment verification | **Finance** (director backstop) |
| Manual CRM stage moves, manager-tier data changes | **Manager or director** |

The **/approvals inbox** (manager/director) lists pending requests **plus a documents queue** for status-based gates: submitted drawings, import-document scans, delivery proofs awaiting verification, and price requests pending director pricing — each deep-linked.

### 10.2 The notification bell

Notifications are computed live per user (nothing is stored stale) and surfaced four ways: the **bell dropdown**, **sidebar badges**, **banner pop-ups with a chime** for new arrivals, and **device push** (§10.3).

Every item is routed **only to who can act on it**, with a severity that controls its color and whether it reaches your phone:

| Kind | Who gets it | Severity |
|---|---|---|
| `approval` — request waiting | manager (manager-tier) / director (all) | high (director-tier) / medium |
| `approval_decided` — *your* request decided, with reason | the requester | low (approved) / medium (rejected) |
| `price_request` — PR handoff (submitted → purchasing; costed → director) | the next actor | medium |
| `price_request_decided` — PR approved/rejected | the requesting sales rep | low / medium |
| `at_risk_deal` — open quote idle ≥ 7 days | owning sales + management | high ≥ 14 d / medium |
| `payment_due` — invoice due ≤ 3 days or overdue | finance + owning sales + management | high (overdue) / medium |
| `stage_task` — dated checklist task due/overdue | the owning role (§4.1) | high (overdue) / medium |
| `missed_deadline` — project past target delivery | management | high |
| `drawing_pending` — drawing awaiting decision | approvers | low |
| `attendance` — attendance gaps | management | low/medium |
| `feedback` — new feedback to the director | director | medium |
| `team_rollup` — team workload summary | director | low |
| `chat` — unread messages roll-up | the recipient | low |
| `chat_oversight` — cross-department chat digest | director | low |

Housekeeping: every item has an **✕ dismiss** — dismissed items stay gone until their underlying state changes (e.g. new unread messages revive the chat row). High-severity items are red; the bell badge shows the count.

### 10.3 Device push (your phone)

Turn on **Device notifications** in the bell menu (per device). From then on, high/medium-severity items are pushed to that device by a background sweeper (~90 s cadence) even when the site is closed — approvals, PR handoffs, overdue invoices, at-risk deals, dated stage tasks. Low-severity housekeeping never buzzes your phone.

- Works on Android/desktop browsers directly; on **iPhone only from the installed home-screen app** (§2.5).
- A **"Send test notification"** button in the bell menu verifies the pipe end-to-end.
- Dead subscriptions (uninstalled app, cleared browser) are cleaned automatically.

### 10.4 Instant pushes (chat & discussions)

Two sources skip the sweeper and push **immediately**:
- **Chat**: every message pushes to the other members of the conversation — sender's name (+ group name) as the title, the message as the body, tap opens the chat. Multiple messages in one conversation collapse into a single re-alerting notification.
- **Discussions**: a comment on a price request / quotation / customer PO / supplier PO pushes to everyone already in the thread **plus** the document's natural stakeholders (requester, coster, approver) — so the *first* comment already reaches the right person. Title carries the document number; tap deep-links to it.

### 10.5 The calendar

A month grid aggregating the same material with identical role routing and purchasing blindness: reminders (with recurrence — daily/weekly/biweekly/monthly until an end date), activities, quotation expiries, invoice dues, target deliveries, and **dated** stage tasks. Each event type has a color and a toggle filter; clicking a day opens its detail; "New reminder" creates personal or customer-linked reminders.

---

## 11. Chat & discussions

- **Chat** (internal): DMs and named group channels with unread badges in the sidebar and header.
  - **Cross-department DMs** can only be *started* by a director, manager, or HR — peers within a department chat freely.
  - The **director has a monitor mode**: silently read (not join) cross-department conversations; a digest of cross-dept activity appears in their bell.
  - Messages can be edited/deleted (soft-delete leaves "message deleted").
  - On phones the chat is **WhatsApp-style**: full-screen list, tap opens a full-screen thread with a back arrow, composer pinned to the bottom.
  - Every message triggers an instant device push to the other members (§10.4).
- **Discussions**: threaded comments on price requests, quotations, customer POs, supplier POs, **projects and invoices** — the async paper-trail companion to chat, with stakeholder pushes. A thread is only readable by people who can open the document behind it.
- **@mentions**: typing `@` in any discussion opens a picker of every internal colleague, marking those who cannot open that page. Mentioning one of them grants **that conversation and nothing else** — they read and reply from their **Mentions** inbox, and never gain the document, its prices or the customer record. Mentions raise a high-severity bell item and a device push; ordinary replies on a thread you are part of raise a medium one.
- **Feedback**: every account can write feedback directly to the director (suggestion box); the director gets notified, reads them in an inbox, and marks items resolved.

---

## 12. People (HR) & other modules

- **Employees**: directory with tags, per-employee KPI page, and a four-slot **documents card: KTP, employment contract, NPWP, BPJS** (uploads by HR; visible to HR/finance/management; empty slots highlight what's missing).
- **Attendance**: clock-in/out, manual corrections (HR), leave/sick/holiday/WFH statuses; late = after 09:15 WIB; monthly summaries feed payroll conversations; gaps alert management.
- **Salary** (director-only): monthly payroll runs posted to the ledger.
- **Sales targets**: director sets per-rep monthly targets; each rep's dashboard shows an achieved-vs-target progress bar; feeds the by-salesperson report.
- **Inventory**: item catalog with categories, stock adjustments with movement history, and reorder requests (edits: admin/director).
- **KPI / Executive / Reports** (management): per-department KPI dashboards (sales, operation, purchasing, finance) with PDF/Excel export; an executive overview; the director-only Reports page (P&L, AR aging, sales-by-person, pipeline-by-stage, lost deals by industry/reason) with per-tab CSV and page-level PDF/Excel export.
- **AI assists**: lead scoring (0–100 with drivers, on the customer page), at-risk-deal detection, Bahasa Indonesia follow-up suggestions (copy-to-clipboard), auto-quotation drafting, document parsing, upsell hints, loss-pattern analysis, a sales coach, and the AI Command Center ("your day, ranked"). Requires an OpenAI API key configured server-side; budget-capped monthly.

---

## 13. Portals

- **Customer portal**: own quotations, projects with the three-leg shipping timeline (forecast amber, actual green), drawings to approve/reject, invoices, and "I paid this" claims with proof upload. No sidebar, no internal data.
- **Supplier portal**: only POs assigned to that vendor; upload drawing PDFs (mirrored to the project for customer approval); set warehouse ETA and ship dates that flow to the customer timeline instantly.
- Portal accounts are created by the director (Admin → Users) and hard-linked to one customer/supplier record — they can never see anyone else's data.

---

## 14. The happy path, end to end

1. **Sales** creates the customer (3-step wizard: basics → PICs → tax/NPWP), logs the first contact, advances Lead → Presentation (manager/director approve, reason recorded).
2. **Sales** files a **price request**. **Purchasing** costs it (pinged instantly). **Director** sets sell prices and approves (pinged when costing lands). Sales is notified of the decision.
3. **Sales** generates the **quotation** from the PR, submits; **director approves** (stage auto-bumps); sales exports the PDF (activity logged) and sends it. Questions along the way live in the PR/quotation discussion threads.
4. Customer says yes → **Mark won** → director approves (revenue posts to the journal). If terms change later: **Post revision** → edit → resubmit → the old version supersedes on approval.
5. **Sales files the customer PO** with the file + ordered items.
   - *Regular*: director approves → **project spawns**.
   - *DP*: finance approves → DP invoice on the PO → customer pays → sales confirms deposit → **project spawns**.
6. **Purchasing** raises the supplier PO (director approves), books origin shipping (director approves dates), completes import documents. **Supplier** uploads the drawing and ETA via the portal.
7. Drawing approved → production → **work orders** flow Receiving → Warehousing → QC on the ops board.
8. **QC passes** → **finance issues the final invoice + delivery order**; **admin stamps arrivals**, uploads the **delivery proof**, the **director verifies**, admin confirms "customer received" → `delivered`.
9. **Finance approves the invoice with the faktur pajak number.** The customer pays — portal claim or manual entry.
10. Full payment auto-advances the project **`paid → closed`**; the deal stage lands on `closed_won`. Every step is traceable backwards: project → PO → quotation → PR, with notes at each gate — and every actor was notified at their moment, on their phone.

---

## 15. Security, audit & testing

- **Auth**: JWT (12 h access / 30-day refresh), argon2 password hashing, per-IP login rate limiting, "Keep me signed in" opt-in (session-only storage by default — safe on shared computers).
- **Audit log** (admin/director): every consequential mutation writes actor / action / entity / before / after / IP — powering the audit page and the stage-history feature.
- **Attachments**: polymorphic, per-owner-type role visibility, authenticated downloads (no bare links), 20 MB cap. Director has an "All files" overview.
- **Testing**: in-process e2e suites drive the real ASGI app against a scratch Postgres with per-role clients — DP flow, permissions, financial math, notification routing, push targeting, stage-task dating, exports/won-lost/revisions.

---

## 16. Operations runbook

| Topic | What to know |
|---|---|
| **Frontend deploys** | automatic on every git push (Vercel), live in ~1 minute |
| **Backend deploys** | require a **Hugging Face Space rebuild** (it clones the repo at build time) |
| **Uploaded files** | live on the Space's `/tmp/storage` — **a Factory rebuild wipes them** (old uploads 404). Mitigation: move to object storage (e.g. Cloudflare R2) or a host with a persistent disk |
| **Database** | Neon Postgres; suspends when idle — first request after a quiet period is slow; boot logs `[boot]…` progress and never hangs silently |
| **Migrations** | none to run by hand — every boot runs the idempotent `seed.py` (create-all + `IF NOT EXISTS` column adds + forward-only data repairs) |
| **Push keys (VAPID)** | auto-generated on first use, stored in the DB — nothing to configure |
| **Key env vars** | `DATABASE_URL`, `JWT_SECRET`, `APP_ENV` (`prod` enforces safety checks), `CORS_ORIGINS`, `STORAGE_LOCAL_DIR`, optional `OPENAI_API_KEY` (AI features), `DEMO_SEED_PASSWORD` (dev-only demo users) |
| **Demo users** | seeded only in dev when `DEMO_SEED_PASSWORD` is set: director/manager/admin/hr/sales1/sales2 `@demo.local` |
| **Locale** | currency IDR (`Rp`, dot separators), timezone Asia/Jakarta, PPN 11 % default, bilingual EN/ID toggle persisted per device |

---

*Generated from the codebase. When workflows change, update this document together with the in-app Role Guide and Help pages.*
