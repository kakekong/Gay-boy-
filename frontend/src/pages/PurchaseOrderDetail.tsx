import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Truck, Building2, Briefcase, Calendar, Loader2, Save,
  Pencil, Check, X, AlertCircle, Plus, Trash2, FileText, FileSpreadsheet,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { CURRENCIES, money } from "@/lib/currency";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { UserLink } from "@/components/UserLink";
import { useAuthStore } from "@/store/auth";
import { T, locale, t as tt } from "@/store/lang";

interface POItem {
  description?: string;
  qty?: number;
  uom?: string;
  /** What we pay per unit. The PO total is the sum of qty × this. */
  unit_price?: number;
  amount?: number;
}
interface PO {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  supplier_category: string | null;
  sales_pic_id: string | null;
  sales_pic_name: string | null;
  price_request_id: string | null;
  price_request_number: string | null;
  project_id: string | null;
  project_code: string | null;
  project_status: string | null;
  project_target_delivery: string | null;
  project_actual_delivery: string | null;
  po_date: string | null;
  /** What the supplier says, not what the lead time implies. Drives the
   *  project page's shipment list. */
  eta: string | null;
  quoted_lead_days: number | null;
  currency: string;
  /** Rupiah per unit of `currency`; null until someone sets one. */
  fx_rate: number | null;
  /** total × fx_rate, or null when no rate is set. */
  total_idr: number | null;
  total: number;
  items: POItem[];
  created_at: string;
}

const STATUS_CHIP: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
};
const STATUSES = ["pending_approval", "open", "received", "closed", "cancelled"];

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

/** What a line is worth.
 *
 *  A line that states a unit price is the authority on its own value, so the
 *  amount follows from qty × price. Reading the stored `amount` first looked
 *  tidier and was wrong: re-pricing a line left the old amount sitting there,
 *  and the PO went on billing the price we had just renegotiated away. Older
 *  lines that carry only an amount still show it.
 */
function lineAmount(it: POItem): number {
  const unit = Number(it.unit_price ?? NaN);
  if (!Number.isNaN(unit)) return Number(it.qty ?? 0) * unit;
  const amt = Number(it.amount ?? NaN);
  return Number.isNaN(amt) ? 0 : amt;
}

