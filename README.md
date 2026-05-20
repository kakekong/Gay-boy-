# IndustriaCRM — A Smart Office Assistant for Industrial Engineering Companies

> Imagine if your sales, purchasing, warehouse, finance, accounting, and HR
> teams all worked from the **same notebook**, and an AI assistant quietly
> read that notebook all day, looking for problems before they happen.
>
> That's what this software does.

---

## Who is this for?

This is built for companies that **make custom industrial products** for big
factories — things like:

- ⛏️ Mining
- ⚡ Power plants (PLTU)
- 🌱 Fertilizer plants
- 🍬 Sugar mills
- 🏗️ Cement plants
- 📰 Pulp & paper mills
- 🍞 Food factories

Selling to these customers is **not like selling on a website**. Each deal is
big, takes months, and follows a long path:

```
Customer asks for a quote
        ↓
We do a presentation
        ↓
Our engineers design the product
        ↓
We send a quotation (a price offer)
        ↓
We negotiate
        ↓
Customer sends a Purchase Order (PO)
        ↓
Customer approves the technical drawings
        ↓
We buy the materials
        ↓
We build it
        ↓
We deliver
        ↓
We send the invoice
        ↓
We receive payment
        ↓
The accounting books update automatically
```

That's a **lot** to track. Most companies do this in spreadsheets, WhatsApp
chats, and emails. Things slip through the cracks. Customers go cold. Margins
get eaten. Bookkeeping falls behind. This software is the fix.

---

## What does it actually do?

Think of it as **four tools in one**:

### 1. 🧲 CRM — "Customer Notebook"
Keeps a tidy record of every customer, every phone call, every WhatsApp
message, every quotation, and where each deal is in the pipeline. Click a
company and you see all their quotations. Click a quotation and you see the
full document, follow-ups, and which accounts it touches.

Every customer page has a **Deal pipeline stepper** — click any stage to move
the deal forward (or back) and the system auto-creates the checklist for that
stage with sensible due dates assigned to the sales PIC. Overdue items light
up in the notification bell and on the calendar. Each stage also shows
**"What to do in this stage"** shortcuts that link to the right module
(Purchasing, Finance, Payment verification, etc.).

### 2. 🏭 ERP — "The Factory Brain"
Once a customer says yes, the system tracks the entire job: buying materials,
managing the workshop, doing quality checks, packing, delivering, invoicing,
and getting paid. All in one place.

### 3. 💰 Accounting (CoA) — "The Books"
A full Indonesian Chart of Accounts (109 pre-seeded accounts: Bank, Kas,
Piutang Usaha, Persediaan, Aset Tetap, Hutang Pajak, etc.). When a deal is
**won**, the matching accounts (Receivable, Revenue, Discount, Tax Payable)
**update automatically** — no double bookkeeping.

### 4. 🤖 AI Assistant — "The Quiet Co-Worker"
This is the special part. An AI quietly watches everything and:

- Warns you when a deal is going cold ("you haven't called PT Bara in 8 days")
- Suggests the **best follow-up message** to send the customer, in Bahasa Indonesia
- Reads incoming Purchase Order PDFs and automatically creates the project
- Tells you which deals are losing money before it's too late
- Reminds customers about overdue payments via WhatsApp at the best time of day
- Suggests upsell opportunities ("PT Cement A probably needs new chains soon")

---

## The 5 types of users

Different people in the company see different things:

| Person | What they can do |
|---|---|
| 👤 **Sales** | See only their own customers and quotations. Make new quotations and log follow-ups. |
| 📝 **Admin** | Help enter data; every change must be approved by a Manager. Manages the **Chart of Accounts**. |
| 👥 **HR** | Sees the **employee directory** — every salesperson's pipeline, win rate, customers and activity. |
| 👔 **Manager** | Approves quotations and discounts. Sees the whole org pipeline. |
| 👑 **Director** | Full access to everything. Approves big discounts. |

### How discounts work (a real example)

Say a salesperson wants to give a customer a discount:

- 💚 **5% or less** → goes through automatically
- 🟡 **Between 5% and 15%** → the Manager has to say yes
- 🔴 **More than 15%** → the Director has to say yes

The system checks this **automatically**. The discount slider on the new
quotation form even shows you, live, who has to approve it before you hit
Submit.

---

## What you'll see on the screen

The software is a website. After logging in, there's a menu on the left,
grouped into sections:

