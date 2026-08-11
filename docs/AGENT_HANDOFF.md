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

**Translation.** The UI is bilingual EN/ID through two mechanisms in
`src/store/lang.ts`:

* `t(en, id)` — both languages at the call site. Use it for anything with an
  interpolated value, where a dictionary key can't be a fixed string.
* `T(en)` — looks the English up in `src/i18n/id.ts`. A miss returns the
  English unchanged, so a new string ships safely before anyone translates it.
  Use this for ordinary static text; it is what the ~1,000 wrapped strings use.

`T` is deliberately **not** reactive — `App` carries `key={lang}` and remounts
the tree on a language change, which is what re-evaluates every `T`. That
avoids threading a hook through forty screens and through plain helper
functions that aren't components.

`id.ts` has two blocks. `ID_STATIC` is checkable: every key must appear as a
literal `T("…")` somewhere. `ID_RUNTIME` holds keys that arrive as *data* —
API status enums (`pending_approval` renders as "pending approval"), industry
values — which never appear as a literal. **Run `npm run i18n:check` after
rewording any UI text**: it reports dictionary entries whose English no longer
exists (a silent fall back to English) and strings with no translation yet.

Dates and numbers go through `locale()` from the same module, not the browser's
locale — otherwise an Indonesian UI still prints "Wednesday, August 5".

**File storage goes through `app/services/storage.py`** — never write to disk
directly. Keys are built by `build_key()` as
`attachments/<owner_type>/<year>/<month>/<owner_id>/<uuid8>_<label>_<name>`, so
pass `owner_type`/`owner_id` to `storage.save()` when the caller knows them —
without it the file still saves, just under `misc/`. `STORAGE_BACKEND` picks local disk or an S3-compatible bucket
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

`backend/tests/e2e/` holds 34 drivers that exercise the **real ASGI app
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
| `test_write_read_symmetry.py` | the property behind that bug: across every (role × owner type) pair, nobody may write where they cannot read — attachments, discussions and chat |
| `test_sales_sees_own_files.py` | a rep can read back the files they filed on their own customer / quotation / customer PO — and still not another rep's |
| `test_storage_layout.py` | bucket key layout: grouped by owner type / month / document, user-supplied names can't traverse, and files written under the **old** flat layout still download |
| `test_storage_s3.py` | the S3/R2 backend against a real moto server, incl. the disk→bucket migration |
| `test_mentions.py` | discussion access control + @mentions granting the thread and nothing else |
| `test_reply_forward.py` | quoted replies + forwarding: same-thread-only quotes, forward permissions both ways, the cross-department DM gate, chained attribution |
| `test_customer_import.py` | importing the customer list out of Accurate a batch at a time: preview writes nothing, `Kategori` resolves to a sales account, the same company written two ways lands once, and re-running continues instead of duplicating |
| `test_data_import.py` | the other three Accurate imports: the chart of accounts never renames an account already on the books, the parts catalogue admits it has no prices, and the quotation export's two self-inflicted data defects are told apart — one repaired, one left alone — with each sheet's stated subtotal as the proof |
| `test_import_undo.py` | undoing an import: it removes exactly what that run created, refuses records somebody has since filed work against (naming both), takes them only on a second explicit yes, and never touches a hand-typed record or a different run |
| `test_export_address.py` | which of a customer's three addresses gets printed is asked at download time, honoured (checked by reading the address back out of the generated PDF/xlsx), falls back to the office when the chosen one is blank, and refuses another customer's contact |
| `test_quotation_meta_edit.py` | a note is not a price change: the edit form posts the whole document back, so every guard that asked "are items in this payload?" had to be taught to ask "did the items change?" — while a real price edit is still refused, or still queued for the director |
| `test_record_delete.py` | deleting named documents (including the flat kinds — parts and chart-of-accounts rows, which is how a test import gets undone): everything downstream of the pick goes, nothing outside it is touched, upstream is never taken, money needs its own confirmation — and the numbering regression that made deleting anything break the creation of the next one |
| `test_purge.py` | the test-data purge: right lineage deleted, no orphans left anywhere, director-only, confirmation phrase, empty keep-list refused |
| `test_pr_director_edit.py` | the director editing a price request past draft — and costing/approved prices surviving the edit |
| `test_lost_and_badges.py` | a lost deal must carry a reason; a dismissed alert stays dismissed when its count moves |
| `test_customer_po_sheet.py` | the order-confirmation PDF: ship-to and PIC chosen at download, address fallback, cross-customer contact refused |
| `test_pr_revisions.py` | negotiation revisions: capped at 3 applied, one pending at a time, a rejection changes nothing and costs nothing |
| `test_cross_dept_chat.py` | cross-department chat by request: approving opens it, rejecting opens nothing, no duplicate asks |
| `test_approval_preview.py` | the document preview on an approval request: lines and per-line money, the keterangan, files attached to the *document*, revision before/after, director-only |
| `test_attendance_alert_window.py` | attendance alerts stay silent before 08:30 **WIB** — includes a threshold that only passes if the comparison isn't done in server/UTC time |
| `test_mark_read.py` | marking a section's alerts read from its sidebar badge: batched, per-user, tolerant of ids that resolved on their own |
| `test_efaktur.py` | e-Faktur CSV export |
| `test_supplier_price_request.py` | asking vendors what they charge: one request per supplier, quotes recorded per line (per-unit or per-line, normalised), the chosen one applied as the cost with its number stamped on the line, a later cheaper quote superseding it, losing quotes kept, and sales locked out of every endpoint |
| `test_supplier_record.py` | the supplier as a real company record: address + pickup address, the company's line kept separate from each PIC's own, PICs added/edited/removed after the fact, the header editable in place (it used to be write-once), vendor paperwork readable by purchasing but not sales, and rows created before the columns existed still showing their legacy `contact` blob |
| `test_quotation_layout.py` | where the printed quotation puts things: the totals block sits on the item grid's own rule (measured out of the PDF, not eyeballed), the KETERANGAN panel gets the width that frees up, and a note the sender numbered themselves prints numbered once |

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

