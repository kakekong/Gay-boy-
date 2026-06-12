import { useState, useEffect } from "react";
import {
  Map, ChevronRight, User, ShoppingCart, HardHat, UserCog, BarChart3, Crown,
  Building2, Factory, BookOpen, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/auth";

type RoleKey =
  | "sales" | "purchasing" | "hr" | "admin" | "manager" | "director"
  | "customer" | "supplier";

interface Step {
  title: string;
  detail?: string;
}
interface ButtonRef {
  page: string;
  button: string;
  effect: string;
}
interface RoleSection {
  key: RoleKey;
  label: string;
  emoji: string;
  Icon: any;
  blurb: string;
  daily: string;
  flow: Step[];
  buttons: ButtonRef[];
  rules: string[];
}

const ROLES: RoleSection[] = [
  {
    key: "sales",
    label: "Sales",
    emoji: "👤",
    Icon: User,
    blurb: "You own customer relationships from first hello to deal won.",
    daily:
      "Every morning: clear the notifications bell, glance at the pipeline, " +
      "tick any overdue stage-checklist items. That's your 5-minute warm-up.",
    flow: [
      { title: "New inquiry comes in", detail: "WhatsApp, email, or referral" },
      { title: "+ New customer", detail: "3-step wizard: basics → PICs (WhatsApp/email/details) → tax info (NPWP/PKP)" },
      { title: "Tick first-contact + qualify-need", detail: "Stage checklist on the customer page" },
      { title: "Click 'Advance to Presentation'", detail: "→ amber banner: sent to director for approval. Once approved, send deck." },
      { title: "Click 'Advance to Quotation' (director approves)", detail: "Then open the customer → + New quotation. Pick the PIC it's addressed to." },
      { title: "Submit quotation → director approves", detail: "EVERY quotation now needs director sign-off in /approvals before it can be sent." },
      { title: "Mark deal Won", detail: "No project yet — the quote just flips to Won." },
      { title: "Customer sends their signed PO → Submit customer PO", detail: "On the quote's 'Next step' card: attach the PO file, pick which line items they actually ordered, set the PO number." },
      { title: "Director approves the customer PO → project is created", detail: "The project carries the PO number, date and value automatically." },
    ],
    buttons: [
      { page: "Customers", button: "+ New customer", effect: "3-step wizard (basics / PICs / tax)" },
      { page: "Customer page", button: "Advance to …", effect: "Request a stage move (director approves)" },
      { page: "Customer page", button: "Log activity", effect: "Record a call or WhatsApp" },
      { page: "Customer page", button: "AI suggest", effect: "Generate a Bahasa Indonesia follow-up" },
      { page: "Customer page", button: "Stage checklist circle", effect: "Tick required actions off" },
      { page: "Quotation page", button: "Submit", effect: "Send to director for approval (always)" },
      { page: "Quotation page (Won)", button: "Submit customer PO", effect: "File the customer's PO → director approval → project" },
      { page: "Customer PO", button: "(sidebar, Workspace)", effect: "Track the POs you've filed and their status" },
      { page: "Notifications bell", button: "Any item", effect: "Jump to whatever needs you" },
    ],
    rules: [
      "You can only edit customers assigned to you (sales PIC).",
      "EVERY quotation needs director approval before it leaves draft — there's no more discount-based auto-approve.",
      "A project is NOT created when you mark a quote Won. You file the customer's PO (with the PO file + ordered items), and the director's approval of that PO is what spawns the project.",
      "When the customer only orders some of the quoted items, untick the rest in the Submit-customer-PO modal and edit prices if they negotiated.",
      "Every stage move needs the director's approval — the customer stays on the old stage until they click Approve in /approvals.",
      "Overdue stage tasks light up the bell and the calendar in red.",
    ],
  },
  {
    key: "purchasing",
    label: "Purchasing",
    emoji: "📦",
    Icon: ShoppingCart,
    blurb:
      "You curate the vendor list. You don't create POs — that's the " +
      "director (keeps supplier ↔ customer mappings private).",
    daily:
      "When the director asks for a new supplier, add them. Keep ratings " +
      "and lead times accurate so the AI can recommend the best vendor.",
    flow: [
      { title: "Director needs a vendor", detail: "Asks you to add them" },
      { title: "Open Purchasing page" },
      { title: "+ New supplier", detail: "Name, category, initial rating, contact PIC" },
      { title: "Click a supplier row → supplier detail", detail: "See rating, lead time, QC fail %, and every PO issued to them" },
      { title: "Director issues the supplier PO", detail: "(out of your hands — director links supplier + project)" },
      { title: "Supplier portal lights up", detail: "Supplier uploads drawing, sets ETA" },
      { title: "Customer sees forecast instantly" },
    ],
    buttons: [
      { page: "Purchasing", button: "+ New supplier", effect: "Add a vendor" },
      { page: "Purchasing (supplier row)", button: "Click row", effect: "Open the supplier detail page + PO history" },
      { page: "Purchasing board", button: "Stage cards", effect: "PR / RFQ / GR / QC explain each procurement step; Supplier PO opens the PO list" },
    ],
    rules: [
      "You can see the supplier directory and each supplier's PO history, but only the director can issue a supplier PO.",
      "Keep rating + lead-time fresh; the AI vendor-picker uses both.",
    ],
  },
  {
    key: "hr",
    label: "HR",
    emoji: "🛠",
    Icon: HardHat,
    blurb: "Employee directory, tags, attendance, and feeding payroll.",
    daily:
      "Every day glance at the Attendance page to fix wrongly-marked absences. " +
      "On the 1st of the month, sweep for anyone with a red missed-days chip.",
    flow: [
      { title: "Day 1 of the month", detail: "Open Employees" },
      { title: "Anyone joined? → Admin → Users → New user" },
      { title: "Anyone left? → deactivate their account" },
      { title: "Daily: Attendance → spot wrong Absent marks → fix" },
      { title: "End of month: scan missed-days chips" },
      { title: "Tell the director who to deduct" },
    ],
    buttons: [
      { page: "Employees", button: "+ Manage tags", effect: "Create / rename labels" },
      { page: "Employee card", button: "(missed-days chip)", effect: "Quick attendance read" },
      { page: "Employee profile", button: "Attendance card → month picker", effect: "Pull any month" },
      { page: "Attendance", button: "+ Manual entry", effect: "Fix wrong clock-in / add leave" },
    ],
    rules: [
      "Yellow chip = 1–2 missed days; red chip = 3+. Red usually means a payroll conversation.",
      "Tags like 'Top performer' or 'Mining specialist' make filtering faster.",
    ],
  },
  {
    key: "admin",
    label: "Admin",
    emoji: "🧑‍💼",
    Icon: UserCog,
    blurb:
      "Data hygiene. You can edit any customer, but big changes route " +
      "through the manager for approval.",
    daily: "Maintain inventory counts and chart-of-accounts. Verify payment claims when they come in.",
    flow: [
      { title: "Open Customers → spot stale data" },
      { title: "Small fix?", detail: "Edit → auto-saves" },
      { title: "Big change?", detail: "Name, terms, owner → goes to Manager for approval" },
      { title: "Inventory → Adjust stock if needed" },
      { title: "Chart of Accounts → add new accounts as the business grows" },
      { title: "Payment verification → match received money to invoices" },
    ],
    buttons: [
      { page: "Customers", button: "(any field)", effect: "Small fixes save instantly, big ones request approval" },
      { page: "Inventory", button: "Adjust", effect: "Correct stock counts" },
      { page: "Chart of Accounts", button: "+ Add account", effect: "New ledger account" },
      { page: "Payment verification", button: "Verify / Reject", effect: "Settle a customer payment" },
    ],
    rules: [
      "You see all customers, but mutating 'important' fields creates an Approval Request.",
      "Adjusting stock writes an audit trail — corrections are visible to the director.",
    ],
  },
  {
    key: "manager",
    label: "Manager",
    emoji: "📊",
    Icon: BarChart3,
    blurb: "Unblock sales by reviewing approvals; watch team performance.",
    daily:
      "Open Approvals first thing in the morning. Then Executive Dashboard — " +
      "ping anyone whose deal looks stuck.",
    flow: [
      { title: "Open Approvals page" },
      { title: "Any pending? Read each request" },
      { title: "Looks right → Approve", detail: "Looks off → Reject with reason" },
      { title: "Open Executive Dashboard" },
      { title: "At-Risk Deals → ping the sales person" },
      { title: "Top Priority Actions → assign" },
    ],
    buttons: [
      { page: "Approvals", button: "Approve / Reject", effect: "Unblock or reject a sales request" },
      { page: "Executive Dashboard", button: "(at-risk row)", effect: "Jump to the slipping deal" },
      { page: "Sales Targets", button: "+ New target", effect: "Set monthly quotas" },
      { page: "Employees", button: "(sales person)", effect: "See KPIs and won revenue" },
    ],
    rules: [
      "You approve 'data change' requests from admins. Quotations now route to the director, not you.",
      "Stage transitions (lead → presentation → … → won), quotations, and customer POs all go to the director, not you — your own stage moves on customers also go through the director.",
      "Anything bigger waits for the director.",
    ],
  },
  {
    key: "director",
    label: "Director",
    emoji: "👑",
    Icon: Crown,
    blurb:
      "The biggest hat. You see everything, sign off on financial moves, " +
      "and own the supplier ⇄ customer link.",
    daily: "Morning: Approvals (quotations + customer POs + stage moves). Monday: Executive Dashboard + AI Recommendations. End of month: Salary.",
    flow: [
      { title: "Open Approvals first", detail: "Quotations, customer POs, stage-move requests — green-light or reject. Approving a quotation lets sales send it." },
      { title: "Approve a customer PO → project is created", detail: "The project carries the customer's PO number, date and ordered items. This is the ONLY way projects are made now." },
      { title: "Executive Dashboard", detail: "Read the AI recommendations" },
      { title: "Project needs material → Purchasing → + New PO", detail: "Link a supplier + project. Non-directors who file a supplier PO need your approval too." },
      { title: "Track everything on PO Recap", detail: "Customer POs + supplier POs in one view, with who's in charge of each." },
      { title: "Supplier portal lights up automatically", detail: "Supplier uploads drawing + sets warehouse ETA" },
      { title: "Drive work on the Operation board", detail: "Each stage (Receiving → … → Delivery) is its own screen; mark work orders Done / Advance them." },
      { title: "End of month: Salary → generate → post → mark paid" },
    ],
    buttons: [
      { page: "Approvals", button: "Approve / Reject", effect: "Sign off on every quotation, customer PO, supplier PO, stage move + data change" },
      { page: "Customer PO (Workspace)", button: "Row / detail", effect: "See every incoming customer PO + the project it spawned" },
      { page: "Purchasing PO (Workspace)", button: "+ New PO", effect: "Issue a supplier PO (link supplier + project)" },
      { page: "PO Recap (Workspace)", button: "Tabs + search", effect: "All POs in one place, with the person in charge" },
      { page: "Operation board", button: "Stage card", effect: "Open a stage's work-order list; mark Done / Advance" },
      { page: "Purchasing (supplier row)", button: "Click row", effect: "Supplier detail + full PO history" },
      { page: "All files", button: "Search / filter / download", effect: "Audit every upload in the system" },
      { page: "Salary", button: "Post to ledger / Mark paid", effect: "Finalize payroll" },
      { page: "Admin → Users", button: "+ New user", effect: "Create any account, any role" },
    ],
    rules: [
      "EVERY quotation needs your approval before sales can send it — no auto-approve on small discounts anymore.",
      "A customer PO is the gate to project creation: approving it is what spawns the project (carrying the PO number / date / value).",
      "Only YOU can issue a supplier PO and decide which supplier serves which project — keeps the customer ↔ supplier mapping private. Non-directors can request one, but it waits for your approval.",
      "Only YOU can approve a CRM stage transition. Every 'Advance to …' from sales/manager/admin queues up in Approvals.",
      "PO Recap is director-only — the company-wide view of customer + supplier POs.",
      "Mark-paid + post-to-ledger feel irreversible — reverse uses a matching reversal entry, not a hard delete.",
    ],
  },
  {
    key: "customer",
    label: "Customer (portal)",
    emoji: "🏢",
    Icon: Building2,
    blurb:
      "What your CUSTOMER sees when they log in. Stripped down — no sidebar, " +
      "no internal data, only their own deals.",
    daily: "Log in, see status of their order, approve drawings, claim payments.",
    flow: [
      { title: "Log in at /portal" },
      { title: "See own quotations + projects + invoices" },
      { title: "Drawing waiting? → Approve or Reject" },
      { title: "Shipping timeline shows Origin → Our warehouse → Their site", detail: "Forecast dates show amber, actuals green" },
      { title: "Already paid? → 'I paid this' modal → upload proof" },
      { title: "Finance verifies → invoice marked paid" },
    ],
    buttons: [
      { page: "Customer portal", button: "Approve / Reject drawing", effect: "Sign off on supplier drawings" },
      { page: "Customer portal", button: "I paid this", effect: "Submit a payment claim with proof" },
    ],
    rules: [
      "They never see your suppliers, costs, other customers, employees, chat, or AI.",
      "Only their own deals.",
    ],
  },
  {
    key: "supplier",
    label: "Supplier (portal)",
    emoji: "🏭",
    Icon: Factory,
    blurb:
      "What a VENDOR sees when they log in. Equally stripped — only POs " +
      "assigned to them.",
    daily: "Open the portal, fill in the warehouse ETA, upload the drawing PDF.",
    flow: [
      { title: "Open the portal → see PO assigned to me" },
      { title: "Upload drawing PDF → customer sees it for approval" },
      { title: "Type estimated arrival at our warehouse → Save dates" },
      { title: "Customer's timeline updates instantly", detail: "No internal step needed" },
      { title: "Update actual ship date as goods leave" },
      { title: "Update actual arrival date as goods arrive" },
    ],
    buttons: [
      { page: "Supplier portal", button: "Upload (Drawing)", effect: "Mirror to project drawings for customer approval" },
      { page: "Supplier portal", button: "Save dates", effect: "Warehouse ETA + ship dates flow to customer" },
    ],
    rules: [
      "Just the estimate is enough — don't wait for actual arrival to communicate the forecast.",
      "They never see other suppliers, your pricing, your other vendors, or your employees.",
    ],
  },
];

const TROUBLES: { problem: string; answer: string }[] = [
  { problem: "Can't log in", answer: "The Director can reset any password (Admin → Users)." },
  { problem: "Discount blocked", answer: "Up to 15% → Manager. Above 15% → Director." },
  { problem: "Stage move stuck on amber 'awaiting approval'", answer: "Ping the Director — every stage transition needs their sign-off in Approvals." },
  { problem: "Where is the file I uploaded?", answer: "Director: open 'All files' in the sidebar, search by filename or filter by owner type." },
  { problem: "Customer asking when goods arrive", answer: "The supplier's ETA in the shipping timeline answers this; if it's stale, ping the supplier." },
  { problem: "Payment claim stuck", answer: "Admin or Director → Finance → Payment verification." },
  { problem: "Attendance wrong", answer: "HR → Attendance → Manual entry — they can fix any record." },
  { problem: "Don't know which button to press", answer: "Open Help in the sidebar — full page-by-page walkthrough." },
];

export default function RoleGuidePage() {
  const me = useAuthStore((s) => s.user);
  // Default to the logged-in user's role if it's in our list, else director
  const initial = (ROLES.find((r) => r.key === me?.role)?.key ?? "director") as RoleKey;
  const [active, setActive] = useState<RoleKey>(initial);

  useEffect(() => {
    const r = ROLES.find((r) => r.key === me?.role);
    if (r) setActive(r.key);
  }, [me?.role]);

  const section = ROLES.find((r) => r.key === active) ?? ROLES[0];

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Map size={22} className="text-brand-600" /> Role guide
          </h1>
          <p className="text-sm muted">
            Pick your role. Get your daily workflow, the buttons you'll touch,
            and the rules. {me?.role && (
              <span>You're logged in as <b className="text-ink-900 capitalize">{me.role}</b>.</span>
            )}
          </p>
        </div>
      </div>

      {/* Role tabs */}
      <div className="card p-1 flex flex-wrap gap-1">
        {ROLES.map((r) => {
          const Icon = r.Icon;
          const isMe = me?.role === r.key;
          return (
            <button
              key={r.key}
              onClick={() => setActive(r.key)}
              className={clsx(
                "px-3 py-1.5 rounded-md text-sm font-medium inline-flex items-center gap-1.5",
                active === r.key
                  ? "bg-brand-600 text-white shadow-sm"
                  : "text-ink-600 hover:bg-ink-100",
              )}
            >
              <Icon size={14} />
              <span>{r.label}</span>
              {isMe && (
                <span className={clsx(
                  "text-[9px] uppercase font-bold tracking-widest px-1.5 py-0.5 rounded",
                  active === r.key ? "bg-white/20" : "bg-brand-50 text-brand-700",
                )}>You</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Header card */}
      <div className="card p-5 lg:p-6 bg-gradient-to-br from-brand-600 to-brand-700 text-white">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-white/15 backdrop-blur grid place-items-center text-2xl shrink-0">
            {section.emoji}
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-widest text-white/70">Role</div>
            <h2 className="text-2xl font-semibold mt-0.5">{section.label}</h2>
            <p className="text-white/90 mt-2 text-sm">{section.blurb}</p>
          </div>
        </div>
      </div>

      {/* Daily snapshot */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-1">
          🌞 Your daily rhythm
        </div>
        <p className="text-sm text-ink-700">{section.daily}</p>
      </div>

      {/* Flow */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-3">
          <ChevronRight size={15} className="text-brand-600" /> Your workflow, step by step
        </div>
        <ol className="space-y-2">
          {section.flow.map((s, i) => (
            <li key={i} className="flex items-start gap-3 rounded-lg border border-ink-200 bg-white p-3">
              <div className="h-7 w-7 rounded-full bg-brand-100 text-brand-700 font-semibold text-sm grid place-items-center shrink-0">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{s.title}</div>
                {s.detail && (
                  <div className="text-xs muted mt-0.5">{s.detail}</div>
                )}
              </div>
              {i < section.flow.length - 1 && (
                <ChevronRight size={14} className="text-ink-300 self-center hidden sm:block" />
              )}
            </li>
          ))}
        </ol>
      </div>

      {/* Buttons reference */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <BookOpen size={15} className="text-brand-600" /> Buttons you'll touch
          </div>
          <div className="text-xs muted">Quick reference card — print this if you like.</div>
        </header>
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Page</th>
              <th className="th">Button</th>
              <th className="th">What it does</th>
            </tr>
          </thead>
          <tbody>
            {section.buttons.map((b, i) => (
              <tr key={i} className="border-t border-ink-100">
                <td className="td muted">{b.page}</td>
                <td className="td font-medium">{b.button}</td>
                <td className="td">{b.effect}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Rules */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-2">
          <AlertCircle size={15} className="text-amber-600" /> Rules to remember
        </div>
        <ul className="space-y-1.5 text-sm">
          {section.rules.map((r, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="text-ink-400 mt-1">•</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* How it all fits together (always visible) */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-3">
          🔄 How everyone's work connects
        </div>
        <SystemFlow />
      </div>

      {/* Troubleshooting */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-2">
          🆘 When something goes wrong
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {TROUBLES.map((t, i) => (
            <div key={i} className="rounded-lg border border-ink-200 p-3 bg-white">
              <div className="text-xs uppercase tracking-wider muted">{t.problem}</div>
              <div className="text-sm mt-0.5">{t.answer}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SystemFlow() {
  // Pure CSS / flexbox depiction of the cross-role flow
  const lane = (emoji: string, label: string, items: string[], colour: string) => (
    <div className={clsx(
      "flex-1 min-w-[140px] rounded-xl border p-3 bg-white",
      colour,
    )}>
      <div className="text-2xl">{emoji}</div>
      <div className="font-semibold mt-1 text-sm">{label}</div>
      <ul className="mt-2 space-y-1 text-xs text-ink-600">
        {items.map((it, i) => <li key={i}>· {it}</li>)}
      </ul>
    </div>
  );

  const arrow = (
    <div className="self-center text-ink-300 hidden lg:block">
      <ChevronRight size={18} />
    </div>
  );

  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
      {lane("🏢", "Customer", ["sends inquiry", "approves drawings", "pays invoices"], "border-cyan-200")}
      {arrow}
      {lane("👤", "Sales", ["adds customer", "builds quote", "files customer PO"], "border-brand-200")}
      {arrow}
      {lane("📊", "Manager", ["reviews data changes", "watches at-risk deals"], "border-emerald-200")}
      {arrow}
      {lane("👑", "Director", ["approves quotes + customer POs", "customer PO → creates project", "issues supplier PO"], "border-red-200")}
      {arrow}
      {lane("🏭", "Supplier", ["uploads drawing", "sets warehouse ETA"], "border-teal-200")}
      {arrow}
      {lane("🛠", "HR / Finance", ["attendance", "payroll", "verify payments"], "border-amber-200")}
    </div>
  );
}
