# Transmisi Eng — User Guide

> Welcome! This guide walks you through every part of the website. No coding,
> no tech jargon — just how things work and what each button does.
>
> **Reading time:** ~10 minutes. **Hands-on tour:** ~20 minutes.

---

## 1. Your first day

### Logging in

Open your browser, go to the company URL (e.g. `https://crm.yourco.com` or
`http://localhost:5173` for the demo), and you'll see a split-screen login.

- **Email** — your work email
- **Password** — given to you by IT
- Click **Sign in**

If you get "Invalid credentials", check the password (it's case-sensitive). If
you forgot it, ask the **Director** to reset it for you.

### What you see depends on your role

The system has **5 roles** with different views:

| Role | What you'll see |
|---|---|
| 👤 **Sales** | Your own customers and quotations, the Calendar, Chat |
| 📝 **Admin** | Data entry pages + Chart of Accounts |
| 👥 **HR** | The Employees directory + tag management |
| 👔 **Manager** | The whole sales pipeline + the Approvals inbox |
| 👑 **Director** | Everything, plus Salary |

A label at the top right shows your name and role.

---

## 2. The layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [search]   💬 chat   🔔 alerts        Your Name (your role)  [avatar]    │
├────────────┬─────────────────────────────────────────────────────────────┤
│ 🏭 Logo    │                                                            │
│            │                                                            │
│ Workspace  │    ←  Whatever page you're on shows here                   │
│  Dashboard │                                                            │
│  CRM       │                                                            │
│  Quotations│                                                            │
│  Calendar  │                                                            │
│  Chat      │                                                            │
│  Approvals │                                                            │
│            │                                                            │
│ Operations │                                                            │
│  Projects  │                                                            │
│  Purchasing│                                                            │
│  Operation │                                                            │
│  Finance   │                                                            │
│  Inventory │                                                            │
│  Accounts  │                                                            │
│            │                                                            │
│ People     │                                                            │
│  Employees │                                                            │
│  Salary    │                                                            │
│            │                                                            │
│ Insights   │                                                            │
│  KPI       │                                                            │
│  Executive │                                                            │
│  AI Command│                                                            │
│  Help      │                                                            │
├────────────┴─────────────────────────────────────────────────────────────┤
│ 👤 You · [logout]                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### The top bar
| Element | What it does |
|---|---|
| 🔍 **Search** | Type to search customers, quotations, projects. `⌘K` / `Ctrl K` opens it from the keyboard. |
| 💬 **Chat button** | Opens the chat page. A **red badge** shows how many unread messages you have. |
| 🔔 **Bell** | Notifications (coming soon) |
| 👤 **Your name + role** | Hover for your account menu |

### The left sidebar

The sidebar is **grouped** so it's easy to find things:

- **Workspace** — your daily tools (Dashboard, CRM, Quotations, Calendar, Chat, Approvals)
- **Operations** — running the business (Projects, Purchasing, Operation, Finance, Inventory, Chart of Accounts)
- **People** — your colleagues (Employees, Salary)
- **Insights** — the numbers (KPI, Executive, AI Command, Help)

Items you don't have permission to see are hidden — your menu is shorter than
this list. That's normal.

### Mobile
On a phone the sidebar tucks away behind a **menu (☰) button** in the top left.

---

## 3. The pages — one by one

### 🏠 Dashboard
The home page. Shows:
- A greeting and 4 KPI cards (New leads · Quote→Win rate · Outstanding AR · Collected)
- Your most recent active customers (click one to open it)
- An "AI tip of the day" with a shortcut to the AI Command Center
- A **+ New quotation** button in the top right

### 🧲 CRM — Customers
Your customer book. The page has **two views you can toggle** between:

#### Table view (default)
- Searchable list with filters (stage, industry)
- Each row: Company · Industry · PIC · Stage · Lifetime value
- **Click a company** → opens its detail page
- **+ New customer** opens a modal
- **Export** downloads everyone to CSV

#### 🆕 Pipeline view (the cool one)
- **13 columns** for each stage (Lead → Presentation → … → Won / Lost)
- Each customer is a **colorful card** tinted to its industry (⛏️ Mining, ⚡ PLTU, 🏗️ Cement, …)
- Each column shows a **count** and the **sum of value** in that column
- **Drag any card to a different column** to move the deal across stages — the books update automatically when relevant
- **Show / Hide closed** toggle controls whether Won/Lost columns appear
- Click a card normally to open the customer; drag to move it

### 👤 Customer detail page
What you see when you click a company:
- **Header** — company name, industry, current stage chip, contact info (phone, WhatsApp, email, address)
- **Export spreadsheet** — downloads a full CSV (profile, financials, all quotations, projects, invoices, payments, activities) for offline review or sharing with management
- **WhatsApp button** — opens the customer's number on `wa.me` so you can chat
- **AI suggest** — generates a polite follow-up message in Bahasa Indonesia you can copy & send
- **AI Lead score** — a 0–100 score with a circular ring + the top reasons
- **Deal pipeline (stepper)** — every stage shown as a clickable chip. Click any stage to move the deal forward (or back, for fixes), or use the **Advance to …** button on the right. Green = stages already passed, blue = current, plain = upcoming. There are also **Mark won / Mark lost** shortcuts.
- **What to do in this stage** — stage-aware shortcuts to the right module: e.g. in *Purchasing* it links straight to the Purchasing screen; in *Delivery* to the project shipping timeline; in *Invoicing* to Finance; in *Payment* to Payment verification.
- **Stage checklist** — the required actions for the current stage, each with a due date. Click the circle to mark done (line-through + green), the pencil icon to add a note or change the due date, and **On calendar** to find it on the calendar. A green progress bar fills as you complete items.
- **Quotations** — every quote ever sent to this customer (click any to open)
- **Projects / Invoices / Payments** — every running project, billed invoice, and received payment
- **Activity timeline** — every call, meeting, WhatsApp message, log entry
- **Log activity** button — record a call, meeting, or note

### 📄 Quotations
List of all price offers. Each row is **clickable** — opens the full quotation
detail page with:
- Number, status, version, link back to customer
- **Line items table** with description / qty / unit price / line total
- **Discount tier indicator** — Auto / Manager / Director (live; tells you who'll need to approve)
- **Totals card** with discount + tax breakdown
- Action buttons by state:
  - `Submit` — sends the draft into the approval pipeline
  - `Approve` / `Reject` — visible to manager/director when status is pending
  - `Mark won` — converts to a project, auto-updates the accounting books
  - `Mark lost` — asks for the reason
- **Linked Accounts** card — shows the 4 ledger accounts that auto-update on win (Receivable, Revenue, Discount, Tax)
- **Follow-ups** card — log what was discussed, schedule the next reminder

### 📅 Calendar
Month grid showing all time-bound events for the visible range:
- 🔵 Reminders (follow-ups you scheduled)
- 🟣 Quote expiries (`valid_until` date)
- 🟢 Target deliveries (projects)
- 🟠 Payment due dates
- 🔴 Overdue invoices
- ⚫ Logged activities

Click a day → right panel shows that day's events. **Double-click a day** to
add a new reminder for it.

### 💬 Chat
Internal team chat — direct messages with any colleague.
- Left pane: your conversations sorted by latest message, with **red unread badges**
- Right pane: message thread
- **+ New chat** opens an employee picker
- **Hover your own messages** to edit (✏️) or delete (🗑️)
- Polls every 5 seconds — you'll see new messages almost instantly

### ✅ Approvals *(manager / director only)*
Inbox of things waiting for your "yes":
- Quotation discount approvals (5–15% needs Manager; > 15% needs Director)
- Data changes made by Admin

Each card shows the request, who asked, and the proposed changes. Click
**Approve** or **Reject**. The requester is notified automatically.

### 💼 Projects
Won deals that are now jobs. Each row shows:
- Project code, status, PO value, margin (estimate vs actual), target delivery
- Click for the full project page (work orders, drawings, deliveries)

### 🛒 Purchasing
Pipeline for buying materials: **PR → RFQ → Supplier PO → Goods Receipt → QC**.
- 5 stage cards across the top showing counts at each stage
- **Suppliers** table — everyone with access to this page can see the vendor list, ratings, and lead times. New suppliers are created from the **+ New supplier** button.
- **Supplier purchase orders** + **+ New PO** — **director only**. The director is the only role who can issue a PO and link it to a specific supplier + project. This keeps the supplier⇄customer mapping inside the director's office so vendors can only see the work assigned to them.

### 🔧 Operation
Work order board. Columns for production stages: Receiving · Warehousing ·
QC · Packaging · Delivery. Work orders flow left to right.

### 💰 Finance
AR Aging dashboard.
- Total outstanding receivables in a stacked colored bar
- 5 buckets: Current · 0–30 · 31–60 · 61–90 · 90+ days past due

### 📦 Inventory *(everyone can view; admin/director can edit)*
"Do we have this in stock?" — your stockroom in one screen.
- 3 KPI cards: items tracked · low/out count · total stock value
- Table: SKU · name · category · stock · reorder-at · unit cost · status chip
- **Status chips**: 🟢 In stock · 🟡 Low · 🔴 Out
- 🛒 **Request order** button — one click creates a Purchase Request at the reorder quantity. Purchasing handles the rest.
- Admin / Director: **Adjust stock** (Stock IN / OUT with reason and reference), **Edit item**, **+ New item**

### 📚 Chart of Accounts *(admin / director only)*
The full Indonesian books (Bagan Akun).
- 109 pre-seeded accounts (Bank, Kas, Piutang Usaha, Persediaan, Aset Tetap, etc.)
- Parent rows shown with grey background and bold
- Child rows indented under their parent
- **Balance column** uses Indonesian format (dot thousands, comma decimal); negatives in red parens like `(375.233.030,22)`
- Filter by account type or suspended state
- Tags accounts marked as **Tax** with a violet chip
- Toolbar: + New · Refresh · Export CSV · Share · Print

### 👥 Employees *(HR / director only)*
Directory of all colleagues, grouped by role.
- Search by name or email; filter by role or **tag**
- Each card shows avatar, role chip, any tags, and — if they have any — a **missed-days chip** for the current month (yellow ≤ 2, red ≥ 3). Calculated as `absent + half-day × 0.5`, the same number used for salary deductions.
- Click a card → **Employee detail page**:
  - Header with contact info + Tags section (HR can add/remove tags from a picker)
  - 6 KPI cards: Customers · Quotations · Won · Lost · Win rate · Won revenue
  - **Missed days this month** KPI strip whenever it's greater than 0
  - Pipeline value strip for sales
  - **Attendance** card with month picker, six summary tiles (workdays · present · half-day · absent · leave · deductible days), total hours, and a daily table of every clock-in/out
  - **Quotations table** — every quote that employee authored
  - **Assigned customers** table
  - **Recent activity** timeline
- **Manage tags** button in the page header opens a tag admin modal (create, rename, recolor, delete)

### 💵 Salary *(director only)*
Monthly payroll.
- Pick a month at the top
- 4 KPI cards: Employees paid · Gross · PPh21 withheld · Net paid
- Table of salary records; per-row actions:
  - `Edit` / `Delete` for drafts
  - `Post to ledger` — auto-updates Beban Gaji, Hutang PPh21, Hutang Gaji
  - `Mark paid` — pays out from the bank account
  - `Reverse` — rolls back the posting (only before payment)
- **+ New salary** modal lets you fill earnings (base, transport, meal, bonus, THR, allowance) and deductions (PPh21, BPJS, other) with a live gross/deductions/net summary

### 📊 KPI
Per-department performance numbers (sales / operation / purchasing / finance).
Each card shows the latest metrics; pulled from real database queries.

### 👑 Executive Dashboard *(manager / director only)*
Big-picture view:
- KPI cards: Pipeline value · Won revenue · Top customers
- Top customers ranked by lifetime value with a bar chart

### 🧠 AI Command Center
The strategic war-room. Open this in the morning.
- **Hero strip**: Forecast vs Reality (progress bar) · At-risk deal count · Profit alert count
- **At Risk Deals** — deals slipping, with reason chips and AI-recommended action
- **Top Priority Actions** — your day, ranked by AI (1, 2, 3…)
- **Profit Alerts** — projects breaching margin estimate
- **AI Recommendations** — upsell opportunities, supplier switches, strategy notes

### 🏢 Customer portal *(customer-role logins only)*
The stripped-down view a customer sees when they log in. No sidebar, no
internal data.
- Their open quotations and project status
- **Shipping timeline** per project: Ship-from-origin → Arrive at our warehouse → Arrive at customer (with estimated + actual dates side by side). Suppliers update the first two; internal team owns the last. **Updates from the supplier appear here automatically — no internal step needed.**
- Drawings awaiting their approval — they can Approve / Reject directly
- Invoices, with an "I paid this" button that opens the payment-claim modal

### 🏭 Supplier portal *(supplier-role logins only)*
What a vendor sees when they log into your system.
- Their open RFQs and Supplier POs (only their own)
- For each PO:
  - **Status tiles** show whether they've uploaded a drawing and set the warehouse ETA
  - **Shipping dates** card — they fill in *Estimated arrival at our warehouse*, *Actual ship-from-origin*, *Actual arrived at warehouse*. The moment they hit **Save dates**, those values appear on the customer's shipping timeline.
  - **Upload** Drawing (PDF) / Invoice / Bill / Delivery proof. Uploading a Drawing on a project-linked PO auto-creates a revision in that project's drawing list — the customer can then approve from their portal.
  - An amber banner warns if drawing or ETA is missing.
- Every PO must be linked to a Supplier **and** a Project before the supplier can set dates. If the PO isn't linked yet, the supplier sees a warning to contact the buyer.

### 📖 Help
This guide, rendered inline so you never have to leave the app.

---

## 4. Common workflows

### A) Starting a new deal
1. Click **CRM → + New customer**
2. Fill company name, industry, PIC name, phone/WhatsApp, email, address
3. Save → you become the **Sales PIC** automatically (if you're sales)
4. Open the customer → log a **call / presentation / technical meeting** activity to remember what you discussed
5. As you progress, **drag the card to the next stage** on the Pipeline view

### B) Sending a quotation
1. On the customer page (or Quotations page), click **+ New quotation**
2. Pick the customer, fill **line items** (description, qty, unit price)
3. Adjust **discount** — the slider tells you live whether it needs no / manager / director approval
4. Save as **draft**, review, then **Submit**
   - ≤5% discount: auto-approved
   - 5–15%: goes to Manager's Approvals inbox
   - >15%: goes to Director
5. Once approved, click **Send** (or download the PDF and email it)
6. Open the quotation page later to **Log a follow-up** with notes + schedule the next reminder

### C) Marking a deal won
1. Open the quotation page → click **Mark won**
2. Three things happen automatically:
   - The quotation status becomes **Won**
   - A **Project** is created with the same value
   - The **Chart of Accounts updates** — Piutang Usaha (Receivable) up, Penjualan (Revenue) up, PPN Keluaran up, Diskon Penjualan up
3. Open **Linked Accounts** card on the quotation to see exactly what posted; click **Reverse** if needed

### D) Following up on a quote
1. Open the quotation → **Follow-ups** card → **Log follow-up**
2. Type notes (or click **✨ AI suggest** for a draft message)
3. Tick **Schedule next follow-up** → pick date + time + channel (Dashboard / WhatsApp / Email)
4. Save → a reminder appears on the **Calendar** and in **AI Command Center → Top Priority Actions**
5. When the reminder pings you, open the customer / quotation, click **Done** on the reminder

### E) Checking if something's in stock
1. **Operations → Inventory**
2. Search the SKU or name
3. Look at the **status chip**:
   - 🟢 In stock — you can promise it
   - 🟡 Low — you can probably promise it, but tell purchasing
   - 🔴 Out — don't promise; click **Request order** to send a Purchase Request

### F) Tagging an employee *(HR / Director)*
1. **People → Employees → Manage tags** → create a tag (e.g. "Top performer", emerald color)
2. Open the employee's detail page → **+ Add tag** → pick from the list
3. The tag chip appears on their card on the Employees page and on their detail page
4. Filter the Employees page by tag to find everyone with that tag

### G) Chatting with a colleague
1. **Workspace → Chat** → **+ New chat**
2. Search the colleague's name, click them → a DM opens
3. Type and **Send**; their unread badge ticks up immediately
4. **Hover your messages** to edit or delete

### H) Approving a discount *(Manager / Director)*
1. The chat icon / Approvals nav shows a count when something's waiting
2. **Approvals** → click the request card → review the proposed discount and total
3. Click **Approve** (or **Reject** with a reason)
4. The salesperson is notified; the quotation status moves on

---

## 5. Role guide — at a glance

| Page | Sales | Admin | HR | Manager | Director |
|---|:-:|:-:|:-:|:-:|:-:|
| Dashboard | ✅ | ✅ | ✅ | ✅ | ✅ |
| CRM (own only for Sales) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Quotations | ✅ | ✅ | ✅ | ✅ | ✅ |
| Calendar | ✅ | ✅ | ✅ | ✅ | ✅ |
| Chat | ✅ | ✅ | ✅ | ✅ | ✅ |
| Approvals | — | — | — | ✅ | ✅ |
| Projects / Purchasing / Operation / Finance | ✅ | ✅ | ✅ | ✅ | ✅ |
| Inventory (view) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Inventory (edit) | — | ✅ | — | — | ✅ |
| Chart of Accounts | — | ✅ | — | — | ✅ |
| Employees | — | — | ✅ | — | ✅ |
| Manage Tags | — | — | ✅ | — | ✅ |
| Salary | — | — | — | — | ✅ |
| KPI | ✅ | ✅ | ✅ | ✅ | ✅ |
| Executive Dashboard | — | — | — | ✅ | ✅ |
| AI Command Center | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 6. Quick reference

### Pipeline stages explained
Every stage has a **checklist** auto-created when you move the deal there. Stage moves happen on the customer page using the **Deal pipeline** stepper — click the next stage, or use the **Advance to …** button.

| Stage | What it means | Auto-checklist |
|---|---|---|
| Lead | Just heard of them; nothing real yet | First contact within 24 h · Qualify need + budget |
| Presentation | We've shown them what we make | Schedule demo · Send company deck |
| Engineering | Our engineers are designing for them | Spec review · Site survey if needed |
| Quotation | We sent a price offer | Draft quotation · Send quotation |
| Negotiation | They're haggling | Follow up · Second follow-up if silent |
| PO | They sent a Purchase Order — it's real | Collect signed PO · Confirm payment terms |
| Drawing | Customer is approving the technical drawings | Send drawing · Collect customer sign-off |
| Purchasing | We're buying materials | Raise PR · Select supplier & issue PO |
| Delivery | Shipping the goods | Schedule delivery · Upload BAST / delivery proof |
| Invoicing | We sent the invoice | Issue invoice · Send invoice to customer |
| Payment | Waiting for the money | Follow up on payment |
| Won | Closed and paid 🎉 | — |

Overdue checklist items appear in the **Notifications bell** (top-right) as red alerts, and on the **Calendar** as red "Stage task" events that link directly back to the customer.

### How the stage stepper works
1. Open a customer.
2. The **Deal pipeline** card shows every stage as a chip; current is blue, completed are green, upcoming are gray.
3. Click any chip to move the deal there — or use **Advance to …** for the next-in-sequence move.
4. The **Stage checklist** below auto-reloads with the new stage's required tasks. Existing tasks for old stages stay (they don't get deleted), so nothing is lost.
5. The **What to do in this stage** card gives stage-aware shortcuts (e.g. "Open Purchasing" when you're at the purchasing stage).
6. Tick checklist circles as you finish each task. Add a note or change the due date with **+ Note / change due**.
7. To skip past stages (e.g. straight from PO to Delivery for a fast-track project), just click the destination stage — no validation blocks you.
| Lost | Didn't win this one |

### Discount tier rules
| Discount | Who approves |
|---|---|
| 0 – 5% | Auto-approved |
| 5 – 15% | Manager |
| > 15% | Director |

The discount slider on the new-quotation modal shows you live which tier
applies. **Don't try to game it** — the system records everything.

### Common chips & their colors
- 🟢 **Won / Approved / In stock / Paid** — good things
- 🟡 **Pending / Low / Negotiation / Quotation** — needs attention
- 🔴 **Lost / Out / Overdue / Rejected** — bad things
- 🟣 **Tax / Quotation expiry** — informational
- 🔵 **Brand-colored** — primary actions, you (in chat), pinned items

### Indonesian number format
We show all money in `Rp` with Indonesian convention:
- `1.234.567,89` (dots for thousands, comma for decimal)
- Negative balances in **red** with parentheses: `(1.234.567)`
- Zero shows as plain `0`

---

## 7. Tips & shortcuts

- **`⌘K` / `Ctrl K`** opens the search bar (coming as a command palette later)
- The **AI suggest** button is on nearly every customer / quotation — use it; it
  drafts a Bahasa Indonesia message you can edit before sending
- **WhatsApp** button on a customer page opens `wa.me/<number>` in a new tab —
  log the call right after via **Log activity**
- The **Calendar** double-click is the fastest way to make a reminder for a
  specific date
- The **AI Command Center** is the best place to start the day — top actions
  are AI-ranked
- **Save searches** as URLs — bookmark `/customers?stage=quotation` to jump
  straight to your active quotes
- Click any **value in the AR Aging stacked bar** to see which invoices are
  there
- The **chart-of-accounts page is printable** — click Print for a clean PDF

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "I can't see the Employees / Salary / Approvals link" | You don't have permission for that role. Ask the Director to grant it. |
| "I made a quote but it's stuck in Pending approval" | The Manager (or Director if >15%) needs to act. Ping them via **Chat**. |
| "The customer card won't drag in pipeline" | Click and hold the card itself, not the link text. On mobile, the pipeline is hard to drag — use the table view. |
| "I see 'Invalid payload' on the login page" | Your password is wrong, or you typed an unexpected character. Try again. |
| "My WhatsApp button does nothing" | The customer record doesn't have a phone or WhatsApp number filled in. Edit the customer and add one. |
| "I deleted a message I shouldn't have" | Sorry — chat deletes are soft (visible as "[deleted]") but you can't restore. Send a new message instead. |
| "I can't find my customer" | Sales see only their own. If you think it's yours but missing, ask Admin who the Sales PIC is. |

---

## 9. Need more help?

- **In-app**: click **Help** in the sidebar to read this guide
- **From IT / Director**: they can see your activity logs and help debug
- **Bug report**: send a screenshot + what you were doing to your developer

— Happy selling! 🚀