9. **The look is the VOLER industrial design system** (source: the user's Drive
   folder "Kettenwerk Industrial Design System"). It lives entirely in
   `tailwind.config.js` + `src/index.css`, so the whole app re-skins from two
   files — don't hardcode colors in pages. Voler Blue `#2A5992` (`brand-*`) is
   the structural interactive colour; **Industrial Orange `#F36C21`
   (`accent-*`) is deliberately rare** — the focus ring, the active-nav rule, a
   screen's single main action (`.btn-accent`). The brand calls for one accent
   moment per view, so adding orange anywhere means asking what it replaces.
   Corners are machined (0–3px), cards are hairline borders not shadows,
   headings are Montserrat uppercase, specs use Roboto Mono (`.spec`), section
   eyebrows use `.overline`. A `/* Legacy palette remap */` block in
   `index.css` maps the old indigo/violet utilities onto blue so pre-existing
   screens follow along; new work should use `brand-*` / `accent-*` directly.

10. **Back navigation lives in the chrome, not on the page.** `Shell.tsx` has a
    `BackButton` in the topbar (mobile *and* desktop) driven by
    `store/navHistory.ts`, which mirrors router navigations into an in-app
    stack. That stack exists so Back can never eject someone to the login page
    or the previous website; with nothing behind them (deep link, push-notif
    tap) the button goes *up* to the parent list via `parentNavPath()` instead.
    So **do not add a generic `← Back` to a new page** — it duplicates the
    chrome. A contextual up-link ("Back to Purchasing") is still fine when a
    page has one specific parent worth naming. A route with no nav entry of its
    own needs an entry in `ORPHAN_PARENT`.

11. **Both conversation surfaces share their rules.** The chat page and the
    discussion thread on a document are separate tables (`chat_messages`,
    `entity_comments`) but one feature set: quoted replies and forwarding, with
    the same UI (`components/MessageQuote.tsx`, `components/ForwardDialog.tsx`)
    and the same policy module (`services/chat_policy.py` — department rules,
    `resolve_dm`, `deliver_forward`). Two rules there are load-bearing and easy
    to break by accident:
    * **A quote may only cite a message from the same channel / the same
      thread.** Otherwise replying becomes a way to copy a line out of a
      conversation you were never in, into one you are.
    * **A forward lands in chat only, and names the original author and nothing
      else.** Not the document, not the channel — naming the origin would carry
      a quotation number or a customer past the scoping rules. Forwards are
      written to the audit log for exactly this reason. Read access to the
      source licenses the forward; membership of the destination is checked
      separately, so the director can forward *out of* a channel they only
      monitor but not *into* one.

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

