import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen, Layout, Users, FileText, CalendarDays, MessageCircle,
  CheckSquare, Briefcase, ShoppingCart, Wrench, Banknote, Package,
  Receipt, Wallet, BarChart3, Crown, BrainCircuit, ChevronRight,
  Sparkles, ArrowRight, KeyRound, AlertCircle, Map,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/auth";

const SECTIONS = [
  { id: "first-day",   label: "Your first day",   icon: KeyRound },
  { id: "layout",      label: "The layout",       icon: Layout },
  { id: "pages",       label: "Pages walkthrough",icon: Map },
  { id: "workflows",   label: "Common workflows", icon: Sparkles },
  { id: "roles",       label: "Role guide",       icon: Users },
  { id: "reference",   label: "Quick reference",  icon: BookOpen },
  { id: "tips",        label: "Tips & shortcuts", icon: ArrowRight },
  { id: "troubles",    label: "Troubleshooting",  icon: AlertCircle },
];

export default function HelpPage() {
  const nav = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [active, setActive] = useState("first-day");

  // Highlight section on scroll
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActive((e.target as HTMLElement).id);
        }
      },
      { rootMargin: "-30% 0px -65% 0px" }
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-ink-900 via-brand-800 to-brand-600 text-white p-6 lg:p-8 shadow-hero">
        <div className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-brand-300/20 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-32 -left-10 h-72 w-72 rounded-full bg-white/5 blur-3xl pointer-events-none" />
        <div className="relative flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-white/15 backdrop-blur flex items-center justify-center">
            <BookOpen size={22} />
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-widest text-white/70">User guide</div>
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight mt-0.5">
              Welcome{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""} 👋
            </h1>
            <p className="text-white/80 text-sm mt-1 max-w-2xl">
              A guided tour of every page and the most common workflows. Use the table of
              contents on the right to jump around — no scrolling marathon needed.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px] gap-6">
        {/* Content */}
        <div className="space-y-8">
          {/* 1. First day */}
          <Section id="first-day" title="1. Your first day" icon={<KeyRound size={20} />}>
            <P>
              Open your browser, go to your company URL, and log in with the email + password
              IT gave you. The top bar shows your name and role; the sidebar adjusts to what
              you can see.
            </P>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
              <Tile icon="👤" title="Sales" body="Your customers, quotations, calendar, chat." />
              <Tile icon="📝" title="Admin" body="Data entry pages + Chart of Accounts." />
              <Tile icon="👥" title="HR" body="The Employees directory + tag management." />
              <Tile icon="👔" title="Manager" body="Whole-org pipeline + Approvals inbox." />
              <Tile icon="👑" title="Director" body="Everything, plus Salary." />
            </div>
          </Section>

          {/* 2. Layout */}
          <Section id="layout" title="2. The layout" icon={<Layout size={20} />}>
            <P>The screen has three parts:</P>
            <ul className="space-y-1.5 text-sm pl-1">
              <li>🔝 <b>Top bar</b> — global search, chat button (with unread badge), bell, your profile</li>
              <li>⬅️ <b>Left sidebar</b> — grouped menu (Workspace · Operations · People · Insights)</li>
              <li>📄 <b>Main area</b> — whichever page you're on</li>
            </ul>
            <P>
              On a phone, the sidebar tucks away behind a <b>menu (☰)</b> button.
            </P>
            <div className="rounded-xl bg-ink-50 border border-ink-100 p-3 text-xs muted">
              <b>Tip:</b> Items you don't have permission to see are hidden, so your menu is
              shorter than the full list. That's by design.
            </div>
          </Section>

          {/* 3. Pages */}
          <Section id="pages" title="3. The pages — one by one" icon={<Map size={20} />}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <PageCard icon={<LayoutIcon />}    title="Dashboard"            blurb="Greeting · 4 KPI cards · recent customers · AI tip of the day." path="/" nav={nav} />
              <PageCard icon={<Users size={18}/>} title="CRM (Customers)"      blurb="Table view OR Pipeline (Kanban) — drag cards across stages." path="/customers" nav={nav} />
              <PageCard icon={<FileText size={18}/>} title="Quotations"        blurb="List of price offers; click for the full detail page with line items, follow-ups, linked accounts." path="/quotations" nav={nav} />
              <PageCard icon={<CalendarDays size={18}/>} title="Calendar"      blurb="Month view aggregating reminders, quote expiries, deliveries, payment dues." path="/calendar" nav={nav} />
              <PageCard icon={<MessageCircle size={18}/>} title="Chat"          blurb="Direct messages with colleagues. Polls every 5s; unread badge in topbar." path="/chat" nav={nav} />
              <PageCard icon={<CheckSquare size={18}/>}  title="Approvals"      blurb="Inbox of discount + data-change requests waiting for your yes (manager/director)." path="/approvals" nav={nav} />
              <PageCard icon={<Briefcase size={18}/>}    title="Projects"       blurb="Won deals turned into deliverables with margin tracking." path="/projects" nav={nav} />
              <PageCard icon={<ShoppingCart size={18}/>} title="Purchasing"     blurb="PR → RFQ → Supplier PO → Goods Receipt → QC pipeline." path="/purchasing" nav={nav} />
              <PageCard icon={<Wrench size={18}/>}       title="Operation"      blurb="Work-order board: Receiving · Warehousing · QC · Packaging · Delivery." path="/operation" nav={nav} />
              <PageCard icon={<Banknote size={18}/>}     title="Finance"        blurb="AR Aging dashboard with 5 stacked buckets." path="/finance" nav={nav} />
              <PageCard icon={<Package size={18}/>}      title="Inventory"      blurb="Stock levels with low/out chips and one-click Request order." path="/inventory" nav={nav} />
              <PageCard icon={<Receipt size={18}/>}      title="Chart of Accounts" blurb="109 pre-seeded Indonesian accounts (admin/director only)." path="/accounts" nav={nav} />
              <PageCard icon={<Users size={18}/>}        title="Employees"      blurb="Directory + per-employee KPI page + tag management (HR/director)." path="/employees" nav={nav} />
              <PageCard icon={<Wallet size={18}/>}       title="Salary"         blurb="Monthly payroll that auto-posts to the ledger (director only)." path="/salary" nav={nav} />
              <PageCard icon={<BarChart3 size={18}/>}    title="KPI"            blurb="Per-department performance numbers." path="/kpi" nav={nav} />
              <PageCard icon={<Crown size={18}/>}        title="Executive"      blurb="Pipeline, won revenue, top customers (manager/director)." path="/executive" nav={nav} />
              <PageCard icon={<BrainCircuit size={18}/>} title="AI Command Center" blurb="At-risk deals, top priority actions, profit alerts, recommendations." path="/ai" nav={nav} accent />
            </div>
          </Section>

          {/* 4. Workflows */}
          <Section id="workflows" title="4. Common workflows" icon={<Sparkles size={20} />}>
            <Workflow
              title="A) Starting a new deal"
              steps={[
                "Click CRM → + New customer",
                "Fill company name, industry, PIC name, phone/WhatsApp, email",
                "You become the Sales PIC automatically (if you're sales)",
                "Open the customer → log a call / presentation / meeting activity",
                "Drag the card to the next stage on the Pipeline view as the deal progresses",
              ]}
            />
            <Workflow
              title="B) Sending a quotation"
              steps={[
                "Click + New quotation (from CRM, the customer page, or the Quotations page)",
                "Pick customer + add line items (description, qty, unit price)",
                "Adjust discount — the slider tells you live who has to approve",
                "Save as draft, then click Submit. The discount tier auto-routes for approval",
                "Once approved, send via WhatsApp or email; log a follow-up afterwards",
              ]}
            />
            <Workflow
              title="C) Marking a deal won (and the books update themselves)"
              steps={[
                "Open the quotation → Mark won",
                "A Project is auto-created with the same value",
                "Chart of Accounts auto-posts: Piutang Usaha ↑, Penjualan ↑, PPN Keluaran ↑, Diskon ↑",
                "Open Linked Accounts card to see exactly what posted; Reverse if needed",
              ]}
            />
            <Workflow
              title="D) Following up on a quote"
              steps={[
                "Open the quotation → Follow-ups card → Log follow-up",
                "Type notes (or click ✨ AI suggest for a draft message)",
                "Tick Schedule next follow-up → pick date + time + channel",
                "The reminder shows on the Calendar and in AI Top Priority Actions",
                "When it pings you, click Done on the reminder",
              ]}
            />
            <Workflow
              title="E) Checking if something's in stock"
              steps={[
                "Operations → Inventory",
                "Search the SKU or name",
                "Look at the status chip: 🟢 in stock, 🟡 low, 🔴 out",
                "Click Request order if low/out — creates a Purchase Request for you",
              ]}
            />
            <Workflow
              title="F) Approving a discount (Manager / Director)"
              steps={[
                "The Approvals nav item shows a count when waiting",
                "Open the request → review the discount and total",
                "Click Approve or Reject (with reason)",
                "The salesperson is notified; the quote moves forward",
              ]}
            />
          </Section>

          {/* 5. Role guide */}
          <Section id="roles" title="5. Role guide — at a glance" icon={<Users size={20} />}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ink-50">
                  <tr>
                    <th className="th text-left">Page</th>
                    {(["Sales","Admin","HR","Manager","Director"] as const).map((r) => (
                      <th key={r} className="th text-center">{r}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <Row page="Dashboard / CRM / Quotations / Calendar / Chat / KPI / AI Command" mask="11111" />
                  <Row page="Approvals" mask="00011" />
                  <Row page="Inventory (view)" mask="11111" />
                  <Row page="Inventory (edit)" mask="01001" />
                  <Row page="Chart of Accounts" mask="01001" />
                  <Row page="Employees + Tags" mask="00101" />
                  <Row page="Salary" mask="00001" />
                  <Row page="Executive Dashboard" mask="00011" />
                </tbody>
              </table>
            </div>
          </Section>

          {/* 6. Reference */}
          <Section id="reference" title="6. Quick reference" icon={<BookOpen size={20} />}>
            <h3 className="font-semibold mt-2 mb-1">Pipeline stages</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
              <Stage label="Lead" desc="Just heard of them; nothing real yet" />
              <Stage label="Presentation" desc="We've shown them what we make" />
              <Stage label="Engineering" desc="Our engineers are designing for them" />
              <Stage label="Quotation" desc="We sent a price offer" />
              <Stage label="Negotiation" desc="They're haggling" />
              <Stage label="PO" desc="They sent a Purchase Order — it's real" />
              <Stage label="Drawing" desc="Customer is approving the technical drawings" />
              <Stage label="Purchasing" desc="We're buying materials" />
              <Stage label="Delivery" desc="Shipping the goods" />
              <Stage label="Invoicing" desc="We sent the invoice" />
              <Stage label="Payment" desc="Waiting for the money" />
              <Stage label="Won / Lost" desc="Terminal outcome 🎉 / 😞" />
            </div>

            <h3 className="font-semibold mt-5 mb-1">Discount tier rules</h3>
            <div className="grid grid-cols-3 gap-2 text-sm">
              <Tier label="0 – 5%" who="Auto-approved" tone="emerald" />
              <Tier label="5 – 15%" who="Manager approval" tone="amber" />
              <Tier label="> 15%" who="Director approval" tone="red" />
            </div>

            <h3 className="font-semibold mt-5 mb-1">Number format</h3>
            <P>
              All money uses Indonesian convention: <code>1.234.567,89</code> (dots for
              thousands, comma for decimal). Negative balances render in <span className="text-red-600">red with parentheses</span> like <code className="text-red-600">(375.233.030,22)</code>. Zero shows as <code>0</code>.
            </P>
          </Section>

          {/* 7. Tips */}
          <Section id="tips" title="7. Tips & shortcuts" icon={<ArrowRight size={20} />}>
            <ul className="space-y-1.5 text-sm list-disc list-inside">
              <li><b>⌘K / Ctrl K</b> opens the search bar</li>
              <li>The <b>AI suggest</b> button is on every customer and quotation — use it</li>
              <li>The <b>WhatsApp button</b> opens <code>wa.me/&lt;number&gt;</code> in a new tab</li>
              <li><b>Double-click a Calendar day</b> to add a reminder for it</li>
              <li>Start every morning at <b>AI Command Center → Top Priority Actions</b></li>
              <li>Bookmark filtered list URLs — e.g. <code>/customers?stage=quotation</code></li>
              <li><b>Chart of Accounts</b> page is printable — File → Print or Cmd-P</li>
            </ul>
          </Section>

          {/* 8. Troubles */}
          <Section id="troubles" title="8. Troubleshooting" icon={<AlertCircle size={20} />}>
            <div className="space-y-2">
              <T q="I can't see Employees / Salary / Approvals" a="You don't have permission for that role. Ask the Director to grant it." />
              <T q="My quotation is stuck in Pending approval" a="Manager (or Director if >15%) needs to act. Ping them in Chat." />
              <T q="The customer card won't drag in Pipeline" a="Click and hold the card body (not the link text). Mobile drag is finicky — use Table view." />
              <T q="I see 'Invalid payload' on login" a="Password is wrong or has unexpected characters. Try again carefully." />
              <T q="WhatsApp button does nothing" a="The customer has no phone/WhatsApp number on file. Edit the customer first." />
              <T q="I deleted a chat message" a="Deletes are soft (shows '[deleted]') and not restorable. Send a new message instead." />
              <T q="I can't find my customer" a="Sales see only their own. If you think it's yours but missing, ask Admin who the Sales PIC is." />
            </div>
          </Section>
        </div>

        {/* TOC */}
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <div className="text-[11px] uppercase tracking-wider muted font-semibold mb-2 px-3">
              On this page
            </div>
            <nav className="space-y-0.5">
              {SECTIONS.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className={clsx(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
                    active === s.id
                      ? "bg-brand-50 text-brand-700 font-medium"
                      : "text-ink-600 hover:bg-ink-100"
                  )}
                >
                  <s.icon size={14} />
                  <span className="truncate">{s.label}</span>
                </a>
              ))}
            </nav>
          </div>
        </aside>
      </div>
    </div>
  );
}