### 🗂️ Workspace
- **Dashboard** — your daily summary with the top customers and an AI tip
- **CRM** — your filterable list of customers (click any company → see all their quotations + activity timeline)
- **Quotations** — every price offer; click any row → full quotation detail page
- **Calendar** — month view that aggregates reminders, quote expiries, payment due dates, target deliveries, and activities
- **Approvals** *(manager / director)* — discount and data-change inbox with one-click Approve / Reject

### 🏭 Operations
- **Projects** — won deals turned into deliverables, with margin tracking
- **Purchasing** — PR → RFQ → Supplier PO → GR → QC pipeline
- **Operation** — work-order board grouped by stage
- **Finance** — AR aging, invoices, payments
- **Chart of Accounts** *(admin / director)* — full Indonesian CoA, 109 accounts pre-seeded

### 👥 People
- **Employees** *(HR / director)* — directory grouped by role; cards show how many **missed days** each person has this month at a glance. Click any salesperson to see their KPIs, full **attendance** history, quotations, customers, and activity
- **Attendance** — daily clock-in/out, monthly summary, auto-feeds the salary deduction calculation

### 📊 Insights
- **KPI** — per-department performance numbers
- **Executive Dashboard** *(manager / director)* — pipeline, forecast, top customers, lost-deal analysis
- **🧠 AI Command Center** — the headline screen

### 🧠 AI Command Center (the cool part)

This page is the **war room**. Open it in the morning and you instantly see:

- 🚨 **At-Risk Deals** — deals about to slip away, with the reason why
- ⚡ **Top Priority Actions** — your personal to-do list, ranked by importance
- 💰 **Profit Alerts** — projects losing money so you can act fast
- 📊 **Forecast vs Reality** — what was promised vs what actually closed
- 💡 **AI Recommendations** — opportunities the AI spotted for you

It's like having a smart assistant who already read every email and message
overnight and prepared a briefing.

---

## 📖 New here?

