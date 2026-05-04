# 04 — UI / UX Design

Tech: **React 18 + Vite + TypeScript + TailwindCSS + shadcn/ui + TanStack Query + Recharts**.
Design language: clean enterprise SaaS, dense data tables, sidebar navigation, dark/light, RTL-friendly text, Bahasa Indonesia + English copy.

## 4.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Topbar:  IndustriaCRM   [search]   🔔 alerts   👤 user (role badge)      │
├────────────┬─────────────────────────────────────────────────────────────┤
│ Sidebar    │  Page content                                              │
│ • Dashboard│                                                            │
│ • CRM      │                                                            │
│ • Quotation│                                                            │
│ • Project  │                                                            │
│ • Purchasing│                                                           │
│ • Operation│                                                            │
│ • Finance  │                                                            │
│ • KPI      │                                                            │
│ • AI Cmd   │                                                            │
│ • Settings │                                                            │
└────────────┴─────────────────────────────────────────────────────────────┘
```

## 4.2 Page inventory

| Page | Purpose | Key components |
|---|---|---|
| **Login** | email/pwd, role-aware redirect | `<AuthForm/>` |
| **Dashboard / Home** | role-specific landing | `<KpiCards/>`, `<TopActions/>`, `<RecentActivity/>` |
| **CRM › Customer list** | filtered by role scope | `<DataTable/>`, `<StageBadge/>`, `<IndustryFilter/>` |
| **CRM › Customer detail** | tabs: overview, activities, quotations, projects, files | `<ActivityTimeline/>`, `<ReminderPanel/>`, `<WhatsAppThread/>` |
| **CRM › Pipeline (Kanban)** | drag-drop stage move | `<KanbanBoard/>` |
| **Quotation › List** | by status | `<QuotationTable/>` |
| **Quotation › Editor** | line items, std + custom, version compare | `<QuotationBuilder/>`, `<DiscountSlider/>` (live discount-rule indicator) |
| **Quotation › Approval inbox** | manager/director | `<ApprovalCard/>` |
| **Project › List & Gantt** | status, target delivery | `<GanttView/>`, `<ProjectCard/>` |
| **Project › Detail** | tabs: drawings, work orders, purchasing, deliveries, profit | `<DrawingApprovalFlow/>`, `<ProfitBreakdown/>` |
| **Purchasing** | PR/RFQ/PO/GR/QC tabs | `<DocChainView/>` |
| **Operation › Work Orders** | board grouped by stage | `<WorkOrderBoard/>` |
| **Operation › Delivery** | resi tracker, split delivery | `<DeliveryTracker/>` |
| **Finance › Invoicing** | issued / overdue / paid | `<InvoiceTable/>`, `<AgingChart/>` |
| **Finance › Payments** | record + reconciliation | `<PaymentForm/>` |
| **KPI** | role tabs: Sales / Purch / Ops / Finance | `<KpiChart/>`, `<TrendCard/>` |
| **Executive Dashboard** | director-only | `<PipelineFunnel/>`, `<ForecastChart/>`, `<TopCustomers/>`, `<LostDealAnalysis/>` |
| **🧠 AI Command Center** | the strategic war-room | see 4.3 |
| **Settings › Users / Roles** | director-only | |
| **Settings › Integrations** | WA, email, n8n, OpenAI keys | |

## 4.3 AI Command Center — page spec

This is the headline screen. Single dense dashboard, 4 quadrants + ribbon.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 🧠 AI Command Center                                  ▼ This week   ⏵   │
├──────────────────────────────────────────────────────────────────────────┤
│ Ribbon: Forecast vs Reality   |   Pipeline value   |   Win rate         │
│        IDR 12.4B vs 9.2B    |  IDR 24B           |  31% (▲ 4)          │
├──────────────────────┬───────────────────────────────────────────────────┤
│ 🚨 At Risk Deals     │  ⚡ Top Priority Actions (per sales)              │
│  • PT Bara Kalsel ─ HIGH (no follow-up 8d, discount 17%)                 │
│  • PT Semen X ─ MED (3 revisions, slow response)                         │
│  • CV Mitra Padi ─ LOW                                                   │
│                       │  1. Call PIC PT Bara Kalsel before 11:00        │
│                       │  2. Send revised quote to PT Sukses (drop 7→5%) │
│                       │  3. Schedule site visit Pabrik Gula Y           │
├──────────────────────┴───────────────────────────────────────────────────┤
│ 💰 Profit Alerts                  │ 🤖 AI Recommendations                │
│ • Project PRJ-2026-0042: margin   │ • PT Cement A — likely needs chain   │
│   estimate 18%, actual 9%.        │   replacement in 3 months. Upsell.   │
│   Cause: logistics +35%.          │ • Switch supplier for bearing X —    │
│   Recommend: change courier.      │   QC fail rate 18% last 90 days.     │
└──────────────────────────────────────────────────────────────────────────┘
```

Components:
- `<AtRiskDealsCard/>` — list with severity color, click → deal detail.
- `<TopActionsList/>` — daily ranked tasks per logged-in sales (by AI Smart Reminder).
- `<ForecastVsRealityRibbon/>` — pipeline forecast vs actual closed-won this period.
- `<ProfitAlertsCard/>` — projects breaching margin threshold.
- `<AIRecommendationsCard/>` — upsell, supplier switch, KB suggestion.

## 4.4 Component library (key)

- `<DataTable/>` — server-side pagination, column filters, persisted views.
- `<StageBadge stage={...} />` — color per pipeline stage.
- `<DiscountSlider/>` — 0–30%, shows live indicator: "Auto / Manager / Director".
- `<ApprovalCard request={...} />` — approve / reject inline with notes.
- `<ActivityTimeline/>` — call/WA/meeting/note merged chronological view; WA bubbles styled.
- `<WhatsAppThread/>` — embedded chat tied to the customer record.
- `<DrawingApprovalFlow/>` — upload → submit → customer link → status.
- `<ProfitBreakdown/>` — stacked bar (material/purchasing/logistics/discount) + delta vs estimate.
- `<RiskFlag level=...>` — red/orange/green chip with tooltip explaining drivers.
- `<KpiCard label value delta sparkline/>` — used everywhere.

## 4.5 UX principles for industrial B2B

1. **Information density, not minimalism.** Sales managers want a lot on one screen.
2. **Stage-first navigation.** Pipeline stage is the dominant axis.
3. **Approval signals are explicit.** Discount slider always shows the rule it triggers, before submit.
4. **WhatsApp is first-class.** Every customer page exposes the WA thread; logged automatically.
5. **Documents everywhere.** Quotations / drawings / PO / GR / invoices linked from any context.
6. **Audit visible.** "Edited by Admin · waiting Manager approval" badge on records.
7. **Mobile.** Sales-on-the-road priority screens: customer detail, log activity, approve, view priority actions, view risk.
