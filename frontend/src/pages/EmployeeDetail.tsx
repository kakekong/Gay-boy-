import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Mail, Phone, Briefcase, FileText, Users, Trophy, Frown,
  Wallet, TrendingUp, Activity as ActivityIcon, Tags, CalendarCheck, Clock,
  CalendarX,
} from "lucide-react";
import { useState } from "react";
import clsx from "clsx";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";
import { EmployeeDocsSection } from "@/components/EmployeeDocsSection";
import { StageBadge } from "@/components/StageBadge";
import { TagChip } from "@/components/TagChip";
import { TagPicker } from "@/components/TagPicker";
import { useAuthStore } from "@/store/auth";

const ROLE_CHIP: Record<string, string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
};

const ATT_CHIP: Record<string, string> = {
  present:  "bg-emerald-50 text-emerald-700",
  wfh:      "bg-emerald-50 text-emerald-700",
  half_day: "bg-amber-50 text-amber-700",
  leave:    "bg-blue-50 text-blue-700",
  sick:     "bg-blue-50 text-blue-700",
  absent:   "bg-red-50 text-red-700",
  holiday:  "bg-ink-100 text-ink-700",
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
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const canTag = me && (me.role === "hr" || me.role === "director");
  const canSeeAttendance = me && (me.role === "hr" || me.role === "director");
  // HR administers people but must not see personal contact info, sales
  // performance, customers, or money — only attendance + fulfillment counts.
  const canSeeContact = me?.role !== "hr";
  const isHR = me?.role === "hr";

  const today = new Date();
  const defaultPeriod = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [period, setPeriod] = useState(defaultPeriod);

  const employee = useQuery({
    queryKey: ["employee", id],
    queryFn: () => api.get(`/users/${id}`).then((r) => r.data),
    enabled: !!id,
  });

  const userTags = useQuery({
    queryKey: ["user-tags", id],
    queryFn: () => api.get(`/tags/users/${id}`).then((r) => r.data as any[]),
    enabled: !!id && !!canTag,
  });

  const detach = useMutation({
    mutationFn: (tagId: string) => api.delete(`/tags/users/${id}/${tagId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-tags", id] });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e: any) => alert(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? "Failed to remove tag"
    ),
  });
  const stats = useQuery({
    queryKey: ["employee-stats", id],
    queryFn: () => api.get(`/users/${id}/stats`).then((r) => r.data),
    enabled: !!id,
  });
  const quotations = useQuery({
    queryKey: ["employee-quotations", id],
    queryFn: () => api.get(`/users/${id}/quotations`).then((r) => r.data),
    enabled: !!id && !isHR,
  });
  const customers = useQuery({
    queryKey: ["employee-customers", id],
    queryFn: () => api.get(`/users/${id}/customers`).then((r) => r.data),
    enabled: !!id && !isHR,
  });
  const projects = useQuery({
    queryKey: ["employee-projects", id],
    queryFn: () => api.get(`/users/${id}/projects`).then((r) => r.data as any[]),
    enabled: !!id && !isHR,
  });
  const activities = useQuery({
    queryKey: ["employee-activities", id],
    queryFn: () => api.get(`/users/${id}/activities`).then((r) => r.data),
    enabled: !!id && !isHR,
  });

  const attendanceSummary = useQuery({
    queryKey: ["employee-attendance-summary", id, period],
    queryFn: () => api.get("/attendance/summary", { params: { user_id: id, period } })
      .then((r) => r.data),
    enabled: !!id && !!canSeeAttendance,
    retry: false,
  });
  const attendanceRows = useQuery({
    queryKey: ["employee-attendance-rows", id, period],
    queryFn: () => api.get("/attendance", { params: { user_id: id, period } })
      .then((r) => r.data as any[]),
    enabled: !!id && !!canSeeAttendance,
    retry: false,
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
          {canSeeContact ? (
            <>
              <Field icon={<Mail size={14} />} label="Email">{e.email}</Field>
              <Field icon={<Phone size={14} />} label="Phone">{e.phone ?? "—"}</Field>
            </>
          ) : (
            <Field icon={<Mail size={14} />} label="Contact">
              <span className="muted">Hidden for HR</span>
            </Field>
          )}
          <Field icon={<Briefcase size={14} />} label="Status">
            {e.is_active ? "Active" : "Inactive"}
          </Field>
        </div>

        {canTag && (
          <div className="mt-6 pt-4 border-t border-ink-100">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider muted mb-2">
              <Tags size={12} /> Tags
            </div>
            <div className="flex flex-wrap gap-1.5 items-center">
              {(userTags.data ?? []).map((t: any) => (
                <TagChip
                  key={t.id}
                  name={t.name}
                  color={t.color}
                  onRemove={() => detach.mutate(t.id)}
                />
              ))}
              <TagPicker
                userId={e.id}
                attachedTagIds={(userTags.data ?? []).map((t: any) => t.id)}
              />
              {(userTags.data ?? []).length === 0 && (
                <span className="text-xs muted">
                  No tags yet — click "+ Add tag" to label this employee.
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Personnel documents — KTP, contract, NPWP, BPJS. HR/finance/management. */}
      <EmployeeDocsSection employeeId={e.id} />

      {/* HR work summary — counts only, no names or money */}
      {isHR && (
        <div className="grid grid-cols-3 gap-3">
          <KpiCard label="Projects" value={stats.data?.projects_total ?? "—"} icon={Briefcase} accent="brand" />
          <KpiCard label="Fulfilled" value={stats.data?.projects_fulfilled ?? "—"} icon={Trophy} accent="emerald" />
          <KpiCard label="Overdue" value={stats.data?.projects_overdue ?? "—"} icon={Frown} accent="red" />
        </div>
      )}

      {/* Sales KPIs — hidden from HR */}
      {!isHR && (
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
      )}

      {canSeeAttendance && (attendanceSummary.data?.deductible_days ?? 0) > 0 && (
        <KpiCard
          label="Missed days this month"
          value={attendanceSummary.data?.deductible_days ?? 0}
          icon={CalendarX}
          accent={(attendanceSummary.data?.deductible_days ?? 0) >= 3 ? "red" : "amber"}
        />
      )}

      {/* All-time attendance tally */}
      {canSeeAttendance && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Total attendance (days)"
            value={stats.data?.attendance_present_total ?? "—"}
            icon={CalendarCheck} accent="emerald" />
          <KpiCard label="Total absences"
            value={stats.data?.attendance_absent_total ?? "—"}
            icon={CalendarX} accent="red" />
          <KpiCard label="Leave / sick (days)"
            value={stats.data?.attendance_leave_total ?? "—"}
            icon={Clock} accent="amber" />
        </div>
      )}

      {isSales && !isHR && (
        <KpiCard
          label="Pipeline value (open quotations)"
          value={stats.data ? idr(stats.data.pipeline_value) : "—"}
          icon={TrendingUp}
          accent="brand"
        />
      )}

      {/* Quotations — hidden from HR */}
      {!isHR && (
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
      )}

      {/* Customers — hidden from HR */}
      {!isHR && (
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
      )}

      {/* Projects / POs tied to this employee's customers — hidden from HR
          (HR sees the fulfillment counts above instead) */}
      {!isHR && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Briefcase size={15} /> Projects / POs
          </div>
          <div className="text-xs muted">{(projects.data ?? []).length} project(s)</div>
        </div>
        {(projects.data ?? []).length === 0 ? (
          <div className="p-8 text-center muted text-sm">No projects.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Code</th>
                  <th className="th">Customer</th>
                  <th className="th">Status</th>
                  <th className="th">Target delivery</th>
                  <th className="th text-right">PO value</th>
                </tr>
              </thead>
              <tbody>
                {(projects.data ?? []).map((p: any) => (
                  <tr
                    key={p.id}
                    className="tr-hover border-t border-ink-100 cursor-pointer"
                    onClick={() => nav(`/projects/${p.id}`)}
                  >
                    <td className="td font-mono text-xs">
                      <Link to={`/projects/${p.id}`} onClick={(ev) => ev.stopPropagation()}
                        className="text-brand-700 hover:underline">{p.code}</Link>
                    </td>
                    <td className="td">{p.customer_name}</td>
                    <td className="td capitalize">{p.status?.replace(/_/g, " ")}</td>
                    <td className="td muted">{p.target_delivery ?? "—"}</td>
                    <td className="td text-right tabular-nums">
                      {p.po_value == null ? "—" : idr(p.po_value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}

      {/* Attendance — HR/Director only */}
      {canSeeAttendance && (
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-semibold flex items-center gap-2">
                <CalendarCheck size={15} /> Attendance
              </div>
              <div className="text-xs muted">
                Daily presence + monthly summary used for salary deductions.
              </div>
            </div>
            <input
              type="month"
              className="input max-w-[180px]"
              value={period}
              onChange={(ev) => setPeriod(ev.target.value)}
            />
          </header>

          {/* Summary tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-5 border-b border-ink-100">
            <SumTile label="Workdays" value={attendanceSummary.data?.workdays_in_month ?? "—"} />
            <SumTile label="Present"
              value={
                (attendanceSummary.data?.counts?.present ?? 0)
                + (attendanceSummary.data?.counts?.wfh ?? 0)
              }
              tone="emerald" />
            <SumTile label="Half day" value={attendanceSummary.data?.counts?.half_day ?? 0} tone="amber" />
            <SumTile label="Absent" value={attendanceSummary.data?.counts?.absent ?? 0} tone="red" />
            <SumTile label="Leave"
              value={
                (attendanceSummary.data?.counts?.leave ?? 0)
                + (attendanceSummary.data?.counts?.sick ?? 0)
              } />
            <SumTile label="Deductible days"
              value={attendanceSummary.data?.deductible_days ?? 0}
              tone="red" />
          </div>

          <div className="px-5 py-2 text-xs muted flex items-center gap-3 flex-wrap">
            <span className="inline-flex items-center gap-1">
              <Clock size={12} /> Total hours:&nbsp;
              <b className="text-ink-900 tabular-nums">
                {attendanceSummary.data?.total_hours ?? 0}
              </b>
            </span>
            {attendanceSummary.error && (
              <span className="text-red-600">
                Couldn't load summary (HTTP {(attendanceSummary.error as any)?.response?.status ?? "?"})
              </span>
            )}
          </div>

          {(attendanceRows.data ?? []).length === 0 ? (
            <div className="p-8 text-center text-sm muted">
              No attendance records for {period}.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ink-50/60">
                  <tr>
                    <th className="th">Date</th>
                    <th className="th">Status</th>
                    <th className="th text-right">Hours</th>
                    <th className="th">Clock in</th>
                    <th className="th">Clock out</th>
                    <th className="th">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {(attendanceRows.data ?? []).map((a: any) => (
                    <tr key={a.id} className="tr-hover border-t border-ink-100">
                      <td className="td tabular-nums">{a.date}</td>
                      <td className="td">
                        <span className={clsx("chip capitalize",
                          ATT_CHIP[a.status] ?? "bg-ink-100 text-ink-700")}>
                          {a.status?.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="td text-right tabular-nums">{a.hours ?? "—"}</td>
                      <td className="td muted tabular-nums">
                        {a.clock_in ? new Date(a.clock_in).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td className="td muted tabular-nums">
                        {a.clock_out ? new Date(a.clock_out).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td className="td muted">{a.notes ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Activity — hidden from HR (customer names) */}
      {!isHR && (
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
      )}
    </div>
  );
}

function SumTile({ label, value, tone }: {
  label: string;
  value: number | string;
  tone?: "emerald" | "amber" | "red";
}) {
  const toneClass = tone === "emerald" ? "text-emerald-700"
    : tone === "amber" ? "text-amber-700"
    : tone === "red" ? "text-red-700"
    : "text-ink-900";
  return (
    <div className="rounded-xl border border-ink-100 p-3">
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className={clsx("mt-1 text-xl font-semibold tabular-nums", toneClass)}>
        {value}
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