**The supplier record has three different audiences, on purpose.** The row
itself (name, category, rating, address, PICs) is readable by any internal
role — it is a directory. Editing it is `_supplier_editors` = admin,
director, manager, **purchasing**: onboarding a vendor stays a management
decision (`_admin_or_director` on POST), but maintaining the record belongs to
the department that talks to them daily. The vendor's *paperwork* —
`owner_type` `supplier` and `supplier_contact`, i.e. company deed, NPWP, bank
details, a PIC's ID card — is narrower again and excludes sales. Supplier
pricing (`supplier_po` files) stays narrowest: director + purchasing only.

**A document is a rep's if it names them OR if the customer is theirs.** That
union lives in `sales_scope()` / `sales_may_see()` in `permissions.py` and is
the rule for price requests, quotations, their discussion threads, their
attachments and their bell rows. It used to be only the first half for those,
while customer POs, projects and invoices already used the second — so a price
request the *director* raised on a rep's account was invisible to that rep,
who therefore could not turn it into a quotation. Any new sales-facing
document needs both halves; scoping on the document's own `sales_pic_id` alone
is the bug.

A useful consequence: a rep who inherits an account can read its closed
history (a won quotation stays with whoever closed it, but the account's new
owner can still open it), which is what makes the handover in
`POST /customers/reassign` honest.

**Changing who is in charge of a customer is the director's alone, and it is
not a field edit.** `PATCH /customers/{id}` refuses `sales_pic_id` outright
(403 for anyone below director, 400 for the director, pointing at the right
door); the door is `POST /customers/reassign` in `customers.py`. It exists as
its own action because ownership is what the whole CRM scopes on, so moving it
has to move three other things at once:
- the customer's **live** price requests and quotations (`move_open_work`,
  default on) — without them the new rep inherits an account whose open quote
  they cannot open, and the departed rep keeps it;
- **decided** work — won/lost quotations, rejected PRs — stays put. It is the
  record of who closed the deal;
- an `Activity(type="assignment")` on the customer's timeline plus an audit
  row, and the `handover` section in `notifications.py` reads that activity to
  tell both reps.

Only `sales`/`manager`/`director` may be put in charge; the endpoint refuses
disabled accounts and everyone else by role. `GET /customers/assignable-reps`
(manager+) returns the roster with each rep's current load, and
`GET /customers?unassigned=true` finds the accounts nobody owns — which is the
state a fresh import leaves behind. `test_customer_handover.py` covers all of
it.

**The importer keeps the rep name even when it matches nobody.** The Accurate
export's Kategori column says whose customer it is ("Customer Diani"). If that
name has no active account here, the customer imports unassigned — and the
name is written to `Customer.meta["sales_rep_hint"]` (exposed as the
`sales_rep_hint` property and on `CustomerOut`) rather than dropped. It is the
only record of who the account belongs to, and without it the only way back is
the spreadsheet. `assignable-reps` returns those names as `from_import` groups
with an unassigned count, `GET /customers?rep_hint=diani` selects them, and the
assign dialog suggests the account whose name shares a part with the hint. The
hint is stored lower-cased because that's the form it matches user names on —
`repHintLabel()` in `AssignSalesDialog.tsx` capitalises it for display.

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

**Discussion threads are gated on the parent document** (`comments.py`).
`_THREAD_ROLES` says which roles belong in each owner type — purchasing is
absent from every customer-facing thread, which is the customer-blindness rule
— and sales is additionally scoped to its own customers. **Being @-mentioned is
the one exception**: it grants that thread and nothing else, which is how
someone gets pulled into a conversation on a document they cannot open. Keep
`_has_document_access` (role/scope only) separate from `_can_view_thread`
(which also honours the mention), or the composer's warning and the "open the
document" link both start lying to the people they exist for.