export default function PurchaseOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";
  // Finance is here for the exchange rate alone — the backend refuses any
  // other field from them, so the rest of the page is read-only.
  const isFinance = me?.role === "finance";
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [editingNumber, setEditingNumber] = useState(false);
  const [draftNumber, setDraftNumber] = useState("");
  const [editingItems, setEditingItems] = useState(false);
  const [draftItems, setDraftItems] = useState<POItem[]>([]);

  const q = useQuery({
    queryKey: ["po", id],
    queryFn: () => api.get(`/purchasing/po/${id}`).then((r) => r.data as PO),
    enabled: !!id,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["po", id] });
  const onErr = (e: any) => {
    // 202 = accepted-but-pending-director-approval. The backend raises
    // HTTPException there, which axios bubbles up as an error; surface
    // it as a friendly green-banner ack instead of a red error.
    if (e?.response?.status === 202) {
      refresh();
      setFlash({
        kind: "ok",
        text: e?.response?.data?.detail
          ?? "Submitted for director approval; changes will apply once approved.",
      });
      setEditingNumber(false);
      setEditingItems(false);
      return;
    }
    setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Update failed",
    });
  };

  // An order covering more than one job. Only then is the per-line project
  // worth a column; on an ordinary PO it would be the same code repeated.
  const sharedOrder = new Set(
    ((q.data?.items ?? []) as any[]).map((i) => i.project_code).filter(Boolean),
  ).size > 1;

  const patch = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/purchasing/po/${id}`, body),
    onSuccess: (resp: any) => {
      refresh();
      // A non-director edit comes back as pending_approval — the change is
      // queued for the director, not applied. Say so instead of "Saved."
      if (resp?.data?.pending_approval) {
        setFlash({
          kind: "ok",
          text: resp.data.detail
            ?? "Submitted for director approval; changes will apply once approved.",
        });
      } else {
        setFlash({ kind: "ok", text: "Saved." });
      }
      setEditingNumber(false);
      setEditingItems(false);
    },
    onError: onErr,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {T("Loading PO…")}</div>
    );
  }
  if (q.error || !q.data) {
    const errAny = q.error as any;
    const httpStatus = errAny?.response?.status;
    const serverMsg = errAny?.response?.data?.detail
      ?? errAny?.response?.data?.errors?.[0]?.message;
    let title: string;
    let body: string;
    if (httpStatus === 403) {
      title = "Not allowed";
      body = "Purchase orders are restricted to procurement / manager / director roles.";
    } else if (httpStatus === 404) {
      title = "PO not found";
      body = serverMsg
        ?? "This PO doesn't exist, or the backend hasn't been restarted to pick up the new endpoint yet. Open the HF Space and click Restart Space, then come back.";
    } else if (httpStatus) {
      title = `Couldn't load this PO (HTTP ${httpStatus})`;
      body = serverMsg ?? "The server rejected the request. Try again in a moment.";
    } else {
      title = "Couldn't reach the server";
      body = "Looks like a network error. Check the connection or try again.";
    }
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">{title}</div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">{body}</p>
        <div className="text-[10px] muted mt-2 font-mono">
          {T("GET /purchasing/po/")}{id}
        </div>
        <div className="flex gap-2 justify-center mt-4">
          <button className="btn-ghost" onClick={() => q.refetch()}>
            <Loader2
              size={13}
              className={clsx(q.isFetching && "animate-spin")}
            />
            {T("Retry")}</button>
          <button className="btn-ghost" onClick={() => nav("/purchase-orders")}>
            <ArrowLeft size={14} /> {T("Back to Purchase Orders")}</button>
        </div>
      </div>
    );
  }

  const p = q.data;
  const draftTotal = draftItems.reduce((s, it) => s + lineAmount(it), 0);
  const foreign = (p.currency ?? "IDR").toUpperCase() !== "IDR";

  function startNumberEdit() {
    setDraftNumber(p.number);
    setEditingNumber(true);
  }
  function commitNumber() {
    const next = draftNumber.trim();
    if (!next || next === p.number) {
      setEditingNumber(false);
      return;
    }
    patch.mutate({ number: next }, { onSuccess: () => { refresh(); setEditingNumber(false); } });
  }

  function startItemsEdit() {
    setDraftItems(p.items.map((i) => ({ ...i })));
    setEditingItems(true);
  }
  function commitItems() {
    // Each line carries its own amount, and the PO total is their sum. Saving
    // lines without it would leave a PO whose header contradicts its own
    // lines — and the header is the figure that prints on the vendor's copy.
    const keep = draftItems
      .filter((it) => (it.description ?? "").trim() || (it.qty ?? 0) > 0)
      .map((it) => ({ ...it, amount: lineAmount(it) }));
    patch.mutate(
      { items: keep, total: keep.reduce((s, it) => s + lineAmount(it), 0) },
      { onSuccess: () => { refresh(); setEditingItems(false); } },
    );
  }

  return (
    <div className="space-y-5">
      <Link to="/purchase-orders" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> {T("All purchase orders")}</Link>

      {!isDirector && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">{T("Changes here need the director — except the ETA")}</div>
            <div className="text-xs mt-0.5">
              {T("Edits you make here are queued for director approval, and the PO won't show them until it's granted from the Approvals page. The expected arrival is the exception: it saves straight away, so the project's shipment list stays current when a supplier moves their date.")}</div>
          </div>
        </div>
      )}
      {p.status === "pending_approval" && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">{T("Waiting on director approval")}</div>
            <div className="text-xs mt-0.5">
              {T("This PO was just created and is pending the director's sign-off. Suppliers won't see it until it's approved.")}</div>
          </div>
        </div>
      )}

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Truck size={13} className="text-brand-600" /> {T("Purchase Order")}</div>
            {editingNumber ? (
              <div className="flex items-center gap-2">
                <input
                  autoFocus
                  className="input font-mono text-lg py-1 w-56"
                  value={draftNumber}
                  onChange={(e) => setDraftNumber(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitNumber();
                    if (e.key === "Escape") setEditingNumber(false);
                  }}
                  disabled={patch.isPending}
                />
                <button
                  className="btn-ghost text-emerald-700"
                  onClick={commitNumber}
                  disabled={patch.isPending}
                  title={T("Save")}
                >
                  {patch.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Check size={14} />}
                </button>
                <button className="btn-ghost" onClick={() => setEditingNumber(false)} title={T("Cancel")}>
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                className="text-2xl font-semibold tracking-tight font-mono inline-flex items-center gap-2 hover:text-brand-700"
                onClick={startNumberEdit}
                title={T("Rename PO")}
              >
                {p.number}
                <Pencil size={14} className="opacity-50" />
              </button>
            )}
            <div className="text-xs muted">
              {T("Issued")}{" "}{new Date(p.created_at).toLocaleString(locale())}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={p.status}
              onChange={(e) => patch.mutate({ status: e.target.value })}
              disabled={patch.isPending}
              className={clsx(
                "input py-1 text-xs font-semibold capitalize w-36",
                STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
              )}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            {/* The order as a document. A PO that only exists on a screen is
                one somebody has to retype into an email; the PDF is what goes
                to the vendor, the sheet is what gets pasted into a stock or
                payment schedule. */}
            <button
              className="btn-ghost"
              title={T("Download as PDF")}
              onClick={() => downloadFile(
                `/purchasing/po/${p.id}/export.pdf`, `PO-${p.number}.pdf`)}
            >
              <FileText size={15} /> {T("PDF")}
            </button>
            <button
              className="btn-ghost"
              title={T("Download as Excel")}
              onClick={() => downloadFile(
                `/purchasing/po/${p.id}/export.xlsx`, `PO-${p.number}.xlsx`)}
            >
              <FileSpreadsheet size={15} /> {T("Excel")}
            </button>
            <div className="text-right">
              <div className="text-[10px] uppercase muted tracking-wider">{T("Total")}</div>
              <div className="text-xl font-semibold tabular-nums">{money(p.total, p.currency)}</div>
            </div>
          </div>
        </div>

        {flash && (
          <div className={clsx(
            "rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}>
            <span className="flex-1">{flash.text}</span>
            <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 text-sm">
          <Meta label={T("Supplier")} icon={<Building2 size={12} />}>
            {p.supplier_name ?? "—"}
            {p.supplier_category && (
              <span className="block text-[11px] muted">{p.supplier_category}</span>
            )}
          </Meta>
          <Meta label={T("Project")} icon={<Briefcase size={12} />}>
            {p.project_id ? (
              <Link
                to={`/projects/${p.project_id}`}
                className="text-brand-700 hover:underline font-mono text-xs"
              >
                {p.project_code ?? p.project_id.slice(0, 8)}
              </Link>
            ) : "—"}
            {p.project_status && (
              <span className="block text-[11px] muted capitalize">
                {T(p.project_status.replace(/_/g, " "))}
              </span>
            )}
          </Meta>
          <Meta label={T("Sales in charge")}>
            {p.sales_pic_name ? <UserLink id={p.sales_pic_id} name={p.sales_pic_name} /> : "—"}
          </Meta>
          {p.price_request_number && (
            <Meta label={T("Price request")}>
              {/* "Sourced from here" was a claim you had to take on trust —
                  the number was printed but not reachable. */}
              {p.price_request_id ? (
                <Link to={`/price-requests?open=${p.price_request_id}`}
                  className="font-mono text-xs text-brand-700 hover:underline">
                  {p.price_request_number}
                </Link>
              ) : (
                <span className="font-mono text-xs">{p.price_request_number}</span>
              )}
              <span className="block text-[11px] muted">{T("buying price sourced from here")}</span>
            </Meta>
          )}
          <Meta label={T("PO date")} icon={<Calendar size={12} />}>
            <input
              type="date"
              value={p.po_date ?? ""}
              onChange={(e) =>
                patch.mutate({ po_date: e.target.value || null })
              }
              disabled={patch.isPending}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
            />
          </Meta>
          {/* The date the project page counts on. It applies immediately
              rather than queueing for the director, because a vendor moving
              their truck is news to record, not a decision to approve — and a
              shipment list nobody can correct is a shipment list nobody
              trusts. */}
          <Meta label={T("Expected arrival (ETA)")} icon={<Truck size={12} />}>
            <input
              type="date"
              value={p.eta ?? ""}
              onChange={(e) => patch.mutate({ eta: e.target.value || null })}
              disabled={patch.isPending}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
            />
            <div className="text-[11px] muted mt-0.5">
              {T("Shows on the project as this shipment's date")}
            </div>
          </Meta>
          <Meta label={T("Lead time (days)")}>
            <input
              type="number"
              min={0}
              defaultValue={p.quoted_lead_days ?? ""}
              onBlur={(e) => {
                const v = e.target.value === "" ? null : Number(e.target.value);
                if (v !== p.quoted_lead_days) patch.mutate({ quoted_lead_days: v });
              }}
              disabled={patch.isPending}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
              placeholder="—"
            />
          </Meta>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm border-t border-ink-100 pt-4">
          {/* The currency the vendor is being asked to invoice in. It prints
              on every money column of the PO, so it belongs beside the total
              rather than buried in the create form. */}
          <Meta label={T("Currency")}>
            <select
              value={p.currency ?? "IDR"}
              onChange={(e) => patch.mutate({ currency: e.target.value })}
              disabled={patch.isPending}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
            >
              {CURRENCIES.map((c) => (
                <option key={c.code} value={c.code}>{c.code} — {T(c.name)}</option>
              ))}
            </select>
          </Meta>
          <Meta label={`${T("Total")} (${p.currency ?? "IDR"})`}>
            <input
              type="number"
              min={0}
              step="0.01"
              defaultValue={p.total}
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (v !== p.total) patch.mutate({ total: v });
              }}
              disabled={patch.isPending || isFinance}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full disabled:opacity-60"
            />
          </Meta>
          {/* What the order is worth in rupiah. Kept on the PO rather than
              looked up live, because the rate that matters is the one the
              payment settles at — a rate fetched today would restate what a
              March order cost. Finance corrects it once the bank confirms. */}
          {foreign && (
            <Meta label={`${T("Rate")} (Rp / ${p.currency})`}>
              <input
                type="number"
                min={0}
                step="any"
                defaultValue={p.fx_rate ?? ""}
                placeholder={T("not set")}
                onBlur={(e) => {
                  const raw = e.target.value.trim();
                  const v = raw === "" ? null : Number(raw);
                  if (v !== (p.fx_rate ?? null)) patch.mutate({ fx_rate: v });
                }}
                disabled={patch.isPending}
                className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
              />
            </Meta>
          )}
          {foreign && (
            <Meta label={T("Total in rupiah")}>
              {p.total_idr == null ? (
                <span className="text-amber-700 text-xs">
                  {T("Set a rate to see this in rupiah")}</span>
              ) : (
                <span className="tabular-nums">{idr(p.total_idr)}</span>
              )}
            </Meta>
          )}
          <Meta label={T("Project target delivery")}>
            {p.project_target_delivery ?? "—"}
          </Meta>
          <Meta label={T("Project actual delivery")}>
            {p.project_actual_delivery ?? "—"}
          </Meta>
        </div>
      </div>

      <ShippingPanel
        poDate={p.po_date}
        eta={p.eta ?? null}
        leadDays={p.quoted_lead_days}
        targetDelivery={p.project_target_delivery}
        actualDelivery={p.project_actual_delivery}
      />

      {/* Items */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="font-semibold">{T("Items")}</div>
            <div className="text-xs muted">{T("What this PO covers.")}</div>
          </div>
          {!editingItems ? (
            <button className="btn-ghost" onClick={startItemsEdit}>
              <Pencil size={13} /> {T("Edit items")}</button>
          ) : (
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setEditingItems(false)}>
                {T("Cancel")}</button>
              <button
                className="btn-primary"
                onClick={commitItems}
                disabled={patch.isPending}
              >
                {patch.isPending
                  ? <Loader2 size={13} className="animate-spin" />
                  : <Save size={13} />}
                {T("Save items")}</button>
            </div>
          )}
        </header>

        {editingItems ? (
          <div className="p-4 space-y-2">
            {draftItems.map((it, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-end">
                <div className="col-span-5">
                  <span className="text-[10px] uppercase muted">{T("Description")}</span>
                  <input
                    className="input"
                    value={it.description ?? ""}
                    onChange={(e) =>
                      setDraftItems((cur) =>
                        cur.map((x, j) => j === i ? { ...x, description: e.target.value } : x)
                      )
                    }
                  />
                </div>
                <div className="col-span-2">
                  <span className="text-[10px] uppercase muted">{T("Qty")}</span>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    className="input"
                    value={it.qty ?? 0}
                    onChange={(e) =>
                      setDraftItems((cur) =>
                        cur.map((x, j) =>
                          j === i ? { ...x, qty: Number(e.target.value) } : x
                        )
                      )
                    }
                  />
                </div>
                {/* The price we agreed per unit. Editing only the PO total
                    meant a renegotiated rate had to be back-solved by hand,
                    and the lines kept saying the old price. */}
                <div className="col-span-2">
                  <span className="text-[10px] uppercase muted">
                    {T("Unit price")} ({p.currency ?? "IDR"})
                  </span>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    className="input"
                    value={it.unit_price ?? 0}
                    onChange={(e) =>
                      setDraftItems((cur) =>
                        cur.map((x, j) =>
                          j === i ? { ...x, unit_price: Number(e.target.value) } : x
                        )
                      )
                    }
                  />
                </div>
                <div className="col-span-2">
                  <span className="text-[10px] uppercase muted">{T("Amount")}</span>
                  <div className="input bg-ink-50/60 text-right tabular-nums truncate"
                       title={String(lineAmount(it))}>
                    {money(lineAmount(it), p.currency)}
                  </div>
                </div>
                <button
                  type="button"
                  className="col-span-1 text-red-600 hover:bg-red-50 rounded p-2"
                  onClick={() => setDraftItems((cur) => cur.filter((_, j) => j !== i))}
                  title={T("Remove")}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="flex items-center justify-between gap-3 flex-wrap pt-1">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setDraftItems((cur) => [...cur, { description: "", qty: 1, unit_price: 0 }])}
              >
                <Plus size={13} /> {T("Add line")}</button>
              <div className="text-sm">
                <span className="muted">{T("Lines add up to")}{" "}</span>
                <span className="font-semibold tabular-nums">
                  {money(draftTotal, p.currency)}
                </span>
                {Math.abs(draftTotal - (p.total ?? 0)) > 0.5 && (
                  <span className="ml-2 text-[11px] text-amber-700">
                    {T("· saving will set the PO total to this")}</span>
                )}
              </div>
            </div>
          </div>
        ) : !p.items?.length ? (
          <div className="p-8 text-center text-sm muted">
            {T("No items yet. Click \"Edit items\" to add a description and quantity.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">{T("Description")}</th>
                {sharedOrder && <th className="th">{T("For project")}</th>}
                <th className="th text-right">{T("Qty")}</th>
                <th className="th text-right">{T("Unit price")}</th>
                <th className="th text-right">{T("Amount")}</th>
              </tr>
            </thead>
            <tbody>
              {p.items.map((it: any, i: number) => (
                <tr key={i} className="border-t border-ink-100">
                  <td className="td muted">{i + 1}</td>
                  <td className="td">{it.description ?? "—"}</td>
                  {/* One truck can carry three customers' work. When it does,
                      each line says whose — otherwise the goods arrive and
                      nobody knows which job to book them against. */}
                  {sharedOrder && (
                    <td className="td font-mono text-xs muted">
                      {it.project_code ?? "—"}
                    </td>
                  )}
                  <td className="td text-right tabular-nums">{it.qty ?? 0}</td>
                  <td className="td text-right tabular-nums">
                    {it.unit_price == null ? "—" : money(it.unit_price, p.currency)}
                  </td>
                  <td className="td text-right tabular-nums">
                    {money(lineAmount(it), p.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink-200">
                <td className="td" colSpan={sharedOrder ? 5 : 4} />
                <td className="td text-right font-semibold tabular-nums">
                  {money(p.total, p.currency)}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {/* Attachments (PO-scoped) */}
      <AttachmentsSection ownerType="supplier_po" ownerId={p.id} />

      <CommentThread ownerType="supplier_po" ownerId={p.id} />
    </div>
  );
}

function ShippingPanel({ poDate, eta, leadDays, targetDelivery, actualDelivery }: {
  poDate: string | null;
  eta: string | null;
  leadDays: number | null;
  targetDelivery: string | null;
  actualDelivery: string | null;
}) {
  const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString(locale()) : "—");
  // A date the supplier actually gave beats one we worked out from their lead
  // time. This panel used to only ever compute it, which meant that once
  // purchasing entered a real ETA the page showed two different arrival dates
  // — the typed one at the top and the arithmetic one here.
  let expected: Date | null = eta ? new Date(eta) : null;
  const quoted = !!eta;
  if (!expected && poDate && leadDays != null) {
    expected = new Date(poDate);
    expected.setDate(expected.getDate() + leadDays);
  }
  const day = 86_400_000;
  // Will the materials land in time for the customer-promised delivery?
  let risk: { cls: string; label: string } | null = null;
  if (expected && targetDelivery && !actualDelivery) {
    const slack = Math.round((new Date(targetDelivery).getTime() - expected.getTime()) / day);
    risk = slack < 0
      ? { cls: "bg-red-100 text-red-800", label: `Arrives ${-slack}d after target` }
      : slack <= 7
        ? { cls: "bg-amber-100 text-amber-800", label: `Only ${slack}d slack` }
        : { cls: "bg-emerald-100 text-emerald-800", label: `${slack}d slack` };
  }
  return (
    <div className="card p-5">
      <div className="font-semibold flex items-center gap-2 mb-3">
        <Truck size={15} className="text-brand-600" /> Shipping &amp; ETA
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <Meta label={T("PO date")} icon={<Calendar size={12} />}>{fmt(poDate)}</Meta>
        <Meta label={T("Lead time")}>{leadDays != null ? tt(`${leadDays} days`, `${leadDays} hari`) : "—"}</Meta>
        <Meta label={T("Expected arrival")}>
          {expected ? (
            <span className="inline-flex items-center gap-2 flex-wrap">
              {expected.toLocaleDateString(locale())}
              <span className="chip text-[10px] uppercase bg-ink-100 text-ink-600">
                {quoted
                  ? tt("from the supplier", "dari pemasok")
                  : tt("from lead time", "dari waktu tunggu")}
              </span>
            </span>
          ) : (
            <span className="muted">{T("set a lead time")}</span>
          )}
        </Meta>
        <Meta label={T("Customer target")}>
          <span className="inline-flex items-center gap-2">
            {fmt(targetDelivery)}
            {risk && <span className={clsx("chip text-[10px] uppercase", risk.cls)}>{T(risk.label)}</span>}
          </span>
        </Meta>
      </div>
      {actualDelivery && (
        <div className="mt-2 text-xs muted">
          {T("Delivered to customer:")}{" "}<b className="text-emerald-700">{fmt(actualDelivery)}</b>
        </div>
      )}
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
        {icon} {T(label)}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}
