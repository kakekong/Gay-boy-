# Transmisi Eng — System Guide

**Enterprise CRM + ERP for project-based industrial engineering**
Built for PT Transmisi Uplindo · live at `transmisisuplindo.com` · v0.1

This document explains what the system is, how it is built, and — in detail — how every workflow inside it operates: from a customer's first inquiry to a closed, fully-paid project.

---

## 1. What the system is

Transmisi Eng is a single web application that runs the entire commercial and operational life of an engineering trading/fabrication business:

- **CRM** — customers, contacts (PICs), a staged deal pipeline, activities, follow-ups, reminders.
- **Pre-sales pricing** — a price-request workflow where sales never invents a price: purchasing costs the items, the director sets the sell price.
- **Quotations** — generated from approved price requests, director-gated, exportable to PDF/Excel, revisable.
- **Order intake** — customer POs (regular and down-payment variants) that spawn projects.
- **Operations/ERP** — projects with a strict production pipeline, work orders, technical drawings, logistics & import documents, a three-leg shipping timeline, QC, delivery orders.
- **Finance** — invoices (DP and final), faktur pajak (Indonesian tax invoice), payment claims and verification, manual payment entry, AR aging, a double-entry-style transaction journal, financial reports, payroll.
- **HR** — employee directory, personnel documents (KTP, contract, NPWP, BPJS), attendance.
- **External portals** — a stripped-down customer portal (order status, drawing approval, payment claims) and supplier portal (assigned POs, drawing upload, ETA entry).
- **Cross-cutting** — role-scoped notifications with banners/sounds, an approvals inbox, chat, audit logging, full English/Indonesian bilingual UI.

The design philosophy: **every consequential action is gated, scoped, and leaves a paper trail.** Sales can't invent prices; purchasing can't see customers; nobody below director can change a customer-visible date silently; every stage move, edit, and payment is either approved or audited.

---

## 2. Architecture & stack

### 2.1 Components

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript, TanStack Query, Tailwind CSS, Zustand, lucide-react | Vercel (auto-deploys on every push) |
| Backend | FastAPI (Python 3.11) + SQLAlchemy 2 async + Pydantic v2 | Hugging Face Space (Docker; clones this GitHub repo at build) |
| Database | PostgreSQL | Neon (serverless Postgres) |
| Cache/queue | Redis | Upstash |
| File storage | Local disk `/tmp/storage` on the Space (ephemeral — wiped on rebuild) | — |

### 2.2 Repository layout

```
backend/
  app/
    api/v1/endpoints/   # one file per domain: customers, quotations, price_requests,
                        # customer_pos, operation, finance, payments, approvals,
                        # notifications, calendar, attachments, comments, chat, hr, …
    core/               # config, db, deps (auth), permissions, approval engine,
                        # audit, stage_playbook, stage_tasks, logging
    models/             # SQLAlchemy models (one file per domain)
    schemas/            # Pydantic request/response models
    scripts/seed.py     # idempotent schema creation + column migrations, run on EVERY boot
    services/           # ledger posting, numbering, quote import (Excel/PDF parsing)
  tests/                # in-process e2e suites (see §15)
frontend/
  src/
    pages/              # one page component per route
    components/         # shared components (AttachmentsSection, CommentThread, Modal, …)
    layouts/Shell.tsx   # sidebar, topbar, role allowlists, notification bell
    store/              # zustand stores: auth, lang (i18n)
docs/                   # this document
```

### 2.3 Request flow

1. The browser loads the React app from Vercel.
2. Every API call goes to the Space's FastAPI under `/api/v1/...` with a JWT bearer token.
3. FastAPI resolves the current user (`get_current_user`), applies role/scope guards per endpoint, talks to Neon via async SQLAlchemy, and returns JSON in a uniform envelope (`{data, errors, meta}` for errors).
4. TanStack Query caches responses client-side and invalidates keys after mutations, so pages refresh without reloads.

### 2.4 Boot sequence (backend)

