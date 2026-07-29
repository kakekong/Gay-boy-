# Agent handoff brief — Transmisi Eng CRM/ERP

**Paste this whole file into a new chat.** It carries the working context of the
previous session: the facts, conventions and hard-won gotchas needed to keep
answering and building the same way. For *what the product does*, read
`docs/SYSTEM_GUIDE.md` — this file is about *how to work on it*.

---

## 0. First message to a new chat

> Read `docs/AGENT_HANDOFF.md` and `docs/SYSTEM_GUIDE.md`, then continue where
> the last session left off.

---

## 1. Who you're working with

- **kakekong** — director of **PT Transmisi Uplindo**, an Indonesian industrial
  engineering trading/fabrication company. Not a professional developer, but
  knows the business cold and tests everything personally in the live app.
- Writes short, lowercase, informal requests, often with a screenshot of the bug.
  Typos are common ("porc" = "pop"/trigger, "distruptions" = disruptions). Read
  through them; don't ask for clarification on obvious ones.
- Requests are almost always **incremental changes to a production system that
  real staff use today**. Nothing here is a toy.
- What they consistently want:
  - The thing actually fixed and **pushed**, not a plan or a patch to review.
  - Proof it works — they respond well to "I reproduced the bug, then verified
    the fix" and badly to "this should now work".
  - Proactive hunting: they've asked more than once for *"all potential errors
    even if you're not sure"*. When they ask for a bug hunt, hunt broadly and
    fix everything found, not just the reported symptom.
  - Concise prose in replies. Tables and step lists when listing many items.
    No preamble, no restating their request back at them.
- They test on **mobile a lot**. Layout regressions on phones matter.
- Decisions they've already made (don't re-ask):
  - Project phases D/E (production vs purchasing) **can happen in any order**.
  - **Admin, not just finance/director, may issue invoices.**
  - **All work goes on `claude/enterprise-crm-erp-ai-IMGRg`**, whatever branch
    the session was opened on (§2).

---

## 2. Repo, branch, deployment

| Fact | Value |
|---|---|
| GitHub repo | `kakekong/Gay-boy-` (the only repo in session scope) |
| **Working branch** | **`claude/enterprise-crm-erp-ai-IMGRg`** — all work goes here |
| Frontend host | Vercel — **auto-deploys on every push**, no action needed |
| Backend host | Hugging Face Space (Docker) — **requires a manual rebuild** |
| Database | Neon serverless Postgres |
| File storage | `/tmp/storage` on the Space — **ephemeral, wiped on every rebuild**. Being replaced by Cloudflare R2 (`docs/DEPLOY_RENDER.md`) |
| Live site | `transmisisuplindo.com` |

**The branch matters.** `infra/hfspace/Dockerfile:21` pins
`ARG GIT_BRANCH=claude/enterprise-crm-erp-ai-IMGRg`; the Space clones *that*
branch at build time, and it is also the repo's default branch. Pushing
anywhere else deploys nothing.

**A session that opens on some other `claude/...` branch should check out IMGRg
and work there — the user confirmed this explicitly, so don't ask again.**
Those auto-generated per-session branches (e.g. `claude/agent-handoff-…`) are
left where they are; nothing is deleted, and no PR is needed. Just
`git checkout claude/enterprise-crm-erp-ai-IMGRg` and commit onto it.

**Always tell the user when a change is backend-side**, because a push alone
does not deploy it: they must open the Space and hit rebuild. The Dockerfile
has a cache-bust `ADD` against the GitHub commits API so a *normal* rebuild
picks up new code — a "Factory rebuild" is not needed.

Frontend-only changes are live within a minute or two of the push.

---

## 3. Stack and layout

**Backend** — FastAPI (Python 3.11), SQLAlchemy 2 async, Pydantic v2.

```
backend/app/
  api/v1/endpoints/   one file per domain (customers, quotations, price_requests,
                      customer_pos, operation, finance, payments, approvals,
                      notifications, push, calendar, chat, comments, attachments,
                      attendance, users, audit, ai, portal, …)
  core/               config, db, deps (auth), permissions, approval engine,
                      audit, stage_playbook, stage_tasks
  models/             SQLAlchemy models, one file per domain
  scripts/seed.py     idempotent schema creation + column migrations — runs on EVERY boot
  services/           webpush, ledger posting, financial reports, numbering,
                      quote import (Excel/PDF), exports
  workers/            background jobs
backend/tests/        pytest unit suites + tests/e2e/ (see §5)
```

**Frontend** — React 18 + Vite + TypeScript, TanStack Query, Zustand, Tailwind,
lucide-react, `frontend/src/pages/*.tsx` one page per screen.