**A price request has a buy side now, and it is a separate document.**
`PriceRequest` (PR-…) is the sell side: what a customer wants, what it costs
us, what we charge. `SupplierPriceRequest` (SPR-…, `supplier_price_requests`,
`app/api/v1/endpoints/supplier_price_requests.py`, mounted at
`/purchasing/price-requests`) is the buy side: what a vendor charges *us*.
**One row per supplier asked**, so three vendors on one job are three rows to
compare; `price_request_id` is nullable, because purchasing also asks with no
deal behind it. `POST /{id}/apply` writes the quoted prices onto the linked
price request as `cost_price`, stamps `cost_source` (the SPR number) on each
line it touched, and moves the request to the director — which is the point of
the whole record: the cost the director sees now has a document behind it
instead of a memory of a WhatsApp call. Applying a second quote supersedes the
first and moves `applied_at` with it; the losing quotes are never deleted.
Numbering is its own series (`next_supplier_price_request_number`) so the two
documents never look like one sequence.

Two constraints on it that are not negotiable. **The router excludes sales
entirely** — its whole content is procurement cost, and `price_requests`
already hides that from them line by line, so there is no version of this
document a rep may open. **It never names the customer**: it is drafted to be
sent to an outside company, so `apply`/create copy the goods across and
nothing else — no customer, no selling price. Covered by
`test_supplier_price_request.py`, and by the orphan sweep in `test_purge.py`
(the FK is SET NULL, so a purged price request would otherwise strand its
supplier quotes).

**A price request's two figures can be corrected after it settles.**
`POST /price-requests/{id}/reprice` is director-only and works at any status:
cost and sell move independently (send one, the other stays), a reason is
required, and each change is stamped into `PriceRequest.price_history` as well
as the audit log. The rule that matters is what it does downstream: a
quotation still in **draft** is rewritten to match (its prices are locked to
the request by design, so leaving it stale would make the lock a lie), and one
already **sent/approved/won** is left exactly as it went out — that is a
statement made to the customer, corrected by a revision, not by editing the
number underneath it. The response says which happened. `_serialize` filters
`price_history` the same way it filters line prices: purchasing sees costs
move and never a selling price, sales the reverse. Covered by
`test_pr_reprice.py`.

**Rejection is never a dead end, and always says why.** All three sales
documents now behave the same way: the reason lives on the row
(`decision_notes` on quotations, customer POs and price requests — the
quotation gained the column, the other two already had it), it is shown on
the document's own page, and a rejected document can be fixed and sent
straight back up under the same number. Quotations resubmit through
`POST /{id}/submit` (which now accepts `rejected`, not only `draft`);
customer POs through `POST /{id}/resubmit`; price requests always could.
Revising a quotation into a new `-R2` is still there and still the right
tool for a quote the *customer* has already seen — resubmission is for one
the director simply handed back. The reason is deliberately kept through a
resubmission: the director is about to look again and wants to see what they
asked for. `test_resubmit.py` covers all three.

**Ownership of one quotation can be moved on its own.**
`POST /quotations/{id}/reassign` is director-only and changes who is
*answerable* for a single deal — who may submit it, withdraw it, edit it,
mark it won — without touching the customer. Handing over the customer moves
everything; this is the finer instrument (one deal covered while its rep is
away). A closed quotation (won/lost/cancelled/superseded) refuses to move:
its owner is the record of who closed it. The move is written to the
customer's timeline as an `assignment` activity naming the quotation.

**The frontend's "is this mine" must match the server's.** `QuotationDetail`
computes `isOwner` as *named on it OR in charge of the customer* — the same
union `sales_scope`/`_may_see` use. Gating the buttons on the raw
`sales_pic_id` alone is the bug that made a director-written quotation
readable but completely inert for the rep whose customer it was.

**A user has two addresses and a signature.** `User.email` is the login and
nothing else — unique, and the only thing `/auth/login` matches on.
`User.contact_email` is where that person corresponds from, is **not** unique
(a shared mailbox is fine), and is never accepted as a credential. Documents
prefer it: the quotation PDF and Excel print `contact_email or email`, so a
customer replying to a quote no longer replies to `sales1@demo.local`.

