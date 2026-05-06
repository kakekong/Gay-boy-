# IndustriaCRM — A Smart Office Assistant for Industrial Engineering Companies

> Imagine if your sales, purchasing, warehouse, and finance teams all worked from
> the **same notebook**, and an AI assistant quietly read that notebook all day,
> looking for problems before they happen.
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
```

That's a **lot** to track. Most companies do this in spreadsheets, WhatsApp
chats, and emails. Things slip through the cracks. Customers go cold. Margins
get eaten. This software is the fix.

---

## What does it actually do?

Think of it as **three tools in one**:

### 1. 🧲 CRM — "Customer Notebook"
Keeps a tidy record of every customer, every phone call, every WhatsApp
message, and where each deal is in the pipeline. So nobody forgets to follow
up, and nobody has to ask "who's handling this customer?"

### 2. 🏭 ERP — "The Factory Brain"
Once a customer says yes, the system tracks the entire job: buying materials,
managing the workshop, doing quality checks, packing, delivering, invoicing,
and getting paid. All in one place.

### 3. 🤖 AI Assistant — "The Quiet Co-Worker"
This is the special part. An AI quietly watches everything and:

- Warns you when a deal is going cold ("you haven't called PT Bara in 8 days")
- Suggests the **best message** to send the customer next, in Bahasa Indonesia
- Reads incoming Purchase Order PDFs and automatically creates the project
- Tells you which deals are losing money before it's too late
- Reminds customers about overdue payments via WhatsApp
- Suggests upsell opportunities ("PT Cement A probably needs new chains soon")

---

## The 4 types of users

Different people in the company see different things:

| Person | What they can do |
|---|---|
| 👤 **Sales** | See only their own customers. Make quotations. Talk to customers. |
| 📝 **Admin** | Help enter data, but every change must be approved by a Manager. |
| 👔 **Manager** | Approve quotations and small discounts. See everything. |
| 👑 **Director** | Full access. Approve big discounts. See the whole company. |

### How discounts work (a real example)

Say a salesperson wants to give a customer a discount:

- 💚 **5% or less** → goes through automatically
- 🟡 **Between 5% and 15%** → the Manager has to say yes
- 🔴 **More than 15%** → the Director has to say yes

The system checks this **automatically**. No more "boss, can I give 10% to
this client?" over WhatsApp.

---

## What you'll see on the screen

The software is a website. After logging in, there's a menu on the left:

- **Dashboard** — your daily summary
- **CRM** — your list of customers
- **Quotations** — the price offers you've sent
- **Approvals** — things waiting for the boss to say yes
- **Projects** — jobs in progress
- **Purchasing** — materials being bought
- **Operation** — what's happening in the workshop
- **Finance** — invoices and payments
- **KPI** — performance numbers
- **Executive Dashboard** — the big-picture view (for managers/directors)
- **🧠 AI Command Center** — the smart room

### The 🧠 AI Command Center (the cool part)

This page is the **war room**. Open it in the morning and you instantly see:

- 🚨 **At-Risk Deals** — deals about to slip away, with the reason why
- ⚡ **Top Priority Actions** — your personal to-do list, ranked by importance
- 💰 **Profit Alerts** — projects losing money so you can act fast
- 📊 **Forecast vs Reality** — what was promised vs what actually closed
- 💡 **AI Recommendations** — opportunities the AI spotted for you

It's like having a smart assistant who already read every email and message
overnight and prepared a briefing.

---

## How does the WhatsApp part work?

This is built for Indonesia, so WhatsApp is the main channel.

- 📥 **Incoming**: when a customer messages your business WhatsApp, the message
  is automatically saved in their customer record. No more "where did I see
  that message?"
- 📤 **Outgoing**: the system sends payment reminders, quotation follow-ups,
  and after-sales messages on its own — but only at the **smart times** when
  that customer usually replies.

---

## What's actually inside this folder?

If you opened this folder on your computer, here's what you'd see:

```
.
├── README.md          ← this file
├── docs/              ← detailed design (for the technical team)
├── backend/           ← the engine that runs behind the scenes
├── frontend/          ← the website you click around in
├── n8n/               ← the automation rules (WhatsApp, reminders, etc.)
├── infra/             ← instructions for putting it all on a server
└── .github/           ← rules for testing the code automatically
```

You don't need to open any of these unless you're working with a developer.
The README in each folder explains what's there.

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
5. Run the database setup command (one-time)
6. Open the website in your browser

👉 **Beginner-friendly step-by-step (with copy-paste commands, screenshots-style
guidance, troubleshooting):** see **[`INSTALL.md`](INSTALL.md)**.

👉 **Production deployment, security hardening, scaling, backups:** see
[`docs/07-deployment.md`](docs/07-deployment.md).

---

## Demo logins (for trying it out)

After your developer runs the setup, you can log in with these demo accounts:

| Role | Email | Password |
|---|---|---|
| Director | `director@demo.local` | `demo1234` |
| Manager | `manager@demo.local` | `demo1234` |
| Sales | `sales1@demo.local` | `demo1234` |
| Admin | `admin@demo.local` | `demo1234` |

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
- 🤖 The AI is trained to think like a **B2B industrial salesperson**, not a
  marketing chatbot

---

## What this software is NOT

To be honest:

- ❌ It's **not a finished product** you download and click "install" on. It's
  a **scaffold** — a strong starting structure that a developer customizes for
  your company.
- ❌ It does **not replace** your accounting software for tax filing. It hands
  off cleanly to one.
- ❌ The AI is **a helper, not a decision-maker.** It suggests; humans approve.

---

## Where to go next

| If you are… | Read this |
|---|---|
| **Just trying to install it** | **[`INSTALL.md`](INSTALL.md)** — 30-min beginner guide |
| The business owner | This README is enough. Hand the rest to your dev team. |
| A non-technical manager | Skim [`docs/04-uiux-design.md`](docs/04-uiux-design.md) to see the screens. |
| A developer | Start at [`docs/01-architecture.md`](docs/01-architecture.md) then [`docs/03-api-design.md`](docs/03-api-design.md). |
| Curious about the AI | Read [`docs/06-ai-logic-design.md`](docs/06-ai-logic-design.md). |
| Ready to deploy to production | Read [`docs/07-deployment.md`](docs/07-deployment.md). |

---

## In one sentence

> **A modern, AI-powered, WhatsApp-native digital office for companies that
> sell custom-engineered industrial products to factories — built so nothing
> falls through the cracks, and your best deals don't go cold.**
