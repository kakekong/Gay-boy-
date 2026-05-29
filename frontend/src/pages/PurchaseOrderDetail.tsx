import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Truck, Building2, Briefcase, Calendar, Loader2, Save,
  Pencil, Check, X, AlertCircle, Plus, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";

interface POItem { description?: string; qty?: number }
interface PO {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  supplier_category: string | null;
  project_id: string | null;
  project_code: string | null;
  project_status: string | null;
  project_target_delivery: string | null;
  project_actual_delivery: string | null;
  po_date: string | null;
  quoted_lead_days: number | null;
  total: number;
  items: POItem[];
  created_at: string;
}

const STATUS_CHIP: Record<string, string> = {
  open:      "bg-amber-50 text-amber-700",
  received:  "bg-blue-50 text-blue-700",
  closed:    "bg-emerald-50 text-emerald-700",
  cancelled: "bg-red-50 text-red-700",
};
const STATUSES = ["open", "received", "closed", "cancelled"];

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function PurchaseOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
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
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? e?.message
      ?? "Update failed",
  });

  const patch = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/purchasing/po/${id}`, body),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: "Saved." });
    },
    onError: onErr,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading PO…
      </div>
    );
  }
  if (q.error || !q.data) {
    const httpStatus = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {httpStatus === 403 ? "Director only" : "Couldn't load this PO"}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {httpStatus === 403
            ? "Supplier POs are restricted to the director."
            : (q.error as any)?.response?.data?.detail ?? "Try again or go back."}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchase-orders")}>
          <ArrowLeft size={14} /> Back to Purchase Orders
        </button>
      </div>
    );
  }

  const p = q.data;

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
    patch.mutate(
      { items: draftItems.filter((it) => (it.description ?? "").trim() || (it.qty ?? 0) > 0) },
      { onSuccess: () => { refresh(); setEditingItems(false); } },
    );
  }

  return (
    <div className="space-y-5">
      <Link to="/purchase-orders" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> All purchase orders
      </Link>

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Truck size={13} className="text-brand-600" /> Purchase Order
            </div>
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
                  title="Save"
                >
                  {patch.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Check size={14} />}
                </button>
                <button className="btn-ghost" onClick={() => setEditingNumber(false)} title="Cancel">
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                className="text-2xl font-semibold tracking-tight font-mono inline-flex items-center gap-2 hover:text-brand-700"
                onClick={startNumberEdit}
                title="Rename PO"
              >
                {p.number}
                <Pencil size={14} className="opacity-50" />
              </button>
            )}
            <div className="text-xs muted">
              Issued {new Date(p.created_at).toLocaleString()}
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
            <div className="text-right">
              <div className="text-[10px] uppercase muted tracking-wider">Total</div>
              <div className="text-xl font-semibold tabular-nums">{idr(p.total)}</div>
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
          <Meta label="Supplier" icon={<Building2 size={12} />}>
            {p.supplier_name ?? "—"}
            {p.supplier_category && (
              <span className="block text-[11px] muted">{p.supplier_category}</span>
            )}
          </Meta>
          <Meta label="Project" icon={<Briefcase size={12} />}>
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
                {p.project_status.replace(/_/g, " ")}
              </span>
            )}
          </Meta>
          <Meta label="PO date" icon={<Calendar size={12} />}>
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
          <Meta label="Lead time (days)">
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
          <Meta label="Total (Rp)">
            <input
              type="number"
              min={0}
              step="0.01"
              defaultValue={p.total}
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (v !== p.total) patch.mutate({ total: v });
              }}
              disabled={patch.isPending}
              className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm w-full"
            />
          </Meta>
          <Meta label="Project target delivery">
            {p.project_target_delivery ?? "—"}
          </Meta>
          <Meta label="Project actual delivery">
            {p.project_actual_delivery ?? "—"}
          </Meta>
        </div>
      </div>

      {/* Items */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="font-semibold">Items</div>
            <div className="text-xs muted">What this PO covers.</div>
          </div>
          {!editingItems ? (
            <button className="btn-ghost" onClick={startItemsEdit}>
              <Pencil size={13} /> Edit items
            </button>
          ) : (
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setEditingItems(false)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={commitItems}
                disabled={patch.isPending}
              >
                {patch.isPending
                  ? <Loader2 size={13} className="animate-spin" />
                  : <Save size={13} />}
                Save items
              </button>
            </div>
          )}
        </header>

        {editingItems ? (
          <div className="p-4 space-y-2">
            {draftItems.map((it, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-end">
                <div className="col-span-9">
                  <span className="text-[10px] uppercase muted">Description</span>
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
                  <span className="text-[10px] uppercase muted">Qty</span>
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
                <button
                  type="button"
                  className="col-span-1 text-red-600 hover:bg-red-50 rounded p-2"
                  onClick={() => setDraftItems((cur) => cur.filter((_, j) => j !== i))}
                  title="Remove"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setDraftItems((cur) => [...cur, { description: "", qty: 1 }])}
            >
              <Plus size={13} /> Add line
            </button>
          </div>
        ) : !p.items?.length ? (
          <div className="p-8 text-center text-sm muted">
            No items yet. Click "Edit items" to add a description and quantity.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">Description</th>
                <th className="th text-right">Qty</th>
              </tr>
            </thead>
            <tbody>
              {p.items.map((it, i) => (
                <tr key={i} className="border-t border-ink-100">
                  <td className="td muted">{i + 1}</td>
                  <td className="td">{it.description ?? "—"}</td>
                  <td className="td text-right tabular-nums">{it.qty ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Attachments (PO-scoped) */}
      <AttachmentsSection ownerType="supplier_po" ownerId={p.id} />
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
