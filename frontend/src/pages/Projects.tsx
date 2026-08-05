import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Briefcase, CheckCircle2, Loader2, User as UserIcon } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { UserLink } from "@/components/UserLink";
import { useAuthStore } from "@/store/auth";
import { T } from "@/store/lang";

const STATUS_COLOR: Record<string, string> = {
  new:               "bg-ink-100 text-ink-700",
  drawing:           "bg-cyan-50 text-cyan-700",
  drawing_approved:  "bg-cyan-100 text-cyan-800",
  purchasing:        "bg-teal-50 text-teal-700",
  production:        "bg-violet-50 text-violet-700",
  qc:                "bg-amber-50 text-amber-700",
  packaging:         "bg-yellow-50 text-yellow-700",
  delivered:         "bg-lime-50 text-lime-700",
  invoiced:          "bg-orange-50 text-orange-700",
  paid:              "bg-emerald-50 text-emerald-700",
  closed:            "bg-emerald-100 text-emerald-800",
};

// A project is finished once it's closed. Everything earlier — including
// 'paid', which auto-advances to closed — is still live work.
const CLOSED_STATUSES = ["closed"];

export default function ProjectsPage() {
  const role = useAuthStore((s) => s.user?.role);
  // Purchasing sees projects for procurement context but not deal
  // economics and not the customer identity — same customer-blindness
  // rule as the PO screens so no customer ↔ supplier map can be built.
  const showMoney = role !== "purchasing";
  const showCustomer = role !== "purchasing";
  const q = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data),
  });

  const { ongoing, closed } = useMemo(() => {
    const all: any[] = q.data ?? [];
    return {
      ongoing: all.filter((p) => !CLOSED_STATUSES.includes(p.status)),
      closed: all.filter((p) => CLOSED_STATUSES.includes(p.status)),
    };
  }, [q.data]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Briefcase size={22} className="text-brand-600" /> {T("Projects")}</h1>
          <p className="text-sm muted">{T("Won deals turned into deliverables.")}</p>
        </div>
      </div>

      <ProjectSection
        title={T("Ongoing")}
        subtitle={T("Still in production, shipping or billing.")}
        icon={<Loader2 size={15} className="text-brand-600" />}
        rows={ongoing}
        emptyText={q.isLoading ? "Loading…" : "No ongoing projects."}
        showMoney={showMoney}
        showCustomer={showCustomer}
      />

      <ProjectSection
        title={T("Closed")}
        subtitle={T("Delivered, paid and wrapped up.")}
        icon={<CheckCircle2 size={15} className="text-emerald-600" />}
        rows={closed}
        emptyText={q.isLoading ? "Loading…" : "No closed projects yet."}
        showMoney={showMoney}
        showCustomer={showCustomer}
        muted
      />
    </div>
  );
}

function ProjectSection({
  title, subtitle, icon, rows, emptyText, showMoney, showCustomer, muted,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  rows: any[];
  emptyText: string;
  showMoney: boolean;
  showCustomer: boolean;
  muted?: boolean;
}) {
  const nav = useNavigate();
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);
  const cols = 2 + (showMoney ? 1 : 0) + (showCustomer ? 2 : 0);
  const total = rows.reduce((s, p) => s + Number(p.po_value || 0), 0);

  return (
    <section className="space-y-2">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-semibold flex items-center gap-2">
            {icon} {title}
            <span className="chip bg-ink-100 text-ink-700">{rows.length}</span>
          </h2>
          <p className="text-xs muted">{subtitle}</p>
        </div>
        {showMoney && rows.length > 0 && (
          <div className="text-xs muted tabular-nums">
            {T("Total PO value")}{" "}<span className="font-medium text-ink-700">{idr(total)}</span>
          </div>
        )}
      </div>

      <div className={clsx("table-shell", muted && "opacity-90")}>
        <table className="w-full">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{T("Code")}</th>
              <th className="th">{T("Status")}</th>
              {showMoney && <th className="th text-right">{T("PO Value")}</th>}
              {showCustomer && <th className="th">{T("Customer")}</th>}
              {showCustomer && <th className="th">{T("Sales rep")}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((p: any) => (
              <tr
                key={p.id}
                className="tr-hover border-t border-ink-100 cursor-pointer"
                onClick={() => nav(`/projects/${p.id}`)}
              >
                <td className="td font-mono text-xs">
                  <Link
                    to={`/projects/${p.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="text-brand-700 hover:underline"
                  >
                    {p.code}
                  </Link>
                </td>
                <td className="td">
                  <span className={clsx("chip capitalize",
                    STATUS_COLOR[p.status] ?? "bg-ink-100 text-ink-600")}>
                    {T(p.status.replace(/_/g, " "))}
                  </span>
                </td>
                {showMoney && (
                  <td className="td text-right tabular-nums">{idr(p.po_value)}</td>
                )}
                {showCustomer && (
                  <td className="td">
                    {p.customer_id ? (
                      <Link
                        to={`/customers/${p.customer_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-brand-700 hover:underline"
                      >
                        {p.customer_name ?? p.customer_id.slice(0, 8)}
                      </Link>
                    ) : <span className="muted">—</span>}
                  </td>
                )}
                {showCustomer && (
                  <td className="td">
                    {p.sales_pic_name ? (
                      <span className="inline-flex items-center gap-1 text-sm">
                        <UserIcon size={11} className="text-ink-400" />
                        <UserLink id={p.sales_pic_id} name={p.sales_pic_name} />
                      </span>
                    ) : <span className="muted">—</span>}
                  </td>
                )}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={cols} className="td text-center muted py-10">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