On every container start:
1. The Space Dockerfile runs `python -m app.scripts.seed` (best-effort), then `uvicorn app.main:app`.
2. The app's lifespan runs `ensure_schema()`: `create_all` for missing tables plus ~90 idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations, and data-repair statements. This is capped at 90 s × 3 attempts with loud `[boot]` log lines — a hung database delays boot instead of bricking it, and the API starts anyway after three timeouts.
3. Prod-safety check: the app refuses to boot in `APP_ENV=prod` with default secrets, default DB password, or `CORS_ORIGINS=["*"]`.

**Deployment note:** the Space clones GitHub *at build time* — backend changes require a Space rebuild; the frontend deploys automatically via Vercel. A Factory rebuild wipes `/tmp/storage` (uploaded files).

---

## 3. Roles & access model

Nine roles. Four internal roles are hard-capped by a sidebar/route allowlist (`ROLE_PAGE_ALLOWLIST` in `Shell.tsx`, enforced again by a route guard); the rest see pages per-item.

| Role | Scope (pages) | One-line job |
|---|---|---|
| **Sales** | CRM, price requests, quotations, customer POs, projects (shell view), ops board (read-only), calendar, chat | Owns customers from first hello to signed PO |
| **Purchasing** | Price requests, purchasing/suppliers, purchase orders, inventory, calendar, projects (customer-blind), attendance, chat | Prices deals, raises supplier POs, books origin shipping — never sees customer identity |
| **Admin** | Projects, operation board, inventory, attendance, chat | Runs production: work orders, arrivals, delivery proofs. No CRM, no money pages |
| **Finance** | Finance, financial reports, estimated finance, payment verification, chart of accounts, recent ledgers, customer POs, projects, attendance, chat | Issues + approves invoices, gates DP POs, verifies/records payments |
| **HR** | Employees, attendance, chat | Personnel documents and attendance |
| **Manager** | Everything (oversight) | Clears manual stage moves + manager-tier data changes; watches every queue |
| **Director** | Everything + Salary, PO Recap, All files, Users, KPI, Audit log | The approval authority for every deal document |
| **Customer** (portal) | Own quotations, projects, invoices, drawings, payment claims | External |
| **Supplier** (portal) | Own assigned POs, drawing upload, ETA entry | External |

The director can also build **custom roles** (name + base tier + page list) from Admin → Users.

### 3.1 Information boundaries (deliberate)

- **Purchasing is customer-blind.** Projects render as "Order PRJ-…"; price requests hide the customer; the calendar and notifications never show company names to purchasing; work-order lists and PO screens are scrubbed server-side (`_can_see_project_customer`).
- **Sales is money/ops-blind.** On a project, sales sees only the customer-facing shell (header, pipeline, shipping timeline, drawings upload). Work orders, invoices, margins, supplier POs, QC and logistics are hidden. Sales also never sees procurement cost on a price request.
- **Internal note scrubbing.** Lines that begin with `[purchasing]`, `[director]`, etc. in price-request notes are a staff side-channel; they are stripped before sales sees the PR and before notes are copied to a quotation (which is customer-facing on PDF and portal).
- **Sales sees only its own records** (customers where they are the sales PIC, and the quotations/PRs/POs of those customers). Enforced on every list and detail endpoint.

---

## 4. The deal pipeline (CRM)

Each customer carries a **stage**: `lead → presentation → engineering → quotation → negotiation → po → drawing → purchasing → delivery → invoicing → payment → closed_won / closed_lost`.

- **Forward moves are one stage at a time** (no skipping); backward moves are always allowed. `closed_lost` can be jumped to from anywhere.
- **Manual stage moves need approval.** Sales files a request (with a mandatory written reason + optional files); a **manager or director** approves. Managers'/directors' own moves apply instantly.
- **Stage notes are permanent.** Clicking a *passed* stage on the pipeline stepper opens that stage's paper trail: every move into/out of it, the reason written at the time, who requested, who decided, and the decision note. A "move back to this stage" button preserves the regression path.
- **The fused pipeline.** Deal documents advance the stage automatically, so sales never files a stage request for ground already covered:
  - quotation approved → stage `quotation`
  - Mark-Won approved → stage `negotiation`
  - customer PO approved → stage `po`
  - project progress mirrors onward stages (`drawing`, `purchasing`, `invoicing`, `payment`, `closed_won`) — forward-only, never regressing.
