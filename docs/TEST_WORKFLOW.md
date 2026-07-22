# Transmisi Eng — Full Test Workflow

A precise, phase-by-phase script to test the whole system end to end, with exact **roles**, **screens**, **actions**, **status transitions**, and — woven in — every recent change. Format for each step: what to do, then **✓ Expect:** what you should see.

> Legend: **status → x** means the record's status becomes `x`. Anything marked **(NEW)** or **(CHANGED)** is recent and needs the Space rebuild (Phase 0).

---

## Phase 0 — Pre-flight

* **Rebuild the Hugging Face Space.** Every backend change below (daily log, dateless stage tasks, instant push, the AI-dashboard crash fix, push hardening) is only live after a rebuild. Frontend (Vercel) is already live.
* While the Space rebuilds, **watch the build log** for `pywebpush` installing cleanly — if push fails later, check this first.
* **Create one login per role** (director → Admin → Users): a **sales**, a **second sales**, a **purchasing**, an **admin**, a **finance**. Keep your **director** login.
* Have **two devices/browsers** ready (send push from one, receive on the other). Keep **director** open on one screen so you can watch approvals land live.
  * ✓ Expect: after rebuild, hard-refresh (⌘/Ctrl-Shift-R) loads the site with no errors.

---

## Phase 1 — Device notifications (set up first; the push checkpoints below rely on it)

* Any role → click the **bell** (top bar) → toggle **Device notifications** on → approve the browser permission prompt.
* Click **Send test notification**.
  * ✓ Expect: a real OS/browser notification within a few seconds.
  * **iPhone:** works only from the **Add-to-Home-Screen** app, not a Safari tab (Apple restriction).
* Dismiss any bell item with its **✕**.
  * ✓ Expect: it stays gone until its underlying state changes (e.g. a new chat message revives the chat row).

---

## Phase A — Price request (buying + selling price)

* **Sales → Price requests → New price request.**
* Pick a customer, add line items (description, qty, UoM, spec). **No prices here.**
* **Create**, then **Submit to purchasing**.
  * ✓ Expect: **status → pending_purchasing**. Purchasing gets a **bell item + device push** (the handoff).
* **Purchasing → Price requests → open it.**
* Enter the **cost (buying) price** per line. Use the **/unit vs total** selector — the live hint shows the implied unit/total. **Submit costs.**
  * ✓ Expect: **status → pending_director**. Director is notified.
  * ✓ Expect: purchasing **never sees the customer name or the selling price**.
* **Director → Price requests → open it.**
* Set the **sell price** per line (also /unit or total), optionally correct the cost, then **Set prices & approve**.
  * ✓ Expect: **status → approved**. Sales is notified of the decision.
  * ✓ Expect: sales **never saw the cost**.

### ✓ Checkpoint — Discussion push (CHANGED)
* On this price request, as **purchasing**, post a **comment** in the discussion thread ("Need the spec sheet").
  * ✓ Expect: **sales** (the requester) gets an **instant device push** — even as the *first* comment. Title shows the PR number; tapping opens the PR. The sender is never pushed their own comment.

