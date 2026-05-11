import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Mail, Phone, Briefcase, FileText, Users, Trophy, Frown,
  Wallet, TrendingUp, Activity as ActivityIcon,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";
import { StageBadge } from "@/components/StageBadge";

const ROLE_CHIP: Record<string, string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
};

const QSTATUS: Record<string, string> = {
  draft:             "bg-ink-100 text-ink-700",
  pending_approval:  "bg-amber-50 text-amber-700",
  approved:          "bg-emerald-50 text-emerald-700",
  rejected:          "bg-red-50 text-red-700",
  sent:              "bg-blue-50 text-blue-700",
  won:               "bg-emerald-100 text-emerald-800",
  lost:              "bg-red-100 text-red-800",
};

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function EmployeeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();

  const employee = useQuery({
    queryKey: ["employee", id],
    queryFn: () => api.get(`/users/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const stats = useQuery({
    queryKey: ["employee-stats", id],
    queryFn: () => api.get(`/users/${id}/stats`).then((r) => r.data),
    enabled: !!id,
  });
  const quotations = useQuery({
    queryKey: ["employee-quotations", id],
    queryFn: () => api.get(`/users/${id}/quotations`).then((r) => r.data),
    enabled: !!id,
  });
  const customers = useQuery({
    queryKey: ["employee-customers", id],
    queryFn: () => api.get(`/users/${id}/customers`).then((r) => r.data),
    enabled: !!id,
  });
  const activities = useQuery({
    queryKey: ["employee-activities", id],
    queryFn: () => api.get(`/users/${id}/activities`).then((r) => r.data),
    enabled: !!id,
  });

  const e = employee.data;
  if (!e) return <div className="muted">Loading…</div>;

  const isSales = e.role === "sales";

  return (
    <div className="space-y-6">
      <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
        <ArrowLeft size={15} /> Back
      </button>

      {/* Header */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div className="h-14 w-14 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white flex items-center justify-center text-xl font-semibold">
              {(e.full_name ?? "U").slice(0, 1).toUpperCase()}
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{e.full_name}</h1>
              <div className="text-sm muted flex items-center gap-2 mt-1">
                <Briefcase size={14} />
                <span className={clsx("chip uppercase", ROLE_CHIP[e.role] ?? "bg-ink-100 text-ink-700")}>
                  {e.role}
                </span>
                {!e.is_active && <span className="chip bg-ink-100 text-ink-600">inactive</span>}
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 text-sm">
          <Field icon={<Mail size={14} />} label="Email">{e.email}</Field>
          <Field icon={<Phone size={14} />} label="Phone">{e.phone ?? "—"}</Field>
          <Field icon={<Briefcase size={14} />} label="Status">
            {e.is_active ? "Active" : "Inactive"}
          </Field>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Customers"     value={stats.data?.customers ?? "—"}      icon={Users}       accent="brand" />
        <KpiCard label="Quotations"    value={stats.data?.quotations ?? "—"}     icon={FileText}    accent="violet" />
        <KpiCard label="Won"           value={stats.data?.won ?? "—"}            icon={Trophy}      accent="emerald" />
        <KpiCard label="Lost"          value={stats.data?.lost ?? "—"}           icon={Frown}       accent="red" />
        <KpiCard
          label="Win rate"
          value={stats.data ? `${Math.round((stats.data.win_rate ?? 0) * 100)}%` : "—"}
          icon={TrendingUp} accent="amber"
        />
        <KpiCard
          label="Won revenue"
          value={stats.data ? idr(stats.data.won_revenue) : "—"}
          icon={Wallet} accent="emerald"
        />
      </div>

      {isSales && (
        <KpiCard
          label="Pipeline value (open quotations)"
          value={stats.data ? idr(stats.data.pipeline_value) : "—"}
          icon={TrendingUp}
          accent="brand"
        />
      )}

      {/* Quotations */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
          <div>
            <div className="font-semibold flex items-center gap-2">
              <FileText size={15} /> Quotations
            </div>
            <div className="text-xs muted">
              {(quotations.data ?? []).length} document(s) authored by {e.full_name}
            </div>
          </div>
        </div>
        {(quotations.data ?? []).length === 0 ? (
          <div className="p-8 text-center muted text-sm">No quotations.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Number</th>
                  <th className="th">Customer</th>
                  <th className="th">Variant</th>
                  <th className="th">Status</th>
                  <th className="th text-right">Discount</th>
                  <th className="th text-right">Total</th>
                  <th className="th">Created</th>
                </tr>
              </thead>
              <tbody>
                {(quotations.data ?? []).map((q: any) => (
                  <tr
                    key={q.id}
                    className="tr-hover border-t border-ink-100 cursor-pointer"
                    onClick={() => nav(`/quotations/${q.id}`)}
                  >
                    <td className="td">
                      <Link
                        to={`/quotations/${q.id}`}
                        onClick={(ev) => ev.stopPropagation()}
                        className="font-mono text-xs text-brand-700 hover:underline"
                      >
                        {q.number}
                      </Link>
                    </td>
                    <td className="td">
                      <Link
                        to={`/customers/${q.customer_id}`}
                        onClick={(ev) => ev.stopPropagation()}
                        className="hover:text-brand-700"
                      >
                        {q.customer_name}
                      </Link>
                    </td>
                    <td className="td capitalize muted">{q.variant}</td>
                    <td className="td">
                      <span className={clsx("chip", QSTATUS[q.status] ?? "bg-ink-100 text-ink-600")}>
                        {q.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="td text-right tabular-nums">{q.discount_pct}%</td>
                    <td className="td text-right font-medium tabular-nums">{idr(q.total)}</td>
                    <td className="td muted">{q.created_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Customers */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Users size={15} /> Assigned customers
          </div>
          <div className="text-xs muted">
            {(customers.data ?? []).length} customer(s)
          </div>
        </div>
        {(customers.data ?? []).length === 0 ? (
          <div className="p-8 text-center muted text-sm">No assigned customers.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Company</th>
                <th className="th">Industry</th>
                <th className="th">Stage</th>
                <th className="th text-right">Lifetime value</th>
              </tr>
            </thead>
            <tbody>
              {(customers.data ?? []).map((c: any) => (
                <tr
                  key={c.id}
                  className="tr-hover border-t border-ink-100 cursor-pointer"
                  onClick={() => nav(`/customers/${c.id}`)}
                >
                  <td className="td font-medium">
                    <Link
                      to={`/customers/${c.id}`}
                      onClick={(ev) => ev.stopPropagation()}
                      className="hover:text-brand-700"
                    >
                      {c.company_name}
                    </Link>
                  </td>
                  <td className="td capitalize muted">{c.industry}</td>
                  <td className="td"><StageBadge stage={c.stage} /></td>
                  <td className="td text-right tabular-nums">{idr(c.lifetime_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Activity */}
      <div className="card p-5">
        <div className="flex items-center gap-2 font-semibold">
          <ActivityIcon size={15} /> Recent activity
        </div>
        <div className="text-xs muted mb-3">
          Last {activities.data?.length ?? 0} interactions logged by {e.full_name}.
        </div>
        {(activities.data ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-ink-200 p-8 text-center text-sm muted">
            No activity logged.
          </div>
        ) : (
          <ul className="space-y-2">
            {(activities.data ?? []).map((a: any) => (
              <li key={a.id} className="flex gap-3 border-b border-ink-100 last:border-b-0 py-2">
                <div className="h-8 w-8 rounded-full bg-brand-50 text-brand-700 grid place-items-center text-xs shrink-0">
                  {a.type.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1">
                  <div className="text-sm capitalize">
                    <b>{a.type.replace(/_/g, " ")}</b>{" "}
                    <span className="muted">· {a.direction}</span>{" "}
                    <span className="muted">·</span>{" "}
                    <Link to={`/customers/${a.customer_id}`} className="text-brand-700 hover:underline">
                      {a.customer_name}
                    </Link>
                  </div>
                  {a.notes && <div className="text-xs muted mt-0.5">{a.notes}</div>}
                  <div className="text-[11px] text-ink-400 mt-0.5">
                    {new Date(a.occurred_at).toLocaleString()}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Field({ icon, label, children }: {
  icon: React.ReactNode; label: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}
