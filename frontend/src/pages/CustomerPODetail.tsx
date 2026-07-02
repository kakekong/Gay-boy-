import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Receipt, Building2, FileText, Briefcase, Calendar,
  Loader2, AlertCircle, Check, X, TrendingUp, Wallet, AlertTriangle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { useAuthStore } from "@/store/auth";

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
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const canDecide = me?.role === "manager" || me?.role === "director";
  const [reason, setReason] = useState("");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const q = useQuery({
    queryKey: ["customer-po", id],
    queryFn: () => api.get(`/customer-pos/${id}`).then((r) => r.data as CustomerPO),
    enabled: !!id,
  });

  const quoteId = q.data?.quotation_id ?? null;
  const custId  = q.data?.customer_id ?? null;

  const quote = useQuery({
    queryKey: ["quotation-recap", quoteId],
    queryFn: () => api.get(`/quotations/${quoteId}`).then((r) => r.data as any),
    enabled: !!quoteId,
    retry: false,
  });

  const custSummary = useQuery({
    queryKey: ["customer-summary-recap", custId],
    queryFn: () => api.get(`/customers/${custId}/summary`).then((r) => r.data as any),
    enabled: !!custId,
    retry: false,
  });

  const decide = useMutation({
    mutationFn: (vars: { approve: boolean }) =>
      api.post(`/customer-pos/${id}/${vars.approve ? "approve" : "reject"}`,
        { notes: reason.trim() || null }),
    onSuccess: (_r, vars) => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-all"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-for-quote"] });
      setReason("");
      setFlash({ kind: "ok", text: vars.approve ? "PO approved — project created." : "PO rejected." });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message ?? "Action failed",
    }),
  });

  function onApprove() {
    setFlash(null);
    decide.mutate({ approve: true });
  }
  function onReject() {
    setFlash(null);
    if (!reason.trim()) {
      setFlash({ kind: "err", text: "Please give a reason for rejecting." });
      return;
    }
    decide.mutate({ approve: false });
  }

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

        {/* Manager/Director approve/reject panel — only while pending. */}
        {canDecide && p.status === "pending_approval" && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 space-y-2">
            <div className="text-xs font-semibold text-amber-900">
              Decision — approving creates the project; rejecting sends it back to sales.
            </div>
            <textarea
              className="input text-sm"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (required to reject, shown to the requester)…"
            />
            <div className="flex gap-2">
              <button
                onClick={onReject}
                className="btn-danger"
                disabled={decide.isPending}
              >
                <X size={14} /> Reject
              </button>
              <button
                onClick={onApprove}
                className="btn-success"
                disabled={decide.isPending}
              >
                {decide.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Check size={14} />}
                Approve
              </button>
            </div>
          </div>
        )}

        {flash && (
          <div className={clsx(
            "rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}>
            <span className="flex-1">{flash.text}</span>
            <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
              <X size={12} />
            </button>
          </div>
        )}

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

      {/* Quotation + customer recap — inline, so reviewers don't have to
          bounce to other pages to sanity-check what this PO is against. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QuotationRecap
          quote={quote.data}
          loading={quote.isLoading}
          linkedId={p.quotation_id}
        />
        <CustomerRecap
          summary={custSummary.data}
          loading={custSummary.isLoading}
          customerId={p.customer_id}
          fallbackName={p.customer_name}
        />
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

      <CommentThread ownerType="customer_po" ownerId={p.id} />
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

const idrCompact = (n: number) => {
  const v = Math.abs(n || 0);
  if (v >= 1e9) return `Rp ${(n / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `Rp ${(n / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `Rp ${(n / 1e3).toFixed(0)}k`;
  return `Rp ${Math.round(n || 0)}`;
};

function QuotationRecap({
  quote, loading, linkedId,
}: { quote: any; loading: boolean; linkedId: string | null }) {
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2">
          <FileText size={14} className="text-brand-600" /> Quotation recap
        </div>
        {quote?.id && (
          <Link
            to={`/quotations/${quote.id}`}
            className="text-xs text-brand-700 hover:underline"
          >
            Open quotation
          </Link>
        )}
      </header>
      <div className="p-5 text-sm">
        {loading ? (
          <div className="text-xs muted flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> Loading…
          </div>
        ) : !linkedId ? (
          <div className="text-xs muted">This PO isn't linked to a quotation.</div>
        ) : !quote ? (
          <div className="text-xs muted">Couldn't load the linked quotation.</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Meta label="Number" icon={<FileText size={12} />}>
                <span className="font-mono text-xs">{quote.number}</span>
              </Meta>
              <Meta label="Status">
                <span className="chip capitalize bg-ink-100 text-ink-700">
                  {String(quote.status ?? "—").replace(/_/g, " ")}
                </span>
              </Meta>
              <Meta label="Variant">
                <span className="capitalize">{quote.variant ?? "—"}</span>
              </Meta>
              <Meta label="Valid until" icon={<Calendar size={12} />}>
                {quote.valid_until ?? "—"}
              </Meta>
              <Meta label="Discount">
                {Number(quote.discount_pct ?? 0)}%
              </Meta>
              <Meta label="Quoted total">
                <span className="tabular-nums font-medium">
                  {idr(Number(quote.total ?? 0))}
                </span>
              </Meta>
            </div>
            {Array.isArray(quote.items) && quote.items.length > 0 && (
              <div className="mt-4 pt-3 border-t border-ink-100">
                <div className="text-[10px] uppercase muted tracking-wider mb-1">
                  Lines quoted ({quote.items.length})
                </div>
                <ul className="space-y-1 text-xs">
                  {quote.items.slice(0, 6).map((it: any, i: number) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="truncate">
                        {i + 1}. {it.description ?? "—"}
                      </span>
                      <span className="tabular-nums muted shrink-0">
                        {Number(it.qty ?? 0)} × {idr(Number(it.unit_price ?? 0))}
                      </span>
                    </li>
                  ))}
                  {quote.items.length > 6 && (
                    <li className="muted text-[11px]">
                      + {quote.items.length - 6} more line(s)…
                    </li>
                  )}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CustomerRecap({
  summary, loading, customerId, fallbackName,
}: {
  summary: any;
  loading: boolean;
  customerId: string | null;
  fallbackName: string | null;
}) {
  const c = summary?.customer;
  const s = summary?.stats;
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2">
          <Building2 size={14} className="text-brand-600" /> Customer recap
        </div>
        {customerId && (
          <Link
            to={`/customers/${customerId}`}
            className="text-xs text-brand-700 hover:underline"
          >
            Open customer
          </Link>
        )}
      </header>
      <div className="p-5 text-sm">
        {loading ? (
          <div className="text-xs muted flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> Loading…
          </div>
        ) : !customerId ? (
          <div className="text-xs muted">No linked customer.</div>
        ) : !summary ? (
          <div className="text-xs muted">
            {fallbackName ?? "Couldn't load customer summary."}
          </div>
        ) : (
          <>
            <div className="font-medium text-ink-900">{c?.company_name}</div>
            <div className="text-xs muted capitalize mt-0.5">
              {c?.industry ?? "—"} · stage {String(c?.stage ?? "").replace(/_/g, " ")}
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <Meta label="Won revenue" icon={<TrendingUp size={12} />}>
                <span className="tabular-nums font-medium text-emerald-700">
                  {idrCompact(s?.won_revenue ?? 0)}
                </span>
              </Meta>
              <Meta label="Pipeline" icon={<FileText size={12} />}>
                <span className="tabular-nums">
                  {idrCompact(s?.pipeline_value ?? 0)}
                </span>
              </Meta>
              <Meta label="Outstanding AR" icon={<AlertTriangle size={12} />}>
                <span className={clsx(
                  "tabular-nums font-medium",
                  (s?.outstanding_ar ?? 0) > 0 ? "text-amber-700" : "text-ink-700",
                )}>
                  {idrCompact(s?.outstanding_ar ?? 0)}
                </span>
              </Meta>
              <Meta label="Active projects" icon={<Briefcase size={12} />}>
                {s?.active_projects ?? 0}
              </Meta>
              <Meta label="Win rate">
                {Math.round((s?.win_rate ?? 0) * 100)}%
                <span className="muted text-[11px] ml-1">
                  ({s?.won ?? 0}/{s?.won + s?.lost || 0})
                </span>
              </Meta>
              <Meta label="Lifetime value" icon={<Wallet size={12} />}>
                <span className="tabular-nums">
                  {idrCompact(Number(c?.lifetime_value ?? 0))}
                </span>
              </Meta>
            </div>
            {s?.last_activity_at && (
              <div className="text-[11px] muted mt-3 pt-3 border-t border-ink-100">
                Last contact:{" "}
                <b className="text-ink-700">
                  {new Date(s.last_activity_at).toLocaleString()}
                </b>
                {" · known "}{s?.days_known ?? 0} day(s)
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