`User.signature_path` holds a scanned signature, uploaded via
`POST /users/{id}/signature` (own, or anybody's if you are the director) and
drawn into the signature block of the quotation PDF and the customer-PO order
confirmation. `app/services/signature.py` owns both halves: `validate()`
refuses anything unusable at upload time, and `fitted_flowable(max_w_mm,
max_h_mm)` scales the scan to the **calling document's** block, preserving
aspect ratio and never enlarging past the source. The two blocks are
different shapes, which is the whole reason the size is not baked into the
image. No signature = the blank space to sign by hand, exactly as before.
A PNG with transparency is what keeps the scan from painting a white
rectangle over the rule. `test_signature_email.py` covers it.

*Frontend gotcha this surfaced:* the API authenticates with a bearer token,
so a protected image can never be shown with a plain `<img src="/api/…">` —
that request carries no token, 401s, and the preview silently shows nothing.
Fetch it through `api.get(..., { responseType: "blob" })` and
`URL.createObjectURL`, as `AdminUsers.tsx` and the attachment components do.

**Approvals** are one `ApprovalRequest` table with `decide()` + `apply_to_target()`.
When a target moves on by another route, its pending request must be cleared,
or the inbox fills with undecidable ghosts.

**Every bell item's `link` decides which sidebar section badges.** `Shell.tsx`
matches each alert's link against the nav paths (longest prefix wins), so the
link is not just where the row navigates — it is what lights up. An alert
pointing at `/` badges nothing and dumps the reader on the dashboard, which is
what "your quotation request was approved" used to do for everyone below
manager. `_TARGET_LINK` in `notifications.py` maps an approval's `target_type`
to its document; extend it when you add a new approval type.

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
- **Write access and read access must be the same question.** `/attachments`
  gated reading by owner type and role but gated writing for external portal
  accounts only. One hole, two bugs: sales could upload a customer file and get
  a 403 listing it (so the upload looked lost), and sales/purchasing/admin
  could write into an **employee** record they cannot read. When you add an
  endpoint that writes into a record, ask the *read* rule first —
  `test_write_read_symmetry.py` walks every (role × owner type) pair and fails
  if the two ever diverge again.
- **`from datetime import UTC` inside a function** shadows the module-level
  import and raises `UnboundLocalError: UTC` on every *other* branch of that
  function. This exact bug crashed the Approvals page once. Import at module
  level, never inside a function body.
- **Dateless rows in date arithmetic.** `smart_reminder.py` crashed on
  `r.due_at - datetime.now(UTC)` when `due_at` was None. Filter with
  `Reminder.due_at.is_not(None)` before subtracting anywhere.
- **Drivers share one database, so re-runs are not free.** `run_all.sh` without
  `--fresh` re-runs everything on the accumulated data. Most drivers tag their
  fixtures with a random suffix and cope; `e2e_dp_flow.py` uses hardcoded
  document numbers (`DP-001`, `PO-CUST-A1`, `INV-EF-001`) and **will** 409 on a
  second run — that is a fixture artefact, not a product bug. Use `--fresh`
  before believing a failure. `--fresh` now terminates open connections and
  aborts loudly if the DROP fails; it used to swallow the error and silently
  run on days-old data, which is how a stale notification dismissal and 52
  leftover customers once read as two product bugs.
- **A driver that dismisses a notification must undo it.** Dismissal ids are
  deliberately day-scoped (that *is* the fix in `test_lost_and_badges.py`), and
  there is no un-dismiss endpoint — so a second run the same day finds the
  alert already gone. That driver deletes its own `notification_dismissed` rows
  up front; copy that if you write another.
- **The customer importer matches sales reps by first name only.** The Accurate
  export records ownership in `Kategori` as free text — "Customer Candra" — so
  that is all there is to match on. A first name shared by two active accounts
  is deliberately left **unmatched** rather than guessed at, and the preview
  names it under `unmatched_reps`. If a driver creates a `Candra` and something
  else in the same database already has one, the match stops working; tag
  fixture names per run (`test_customer_import.py` does).
- **Document numbers come from the highest suffix issued, never a row count.**
  `PR-2026-0007` used to be `count(*) + 1`, which is correct right up until
  something is deleted — then the counter walks backwards and hands the next
  document a number that is still in use, the insert dies on the unique index,
  and the user is told only that it could not be created. Deleting one price
  request broke making the next one. Fixed in `services/numbering.py`
  (`_next_suffix`), and `operation._next_doc_number` (invoices, DOs) and the
  supplier-PO generator now share it. Any new numbering must too.
- **Sample files for testing the importers** live in the repo at
  `docs/samples/` — real slices of the user's own Accurate exports, cut so the
  four run in order (the 8 sample quotations name customers that the 11 sample
  customers contain, and the sample chart of accounts contains all 15 accounts
  the seed does *not* have, so it demonstrates an import rather than reporting
  "already here" 22 times).
- **A customer has three addresses and they are different places.** Office,
  delivery and tax — which one a document prints is a decision about *that
  document*, made at download time, not a property of the customer.
  `services/print_address.py` is the only place that knows the list; the
  quotation and customer-PO exports both read it, which is what stops them
  drifting apart again (they already had, with two different ideas of
  "delivery" and only one of them offering the tax address).
- **Reading a generated PDF back needs a real parser.** `pypdf` is in
  requirements as a test-only dependency. A substring search over the raw
  bytes finds nothing even when the words are plainly on the page — the
  streams are compressed and the text is split across drawing operators — and
  a driver built that way fails on behaviour that is entirely correct. For
  *where* something landed rather than whether it is there, PyMuPDF (`fitz`)
  is also installed: `page.search_for(text)` gives the box in points and
  `page.get_drawings()` gives the filled panels, which is how a layout ask
  ("put the price behind this line") becomes an assertion instead of a
  screenshot. `pdftoppm` is **not** installed; render with `fitz` too.
- **Print blocks are sized off each other, not off the page.** The quotation's
  totals block used to be page fractions (48/8/24/20), which left it 9mm
  inside the SATUAN column: prices under the wrong heading, and the notes
  panel squeezed for nothing. It is now `content_w - 69mm - 4mm | 4mm | 30mm |
  39mm`, where 69mm is exactly the item grid's last three columns — change an
  item column width and the totals follow it. Senders also type their own
  "1." on each note, so the builder strips a leading number before adding
  one; without that every line printed as "1. 1. …".
- **The edit forms post the whole document back, every time.** So "field is
  present in the payload" never means "field was changed" — a sales rep typing
  a note sends every line item along with it. `quotations.PATCH` prunes
  unchanged fields (`_changed`) before any rule looks at them; without that,
  a note was refused with "line prices are fixed by the approved price
  request" on a draft, and silently became a director approval request on an
  approved one. Any new guard that branches on a field's presence needs the
  same treatment.
- **A field that changes on its own belongs on the page, not in the form.**
  Quotation notes are now typed in a card on the quotation page (`NotesCard`,
  mirroring the customer PO's `KeteranganCard`) that PATCHes `{notes}` alone;
  the edit modal no longer has the box and **omits the key entirely** when
  editing, rather than posting `null`, so it cannot clobber what was typed on
  the page while the modal was open. Two boxes for one field is the bug this
  avoids, and the last save would have won it. The card's preview numbers the
  lines exactly as `quotation_pdf.py` does, so the screen shows what prints.
- **`GET /customers` is the only paged list, and its sort must stay a total
  order.** It was `ORDER BY created_at DESC` alone; an import writes dozens of
  customers in one transaction, so they share a timestamp to the microsecond
  and Postgres ordered those ties differently per query. OFFSET paging then
  served some rows twice and never showed others — 87 customers paged out as
  71 distinct ones. It now sorts `created_at DESC, company_name ASC, id DESC`:
  name before id deliberately, because a whole imported batch lands on one
  timestamp and whoever is checking it against the spreadsheet wants those
  rows alphabetical. Any new paged endpoint needs the same treatment.
- **"Is my import complete?" is answered by re-uploading the file**, not by
  counting. The preview checks every row against what is in the CRM, and the
  verdict banner in `DataImport.tsx` states it outright: "Nothing is missing"
  or "N of M rows are not in yet", naming them. `test_customer_paging.py`
  pins both that and the paging.
- **Not every link between documents is a foreign key.** `PriceRequest
  .quotation_id`, `Quotation.project_id`, `Quotation.price_request_id`,
  `Project.price_request_id` and `SupplierPO.price_request_id` are bare uuid
  columns, so the database will not clear them and will not complain. A price
  request left pointing at a deleted quotation refuses to make a new one
  ("this price request already has a quotation"). `_execute_plan` clears them
  explicitly — add to that list when you add a soft reference.
- **`'text/html' is not a valid JavaScript MIME type`** — a stale-build symptom
  after a Vercel deploy: the browser holds an old index.html referencing a hash
  that no longer exists. Handled by a reload-on-chunk-error path; if it
  resurfaces, that's where to look.

---

## 9. Where the work has been

Recent commits on `claude/enterprise-crm-erp-ai-IMGRg`, newest first:

```
Let the director change which sales rep is in charge of a customer
Make an import undoable in one action, and refuse the parts that aren't
Ask which address to print on before exporting
Let sales add a note to a quotation without being told the price is fixed
Show the document behind an approval request
Open cross-department chats by request instead of refusing them
Let sales negotiate a price request, capped at three revisions
Add a keterangan and an order confirmation sheet to the customer PO
Require a reason to mark a deal lost, and make dismissed alerts stay dismissed
Let the director edit a price request after it leaves draft
Add a director-only screen for clearing test data
Add WhatsApp-style replies and forwarding to every conversation
Add a Back button to the app chrome, on mobile and desktop
Quotation PDF: use the real TE mark and draw the capability icons
Quotation PDF: rebuild on the company's PENAWARAN HARGA letterhead
Re-skin the app to the VOLER industrial design system
Discussions: @mentions, and gate threads on the document behind them
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
Ongoing/Closed project sections, the VOLER re-skin, @mentions, a Back button in
the app chrome, WhatsApp-style replies and forwarding, the director-only test
data purge, director-editable price requests with capped negotiation revisions,
the customer-PO keterangan and order confirmation sheet, cross-department chat
by request, document previews in the approval inbox, a director-only
customer importer for the old Accurate data, an address picker on every
export, and director-controlled customer ownership.

## 10. Open items

- **An import is undoable as one action.** Every commit writes an `ImportRun`
  plus an `ImportedRecord` per row created; *Import data* lists recent runs
  with an Undo. Undo removes only the records nothing has been built on —
  anything with a price request, PO or invoice filed against it since is kept
  and named, and taking those needs a separate tick. That split is what makes
  it safe to try an import on production, so keep it if you touch the code.
- **All four Accurate exports import; none has been run against production.**
  The user's Google Drive "Data transmisi" folder
  (`1CqQpxzFLPRSJkEJMEJIPJgYGgZcM-C7W`) holds `daftar-pelanggan.xlsx` (97 rows
  → 87 customers), `daftar-barang.xlsx` (731 parts), `akun-perkiraan.xlsx`
  (112 accounts, 97 of which the seed already has) and
  `rincian_penawaran_penjualan_*.xlsx` (137 quotations, 487 lines,
  Rp 43.2 bn). All four are mapped, tested and reachable from *Import data*.
  **Order matters**: create the sales accounts first (or every customer lands
  unassigned), then customers, then quotations (a quotation needs a customer
  to belong to — 134 of 137 match once the customers are in).
- **Nothing has actually been purged yet.** The director-only *Clear test data*
  screen is built, tested and deployed, but it is the user who has to run it
  against production. Until they do, the test customers/projects/POs they asked
  about are still there. Preview first — it lists exactly what will go.
- **The 11 real staff accounts have not been created.** The emails and roles
  were supplied (7 sales, director, purchasing, finance, admin, all
  `@voler.co.id`); creating them is a production action the user performs.
  A self-service password-change screen was offered and not built — ask before
  assuming it is wanted.
- **This sandbox cannot reach production.** The proxy returns 000/403 for
  `onrender.com`, `vercel.app` and the Neon database. Anything that has to
  touch live data is the user's to run; never claim to have verified it.
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
