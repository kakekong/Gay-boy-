import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Truck, Plus, Loader2, AlertCircle, X, Save, Pencil, Check,
  Search, Filter, ChevronRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

interface SupplierLite {
  id: string;
  name: string;
}
interface PO {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  project_id: string | null;
  po_date: string | null;
  total: number;
  quoted_lead_days: number | null;
  items: Array<{ description?: string; qty?: number }>;
  created_at: string;
}

const STATUS_CHIP: Record<string, string> = {
  open:      "bg-amber-50 text-amber-700",
  received:  "bg-blue-50 text-blue-700",
  closed:    "bg-emerald-50 text-emerald-700",
  cancelled: "bg-red-50 text-red-700",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function PurchaseOrdersPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";

  const [openNew, setOpenNew] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [editingNumberId, setEditingNumberId] = useState<string | null>(null);
  const [draftNumber, setDraftNumber] = useState("");

  const pos = useQuery({
    queryKey: ["supplier-pos"],
    queryFn: () => api.get("/purchasing/po").then((r) => r.data as PO[]),
    enabled: isDirector,
    retry: false,
  });
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as SupplierLite[]),
    retry: false,
  });
  const projects = useQuery({
    queryKey: ["projects-min"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data as any[]),
    enabled: openNew && isDirector,
    retry: false,
  });

  const patchPo = useMutation({
    mutationFn: (vars: { id: string; body: Record<string, any> }) =>
      api.patch(`/purchasing/po/${vars.id}`, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["supplier-pos"] });
      setEditingNumberId(null);
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Update failed",
    }),
  });

  const supplierName = (id: string) =>
    (suppliers.data ?? []).find((s) => s.id === id)?.name ?? id.slice(0, 8);

  const rows = useMemo(() => {
    let list = pos.data ?? [];
    if (statusFilter) list = list.filter((p) => p.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((p) =>
        p.number.toLowerCase().includes(q)
        || supplierName(p.supplier_id).toLowerCase().includes(q)
      );
    }
    return list;
  // supplierName depends on suppliers.data which is referenced via closure
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos.data, suppliers.data, statusFilter, search]);

  function startEditNumber(po: PO) {
    setDraftNumber(po.number);
    setEditingNumberId(po.id);
  }
  function commitNumber(po: PO) {
    const next = draftNumber.trim();
    if (!next || next === po.number) {
      setEditingNumberId(null);
      return;
    }
    patchPo.mutate({ id: po.id, body: { number: next } });
  }

  if (!isDirector) {
    return (
      <div className="card p-12 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">Director only</div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          Supplier POs are restricted to the director to limit who sees the
          supplier ⇄ customer mapping.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Truck size={22} className="text-brand-600" /> Purchase Orders
          </h1>
          <p className="text-sm muted">
            Every supplier PO. Click a PO number to rename it; conflicts are
            rejected so two POs can never share a number.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={15} /> New PO
        </button>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
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

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by PO number or supplier…"
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input max-w-[180px]"
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="received">Received</option>
          <option value="closed">Closed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <div className="text-xs muted">
          <Filter size={12} className="inline mr-1" />
          {rows.length} of {pos.data?.length ?? 0}
        </div>
      </div>

      {pos.error ? (
        <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">Couldn't load purchase orders.</div>
            <div className="text-xs mt-0.5 break-all">
              {(pos.error as any)?.response?.data?.detail
                ?? (pos.error as any)?.message
                ?? "Request failed"}
            </div>
          </div>
        </div>
      ) : pos.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading purchase orders…
        </div>
      ) : !rows.length ? (
        <div className="card p-12 text-center">
          <div className="text-sm muted mb-3">
            {(pos.data?.length ?? 0) === 0
              ? "No purchase orders yet."
              : "No POs match your filters."}
          </div>
          {(pos.data?.length ?? 0) === 0 && (
            <button className="btn-primary" onClick={() => setOpenNew(true)}>
              <Plus size={14} /> Issue your first PO
            </button>
          )}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">PO number</th>
                <th className="th">Supplier</th>
                <th className="th">Project</th>
                <th className="th">PO date</th>
                <th className="th">Lead</th>
                <th className="th">Status</th>
                <th className="th text-right">Total</th>
                <th className="th w-8"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const editing = editingNumberId === p.id;
                return (
                  <tr
                    key={p.id}
                    className="tr-hover border-t border-ink-100 cursor-pointer"
                    onClick={() => { if (!editing) nav(`/purchase-orders/${p.id}`); }}
                  >
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      {editing ? (
                        <div className="flex items-center gap-1">
                          <input
                            autoFocus
                            className="input py-1 text-xs font-mono w-40"
                            value={draftNumber}
                            onChange={(e) => setDraftNumber(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitNumber(p);
                              if (e.key === "Escape") setEditingNumberId(null);
                            }}
                            disabled={patchPo.isPending}
                          />
                          <button
                            className="btn-ghost text-emerald-700"
                            onClick={() => commitNumber(p)}
                            disabled={patchPo.isPending}
                            title="Save"
                          >
                            {patchPo.isPending
                              ? <Loader2 size={13} className="animate-spin" />
                              : <Check size={13} />}
                          </button>
                          <button
                            className="btn-ghost"
                            onClick={() => setEditingNumberId(null)}
                            title="Cancel"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ) : (
                        <button
                          className="inline-flex items-center gap-1.5 font-mono text-xs text-brand-700 hover:underline"
                          onClick={() => startEditNumber(p)}
                          title="Click to rename"
                        >
                          {p.number}
                          <Pencil size={11} className="opacity-50" />
                        </button>
                      )}
                    </td>
                    <td className="td">{supplierName(p.supplier_id)}</td>
                    <td className="td font-mono text-xs">
                      {p.project_id ? p.project_id.slice(0, 8) : "—"}
                    </td>
                    <td className="td muted">{p.po_date ?? "—"}</td>
                    <td className="td muted tabular-nums">
                      {p.quoted_lead_days != null ? `${p.quoted_lead_days}d` : "—"}
                    </td>
                    <td className="td">
                      <span className={clsx(
                        "chip capitalize",
                        STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
                      )}>
                        {p.status}
                      </span>
                    </td>
                    <td className="td text-right tabular-nums">{idr(p.total ?? 0)}</td>
                    <td className="td text-right">
                      <ChevronRight size={14} className="text-ink-400" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {openNew && (
        <NewPOModal
          suppliers={suppliers.data ?? []}
          projects={projects.data ?? []}
          projectsLoading={projects.isLoading}
          onClose={() => setOpenNew(false)}
          onCreated={(number) => {
            qc.invalidateQueries({ queryKey: ["supplier-pos"] });
            setOpenNew(false);
            setFlash({ kind: "ok", text: `PO ${number} issued.` });
          }}
          onError={(msg) => setFlash({ kind: "err", text: msg })}
        />
      )}
    </div>
  );
}

function NewPOModal({
  suppliers, projects, projectsLoading, onClose, onCreated, onError,
}: {
  suppliers: SupplierLite[];
  projects: any[];
  projectsLoading: boolean;
  onClose: () => void;
  onCreated: (number: string) => void;
  onError: (msg: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [supplierId, setSupplierId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [poNumber, setPoNumber] = useState("");
  const [poDate, setPoDate] = useState(today);
  const [leadDays, setLeadDays] = useState("");
  const [total, setTotal] = useState("");
  const [description, setDescription] = useState("");

  const create = useMutation({
    mutationFn: () => api.post("/purchasing/po", {
      supplier_id: supplierId,
      project_id: projectId,
      number: poNumber.trim() || null,
      po_date: poDate || null,
      quoted_lead_days: leadDays ? Number(leadDays) : null,
      total: total ? Number(total) : 0,
      items: description ? [{ description, qty: 1 }] : [],
    }).then((r) => r.data),
    onSuccess: (r) => onCreated(r.number),
    onError: (e: any) => onError(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to create PO"
    ),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">New Purchase Order</h2>
          <p className="text-sm muted mt-0.5">
            Pick the supplier and the project. The number defaults to an
            auto-generated one; type your own if you want.
          </p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <Field label="Supplier *">
            {suppliers.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>No suppliers yet. Add one from the Purchasing page first.</span>
              </div>
            ) : (
              <select
                required
                className="input"
                value={supplierId}
                onChange={(e) => setSupplierId(e.target.value)}
              >
                <option value="">Choose a supplier…</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            )}
          </Field>

          <Field label="Project *">
            {projectsLoading ? (
              <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> Loading projects…
              </div>
            ) : projects.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>No projects yet. Open Operations and create one.</span>
              </div>
            ) : (
              <select
                required
                className="input"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
              >
                <option value="">Choose a project…</option>
                {projects.map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.code} {p.status ? `· ${p.status}` : ""}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="PO number">
              <input
                className="input font-mono text-sm"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                placeholder="Auto: PO-YYMMDD-NNN"
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                Leave blank for the next sequential number, or type your own.
              </span>
            </Field>
            <Field label="PO date *">
              <input
                type="date"
                required
                className="input"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                The day the PO is issued.
              </span>
            </Field>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Lead time (days)">
              <input
                type="number"
                min={0}
                className="input"
                value={leadDays}
                onChange={(e) => setLeadDays(e.target.value)}
              />
            </Field>
            <Field label="Total (Rp)">
              <input
                type="number"
                min={0}
                step="0.01"
                className="input"
                value={total}
                onChange={(e) => setTotal(e.target.value)}
              />
            </Field>
          </div>

          <Field label="Description (optional)">
            <textarea
              rows={2}
              className="input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What's being purchased…"
            />
          </Field>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button
              type="submit"
              className="btn-primary"
              disabled={create.isPending || !supplierId || !projectId}
            >
              {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Issue PO
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{label}</span>
      {children}
    </label>
  );
}