**File storage goes through `app/services/storage.py`** — never write to disk
directly. `STORAGE_BACKEND` picks local disk or an S3-compatible bucket
(Cloudflare R2 in production). Crucially, **reads dispatch on the stored path,
not the current setting**: a row whose `storage_path` starts with `s3://` is
fetched from the bucket, anything else from disk. That is what lets the backend
be switched with no migration and no downtime; `app/scripts/migrate_storage.py`
consolidates afterwards. boto3 is sync, so every call goes through a worker
thread — don't call it inline.

**There is no Alembic.** Schema changes go in `app/scripts/seed.py`:
`Base.metadata.create_all` creates new tables, and the `COLUMN_MIGRATIONS` list
adds columns to existing ones. Both run inside `ensure_schema()` on every boot,
so they must be idempotent and safe against a live DB. Adding a column =
append a row to `COLUMN_MIGRATIONS`; never hand-edit the production DB.

---

## 4. Local dev environment

The container has Postgres 16 available but not running as a service. The
scratch DB used for all testing:

```bash
# start it (runs as nobody, socket in /tmp, TCP on 55432)
su -s /bin/bash nobody -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgdata_test \
  -o '-p 55432 -k /tmp -c listen_addresses=127.0.0.1' -l /tmp/pg_test.log start"
```

Environment for any backend script or test:

```bash
export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test"
export APP_ENV=dev
export DEMO_SEED_PASSWORD=test-pass-123
export STORAGE_LOCAL_DIR=/tmp/storage_test
export JWT_SECRET=e2e-test-secret
```

Seed / migrate: `cd backend && python -m app.scripts.seed`

Frontend: `cd frontend && npm run build` (or `npm run typecheck`). **Always
build or typecheck after touching TSX** — Vercel will happily deploy a broken
bundle if you don't catch it here.

