import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Briefcase } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

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

export default function ProjectsPage() {
  const nav = useNavigate();
  const q = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data),
  });
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Briefcase size={22} className="text-brand-600" /> Projects
          </h1>
          <p className="text-sm muted">Won deals turned into deliverables.</p>
        </div>
      </div>

      <div className="table-shell">
        <table className="w-full">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Code</th>
              <th className="th">Status</th>
              <th className="th text-right">PO Value</th>
              <th className="th">Customer</th>
              <th className="th">Target delivery</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((p: any) => (
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
                    {p.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{idr(p.po_value)}</td>
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
                <td className="td muted">{p.target_delivery ?? "—"}</td>
              </tr>
            ))}
            {!q.data?.length && (
              <tr>
                <td colSpan={5} className="td text-center muted py-12">
                  No projects yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

