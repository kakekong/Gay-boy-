# Transmisi Eng — Full Test Workflow

A step-by-step script to verify the whole system end-to-end, including everything changed recently. Each step says **what to do** and **what you should see**. Tick as you go.

---

## 0. Before you start (do this first)

- [ ] **Rebuild the Hugging Face Space.** Most recent changes are backend (daily log, notification fixes, push hardening, the AI-dashboard crash fix). They only go live after a Space rebuild. The frontend (Vercel) is already live.
- [ ] After the rebuild finishes, open the site and hard-refresh once (⌘/Ctrl-Shift-R).
- [ ] **Watch the first rebuild's build log** for the line installing `pywebpush` — confirm it builds without error. If push doesn't work later, this is the first thing to check.
- [ ] **Accounts:** you'll want one login per role to see the boundaries. As director (Admin → Users) create test accounts if you don't have them: a **sales**, a second **sales**, a **purchasing**, an **admin**, a **finance**, and keep your **director** login. (Two sales accounts are needed for the chat and privacy tests.)
- [ ] **Two devices/browsers** help for the push tests (send from one, receive on the other). A phone + laptop is ideal.

> Tip: keep the **director** logged in on one browser and whichever **role** you're testing on another, so you can watch approvals arrive in real time.

---

## 1. Notifications & device push (test this early — it underpins the rest)

1. [ ] Log in, click the **bell** (top bar). You should see a dropdown; a red count means high-severity items.
2. [ ] In the bell menu, turn on **Device notifications**. Approve the browser permission prompt.
3. [ ] Click **Send test notification**. You should get a real OS/browser notification within a few seconds.
   - **On iPhone:** this only works if you first **Add the site to your Home Screen** and open it from that icon (Apple restriction). A normal Safari tab won't receive push.
4. [ ] Dismiss any bell item with its **✕**. It should stay gone until its underlying state changes.

> If the test notification never arrives: re-check the `pywebpush` build log from step 0, and that you're on the rebuilt Space.

---

## 2. The core deal-to-cash workflow

Do these in order — each step feeds the next. Watch the customer's **stage** advance automatically as documents get approved.

### 2a. Sales — create a customer
- [ ] As **sales**, go to **CRM → New customer**. Fill the 3 steps (basics → PICs → tax/NPWP). Save.
- [ ] Open the customer. You should see the **stage pipeline** at `lead`, a **stage checklist** ("Make first contact", "Qualify need + budget"), contacts, and an activity timeline.
- [ ] **Stage-task date behavior (changed):** the checklist tasks should show **"No deadline — set a date to get reminders"**, and should **NOT** appear on the calendar or in the bell yet.
  - [ ] Click **+ Set deadline / note** on one task, pick a date (today or tomorrow), save.
  - [ ] Now open the **Calendar** — that task should appear on the date you set. The **bell** should show it if it's due soon/overdue. (Tasks without a date stay silent — that's the point.)

### 2b. Sales → Purchasing → Director — price request
- [ ] As **sales**, on the customer, create a **Price Request**: add line items (description, qty, unit) — **no prices**. Submit.
- [ ] **Purchasing** should get a bell item + device push (the handoff). As **purchasing**, open the PR and enter the **cost per line**. Submit to director.
- [ ] **Director** gets notified. As **director**, open the PR, set the **sell price per line**, approve.
- [ ] Back as **sales**: you're notified of the decision. Confirm sales **never saw the cost**, and purchasing **never saw the customer name**.

### 2c. Discussion thread push (changed)
- [ ] On that same Price Request, as **purchasing**, post a **comment** ("Need the spec sheet").
- [ ] **Sales** (the requester) should get an **instant device push** — even as the first comment on the thread. Title shows the PR number; tapping opens the PR.

### 2d. Sales — quotation
- [ ] As **sales**, from the approved PR, **generate the quotation**. Every unit price should already be the director's sell price.
- [ ] **Submit** it. **Director** approves (in the quote or in **Approvals**). The customer stage should auto-advance to `quotation`.
- [ ] **Export PDF** and **Export Excel** — both should download with the company header. Check the customer **activity timeline** logged an "export" entry.
- [ ] **Mark won** → this files a request to the director. Director approves → quote flips to **Won**, revenue posts to the ledger, stage moves to `negotiation`.
  - [ ] Confirm **Mark lost** is now blocked (won/lost are mutually exclusive).

### 2e. Sales → Director — customer PO spawns the project
- [ ] As **sales**, from the Won quote's **"Next step"** card, file the **Customer PO** (attach a file, pick ordered items, set PO number/date). Leave the DP box unticked for a normal order.
- [ ] **Director** approves the Customer PO → a **Project** is created. Stage moves to `po`.
- [ ] Open **Projects** → your new project should be there.

