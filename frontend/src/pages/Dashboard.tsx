import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Users, FileText, Banknote, Wallet, ArrowUpRight, Sparkles, Target,
  ListTodo, Send, Clock, BellRing, Trophy,
} from "lucide-react";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";
import { StageBadge } from "@/components/StageBadge";
import { useAuthStore } from "@/store/auth";

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const sales = useQuery({
    queryKey: ["kpi-sales"],
    queryFn: () => api.get("/kpi/sales").then((r) => r.data),
  });
  const fin = useQuery({
    queryKey: ["kpi-finance"],
    queryFn: () => api.get("/kpi/finance").then((r) => r.data),
  });
  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get("/customers").then((r) => r.data),
  });
  const myTarget = useQuery({
    queryKey: ["my-target"],
    queryFn: () => api.get("/sales-targets/me/current").then((r) => r.data),
    enabled: user?.role === "sales",
  });

  const idr = (n: number) =>
    "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const pct = (n: number) => `${Math.round((n ?? 0) * 100)}%`;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="muted text-sm">Welcome back, {user?.full_name?.split(" ")[0]}</p>
          <h1 className="text-2xl font-semibold tracking-tight">Today's overview</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/ai" className="btn-ghost">
            <Sparkles size={15} /> AI Command Center
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          label="New leads (30d)"
          value={sales.data?.new_leads ?? "—"}
          icon={Users}
          accent="brand"
          delta={{ value: "+12%", trend: "up" }}
        />
        <KpiCard
          label="Quote → Win"
          value={sales.data ? pct(sales.data.quote_to_win_rate) : "—"}
          icon={FileText}
          accent="violet"
          hint="last 30 days"
        />
        <KpiCard
          label="Outstanding AR"
          value={fin.data ? idr(fin.data.outstanding) : "—"}
          icon={Wallet}
          accent="amber"
          hint="open invoices"
        />
        <KpiCard
          label="Collected"
          value={fin.data ? idr(fin.data.collected) : "—"}
          icon={Banknote}
          accent="emerald"
          delta={{ value: "+4%", trend: "up" }}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="section-title">Active customers</div>
              <p className="text-sm muted">Latest by stage.</p>
            </div>
            <Link to="/customers" className="text-sm text-brand-700 hover:underline inline-flex items-center gap-1">
              View all <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="overflow-x-auto -mx-5">
            <table className="w-full">
              <thead>
                <tr className="border-y border-ink-100">
                  <th className="th">Company</th>
                  <th className="th">Industry</th>
                  <th className="th">PIC</th>
                  <th className="th">Stage</th>
                </tr>
              </thead>
              <tbody>
                {(customers.data?.data ?? []).slice(0, 6).map((c: any) => (
                  <tr key={c.id} className="tr-hover border-b border-ink-100">
                    <td className="td font-medium">
                      <Link to={`/customers/${c.id}`} className="hover:text-brand-700">
                        {c.company_name}
                      </Link>
                    </td>
                    <td className="td capitalize muted">{c.industry}</td>
                    <td className="td muted">{c.pic_name ?? "—"}</td>
                    <td className="td"><StageBadge stage={c.stage} /></td>
                  </tr>
                ))}
                {!customers.data?.data?.length && (
                  <tr>
                    <td colSpan={4} className="td text-center muted py-12">
                      No customers yet — start by adding one.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
        {user?.role === "sales" && <MyQueueCard />}
        {user?.role === "sales" && myTarget.data && (
          <div className="card p-5">
            <div className="flex items-start gap-3 mb-2">
              <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-white">
                <Target size={18} />
              </div>
              <div>
                <div className="section-title">Your monthly target</div>
                <p className="text-sm muted">{myTarget.data.period}</p>
              </div>
            </div>
            {myTarget.data.no_target ? (
              <div className="text-sm muted">
                No target set this month yet. Achieved so far:{" "}
                <b className="tabular-nums">{idr(myTarget.data.achieved_amount)}</b>
              </div>
            ) : (
              <>
                <div className="text-2xl font-semibold tabular-nums">
                  {idr(myTarget.data.achieved_amount)} <span className="text-base muted">/ {idr(myTarget.data.target_amount)}</span>
                </div>
                <div className="mt-2 h-2 rounded-full bg-ink-100 overflow-hidden">
                  <div
                    className={clsx(
                      "h-full transition-all",
                      myTarget.data.progress_pct >= 100 ? "bg-gradient-to-r from-emerald-500 to-emerald-300"
                      : myTarget.data.progress_pct >= 70 ? "bg-emerald-500"
                      : myTarget.data.progress_pct >= 40 ? "bg-amber-500"
                      : "bg-red-500"
                    )}
                    style={{ width: `${Math.min(100, myTarget.data.progress_pct)}%` }}
                  />
                </div>
                <div className="mt-2 text-xs muted">
                  <b>{Math.round(myTarget.data.progress_pct)}%</b> · {idr(myTarget.data.remaining)} to go
                </div>
              </>
            )}
          </div>
        )}

        <div className="card p-5">
          <div className="flex items-start gap-3 mb-3">
            <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white">
              <Sparkles size={18} />
            </div>
            <div>
              <div className="section-title">AI tip of the day</div>
              <p className="text-sm muted">From your Command Center.</p>
            </div>
          </div>
          <div className="rounded-xl bg-gradient-to-br from-brand-50 to-violet-50 p-4 text-sm text-ink-700">
            Three deals haven't been touched in the last 7 days. Open the AI
            Command Center to see who needs a follow-up — and a suggested
            WhatsApp message.
          </div>
          <Link
            to="/ai"
            className="btn-primary w-full mt-4"
          >
            Open AI Command Center <ArrowUpRight size={14} />
          </Link>
        </div>
        </div>
      </div>
    </div>
  );
}

