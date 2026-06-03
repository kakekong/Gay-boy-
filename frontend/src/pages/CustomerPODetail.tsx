import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Receipt, Building2, FileText, Briefcase, Calendar,
  Loader2, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";

interface CustomerPO {
  id: string;
  number: string;
  po_date: string | null;
  total: number;
  status: string;
  customer_id: string;
  customer_name: string | null;
  quotation_id: string | null;
  quotation_number: string | null;
  project_id: string | null;
  project_code: string | null;
  items: Array<{
    description?: string;
    qty?: number;
    unit_price?: number;
    uom?: string | null;
  }>;
  notes: string | null;
  decided_at: string | null;
  decision_notes: string | null;
  created_at: string;
}

const STATUS_CHIP: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved:         "bg-emerald-50 text-emerald-700",
  rejected:         "bg-red-50 text-red-700",
  cancelled:        "bg-ink-100 text-ink-600",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function CustomerPODetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();

  const q = useQuery({
    queryKey: ["customer-po", id],
    queryFn: () => api.get(`/customer-pos/${id}`).then((r) => r.data as CustomerPO),
    enabled: !!id,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading customer PO…
      </div>
    );
  }
  if (q.error || !q.data) {
    const errAny = q.error as any;
    const httpStatus = errAny?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {httpStatus === 404 ? "Customer PO not found" : "Couldn't load this PO"}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {errAny?.response?.data?.detail ?? "Try again or go back."}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav("/customer-pos")}>
          <ArrowLeft size={14} /> Back to Customer POs
        </button>
      </div>
    );
  }

  const p = q.data;

  return (
    <div className="space-y-5">
      <Link
        to="/customer-pos"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> All customer POs
      </Link>

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Receipt size={13} className="text-brand-600" /> Customer PO
            </div>
            <div className="text-2xl font-semibold tracking-tight font-mono mt-0.5">
              {p.number}
            </div>
            <div className="text-xs muted">
              Filed {new Date(p.created_at).toLocaleString()}
              {p.po_date && <> · PO dated {p.po_date}</>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className={clsx(
              "chip capitalize px-3 py-1 text-xs font-semibold",
              STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
            )}>
              {p.status.replace(/_/g, " ")}
            </span>
            <div className="text-right">
              <div className="text-[10px] uppercase muted tracking-wider">Total</div>
              <div className="text-xl font-semibold tabular-nums">{idr(p.total)}</div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 text-sm border-t border-ink-100">
          <Meta label="Customer" icon={<Building2 size={12} />}>
            {p.customer_id ? (
              <Link
                to={`/customers/${p.customer_id}`}
                className="text-brand-700 hover:underline"
              >
                {p.customer_name ?? p.customer_id.slice(0, 8)}
              </Link>
            ) : "—"}
          </Meta>
          <Meta label="Against quotation" icon={<FileText size={12} />}>
            {p.quotation_id ? (
              <Link
                to={`/quotations/${p.quotation_id}`}
                className="font-mono text-xs text-brand-700 hover:underline"
              >
                {p.quotation_number ?? p.quotation_id.slice(0, 8)}
              </Link>
            ) : "—"}
          </Meta>
          <Meta label="Spawned project" icon={<Briefcase size={12} />}>
            {p.project_id ? (
              <Link
                to={`/projects/${p.project_id}`}
                className="font-mono text-xs text-brand-700 hover:underline"
              >
                {p.project_code ?? p.project_id.slice(0, 8)}
              </Link>
            ) : (
              <span className="muted">
                {p.status === "pending_approval"
                  ? "Awaiting director approval"
                  : p.status === "rejected"
                    ? "PO was rejected"
                    : "—"}
              </span>
            )}
          </Meta>
          <Meta label="PO date" icon={<Calendar size={12} />}>
            {p.po_date ?? "—"}
          </Meta>
        </div>

        {p.decision_notes && p.status !== "pending_approval" && (
          <div className="rounded-lg border border-ink-100 bg-ink-50/60 px-3 py-2 text-xs">
            <div className="font-semibold mb-0.5">Director decision</div>
            <div className="text-ink-700">{p.decision_notes}</div>
            {p.decided_at && (
              <div className="text-ink-500 mt-0.5">
                {new Date(p.decided_at).toLocaleString()}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Line items */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold">Items</div>
          <div className="text-xs muted">
            The lines the customer ordered from the linked quotation.
          </div>
        </header>
        {!p.items?.length ? (
          <div className="p-8 text-center text-sm muted">No items.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">Description</th>
                <th className="th text-right">Qty</th>
                <th className="th text-right">Unit price</th>
                <th className="th text-right">Line total</th>
              </tr>
            </thead>
            <tbody>
              {p.items.map((it, i) => (
                <tr key={i} className="border-t border-ink-100">
                  <td className="td muted">{i + 1}</td>
                  <td className="td">{it.description ?? "—"}</td>
                  <td className="td text-right tabular-nums">
                    {it.qty ?? 0} {it.uom ?? ""}
                  </td>
                  <td className="td text-right tabular-nums">
                    {idr(Number(it.unit_price ?? 0))}
                  </td>
                  <td className="td text-right tabular-nums">
                    {idr(Number(it.qty ?? 0) * Number(it.unit_price ?? 0))}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-ink-100 bg-ink-50/60">
                <td colSpan={4} className="td text-right font-semibold">PO total</td>
                <td className="td text-right font-semibold tabular-nums">{idr(p.total)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {p.notes && (
        <div className="card p-5">
          <div className="text-[10px] uppercase tracking-wider muted mb-1">Notes</div>
          <div className="text-sm whitespace-pre-wrap">{p.notes}</div>
        </div>
      )}

      {/* PO file (and any other attachments) */}
      <AttachmentsSection ownerType="customer_po" ownerId={p.id} />
    </div>
  );
}

function Meta({
  label, icon, children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
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
