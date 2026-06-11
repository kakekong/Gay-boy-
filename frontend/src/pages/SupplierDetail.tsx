import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Building2, Star, Truck, Loader2, AlertCircle, Mail, Phone,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface Contact { name?: string; phone?: string; email?: string }

interface PO {
  id: string;
  number: string;
  status: string;
  po_date: string | null;
  total: number;
  project_id: string | null;
}

interface SupplierDetail {
  id: string;
  name: string;
  category: string | null;
  rating: number;
  lead_time_days_avg: number;
  qc_fail_rate: number;
  price_volatility: number;
  contact: Contact;
  po_count: number;
  open_po_count: number;
  lifetime_value: number;
  purchase_orders: PO[];
}

const POSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();

  const q = useQuery({
    queryKey: ["supplier", id],
    queryFn: () => api.get(`/purchasing/suppliers/${id}`)
      .then((r) => r.data as SupplierDetail),
    enabled: !!id,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading supplier…
      </div>
    );
  }
  if (q.error || !q.data) {
    const httpStatus = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {httpStatus === 404 ? "Supplier not found" : "Couldn't load supplier"}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {(q.error as any)?.response?.data?.detail ?? "Try again."}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchasing")}>
          <ArrowLeft size={14} /> Back to Purchasing
        </button>
      </div>
    );
  }

  const s = q.data;
  const c = s.contact || {};

  return (
    <div className="space-y-5">
      <Link
        to="/purchasing"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> Back to Purchasing
      </Link>

      <div className="card p-6 lg:p-8 space-y-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Building2 size={13} className="text-brand-600" /> Supplier
            </div>
            <h1 className="text-2xl font-semibold tracking-tight mt-0.5">{s.name}</h1>
            <div className="text-xs muted mt-1">{s.category ?? "Uncategorised"}</div>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Stat
              label="Rating"
              value={
                <span className="inline-flex items-center gap-1 tabular-nums">
                  <Star size={13} className="text-amber-500" />
                  {s.rating.toFixed(2)}
                </span>
              }
            />
            <Stat label="Avg lead" value={`${s.lead_time_days_avg.toFixed(1)} d`} />
            <Stat label="QC fail" value={`${(s.qc_fail_rate * 100).toFixed(1)}%`} />
            <Stat label="Volatility" value={s.price_volatility.toFixed(2)} />
          </div>
        </div>

        {/* Contact */}
        {(c.name || c.phone || c.email) && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm border-t border-ink-100 pt-4">
            {c.name && (
              <div>
                <div className="text-[10px] uppercase tracking-wider muted">Contact</div>
                <div className="mt-0.5">{c.name}</div>
              </div>
            )}
            {c.phone && (
              <div>
                <div className="text-[10px] uppercase tracking-wider muted">Phone</div>
                <a
                  href={`tel:${c.phone}`}
                  className="mt-0.5 inline-flex items-center gap-1 text-brand-700 hover:underline"
                >
                  <Phone size={12} /> {c.phone}
                </a>
              </div>
            )}
            {c.email && (
              <div>
                <div className="text-[10px] uppercase tracking-wider muted">Email</div>
                <a
                  href={`mailto:${c.email}`}
                  className="mt-0.5 inline-flex items-center gap-1 text-brand-700 hover:underline"
                >
                  <Mail size={12} /> {c.email}
                </a>
              </div>
            )}
          </div>
        )}
      </div>

      {/* PO history */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
        <BigStat label="POs issued" value={s.po_count} />
        <BigStat label="Open POs" value={s.open_po_count} tone="amber" />
        <BigStat label="Lifetime spend" value={idr(s.lifetime_value)} />
      </div>

      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
          <Truck size={15} className="text-brand-600" />
          <span className="font-semibold">Purchase orders</span>
          <span className="text-[10px] uppercase tracking-wider muted ml-auto">
            {s.purchase_orders.length}
          </span>
        </header>
        {!s.purchase_orders.length ? (
          <div className="p-8 text-center text-sm muted">
            No POs issued to this supplier yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">PO number</th>
                <th className="th">PO date</th>
                <th className="th">Project</th>
                <th className="th">Status</th>
                <th className="th text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {s.purchase_orders.map((p) => (
                <tr key={p.id} className="border-t border-ink-100 tr-hover">
                  <td className="td">
                    <Link
                      to={`/purchase-orders/${p.id}`}
                      className="font-mono text-xs text-brand-700 hover:underline"
                    >
                      {p.number}
                    </Link>
                  </td>
                  <td className="td muted">{p.po_date ?? "—"}</td>
                  <td className="td font-mono text-xs muted">
                    {p.project_id ? p.project_id.slice(0, 8) : "—"}
                  </td>
                  <td className="td">
                    <span className={clsx(
                      "chip capitalize",
                      POSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
                    )}>
                      {p.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(p.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function BigStat({ label, value, tone }: {
  label: string; value: React.ReactNode; tone?: "amber";
}) {
  return (
    <div className="card p-4">
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className={clsx(
        "text-2xl font-semibold tabular-nums mt-1",
        tone === "amber" && "text-amber-700",
      )}>
        {value}
      </div>
    </div>
  );
}