interface QueueItem {
  id: string;
  number: string;
  customer_name: string | null;
  total: number;
  status: string;
}
interface ReminderDue {
  id: string;
  kind: string;
  due_at: string;
  message: string | null;
  customer_id: string | null;
  customer_name: string | null;
}
interface MyQueue {
  drafts: QueueItem[];
  pending_approval: QueueItem[];
  approved: QueueItem[];
  reminders_due: ReminderDue[];
  counts: {
    drafts: number;
    pending_approval: number;
    approved: number;
    reminders_due: number;
  };
}

function MyQueueCard() {
  const q = useQuery({
    queryKey: ["my-queue"],
    queryFn: () => api.get("/dashboard/my-queue").then((r) => r.data as MyQueue),
    refetchInterval: 60_000,
  });
  const idr = (n: number) =>
    "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

  const c = q.data?.counts;
  const totalOpen =
    (c?.drafts ?? 0) + (c?.approved ?? 0) + (c?.reminders_due ?? 0);

  return (
    <div className="card p-5">
      <div className="flex items-start gap-3 mb-3">
        <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white">
          <ListTodo size={18} />
        </div>
        <div className="flex-1">
          <div className="section-title">My queue</div>
          <p className="text-sm muted">
            {q.isLoading
              ? "Loading…"
              : totalOpen === 0
                ? "All caught up 🎉"
                : `${totalOpen} item${totalOpen === 1 ? "" : "s"} need your attention`}
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <QueueBucket
          icon={<BellRing size={14} className="text-red-600" />}
          label="Follow-ups due"
          count={c?.reminders_due ?? 0}
          tone="red"
        >
          {(q.data?.reminders_due ?? []).map((r) => (
            <Link
              key={r.id}
              to={r.customer_id ? `/customers/${r.customer_id}` : "/calendar"}
              className="flex items-center justify-between gap-2 text-sm py-1 hover:text-brand-700"
            >
              <span className="truncate">
                {r.customer_name ?? r.kind}
                {r.message ? <span className="muted"> · {r.message}</span> : null}
              </span>
              <span className="text-[11px] text-red-600 shrink-0 inline-flex items-center gap-1">
                <Clock size={11} />
                {new Date(r.due_at).toLocaleDateString()}
              </span>
            </Link>
          ))}
        </QueueBucket>

        <QueueBucket
          icon={<Send size={14} className="text-amber-600" />}
          label="Drafts to submit"
          count={c?.drafts ?? 0}
          tone="amber"
        >
          {(q.data?.drafts ?? []).map((d) => (
            <QuoteLine key={d.id} item={d} idr={idr} />
          ))}
        </QueueBucket>

        <QueueBucket
          icon={<Trophy size={14} className="text-emerald-600" />}
          label="Approved · chase to Won"
          count={c?.approved ?? 0}
          tone="emerald"
        >
          {(q.data?.approved ?? []).map((d) => (
            <QuoteLine key={d.id} item={d} idr={idr} />
          ))}
        </QueueBucket>

        {(c?.pending_approval ?? 0) > 0 && (
          <div className="text-xs muted flex items-center gap-1.5 pt-1">
            <Clock size={12} />
            {c?.pending_approval} awaiting approval
          </div>
        )}
      </div>

      <Link to="/quotations" className="btn-ghost w-full mt-4">
        Open quotations <ArrowUpRight size={14} />
      </Link>
    </div>
  );
}

function QueueBucket({
  icon, label, count, tone, children,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  tone: "red" | "amber" | "emerald";
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  const ring = {
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-sm font-medium">{label}</span>
        <span className={clsx("chip ml-auto", ring)}>{count}</span>
      </div>
      <div className="pl-6 divide-y divide-ink-100">{children}</div>
    </div>
  );
}

function QuoteLine({ item, idr }: { item: QueueItem; idr: (n: number) => string }) {
  return (
    <Link
      to={`/quotations/${item.id}`}
      className="flex items-center justify-between gap-2 text-sm py-1 hover:text-brand-700"
    >
      <span className="truncate">
        <span className="font-mono text-xs">{item.number}</span>
        {item.customer_name ? <span className="muted"> · {item.customer_name}</span> : null}
      </span>
      <span className="tabular-nums text-xs shrink-0">{idr(item.total)}</span>
    </Link>
  );
}