### 2f. Purchasing / Admin — production
- [ ] As **purchasing**, raise a **Supplier PO** (director approves). Note the project shows to purchasing as "Order PRJ-…" with **no customer name**.
- [ ] As **admin**, on the project, walk the **work orders**: Receiving → Warehousing → QC. Confirm each stage gates on the project having reached the right phase.
- [ ] Upload/approve a **drawing** if you want to exercise that; drawing approval advances the project.

### 2g. Finance — invoice & payment
- [ ] As **finance**, after QC passes, issue the **final invoice + delivery order** from the project.
- [ ] Approve the invoice entering a **faktur pajak** number + file.
- [ ] Record a **payment** (manual entry on the invoice card, or verify a portal claim). When fully paid, the project should auto-advance **paid → closed**, and the deal stage lands on `closed_won`.
- [ ] As **finance/director**, open **Financial reports** — P&L, cash, balance sheet, by-salesperson — and **export** one to PDF/Excel.

---

## 3. Chat (instant push + mobile layout — changed)

- [ ] As **sales**, open **Chat**, start a DM with a colleague in the **same department**, send a message.
- [ ] On the **recipient's** other device/browser (tab closed is fine), a **push** should arrive within a second or two — sender's name as title, message as body; tapping opens the chat.
- [ ] Send several messages quickly — they should **collapse into one** re-alerting notification per conversation, not stack.
- [ ] **Cross-department DM:** as plain **sales**, try to start a DM with **purchasing** — it should be blocked (only director/manager/HR can start cross-department chats).
- [ ] **Mobile layout:** open Chat on your **phone**. You should see the conversation **list**; tapping a conversation opens a **full-screen thread** with a **‹ back** arrow, and the message box pinned at the bottom (the newest message and composer must both be visible — this was the bug you reported).

---

## 4. Daily log (new — under Attendance)

- [ ] Go to **Attendance**. Below the clock-in card there's a new **Daily log**.
- [ ] Type what you did in **"What did you work on?"**.
- [ ] Click **Add link**, give it a label + URL (try a bare domain like `docs.google.com/x` — it should auto-save as `https://…`).
- [ ] Click **Save log**. The **Files** area should switch from "Save your log once to attach files" to an uploader.
- [ ] **Attach a file** (drag-drop or Upload).
- [ ] **Reload the page** — your text, link, and file should all persist. It should show **"Saved"** with no lingering "Unsaved changes".
- [ ] Use the **date picker** to view a past day (you can back-fill; future dates are blocked).
- [ ] **My recent logs** below should list your entry (with link/file counts), expandable.
- [ ] **Privacy check:** a second **sales** account should **not** be able to see the first sales user's log or its files.
- [ ] **Team view:** as **HR / manager / director**, an extra **"Team daily logs"** panel should appear — pick a date and see everyone's entries, each expandable with body, links, and files.

---

## 5. Approvals inbox (manager/director)

- [ ] As **director**, open **Approvals**. Every gate from section 2 (quotation submit, mark-won, customer PO, supplier PO, price-request pricing) should have appeared here, plus a **documents queue** (submitted drawings, delivery proofs, PRs pending pricing).
- [ ] Approve/reject something with a note — the **requester** should get a decision notification with your reason.

---

## 6. Auto-recovery on deploy (changed — the "Something went wrong / MIME type" fix)

- [ ] Keep a tab **open** on the site. The next time a **new frontend deploy** goes out (or trigger one), navigate to a page you haven't visited yet in that tab.
- [ ] Instead of the old **"Something went wrong — not a valid JavaScript MIME type"** card, you should briefly see **"Updating to the latest version…"** and the page should **reload itself** onto the new version. No manual refresh needed.

---

## 7. Quick regression checklist (spot-check the boundaries)

- [ ] **Sales** can only see **their own** customers (log in as the *other* sales account — the first one's customers shouldn't appear).
- [ ] **Sales** cannot see the **ledger / margins / supplier POs / invoices** on a project (only the customer-facing shell).
- [ ] **Purchasing** never sees a **customer name** anywhere (PO screens, calendar, notifications).
- [ ] **Reports / KPI / Users / Audit log** are **director-only**.
- [ ] The **AI Command Center** / dashboard loads without error for a **sales** user who has stage tasks (this was crashing before the recent fix — confirm it opens cleanly).
- [ ] **Language toggle** (EN · ID) flips the sales surface; **global search** (⌘/Ctrl-K) opens.

---

### If something fails
Note the **role**, the **page**, and the exact **error text** (or a screenshot), and tell me. For anything push-related, first confirm you're on the **rebuilt Space** and that **Device notifications** are on for that specific device.
