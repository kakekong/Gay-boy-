import { useMemo, useState } from "react";
import { ModalCloseX } from "@/components/ModalCloseX";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  Truck, Plus, Loader2, AlertCircle, X, Save, Pencil, Check,
  Search, Filter, ChevronRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { UserLink } from "@/components/UserLink";
import { T, t } from "@/store/lang";

interface SupplierLite {
  id: string;
  name: string;
}
interface PO {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  project_id: string | null;
  project_code: string | null;
  customer_id: string | null;
  customer_name: string | null;
  sales_pic_id: string | null;
  sales_pic_name: string | null;
  po_date: string | null;
  total: number;
  quoted_lead_days: number | null;
  items: Array<{ description?: string; qty?: number }>;
  created_at: string;
}

const STATUS_CHIP: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
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
    enabled: openNew,
    retry: false,
  });

  const patchPo = useMutation({
    // axios treats 202 as a thrown error because we raise HTTPException(202)
    // on the backend's approval path; catch both shapes so the user always
    // sees a useful message.
    mutationFn: (vars: { id: string; body: Record<string, any> }) =>
      api.patch(`/purchasing/po/${vars.id}`, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["supplier-pos"] });
      setEditingNumberId(null);
    },
    onError: (e: any) => {
      const status = e?.response?.status;
      if (status === 202) {
        setEditingNumberId(null);
        qc.invalidateQueries({ queryKey: ["supplier-pos"] });
        setFlash({
          kind: "ok",
          text: e?.response?.data?.detail
            ?? "Submitted for director approval.",
        });
        return;
      }
      setFlash({
        kind: "err",
        text: e?.response?.data?.errors?.[0]?.message
          ?? e?.response?.data?.detail
          ?? e?.message
          ?? "Update failed",
      });
    },
  });

  const supplierName = (po: PO) =>
    po.supplier_name
    ?? (suppliers.data ?? []).find((s) => s.id === po.supplier_id)?.name
    ?? po.supplier_id.slice(0, 8);

  const rows = useMemo(() => {
    let list = pos.data ?? [];
    if (statusFilter) list = list.filter((p) => p.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((p) =>
        p.number.toLowerCase().includes(q)
        || supplierName(p).toLowerCase().includes(q)
        || (p.customer_name ?? "").toLowerCase().includes(q)
        || (p.sales_pic_name ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  // supplierName closes over suppliers.data
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

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Truck size={22} className="text-brand-600" /> {T("Purchase Orders")}</h1>
          <p className="text-sm muted">
            {isDirector
              ? T("Every supplier PO. Click a PO number to rename it.")
              : T("Every PO change is submitted to the director for approval before it takes effect.")}
          </p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={15} /> {T("New PO")}</button>
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
            placeholder={T("Search by PO number, supplier, customer or sales rep…")}
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input max-w-[200px]"
        >
          <option value="">{T("All statuses")}</option>
          <option value="pending_approval">{T("Pending approval")}</option>
          <option value="open">{T("Open")}</option>
          <option value="received">{T("Received")}</option>
          <option value="closed">{T("Closed")}</option>
          <option value="cancelled">{T("Cancelled")}</option>
        </select>
        <div className="text-xs muted">
          <Filter size={12} className="inline mr-1" />
          {rows.length} {T("of")}{" "}{pos.data?.length ?? 0}
        </div>
      </div>

      {pos.error ? (
        <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">{T("Couldn't load purchase orders.")}</div>
            <div className="text-xs mt-0.5 break-all">
              {(pos.error as any)?.response?.data?.detail
                ?? (pos.error as any)?.message
                ?? T("Request failed")}
            </div>
          </div>
        </div>
      ) : pos.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading purchase orders…")}</div>
      ) : !rows.length ? (
        <div className="card p-12 text-center">
          <div className="text-sm muted mb-3">
            {(pos.data?.length ?? 0) === 0
              ? T("No purchase orders yet.")
              : T("No POs match your filters.")}
          </div>
          {(pos.data?.length ?? 0) === 0 && (
            <button className="btn-primary" onClick={() => setOpenNew(true)}>
              <Plus size={14} /> {T("Issue your first PO")}</button>
          )}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("PO number")}</th>
                <th className="th">{T("Supplier")}</th>
                <th className="th">{T("Customer")}</th>
                <th className="th">{T("Sales rep")}</th>
                <th className="th">{T("Project")}</th>
                <th className="th">{T("PO date")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Total")}</th>
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
                            title={T("Save")}
                          >
                            {patchPo.isPending
                              ? <Loader2 size={13} className="animate-spin" />
                              : <Check size={13} />}
                          </button>
                          <button
                            className="btn-ghost"
                            onClick={() => setEditingNumberId(null)}
                            title={T("Cancel")}
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ) : (
                        <button
                          className="inline-flex items-center gap-1.5 font-mono text-xs text-brand-700 hover:underline"
                          onClick={() => startEditNumber(p)}
                          title={T("Click to rename")}
                        >
                          {p.number}
                          <Pencil size={11} className="opacity-50" />
                        </button>
                      )}
                    </td>
                    <td className="td">{supplierName(p)}</td>
                    <td className="td">
                      {p.customer_id && p.customer_name ? (
                        <a
                          href={`/customers/${p.customer_id}`}
                          onClick={(e) => { e.stopPropagation(); }}
                          className="text-brand-700 hover:underline"
                        >
                          {p.customer_name}
                        </a>
                      ) : "—"}
                    </td>
                    <td className="td muted"><UserLink id={p.sales_pic_id} name={p.sales_pic_name} /></td>
                    <td className="td font-mono text-xs">
                      {p.project_id
                        ? (p.project_code ?? p.project_id.slice(0, 8))
                        : "—"}
                    </td>
                    <td className="td muted">{p.po_date ?? "—"}</td>
                    <td className="td">
                      <span className={clsx(
                        "chip capitalize",
                        STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
                      )}>
                        {T(p.status.replace(/_/g, " "))}
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
          onCreated={(number, pendingApproval) => {
            qc.invalidateQueries({ queryKey: ["supplier-pos"] });
            setOpenNew(false);
            setFlash({
              kind: "ok",
              text: pendingApproval
                ? `PO ${number} submitted for director approval.`
                : `PO ${number} issued.`,
            });
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
  onCreated: (number: string, pendingApproval: boolean) => void;
  onError: (msg: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [supplierId, setSupplierId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [poNumber, setPoNumber] = useState("");
  const [poDate, setPoDate] = useState(today);
  const [leadDays, setLeadDays] = useState("");
  const [total, setTotal] = useState("");
  const [totalEdited, setTotalEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);

  const [manualPrId, setManualPrId] = useState("");

  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

  // Once a project is chosen, pull its approved price request so the PO can
  // auto-fill the buying (cost) price purchasing already entered — no retyping.
  // If a project isn't auto-linked, the user can pick a price request manually
  // (manualPrId), which takes precedence.
  const prefill = useQuery({
    queryKey: ["po-prefill", projectId, manualPrId],
    queryFn: () => api.get("/purchasing/po/prefill", {
      params: manualPrId ? { price_request_id: manualPrId } : { project_id: projectId },
    }).then((r) => r.data),
    enabled: !!projectId,
  });
  // Approved price requests, offered as a manual fallback link.
  const prOptions = useQuery({
    queryKey: ["pr-options"],
    queryFn: () => api.get("/purchasing/po/price-request-options").then((r) => r.data),
    enabled: !!projectId,
  });
  const linkedPR: string | null = prefill.data?.price_request_id ?? null;
  const prItems: any[] = prefill.data?.items ?? [];
  const prTotal: number = Number(prefill.data?.total ?? 0);

  // When the price request loads, seed the total from it (unless the user has
  // already typed their own — purchasing may negotiate a different figure).
  if (linkedPR && !totalEdited && total === "" && prTotal > 0) {
    setTotal(String(prTotal));
  }

  const create = useMutation({
    mutationFn: () => api.post("/purchasing/po", {
      supplier_id: supplierId,
      project_id: projectId,
      number: poNumber.trim() || null,
      po_date: poDate || null,
      quoted_lead_days: leadDays ? Number(leadDays) : null,
      total: total ? Number(total) : 0,
      price_request_id: linkedPR,
      // Prefer the price-request lines (with buying prices); fall back to the
      // free-text description if there's no linked price request.
      items: prItems.length ? prItems : (description ? [{ description, qty: 1 }] : []),
    }).then((r) => r.data),
    onSuccess: (r) => onCreated(r.number, !!r.pending_approval),
    onError: (e: any) => {
      const httpStatus = e?.response?.status;
      const msg = e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to create PO";
      // Show the failure right inside the modal so the user can fix and
      // retry without losing their input — and also bubble up so the
      // outer flash banner echoes it.
      setLocalErr(httpStatus ? `${msg} (HTTP ${httpStatus})` : msg);
      onError(msg);
    },
  });

  function attemptSubmit() {
    setLocalErr(null);
    const missing: string[] = [];
    if (!supplierId) missing.push("supplier");
    if (!projectId) missing.push("project");
    if (missing.length) {
      setLocalErr(`Please choose a ${missing.join(" and a ")} first.`);
      return;
    }
    create.mutate();
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      {/* No onClick: a stray click beside the box must not throw away
          what has been typed into it. The X and Escape close it. */}
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <ModalCloseX onClose={onClose} />
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">{T("New Purchase Order")}</h2>
          <p className="text-sm muted mt-0.5">
            {T("Pick the supplier and the project. The number defaults to an auto-generated one; type your own if you want.")}</p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); attemptSubmit(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <Field label={T("Supplier *")}>
            {suppliers.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{T("No suppliers yet. Add one from the Purchasing page first.")}</span>
              </div>
            ) : (
              <select
                required
                className="input"
                value={supplierId}
                onChange={(e) => setSupplierId(e.target.value)}
              >
                <option value="">{T("Choose a supplier…")}</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            )}
          </Field>

          <Field label={T("Project *")}>
            {projectsLoading ? (
              <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> {T("Loading projects…")}</div>
            ) : projects.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{T("No projects yet. Open Operations and create one.")}</span>
              </div>
            ) : (
              <select
                required
                className="input"
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  // New project → re-seed the total from its price request.
                  setTotal("");
                  setTotalEdited(false);
                  setManualPrId("");
                }}
              >
                <option value="">{T("Choose a project…")}</option>
                {projects.map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.code} {p.status ? `· ${p.status}` : ""}
                  </option>
                ))}
              </select>
            )}
          </Field>

          {projectId && (
            prefill.isLoading ? (
              <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> {T("Checking the price request…")}</div>
            ) : linkedPR ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 text-sm">
                <div className="flex items-center gap-2 text-emerald-800 font-medium">
                  <Check size={14} className="shrink-0" />
                  {T("Linked to price request")}{" "}
                  {/* Same tab — see the twin of this panel in Purchasing.tsx:
                      a new tab loses the session for anyone who did not tick
                      "keep me signed in". */}
                  <Link to={`/price-requests?open=${linkedPR}`}
                    className="font-mono underline underline-offset-2 hover:text-emerald-900"
                    title={T("Open this price request")}>
                    {prefill.data?.price_request_number ?? ""}
                  </Link>
                </div>
                <p className="text-[11px] text-emerald-700/90 mt-0.5">
                  {(prefill.data?.uncosted ?? 0) > 0
                    ? t(`${prefill.data.uncosted} of ${prItems.length} line${prItems.length === 1 ? "" : "s"} on this request has no buying price yet — those show Rp 0. Cost them on the price request, or type the total in below.`,
                        `${prefill.data.uncosted} dari ${prItems.length} baris pada permintaan ini belum ada harga beli — yang itu tampil Rp 0. Isi biayanya di permintaan harga, atau ketik totalnya di bawah.`)
                    : T("Buying prices below are pulled from purchasing's costing — no need to retype.")}</p>
                {prItems.length > 0 && (
                  <table className="w-full text-xs mt-2">
                    <thead className="text-ink-500">
                      <tr>
                        <th className="text-left font-medium py-1">{T("Item")}</th>
                        <th className="text-right font-medium py-1">{T("Qty")}</th>
                        <th className="text-right font-medium py-1">{T("Unit cost")}</th>
                        <th className="text-right font-medium py-1">{T("Amount")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prItems.map((it, i) => (
                        <tr key={i} className="border-t border-emerald-100">
                          <td className="py-1 pr-2">{it.description || "—"}</td>
                          <td className="py-1 text-right tabular-nums">
                            {it.qty}{it.uom ? ` ${it.uom}` : ""}
                          </td>
                          <td className="py-1 text-right tabular-nums">{idr(it.unit_price)}</td>
                          <td className="py-1 text-right tabular-nums">{idr(it.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-emerald-200 font-medium">
                        <td className="py-1" colSpan={3}>{T("Total buying price")}</td>
                        <td className="py-1 text-right tabular-nums">{idr(prTotal)}</td>
                      </tr>
                    </tfoot>
                  </table>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2.5 space-y-1.5">
                <p className="text-[11px] muted">
                  {T("This project isn't auto-linked to a price request. Pick one to pull in its buying prices, or enter the total manually below.")}</p>
                <select
                  className="input text-sm"
                  value={manualPrId}
                  onChange={(e) => { setManualPrId(e.target.value); setTotal(""); setTotalEdited(false); }}
                >
                  <option value="">{T("No price request — enter manually")}</option>
                  {(prOptions.data ?? []).map((o: any) => (
                    <option key={o.id} value={o.id}>
                      {o.number} · {o.line_count} {T("line")}{o.line_count === 1 ? "" : "s"} · {idr(o.total_cost)}
                    </option>
                  ))}
                </select>
              </div>
            )
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={T("PO number")}>
              <input
                className="input font-mono text-sm"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                placeholder={T("Auto: PO-YYMMDD-NNN")}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("Leave blank for the next sequential number, or type your own.")}</span>
            </Field>
            <Field label={T("PO date *")}>
              <input
                type="date"
                required
                className="input"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("The day the PO is issued.")}</span>
            </Field>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={T("Lead time (days)")}>
              <input
                type="number"
                min={0}
                className="input"
                value={leadDays}
                onChange={(e) => setLeadDays(e.target.value)}
              />
            </Field>
            <Field label={T("Total (Rp)")}>
              <input
                type="number"
                min={0}
                step="0.01"
                className="input"
                value={total}
                onChange={(e) => { setTotal(e.target.value); setTotalEdited(true); }}
              />
              {linkedPR && (
                <span className="block text-[10px] text-ink-400 mt-1">
                  {T("Pre-filled from the price request — override if you negotiated a different price.")}</span>
              )}
            </Field>
          </div>

          {!(linkedPR && prItems.length > 0) && (
            <Field label={T("Description (optional)")}>
              <textarea
                rows={2}
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={T("What's being purchased…")}
              />
            </Field>
          )}

          {localErr && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{localErr}</span>
            </div>
          )}

          <div className="flex items-center justify-between gap-2 pt-2 flex-wrap">
            <div className="text-[11px] muted">
              {(!supplierId || !projectId) && (
                <>
                  {T("Need:")}{" "}{!supplierId && <span className="font-semibold">{T("supplier")}</span>}
                  {!supplierId && !projectId && " · "}
                  {!projectId && <span className="font-semibold">{T("project")}</span>}
                </>
              )}
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
              {/* Only disable on pending, not on missing fields — clicking
                  while incomplete now surfaces an inline error instead of
                  looking unresponsive. */}
              <button
                type="submit"
                className="btn-primary"
                disabled={create.isPending}
              >
                {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {T("Issue PO")}</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{T(label)}</span>
      {children}
    </label>
  );
}