Playwright + Chromium are preinstalled: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`.
Never run `playwright install`.

---

## 5. The test suite — use it

```bash
bash backend/tests/e2e/run_all.sh --fresh   # recreate DB, seed, run everything
bash backend/tests/e2e/run_all.sh           # re-run on the existing DB
```

`backend/tests/e2e/` holds 14 drivers that exercise the **real ASGI app
in-process** via `httpx.ASGITransport`, with real logins per role — no mocks,
no fixtures pretending to be permissions. This is the pattern to copy when
writing a new check:

```python
c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                      base_url="http://t/api/v1", timeout=40)
d = await login(c, "director@demo.local")   # password from DEMO_SEED_PASSWORD
```

| Driver | Covers |
|---|---|
| `wf_full.py` | the whole happy path, lead → closed project (`PROBLEMS: 0`) |
| `test_security.py` | portal-role privilege escalation (`CONFIRMED HOLES: 0`) |
| `test_portal_ok.py` | portal roles can still do their legitimate work (13/13) |
| `test_money_integrity.py` | invoice DPP, ghost payments, forged QC pass |
| `test_pending_docs.py` | stale delivery orders / documents on closed projects |
| `test_stale_approvals.py` | approval requests whose target already moved on |
| `test_batch_fixes.py` | stage-task retirement, approval gates, scoping, tax period |
| `test_partial_payment_ar.py` | a partially-paid invoice is owed only its remainder, on all four AR surfaces |
| `verify_order.py` | project phases D/E work in either order |
| `test_link_attach.py` | link (URL) attachments + who may attach |
| `test_daily_log.py` | attendance daily log |
| `test_clock_note.py` | clock-in/out notes; nobody overwrites HR's note or each other's |
| `test_storage_s3.py` | the S3/R2 backend against a real moto server, incl. the disk→bucket migration |
| `test_efaktur.py` | e-Faktur CSV export |

Plus `pytest tests/test_permissions.py tests/test_discount_rules.py tests/test_financials.py`
and `python tests/e2e_dp_flow.py` (down-payment flow, 26/26), both invoked by
`run_all.sh`.

**Last known state: everything green.**

---

## 6. Working conventions that actually matter

These were learned the hard way in the previous session. They are the
difference between being useful here and being confidently wrong.

1. **Verify empirically. Always.** Before claiming a bug exists, *reproduce it*
   — write a throwaway driver against the scratch DB and watch it fail. After
   fixing, run the same driver and watch it pass. "Reading the code suggests…"
   has produced several false alarms; running it has produced zero.

2. **Do not trust subagent claims.** In the last session one agent reported "no
   webpush/VAPID implementation exists in the backend" (it did, in
   `app/services/webpush.py`), and another reported `mark_delivered` had no
   guard (it has a workflow guard). Grep and read the file yourself before
   acting on any agent's finding. *(Also: don't spawn subagents unless the user
   asks for them.)*

3. **Distinguish test artifacts from product bugs.** Several drivers use
   hardcoded document numbers (`PO-CUST-A1`, `DP-001`, `INV-EF-001`). Re-running
   on a dirty DB produces "already exists" 409s that look exactly like bugs and
   are not. Re-run with `--fresh` before believing a failure. Same class of
   trap: a driver that picks the *first* pending approval request instead of
   matching on `target_id` will approve a leftover from an earlier run and fail
   downstream with a confusing error. Always match by `target_id`:
   ```python
   wr = next(x for x in reqs if x.get("target_type") == "quotation_won"
             and str(x.get("target_id")) == str(q))
   ```

4. **Fix the whole class, not the one instance.** When the user reported one
   stale delivery order on a closed project, the same staleness existed in 7
   other queries. Grep for the pattern across the codebase and fix every site.

5. **Watch for regressions you introduce.** A security fix in the last session
   reused the *view* rule (director-only for customer files) as the *upload*
   guard and locked sales out of attaching files. `test_link_attach.py` caught
   it. Run the full suite before pushing anything that touches permissions.

6. **Commit style** — imperative subject line, a body explaining *why* in plain
   prose, and the trailers:
   ```
   Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
   Claude-Session: <session url>
   ```
   Push with `git push -u origin claude/enterprise-crm-erp-ai-IMGRg`; retry with
   exponential backoff on network errors. **Never put the model identifier in a
   commit message, PR, or code comment.** Do not open a PR unless asked.

7. **Match the surrounding code.** Comment density in this repo is moderate and
   comments explain *why*, often a business rule ("Purchasing sees projects for
   procurement context but not the customer identity — same customer-blindness
   rule as the PO screens"). Keep that voice.

8. **Dark mode is class-based** (`html.dark`) with **global utility overrides in
   `frontend/src/index.css`** — this codebase does *not* use Tailwind `dark:`
   variants. Adding a new color means adding an override there, or it will look
   broken at night. The user notices.

---

## 7. Domain rules a new agent will otherwise get wrong

**Role hierarchy** (`app/core/permissions.py`):

```
customer, supplier = 0   ← external portal roles
sales              = 1
admin, hr, purchasing, finance = 2
manager            = 3
director           = 4
```
Gates: `require(*roles)` for exact membership, `require_min(Role.X)` for the
hierarchy. **23 endpoint routers carry `dependencies=[Depends(require_min(Role.SALES))]`
specifically to keep the two portal roles out of internal data** — if you add a
new internal router, add that dependency too, or you've opened a hole.

**Purchasing is customer-blind on purpose.** Purchasing sees projects and POs
for procurement context but never the customer identity or deal economics, so
no customer↔supplier map can be reconstructed. Preserve this on any new screen
(`Projects.tsx` shows the pattern: `showMoney`/`showCustomer` flags).

**Sales sees only their own customers** (`can_view_customer`). Everyone above
sees all.

**Invoice lifecycle** — the app writes only:
`pending_finance → approved → partial → paid` (or `→ rejected`).
`issued` and `overdue` are legacy values nothing sets any more but old rows
still carry. Anything asking "is this invoice still owed?" must use the shared
constant, not an ad-hoc list:
```python
from app.models.finance import OUTSTANDING_INVOICE_STATUSES  # models/finance.py:21
```
It is used at 9 call sites (notifications ×2, finance ×2, kpi, reports,
calendar, customers ×2, payments). Missing it makes approved invoices
invisible in AR — that was a real bug.

**Invoice `amount` is the net DPP** (tax base), not the gross. Tax is computed
on top. A previous bug treated a tax-inclusive figure as DPP and overcharged.

**"Outstanding" always means face value minus verified payments.** `Payment`
rows only exist once verified (portal claims live in `PaymentClaim`), so
`SUM(Payment.amount)` per invoice is the banked figure. Summing `Invoice.total`
over the outstanding statuses counts a half-paid invoice at full value — that
bug lived in `/reports/ar-aging-detail`, `/kpi/finance` and the customer
summary card while `/finance/ar/aging` was already netting correctly.
`test_partial_payment_ar.py` pins all four to the same number.

**Project stages are order-independent going forward.**
`advance_project_status()` in `app/models/operation.py` jumps straight to the
target milestone rather than stepping one stage at a time, and never moves
backwards. Don't reintroduce a strict sequence.

**Stage tasks** (`app/core/stage_tasks.py`) — a deal-stage playbook generates
tasks. Two rules the user asked for explicitly:
- A stage task becomes a calendar event / notification **only when a date is
  explicitly entered**. No date = no nagging.
- `close_superseded_stage_tasks()` runs at the *top* of `ensure_stage_tasks()`,
  before any early return, so moving to `closed_won`/`closed_lost` retires
  earlier tasks even though those stages have no playbook.

**Approvals** are one `ApprovalRequest` table with `decide()` + `apply_to_target()`.
When a target moves on by another route, its pending request must be cleared,
or the inbox fills with undecidable ghosts.

**Push notifications** — `app/services/webpush.py`. VAPID keys live in the DB,
created under `pg_advisory_xact_lock(429173001)` with `ORDER BY created_at` so
concurrent boots can't mint two keypairs. Background sends go through
`fire_and_forget()`, which **holds a strong reference** to the task — without it
Python garbage-collects the coroutine mid-flight and the push silently vanishes.
Chat messages and discussion comments both push instantly.

---

## 8. Known gotchas

- **`pywebpush` will not `pip install` in this container** (network/build). The
  push code is written to degrade gracefully; test its logic, not its delivery.
- **The seed creates only 6 demo users** — director, manager, admin, hr, sales1,
  sales2. There is **no** `purchasing@demo.local` or `finance@demo.local`;
  `run_all.sh --fresh` creates them itself. Any new driver needing those roles
  must do the same.
- **Ephemeral storage.** Files uploaded to the live Space vanish on rebuild.
  Never suggest the user "just re-upload" as a fix without saying why.
- **`from datetime import UTC` inside a function** shadows the module-level
  import and raises `UnboundLocalError: UTC` on every *other* branch of that
  function. This exact bug crashed the Approvals page once. Import at module
  level, never inside a function body.
- **Dateless rows in date arithmetic.** `smart_reminder.py` crashed on
  `r.due_at - datetime.now(UTC)` when `due_at` was None. Filter with
  `Reminder.due_at.is_not(None)` before subtracting anywhere.
- **`'text/html' is not a valid JavaScript MIME type`** — a stale-build symptom
  after a Vercel deploy: the browser holds an old index.html referencing a hash
  that no longer exists. Handled by a reload-on-chunk-error path; if it
  resurfaces, that's where to look.

---

## 9. Where the work has been

Recent commits on `claude/enterprise-crm-erp-ai-IMGRg`, newest first:

```
Count only what is still owed as outstanding AR
docs: handoff brief so a new chat picks up with the same context
Preserve the end-to-end audit drivers as a runnable suite
Projects: split the list into Ongoing and Closed sections
Fix the remaining audited bugs: stale queues, approval gates, scoping
Fix money + data-integrity bugs: invoice DPP, ghost payments, forged QC pass
Security: lock external portal roles out of internal data; scope projects
Approvals: clear stale requests whose target already moved on
Approvals: drop stale documents for delivered/paid/closed projects
Dark mode: close remaining color-coverage gaps
Add e-Faktur CSV export for approved output invoices
Attachments: allow submitting a link, not just a file
Fix 500 on Approvals when handling a follow-up (UnboundLocalError: UTC)
Make project stage order-independent + let admin issue invoices
docs: detailed phase-by-phase test workflow (A–H + checkpoints)
Harden push, daily-log, and stale-build recovery (audit follow-ups)
Fix AI Top Actions crash on dateless stage tasks
```

Features added in that stretch: instant push for chat and discussions,
date-gated stage tasks, mobile chat scroll fix, attendance **daily log** (text +
file + link attachments), link attachments generally, e-Faktur CSV export,
Ongoing/Closed project sections.

## 10. Open items

- **The Hugging Face Space still needs a manual rebuild.** A large batch of
  backend fixes (security lockdown, money integrity, stale queues, approval
  gates, outstanding-AR netting) is pushed but **not live** until the user
  rebuilds. Remind them.
- **Rebuilding the local scratch environment.** A fresh container has neither
  the Postgres data directory nor the Python packages. Before any driver runs:
  `initdb -D /tmp/pgdata_test -U postgres -A trust` (as `nobody`) then the
  `pg_ctl` line in §4, and
  `grep -vi "pywebpush\|http-ece" backend/requirements.txt > /tmp/req.txt &&
  pip install --ignore-installed -r /tmp/req.txt` — `pywebpush` fails to build
  (§8) and `--ignore-installed` is needed because pip cannot uninstall the
  distro-provided PyJWT.
- `docs/TEST_WORKFLOW.md` is the phase-by-phase manual test script (Phases A–H
  with `✓ Expect` lines) written for the user to walk through in the live app.
  Keep it current when workflows change.

---

## 11. Other docs

| File | What it is |
|---|---|
| `docs/SYSTEM_GUIDE.md` | the complete product reference — every module and workflow, ~440 lines |
| `docs/TEST_WORKFLOW.md` | manual end-to-end test script, Phases A–H |
| `docs/DEPLOY_RENDER.md` | migrating the backend off the HF Space onto Render (persistent disk, auto-deploy) |
| `docs/ROLE_GUIDES.md` | per-role usage guides (mirrored in-app) |
| `docs/01-architecture.md` … `07-deployment.md` | original design docs |