If you've just been given an account, jump straight to **[`USER_GUIDE.md`](USER_GUIDE.md)**
(or click **Help** in the app's sidebar once you log in). It explains every page,
every button, and the most common day-to-day workflows in plain language.

---

## Working a deal — a typical day

1. **CRM** → click your customer → see their **last WhatsApp message, full
   activity timeline, and a panel listing every quotation you've sent**.
2. Click **+ New quotation** → modal with line-item editor and a discount
   slider that shows live the approval tier (Auto / Manager / Director).
3. Submit → if discount > 5%, an Approval card shows up in the manager's
   inbox; manager hits Approve.
4. Open the quotation detail page → **Log follow-up** modal records what was
   discussed, optionally schedules the next reminder (which immediately shows
   on the Calendar and the AI Top Priority Actions).
5. Click **Mark won** → status flips, a **Project** is auto-created, and the
   **accounting books update themselves**: Piutang Usaha goes up by the total,
   Penjualan goes up by the net amount, PPN Keluaran goes up by the tax,
   Diskon Penjualan goes up by the discount.
6. **HR or Director** can open the **Employees** page, click your name, and see
   exactly which quotations you've worked on, your win rate, and your
   pipeline value — without bugging you for a report.

---

## How does the WhatsApp part work?

This is built for Indonesia, so WhatsApp is the main channel.

- 📥 **Incoming**: when a customer messages your business WhatsApp, the message
  is automatically saved in their customer record.
- 📤 **Outgoing**: the system sends payment reminders, quotation follow-ups,
  and after-sales messages on its own — but only at the **smart times** when
  that customer usually replies (learned from their past response patterns).
- ✨ **AI suggest** button on every customer & quotation → drafts a polite,
  professional WhatsApp message in Bahasa Indonesia you can copy and send.

---

## What's actually inside this folder?

If you opened this folder on your computer, here's what you'd see:

```
.
├── README.md          ← this file
├── USER_GUIDE.md      ← new employee walkthrough (every page, every workflow)
├── INSTALL.md         ← beginner-friendly install (30 min, copy-paste)
├── preview.html       ← open in a browser to preview the UI without installing
├── docs/              ← detailed design (for the technical team)
├── backend/           ← the engine that runs behind the scenes (FastAPI + PostgreSQL)
├── frontend/          ← the website you click around in (React + Vite + Tailwind)
├── n8n/               ← the automation rules (WhatsApp, reminders, etc.)
├── infra/             ← instructions for putting it all on a server (Docker)
└── .github/           ← rules for testing the code automatically (CI)
```

You don't need to open any of these unless you're working with a developer.
Each module has its own README explaining what's there.

---

## How do you actually run it?

You can try this on your **own laptop in about 30 minutes**, or put it on a
small cloud server for your team to use. Both options use **one tool** called
Docker.

The whole thing in plain words:

1. Install Docker (it's free, takes 5 minutes)
2. Download the code (one command)
3. Copy the example settings file
4. Run **one start command** — Docker fetches the database, the website, the
   automation engine, and starts them all
5. Run the seed command (one-time) — creates the database tables, adds demo
   users + customers, and pre-populates the 109-account Indonesian Chart of
   Accounts
6. Open the website in your browser

👉 **Beginner-friendly step-by-step (with copy-paste commands, screenshots-style
guidance, troubleshooting):** see **[`INSTALL.md`](INSTALL.md)**.

👉 **Want to see what it looks like first, without installing?** Open
[`preview.html`](preview.html) in your browser — it's a static preview of the
main screens with demo data.

👉 **Production deployment, security hardening, scaling, backups:** see
[`docs/07-deployment.md`](docs/07-deployment.md).

---

## Demo logins (for trying it out)

After your developer runs the setup, you can log in with these demo accounts:

| Role | Email | Password | Sees |
|---|---|---|---|
| Director | `director@demo.local` | `demo1234` | Everything |
| Manager | `manager@demo.local` | `demo1234` | Org-wide CRM, KPIs, approvals |
| HR | `hr@demo.local` | `demo1234` | The Employees directory |
| Admin | `admin@demo.local` | `demo1234` | Data entry + Chart of Accounts |
| Sales | `sales1@demo.local` | `demo1234` | Their own customers + quotations |
| Sales | `sales2@demo.local` | `demo1234` | Their own customers + quotations |

Each one shows a slightly different view, so you can see how permissions work.

---

## What's special about this vs. a generic CRM?

Most CRMs (HubSpot, Salesforce, Zoho) are designed for selling **standard
products** to **many customers**. This one is the opposite:

- 🎯 Built for **few, high-value, custom-engineered deals**
- 🇮🇩 Speaks **Bahasa Indonesia** by default (WhatsApp messages, quotations)
- 📋 Knows the **drawing approval** stage (custom products need this)
- 💰 Tracks **profit per project** in real time (not just revenue)
- 🚛 Handles **split delivery** (one PO can be delivered in pieces)
- 💳 Knows **DP / Tempo / Termin** payment terms (not just credit cards)
- 🤝 Built around the **approval culture** of Indonesian B2B (manager OKs everything)
- 📚 Has a **real Chart of Accounts inside** (Penjualan, Piutang Usaha, PPN
  Keluaran, etc.) that **auto-updates when a deal is won** — no double entry
  between your CRM and your accounting app
- 🤖 The AI is trained to think like a **B2B industrial salesperson**, not a
  marketing chatbot

---

## What this software is NOT

To be honest:

- ❌ It's **not a finished product** you download and click "install" on. It's
  a **scaffold** — a strong starting structure that a developer customizes for
  your company.
- ❌ It does **not replace** a full general ledger (e.g. for e-Faktur tax
  reporting). It tracks balances cleanly and can hand off to a proper
  accounting app at month-end.
- ❌ The AI is **a helper, not a decision-maker.** It suggests; humans approve.

---

## Where to go next

| If you are… | Read this |
|---|---|
| **A new employee opening the app for the first time** | **[`USER_GUIDE.md`](USER_GUIDE.md)** — every page explained, common workflows, troubleshooting. Also available **inside the app** at **Help** in the sidebar. |
| **Just want to see the UI** | Open **[`preview.html`](preview.html)** in any browser — no install |
| **Just trying to install it** | **[`INSTALL.md`](INSTALL.md)** — 30-min beginner guide |
| The business owner | This README is enough. Hand the rest to your dev team. |
| A non-technical manager | Skim [`docs/04-uiux-design.md`](docs/04-uiux-design.md) to see the screens. |
| A developer | Start at [`docs/01-architecture.md`](docs/01-architecture.md) then [`docs/03-api-design.md`](docs/03-api-design.md). |
| Curious about the AI | Read [`docs/06-ai-logic-design.md`](docs/06-ai-logic-design.md). |
| Ready to deploy to production | Read [`docs/07-deployment.md`](docs/07-deployment.md). |

---

## In one sentence

> **A modern, AI-powered, WhatsApp-native digital office for Indonesian
> companies that sell custom-engineered industrial products to factories —
> CRM, ERP, accounting, HR, and AI follow-ups in one place, so nothing falls
> through the cracks and your best deals don't go cold.**