// ─── tiny presentational helpers ────────────────────────────────────────────

function Section({ id, title, icon, children }: {
  id: string; title: string; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section id={id} className="card p-5 lg:p-6 scroll-mt-24">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight mb-3">
        <span className="text-brand-600">{icon}</span> {title}
      </h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}
function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-ink-700">{children}</p>;
}
function Tile({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-ink-100 bg-gradient-to-br from-white to-ink-50/40 p-3">
      <div className="text-2xl">{icon}</div>
      <div className="font-semibold text-sm mt-1">{title}</div>
      <div className="text-xs muted">{body}</div>
    </div>
  );
}
function PageCard({ icon, title, blurb, path, nav, accent }: {
  icon: React.ReactNode; title: string; blurb: string; path: string;
  nav: (path: string) => void; accent?: boolean;
}) {
  return (
    <button
      onClick={() => nav(path)}
      className={clsx(
        "text-left rounded-xl border p-3 transition-all flex items-start gap-3",
        accent
          ? "border-brand-200 bg-gradient-to-br from-brand-50/80 to-violet-50/80 hover:shadow-soft"
          : "border-ink-100 bg-white hover:border-brand-300 hover:shadow-soft"
      )}
    >
      <div className={clsx(
        "h-8 w-8 rounded-lg grid place-items-center shrink-0",
        accent ? "bg-gradient-to-br from-brand-500 to-brand-700 text-white" : "bg-ink-100 text-ink-700"
      )}>{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm">{title}</div>
        <div className="text-xs muted">{blurb}</div>
      </div>
      <ChevronRight size={14} className="text-ink-400 mt-1 shrink-0" />
    </button>
  );
}
function Workflow({ title, steps }: { title: string; steps: string[] }) {
  return (
    <div className="rounded-xl border border-ink-100 p-4 bg-white">
      <div className="font-semibold text-sm mb-2">{title}</div>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <span className="h-5 w-5 rounded-full bg-brand-50 text-brand-700 grid place-items-center text-[11px] font-semibold shrink-0 mt-0.5">
              {i + 1}
            </span>
            {s}
          </li>
        ))}
      </ol>
    </div>
  );
}
function Row({ page, mask }: { page: string; mask: string }) {
  // mask is "11011" — order: Sales, Admin, HR, Manager, Director
  return (
    <tr className="border-t border-ink-100">
      <td className="td">{page}</td>
      {mask.split("").map((b, i) => (
        <td key={i} className="td text-center">{b === "1" ? "✅" : <span className="text-ink-300">—</span>}</td>
      ))}
    </tr>
  );
}
function Stage({ label, desc }: { label: string; desc: string }) {
  return (
    <div className="rounded-lg bg-ink-50 border border-ink-100 px-3 py-1.5">
      <div className="font-semibold text-xs">{label}</div>
      <div className="text-[11px] muted">{desc}</div>
    </div>
  );
}
function Tier({ label, who, tone }: { label: string; who: string; tone: "emerald" | "amber" | "red" }) {
  const cls = {
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber:   "bg-amber-50 text-amber-700 ring-amber-200",
    red:     "bg-red-50 text-red-700 ring-red-200",
  }[tone];
  return (
    <div className={clsx("rounded-xl ring-1 p-3", cls)}>
      <div className="font-semibold">{label}</div>
      <div className="text-xs">{who}</div>
    </div>
  );
}
function T({ q, a }: { q: string; a: string }) {
  return (
    <details className="rounded-xl border border-ink-100 bg-white p-3 group">
      <summary className="font-medium text-sm cursor-pointer flex items-center justify-between">
        <span>{q}</span>
        <ChevronRight size={14} className="text-ink-400 group-open:rotate-90 transition-transform" />
      </summary>
      <p className="text-sm text-ink-600 mt-2">{a}</p>
    </details>
  );
}
function LayoutIcon() { return <Layout size={18} />; }