### ✓ Checkpoint — Attachments & PR number
* On the PR: **upload a file** (spec / customer RFQ), and try **editing the PR number** (e.g. to mirror the customer's RFQ number).
  * ✓ Expect: the file rides on the PR; the renamed number is unique and doesn't break any links.

---

## Phase B — Quotation

* **Sales (or director) → open the approved price request → Create quotation.**
  * ✓ Expect: a quotation is generated with the **selling prices auto-filled** (sales never types a price). Opens the quotation detail.
* **Sales → Submit** the quotation.
  * ✓ Expect: **status → pending_approval** (every quotation needs director sign-off).
* **Director → Approvals** (or on the quote) → **Approve**.
  * ✓ Expect: **status → approved**; the customer **stage auto-advances to `quotation`**.
* **Export PDF** and **Export Excel** from the quotation.
  * ✓ Expect: both download with the company header; the customer **activity timeline** logs an "export" entry.
* **Mark won** (sales) → files a request to the director → **Director approves**.
  * ✓ Expect: **status → won**, revenue posts to the ledger, customer **stage → `negotiation`**.
  * ✓ Expect: **Mark lost** is now blocked (won/lost are mutually exclusive).
* *(Optional)* **Post revision** on the won/approved quote → edits a clone numbered `-R2` → resubmit → director approves.
  * ✓ Expect: the revision goes live and the original flips to **superseded**.

---

## Phase C — Customer PO → Project

* **Sales → Customer PO → create one** referencing that quotation/customer (attach the PO file, pick ordered items, set PO number/date). Leave the DP box unticked for a normal order.
  * ✓ Expect: created by a non-director → **status → pending_approval**.
* **Director → Approvals → approve the customer PO.**
  * ✓ Expect: approving **spawns a Project (status → new)**; the project carries the **price-request link**; customer **stage → `po`**.
  * *(A director creating the PO skips approval — the project is created immediately.)*
* Open **Projects**.
  * ✓ Expect: the new project is listed, header links the chain **customer → quotation → customer PO → PR number**.

---

## Phase D — Drawing (NEW: internal upload + director sign-off)

* **Purchasing / Sales / Ops → Projects → open the project → Drawings card.**
* Pick the drawing file, optional note, **Upload drawing**.
  * ✓ Expect: it lands as **submitted**; **project → `drawing`**.
  * *(Sales may only file drawings on their own customers' projects.)*
* **Director → same Drawings card → Approve** (or **Revise**).
  * ✓ Expect: **Approve** advances **project → `drawing_approved`**.
  * *(The customer-portal approval still works as a fallback if you ever use it.)*

---

## Phase E — Supplier PO (NEW: auto-fills buying price)

* **Purchasing → Purchasing PO → New PO.**
* Pick **supplier + project**.
  * ✓ Expect: if the project is linked to the price request, a green **"Linked to price request"** banner shows the **buying prices** and seeds the total. If not auto-linked, use the **"pick a price request"** dropdown.
* **Issue PO.**
  * ✓ Expect: non-director → **status → pending_approval**.
* **Director → Approvals → approve the supplier PO** (labeled with the PO number).
  * ✓ Expect: **status → open**, and the PO **persists and shows up** (this is the bug you hit — now fixed).
  * *Note:* any later PO status change by purchasing also files an approval and shows **"submitted for director approval"**; the director clears it in **Approvals**.

---

## Phase F — Logistics & import docs

* **Purchasing → project → Logistics & import documents** (only enabled **after the drawing is approved**).
* Set **delivery mode + estimated delivery date**; tick off required **import docs**.
* **Confirm delivery.**
  * ✓ Expect: **project → `production`** and the **receiving work order** is spawned on the operations board.
* **Shipping timeline** (three legs: origin → our warehouse → customer): set the est./actual dates.
  * ✓ Expect: purchasing owns *shipped-from-origin*; admin owns the arrival dates; any non-director date change is **queued for director approval** (customer-visible promises).

---

## Phase G — Operations & QC

1. **Operations/Admin → project → Work orders** (Receiving → Warehousing → QC → …) → mark them complete.
   * ✓ Expect: each stage gates on the project having reached the right phase (can't open a QC WO before `production`, etc.).
2. **Operations → record QC pass** (with findings).
   * ✓ Expect: hands the project to admin (**status → `qc`**); passing QC **unlocks the final invoice + delivery order**.

---

## Phase H — Invoice, DO & faktur pajak

1. **Admin → project → Invoice & faktur pajak → issue the invoice + delivery order.**
   * ✓ Expect: the invoice is created; the **faktur pajak number is left blank at issue** (finance fills it on approval).
2. **Finance → Invoices (pending) → approve the invoice**, entering the **faktur pajak number** (+ file).
   * ✓ Expect: **faktur pajak status → issued**, **invoice status → approved**. This is **document approval only — it does NOT post to the ledger** (invoicing stays decoupled from the journal).
   * ✓ Expect: approval is **blocked without a faktur pajak number**.
3. *(Payment)* **Finance → record a payment** (manual entry on the invoice card, or verify a portal claim).
   * ✓ Expect: when fully paid, the **project auto-advances `paid → closed`** and the customer deal **stage → `closed_won`**.
4. **Admin → mark customer received.**
   * ✓ Expect: **project → `delivered`**. Workflow complete — traceable backwards project → PO → quotation → PR.

---

## Cross-cutting checkpoints (test any time)

### Stage tasks — dateless by default (CHANGED)
* On any customer, open the **stage checklist**.
  * ✓ Expect: tasks read **"No deadline — set a date to get reminders"**, and do **NOT** appear on the calendar or bell.
* Click **+ Set deadline / note**, pick a date, save.
  * ✓ Expect: the task now appears on the **Calendar** for that date and starts notifying (due-soon at 2 days, overdue after). Dateless tasks stay silent.

### Chat — instant push + mobile layout (CHANGED)
* **Same-department DM:** send a message; on the recipient's other device (tab can be closed) a **push** arrives in ~1-2s — sender's name as title, message as body; tap opens the chat. Rapid messages **collapse into one** re-alerting notification.
* **Cross-department DM:** as plain **sales**, try to DM **purchasing** — blocked (only director/manager/HR can start cross-department chats).
* **Mobile (phone):** open **Chat**. You see the conversation **list**; tapping opens a **full-screen thread** with a **‹ back** arrow and the composer pinned at the bottom.
  * ✓ Expect: the newest message and the message box are both visible (this was the bug you reported).

### Daily log — under Attendance (NEW)
* **Attendance → Daily log** (below clock-in): type **"What did you work on?"**, **Add link** (try a bare domain like `docs.google.com/x` → auto-saves as `https://…`), **Save log**.
  * ✓ Expect: the **Files** area unlocks after the first save; attach a file; **reload** → text, link and file persist; shows **"Saved"** with no lingering "Unsaved changes".
* **Date picker:** view a past day (back-fill allowed; future dates blocked). **My recent logs** lists your entries with link/file counts.
* **Privacy:** a second **sales** account can **not** see the first's log or files.
* **Team view:** as **HR / manager / director** a **"Team daily logs"** panel appears — pick a date, see everyone's entries, expandable with body/links/files.

### Auto-recovery on deploy (CHANGED)
* Keep a tab **open**; after the next frontend deploy, navigate to a page you haven't visited in that tab.
  * ✓ Expect: instead of the old **"Something went wrong — not a valid JavaScript MIME type"** card, you see a brief **"Updating to the latest version…"** and the page **reloads itself** onto the new build.

### Role boundaries (spot-check)
* **Sales** sees only **their own** customers (log in as the *other* sales — the first's customers shouldn't appear).
* **Sales** can't see **ledger / margins / supplier POs / invoices** on a project (only the customer-facing shell).
* **Purchasing** never sees a **customer name** anywhere (PO screens, calendar, notifications).
* **Reports / KPI / Users / Audit log** are **director-only**.
* **AI Command Center / dashboard** opens cleanly for a **sales** user who has stage tasks (this was crashing before the recent fix — confirm no error).

---

### If something fails
Note the **role**, the **screen**, the **status** it was at, and the exact **error text** (or a screenshot). For push issues, first confirm you're on the **rebuilt Space** and **Device notifications** are on for that specific device.