- **Stage tasks (playbook).** Entering a stage auto-spawns that stage's required checklist as reminders (e.g. lead: "Make first contact" due in 1 day). Each task is owned by a role (see §10) and shows on the customer page as a tickable checklist with due dates, notes, and calendar entries.

---

## 5. Pricing: the price request (PR)

Sales cannot type a price anywhere. The flow:

1. **Sales files a PR** on the customer page: line items (description, qty, UoM, spec), no prices. Status `draft` → `pending_purchasing` on submit.
2. **Purchasing costs it**: procurement cost per line (entered per-unit or as line total; stored per-unit). Status → `pending_director`. Purchasing can attach an internal `[purchasing]` note.
3. **Director prices it**: sets the sell price per line (and may correct costs), approves. Status → `approved`.
4. **Sales generates the quotation** from the approved PR — every unit price is the director's sell price, carried automatically.

Around the PR:
- **The PR number is editable at any stage** (unique, audited) — e.g. to mirror the customer's own RFQ number. All links are by id, so renames orphan nothing.
- **File uploads** ride on the PR (spec sheets, the customer's RFQ) so purchasing can cost from source documents.
- **A discussion thread** (sales ↔ purchasing ↔ director) lives on the PR.
- **Log activity** posts to the customer's timeline from the PR page.
- Serialization is role-aware: purchasing never receives sell price or customer name; sales never receives cost.

---

## 6. Quotations

### 6.1 Lifecycle

`draft → pending_approval → approved → (sent) → won / lost`, plus `rejected`, `cancelled`, and `superseded` (see revisions).

- **Creation**: sales only via *generate from approved PR* (direct `POST /quotations` returns 409 for sales). Director/manager/admin retain a direct-creation path for off-system negotiated deals. Numbers are auto-generated with an editable token, or fully custom (uniqueness enforced).
- **Submit**: every quotation requires **director approval** — there is no discount-based auto-approve. Submitting creates an approval request.
- **Unsubmit**: while still pending, the owner (or director) can withdraw — the quote returns to draft and the pending approval request is deleted so a stale decision can't land.
- **Approval**: director approves/rejects (inline on the quote or in /approvals). Approval bumps the customer stage to `quotation`.
- **Editing rules**:
  - `draft`/`rejected`: fully editable by the owner or director.
  - `approved`/`sent`: pricing edits are allowed but **queue a `quotation_edit` approval** — changes apply only when the director approves; the quote shows an "Edit awaiting director" chip meanwhile. Director edits apply instantly. `valid_until` and `notes` (meta) stay directly editable at any open stage.
  - `pending_approval`: locked — unsubmit first.
  - PR-backed drafts: line prices are fixed by the approved PR; sales can't change items directly (but can via the queued-edit path on an approved quote, since the director signs off again).
- **Mark won**: sales' click files a `quotation_won` request to the director; approval flips the quote to Won, posts revenue to the ledger, and bumps the stage. **Won does not create a project** — the customer PO does.
- **Mark lost**: requires a written reason; blocked while a Mark-won request is pending and on won/closed quotes (mutually exclusive outcomes, enforced in UI and API).
- **Exports**: PDF and Excel, styled with the company header, PIC addressing and totals. **Every export writes an `export` activity** to the customer timeline (who, which quote, which format, when).
- **Follow-ups**: logged on the quote; they route to the director for approval before being recorded; approved follow-ups can schedule the next reminder.

### 6.2 Revisions

"Post revision" on an approved/sent/rejected/lost quote clones it into a **new editable draft** numbered `<base>-R<n>` (version bumped, `parent_id` linked, items/prices/PR link copied). The revision walks the normal submit → director approval path. **When the revision is approved, the original flips to `superseded`** so only one version of the offer is ever live. One open revision at a time; the header shows the whole revision chain as links; a superseded quote can't be revised (revise the live one).

### 6.3 Ledger link

Winning (or posting) a quotation writes to the chart of accounts: Piutang Usaha ↑, Penjualan ↑, PPN Keluaran ↑, Diskon ↑ — visible in the Linked Accounts panel with per-quote account overrides and a reversal mechanism (reversal entries, never hard deletes).

---

## 7. Order intake: customer POs

Filed from the Won quotation's "Next step" card: attach the customer's PO file, pick which quoted items they actually ordered (with price edits if negotiated), set the PO number/date, and optionally tick **"This PO is a down payment"**.

### 7.1 Regular PO path
`pending_approval` → **director** approves → **project spawns** carrying PO number, date, value and ordered items. Rejection stores a reason shown inline on the quotation and customer page.

### 7.2 Down-payment (DP) path
1. Sales files the PO with the DP flag → status `pending_finance`. **Finance** (not the director) is pinged.
2. Finance reviews on the Customer PO page → **Finance approve DP** (or reject with a reason) → status `pending_sales_confirm`.
3. Finance issues the **DP invoice against the PO itself** — the project doesn't exist yet; the invoice attaches via `customer_po_id`.
4. Finance approves the DP invoice with the faktur pajak number.
5. The customer pays; **sales clicks "Confirm deposit received"** — this is what **spawns the project**, and every invoice on the PO is re-linked to it.
- The director still sees DP POs in the approvals feed for visibility, and an /approvals decision on one is DP-aware (it advances the DP state machine, never spawns the project early). All approval requests are closed on decision so duplicates can't spawn.

---

## 8. Projects & production

### 8.1 Project pipeline

`new → purchasing → drawing → drawing_approved → production → qc → packaging → invoiced → delivered → paid → closed`

- Advancement is **one stage at a time, forward-only** (`advance_project_status` caps at a single step). Boot-time repair migrations guarantee a Space restart can never regress a project's stage.
- The project header links the whole traceability chain: customer → quotation → customer PO → **PR number** — all clickable (role-permitting).
- Only the **director can delete a project** (soft-delete; the PO/quotation/invoice history stays; the linked customer PO is unlinked for potential re-approval).
- Editable header dates (PO date, start, target delivery) are role-gated; **target delivery is the promise** and actual delivery the measured outcome — the gap drives on-time reporting.

### 8.2 Work orders (ops board)

Work orders progress through **Receiving → Warehousing → QC → Packaging → Delivery** on the Operation board. Rules:
- Only **purchasing, admin, director** can create/advance WOs.
- WOs are **stage-gated to the project**: receiving/warehousing/QC WOs require the project to have reached `production`; packaging requires `qc`; delivery requires `packaging`. You can't open a work order for a phase the project hasn't earned.
- Sales sees the board read-only with WO codes, notes and buttons hidden.

### 8.3 Drawings

- Internal staff (purchasing/admin/manager/director) upload technical drawings; **sales can upload the customer's own drawing** on their customers' projects; suppliers upload via their portal (mirrored to the project).
- Submitted drawings are approved internally (manager/director/admin) and/or by the customer on their portal. Drawing approval advances the project (`drawing → drawing_approved`).

### 8.4 Logistics & imports

For import orders, purchasing maintains the required import documents (invoice, packing list, B/L, PIB, …) per delivery mode on the project's logistics card — expected complete before goods land. Document scans go through a director check.

### 8.5 Shipping timeline (three legs)

Origin → our warehouse → customer's site; each leg has estimated + actual dates, shown identically to the customer portal.

Lane ownership:
- **Purchasing**: Est. + Actual *shipped-from-origin*, the import flag, origin location.
- **Admin**: Est. + Actual *arrival at our warehouse* and *at the customer*.
- **Manager**: any field. **Director**: any field, applies instantly.
- Any non-director date change is **queued for director approval** (these dates are customer-visible promises) — the timeline updates only when approved.

### 8.6 QC and delivery

- Operations records the QC decision (pass/fail with findings). **Passing QC unlocks the final invoice + delivery order** (issued by finance).
- Admin uploads the **delivery proof** (POD/courier slip); the **director verifies** it; then delivery can be confirmed ("customer received") which moves the project to `delivered`.

---

## 9. Finance

### 9.1 Invoices

- **Finance owns invoice issuing** (director as backstop). Two flavours:
  - **DP invoice** — issued from the *customer PO page* before any project exists; re-linked to the project at sales-confirm.
  - **Final invoice** — issued from the project page after QC passes, together with the delivery order.
- **Faktur pajak** is entered at the *approval* step, not at issue (finance double-checks before the tax record is touched): Finance → Pending invoices → enter FP number + upload the FP file → Approve.
- Finance can **delete** a duplicate/mistaken invoice with its FP record — blocked once any payment is verified against it.

### 9.2 Payments — two paths, one outcome

1. **Portal claim**: the customer clicks "I paid this" on their portal, attaching proof → finance **verifies or rejects** (reason shown to the customer) on Payment verification.
2. **Manual entry**: for customers who pay by transfer without the portal — finance opens the project's invoice card → **"Enter payment manually"**: amount (prefilled to outstanding), date, method, reference, notes, optional proof upload. Recorded **and** verified in one stroke (the audit trail matches the portal flow: a pre-verified claim tagged "recorded by finance").

Both paths: create a Payment row, post cash-up/receivable-down to the journal (attributed to the customer's sales rep), recompute the invoice status (`partial` until covered), and **when the invoice is fully paid, auto-advance the project `paid → closed`**.

### 9.3 Ledger & reports

Every financial movement (quotation posting, payments, payroll) writes signed journal lines against the 109 pre-seeded Indonesian chart of accounts. The reporting engine slices P&L, cash flow, AR aging (issued/approved/partial/overdue buckets minus payments), and revenue-by-sales-rep by month/quarter/year, with exports. Reversals are matching journal entries, never deletes.

### 9.4 Payroll

Director-only: generate the monthly run → post to ledger → mark paid.

---

## 10. Approvals & notifications

### 10.1 The approvals engine

A single `ApprovalRequest` table (target type + id, requester, required role, reason, JSON payload, decision fields) drives every gate. `decide()` enforces who may decide (`DIRECTOR`-required → director only; `MANAGER` → manager or director; `FINANCE` → finance or director) and `apply_to_target()` applies the effect atomically: quotation status + stage bump, queued quotation edits, customer stage changes + checklist spawn, customer-PO project spawn (DP-aware), supplier-PO/PR/inventory/project-date effects, revision superseding.

**Who approves what**

| Decision | Approver |
|---|---|
| Quotation submit, Mark-won, customer PO (regular), supplier PO, price-request pricing, shipping/delivery date changes, sales follow-ups, quotation edits | **Director only** |
| DP customer PO, faktur pajak, payment verification | **Finance** (director backstop) |
| Manual CRM stage moves, manager-tier data changes | **Manager or director** |

The **/approvals inbox** (manager/director) lists pending requests **plus a documents queue** for status-based gates that bypass the request table: submitted drawings, import-document scans, delivery proofs awaiting verification, and price requests pending director pricing — each deep-linked.

### 10.2 Notifications

Computed live (no notifications table), returned by `GET /notifications` and surfaced as: the bell dropdown, sidebar badges, banner pop-ups with a chime and OS notifications, and an auto-refreshing stripe.

**Routed by role** — each item goes only to who can act on it:
- Approvals waiting → manager/director. DP `pending_finance` → finance; DP `pending_sales_confirm` → the owning sales rep.
- Decisions on *your* requests (with the decision reason) → the requester.
- At-risk deals (idle ≥ 7 days) → owning sales + management.
- Invoice due/overdue → finance + owning sales + management.
- Stage-task nags follow the playbook's owning role: deal chores → sales (own customers only); raise-PR/select-supplier → purchasing (customer-blind, linked to their queue); drawing/delivery chores → admin; issue/send-invoice + payment follow-up → finance. Manager/director see everything; HR gets none.
- Attendance gaps and missed project deadlines → management. Cross-department chat oversight → director.

The calendar aggregates the same material (stage tasks, reminders, quote expiries, invoice dues, target deliveries) with identical role routing and purchasing blindness.

---

## 11. HR

- Employee directory with tags, per-employee KPI page, and a four-slot **documents card: KTP, employment contract, NPWP, BPJS** (uploads by HR; visible to HR/finance/management; empty slots highlight what's missing).
- Attendance: clock-ins, manual corrections, leave/sick/holiday/WFH statuses; late = after 09:15 WIB; monthly missed-day chips feed payroll conversations.
- Account creation is director-only (Admin → Users); HR files documents once the account exists.

---

## 12. Portals

- **Customer portal**: own quotations, projects with the three-leg shipping timeline (forecast amber, actual green), drawings to approve/reject, invoices, and "I paid this" claims with proof upload. No sidebar, no internal data.
- **Supplier portal**: only POs assigned to that vendor; upload drawing PDFs (mirrored to the project for customer approval), set warehouse ETA and ship dates that flow to the customer timeline instantly.

---

## 13. Cross-cutting features

- **Attachments**: a single polymorphic table (`owner_type` + `owner_id`) with per-owner-type role visibility (e.g. supplier-PO files → director+purchasing; invoice files → finance/admin/management/sales; PR files → the PR audience). Downloads are authenticated (blob fetch, not bare links). Max 20 MB.
- **Discussions**: comment threads on quotations, customer POs, supplier POs and price requests.
- **Chat**: internal DM/channels with unread badges; deletes are soft.
- **Audit log**: every consequential mutation writes actor/action/entity/before/after — powering the director's audit page and the stage-history feature.
- **i18n**: a per-string `t("English", "Indonesian")` system with a persisted language toggle. The sidebar, Login, Help, Role guide, and the entire sales surface (CRM, customer detail, price requests, quotations + forms, customer POs + DP flow, projects, dashboard, calendar) are fully bilingual; backend status keys translate through display-label maps so API values never change.
- **AI assists**: Bahasa Indonesia follow-up suggestions, vendor recommendations (rating + lead time), lead scoring, at-risk-deal detection, the AI Command Center.
- **In-app guides**: a role-scoped Role Guide (per-role daily rhythm, workflows, button reference, rules, troubleshooting — directors can read all roles) and a page-by-page Help.

---

## 14. The happy path, end to end

1. **Sales** creates the customer (3-step wizard: basics → PICs → tax/NPWP), logs the first contact, advances Lead → Presentation (manager/director approve, reason recorded).
2. **Sales** files a **price request** with the items. **Purchasing** costs it. **Director** sets sell prices and approves.
3. **Sales** generates the **quotation** from the PR, submits; **director approves** (stage auto-bumps to `quotation`); sales exports the PDF (activity logged) and sends it.
4. Customer says yes → **Mark won** → director approves (stage → `negotiation`, revenue posts). If terms change later: **Post revision** → edit → resubmit → the old version supersedes on approval.
5. **Sales files the customer PO** with the file + ordered items.
   - *Regular*: director approves → **project spawns** (stage → `po`).
   - *DP*: finance approves → finance issues the DP invoice on the PO → customer pays → sales confirms deposit → **project spawns**.
6. **Purchasing** raises the supplier PO (director approves), books the origin shipment (est./actual ship-from-origin; director approves dates), and completes import documents. **Supplier** uploads the drawing and ETA via the portal.
7. Drawing approved → production → **work orders** flow Receiving → Warehousing → QC on the ops board (admin/purchasing).
8. **QC passes** → **finance issues the final invoice + delivery order**; **admin stamps arrivals**, uploads the **delivery proof**, the **director verifies** it, admin confirms "customer received" → `delivered`.
9. **Finance approves the invoice with the faktur pajak number.** The customer pays — via a portal claim finance verifies, or finance enters it manually on the project.
10. Full payment auto-advances the project **`paid → closed`**; the customer's deal stage lands on `closed_won`. Every step above is traceable backwards: project → PO → quotation → PR, with notes at each gate.

---

## 15. Testing & operations

- **In-process e2e suites** (`backend/tests/`) drive the real ASGI app against a scratch Postgres with per-role authenticated clients — covering the DP flow (26 assertions), permissions, financial math, and (in session scratchpads) manual payments, notification routing, shipping lanes, stage history, and the export/won-lost/revision cluster.
- **Idempotent boot migrations**: `seed.py` is safe to run on every start; column adds use `IF NOT EXISTS`; data repairs are forward-only.
- **Operational cautions**:
  - Backend changes need a **Space rebuild**; frontend deploys automatically.
  - A Factory rebuild **wipes `/tmp/storage`** — previously uploaded files 404 afterwards (mitigation: object storage such as Cloudflare R2, or a host with a persistent disk — see the hosting recommendation).
  - Neon suspends when idle; the hardened boot logs `[boot] …` progress and never hangs silently on it.

---

*Generated from the codebase on the `claude/enterprise-crm-erp-ai-IMGRg` branch. When workflows change, update this document together with the in-app Role Guide and Help pages.*
