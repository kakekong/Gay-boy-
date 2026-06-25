import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardList, Send, Truck, PackageCheck, CheckCircle2, ArrowRight,
  ShoppingCart, Plus, Loader2, Star, AlertCircle, X, Save, ChevronRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

interface PStage {
  key: string;
  label: string;
  icon: typeof ClipboardList;
  hint: string;
  to: string | null;
}

const STAGES: PStage[] = [
  { key: "PR",  label: "Purchase Request", icon: ClipboardList, hint: "Internal request",
    to: "/purchasing/stage/pr" },
  { key: "RFQ", label: "RFQ",              icon: Send,          hint: "Quote suppliers",
    to: "/purchasing/stage/rfq" },
  { key: "PO",  label: "Supplier PO",      icon: Truck,         hint: "Order placed",
    to: "/purchase-orders" },
  { key: "GR",  label: "Goods Receipt",    icon: PackageCheck,  hint: "Received",
    to: "/purchasing/stage/gr" },
  { key: "QC",  label: "QC",               icon: CheckCircle2,  hint: "Quality check",
    to: "/purchasing/stage/qc" },
];

interface Supplier {
  id: string;
  name: string;
  category: string | null;
  rating: number;
  lead_time_days_avg: number;
  qc_fail_rate: number;
}

export default function PurchasingPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";

  const [openNew, setOpenNew] = useState(false);
  const [openPO, setOpenPO] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  // Tab persisted across sessions so the user lands back where they left off.
  const [tab, setTab] = useState<"suppliers" | "pos" | "requests">(() => {
    const stored = localStorage.getItem("purchasing-tab");
    if (stored === "pos" || stored === "requests") return stored;
    return "suppliers";
  });
  function pickTab(t: "suppliers" | "pos" | "requests") {
    setTab(t);
    localStorage.setItem("purchasing-tab", t);
  }

  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as Supplier[]),
    retry: false,
  });

  // PO creation + the supplier→project mapping are director-only to avoid
  // leaking which supplier serves which customer to internal staff.
  const pos = useQuery({
    queryKey: ["supplier-pos"],
    queryFn: () => api.get("/purchasing/po").then((r) => r.data as any[]),
    enabled: isDirector,
    retry: false,
  });

  const projects = useQuery({
    queryKey: ["projects-min"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data as any[]),
    enabled: openPO && isDirector,
    retry: false,
  });

  // Live counts for the procurement-chain cards. Each stage endpoint is
  // purchasing-gated, same audience as this page.
  const prList  = useQuery({ queryKey: ["pr-list"],  queryFn: () => api.get("/purchasing/pr").then((r) => r.data as any[]),  retry: false });
  const rfqList = useQuery({ queryKey: ["rfq-list"], queryFn: () => api.get("/purchasing/rfq").then((r) => r.data as any[]), retry: false });
  const grList  = useQuery({ queryKey: ["gr-list"],  queryFn: () => api.get("/purchasing/gr").then((r) => r.data as any[]),  retry: false });
  const qcList  = useQuery({ queryKey: ["qc-list"],  queryFn: () => api.get("/purchasing/qc").then((r) => r.data as any[]),  retry: false });

  const stageCount = (key: string): number => {
    switch (key) {
      case "PR":  return prList.data?.filter((p: any) => p.status === "open" || p.status === "pending_approval").length ?? 0;
      case "RFQ": return rfqList.data?.length ?? 0;
      case "PO":  return pos.data?.filter((p: any) => p.status === "open" || p.status === "pending_approval").length ?? 0;
      case "GR":  return grList.data?.length ?? 0;
      case "QC":  return qcList.data?.length ?? 0;
      default:    return 0;
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <ShoppingCart size={22} className="text-brand-600" /> Purchasing
          </h1>
          <p className="text-sm muted">Track every document along the procurement chain.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => setOpenNew(true)}>
            <Plus size={15} /> New supplier
          </button>
          {isDirector && (
            <button className="btn-primary" onClick={() => setOpenPO(true)}>
              <Plus size={15} /> New PO
            </button>
          )}
        </div>
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

      {/* Tabs */}
      <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
        <button
          onClick={() => pickTab("suppliers")}
          className={clsx(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
            tab === "suppliers" ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
          )}
        >
          <Star size={14} /> Suppliers
          {suppliers.data && (
            <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
              {suppliers.data.length}
            </span>
          )}
        </button>
        <button
          onClick={() => pickTab("requests")}
          className={clsx(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
            tab === "requests" ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
          )}
        >
          <ClipboardList size={14} /> Requests
          {prList.data && (
            <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
              {prList.data.length}
            </span>
          )}
        </button>
        {isDirector && (
          <button
            onClick={() => pickTab("pos")}
            className={clsx(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              tab === "pos" ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
            )}
          >
            <Truck size={14} /> Purchase Orders
            {pos.data && (
              <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
                {pos.data.length}
              </span>
            )}
          </button>
        )}
      </div>

      <div className="card p-4 lg:p-6 overflow-x-auto">
        <div className="flex items-stretch gap-3 min-w-[700px]">
          {STAGES.map((s, i) => {
            const count = stageCount(s.key);
            const inner = (
              <div className="flex-1 rounded-xl border border-ink-200 hover:border-brand-300 transition-colors p-4 bg-white relative">
                <div className="flex items-center gap-2 text-ink-800">
                  <s.icon size={16} className="text-brand-600" />
                  <span className="font-semibold">{s.label}</span>
                </div>
                <div className="mt-1 text-xs muted">{s.hint}</div>
                <div className="mt-3 text-2xl font-semibold tabular-nums text-ink-900">
                  {count}
                </div>
                <div className="text-[11px] muted">open documents</div>
                <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-brand-700 font-semibold">
                  Open <ChevronRight size={11} />
                </div>
              </div>
            );
            return (
              <div key={s.key} className="flex items-stretch gap-2 flex-1">
                {s.to ? (
                  <Link to={s.to} className="flex-1 flex">{inner}</Link>
                ) : inner}
                {i < STAGES.length - 1 && (
                  <ArrowRight className="self-center text-ink-300 shrink-0" size={18} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {tab === "suppliers" && (
      <div className="card overflow-hidden">
        <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-semibold text-ink-900">Suppliers</div>
            <div className="text-xs muted">
              Vendors you buy from. Rating averages lead-time, QC pass rate, and price volatility.
            </div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted">
            {suppliers.data?.length ?? 0} total
          </div>
        </header>

        {suppliers.error ? (
          <div className="px-5 py-6 text-sm text-red-700 flex items-start gap-2">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <div className="flex-1">
              <div className="font-medium">
                Couldn't load suppliers
                {(suppliers.error as any)?.response?.status
                  ? ` (HTTP ${(suppliers.error as any).response.status})` : ""}.
              </div>
              <div className="text-xs mt-0.5 break-all">
                {(suppliers.error as any)?.response?.data?.errors?.[0]?.message
                  ?? (suppliers.error as any)?.response?.data?.detail
                  ?? (suppliers.error as any)?.message
                  ?? "Request failed"}
              </div>
              <button
                onClick={() => suppliers.refetch()}
                className="mt-2 text-xs underline hover:no-underline"
              >
                Retry
              </button>
            </div>
          </div>
        ) : suppliers.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !suppliers.data?.length ? (
          <div className="px-5 py-12 text-center">
            <div className="text-sm muted mb-3">No suppliers yet.</div>
            <button className="btn-primary" onClick={() => setOpenNew(true)}>
              <Plus size={14} /> Add your first supplier
            </button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Name</th>
                <th className="th">Category</th>
                <th className="th text-right">Rating</th>
                <th className="th text-right">Avg lead time</th>
                <th className="th text-right">QC fail rate</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.data.map((s) => (
                <tr
                  key={s.id}
                  className="tr-hover border-t border-ink-100 cursor-pointer"
                  onClick={() => nav(`/suppliers/${s.id}`)}
                >
                  <td className="td font-medium">{s.name}</td>
                  <td className="td muted">{s.category ?? "—"}</td>
                  <td className="td text-right">
                    <span className="inline-flex items-center gap-1 tabular-nums">
                      <Star size={12} className="text-amber-500" />
                      {(s.rating ?? 0).toFixed(2)}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">
                    {(s.lead_time_days_avg ?? 0).toFixed(1)} d
                  </td>
                  <td className="td text-right tabular-nums">
                    {((s.qc_fail_rate ?? 0) * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Purchase / inventory requests */}
      {tab === "requests" && (
      <div className="card overflow-hidden">
        <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-semibold text-ink-900">Purchase requests</div>
            <div className="text-xs muted">
              Demand raised from Inventory or the board. Each one needs director
              approval before purchasing sources it — pending requests show in
              the director's Approvals inbox.
            </div>
          </div>
          <Link to="/purchasing/stage/pr" className="text-xs text-brand-700 hover:underline">
            Open PR workspace →
          </Link>
        </header>
        {prList.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !prList.data?.length ? (
          <div className="px-5 py-12 text-center text-sm muted">No purchase requests yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Project</th>
                <th className="th">Requested by</th>
                <th className="th">Items</th>
                <th className="th">Status</th>
              </tr>
            </thead>
            <tbody>
              {prList.data.map((r: any) => (
                <tr key={r.id} className="tr-hover border-t border-ink-100">
                  <td className="td font-mono text-xs">{r.number}</td>
                  <td className="td font-mono text-xs">{r.project_code ?? "—"}</td>
                  <td className="td">{r.requested_by_name ?? "—"}</td>
                  <td className="td muted">{(r.items ?? []).length} line(s)</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      r.status === "open" ? "bg-emerald-50 text-emerald-700"
                      : r.status === "pending_approval" ? "bg-amber-50 text-amber-700"
                      : r.status === "cancelled" ? "bg-red-50 text-red-700"
                      : "bg-ink-100 text-ink-700")}>
                      {r.status?.replace(/_/g, " ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Supplier POs — director-only to limit who sees the supplier⇄customer mapping */}
      {tab === "pos" && isDirector && (
      <div className="card overflow-hidden">
        <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-semibold text-ink-900">Supplier purchase orders</div>
            <div className="text-xs muted">
              Director-only. Every PO must reference a supplier and a project.
              Suppliers see them in their portal and update dates that flow to
              the customer.
            </div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted">
            {pos.data?.length ?? 0} total
          </div>
        </header>

        {pos.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !pos.data?.length ? (
          <div className="px-5 py-12 text-center">
            <div className="text-sm muted mb-3">No purchase orders yet.</div>
            <button className="btn-primary" onClick={() => setOpenPO(true)}>
              <Plus size={14} /> Issue your first PO
            </button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Supplier</th>
                <th className="th">Project</th>
                <th className="th">PO date</th>
                <th className="th">Status</th>
                <th className="th text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {pos.data.map((p: any) => {
                const supplier = (suppliers.data ?? []).find((s) => s.id === p.supplier_id);
                return (
                  <tr key={p.id} className="tr-hover border-t border-ink-100">
                    <td className="td font-mono text-xs">{p.number}</td>
                    <td className="td">{supplier?.name ?? p.supplier_id.slice(0, 8)}</td>
                    <td className="td font-mono text-xs">
                      {p.project_id ? p.project_id.slice(0, 8) : "—"}
                    </td>
                    <td className="td muted">{p.po_date ?? "—"}</td>
                    <td className="td">
                      <span className="chip bg-ink-100 text-ink-700 uppercase">{p.status}</span>
                    </td>
                    <td className="td text-right tabular-nums">{idr(p.total ?? 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      )}

      {openNew && (
        <NewSupplierModal
          onClose={() => setOpenNew(false)}
          onCreated={(name) => {
            qc.invalidateQueries({ queryKey: ["suppliers"] });
            qc.invalidateQueries({ queryKey: ["suppliers-min"] });
            setOpenNew(false);
            setFlash({ kind: "ok", text: `Supplier "${name}" added.` });
          }}
          onError={(msg) => setFlash({ kind: "err", text: msg })}
        />
      )}
      {openPO && (
        <NewPOModal
          suppliers={suppliers.data ?? []}
          projects={projects.data ?? []}
          projectsLoading={projects.isLoading}
          onClose={() => setOpenPO(false)}
          onCreated={(number) => {
            qc.invalidateQueries({ queryKey: ["supplier-pos"] });
            setOpenPO(false);
            setFlash({ kind: "ok", text: `PO ${number} issued.` });
          }}
          onError={(msg) => setFlash({ kind: "err", text: msg })}
        />
      )}
    </div>
  );
}

function idr(n: number) { return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0)); }

function NewSupplierModal({ onClose, onCreated, onError }: {
  onClose: () => void;
  onCreated: (name: string) => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [rating, setRating] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactEmail, setContactEmail] = useState("");

  const create = useMutation({
    mutationFn: () => api.post("/purchasing/suppliers", {
      name: name.trim(),
      category: category.trim() || null,
      rating: rating ? Number(rating) : 0,
      contact: {
        name: contactName || undefined,
        phone: contactPhone || undefined,
        email: contactEmail || undefined,
      },
    }),
    onSuccess: () => onCreated(name.trim()),
    onError: (e: any) => onError(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to create supplier"
    ),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">New supplier</h2>
          <p className="text-sm muted mt-0.5">Add a vendor so you can issue POs against them.</p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <Field label="Name *">
            <input
              className="input" required
              value={name} onChange={(e) => setName(e.target.value)}
              placeholder="PT Sumber Logam Indonesia"
            />
          </Field>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Category">
              <input
                className="input"
                value={category} onChange={(e) => setCategory(e.target.value)}
                placeholder="raw_material / fabrication / shipping…"
              />
            </Field>
            <Field label="Initial rating (0–5)">
              <input
                className="input" type="number" min={0} max={5} step="0.1"
                value={rating} onChange={(e) => setRating(e.target.value)}
                placeholder="0"
              />
            </Field>
          </div>
          <div className="rounded-xl border border-ink-100 p-3 space-y-3">
            <div className="text-[10px] uppercase tracking-wider muted">Contact (optional)</div>
            <Field label="PIC name">
              <input
                className="input"
                value={contactName} onChange={(e) => setContactName(e.target.value)}
              />
            </Field>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Phone">
                <input
                  className="input"
                  value={contactPhone} onChange={(e) => setContactPhone(e.target.value)}
                />
              </Field>
              <Field label="Email">
                <input
                  className="input" type="email"
                  value={contactEmail} onChange={(e) => setContactEmail(e.target.value)}
                />
              </Field>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={create.isPending}>
              {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Create supplier
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

function NewPOModal({
  suppliers, projects, projectsLoading, onClose, onCreated, onError,
}: {
  suppliers: Supplier[];
  projects: any[];
  projectsLoading: boolean;
  onClose: () => void;
  onCreated: (number: string) => void;
  onError: (msg: string) => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [poNumber, setPoNumber] = useState("");
  const [poDate, setPoDate] = useState(new Date().toISOString().slice(0, 10));
  const [leadDays, setLeadDays] = useState("");
  const [total, setTotal] = useState("");
  const [totalEdited, setTotalEdited] = useState(false);
  const [description, setDescription] = useState("");

  const [localErr, setLocalErr] = useState<string | null>(null);

  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

  // Pull the project's approved price request so the PO auto-fills the buying
  // (cost) price purchasing already entered — no retyping.
  const prefill = useQuery({
    queryKey: ["po-prefill", projectId],
    queryFn: () => api.get("/purchasing/po/prefill", { params: { project_id: projectId } })
      .then((r) => r.data),
    enabled: !!projectId,
  });
  const linkedPR: string | null = prefill.data?.price_request_id ?? null;
  const prItems: any[] = prefill.data?.items ?? [];
  const prTotal: number = Number(prefill.data?.total ?? 0);
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
      items: prItems.length ? prItems : (description ? [{ description, qty: 1 }] : []),
    }).then((r) => r.data),
    onSuccess: (r) => onCreated(r.number),
    onError: (e: any) => {
      const status = e?.response?.status;
      const msg = e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to create PO";
      setLocalErr(status ? `${msg} (HTTP ${status})` : msg);
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
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">Issue purchase order</h2>
          <p className="text-sm muted mt-0.5">
            The PO must reference a supplier and a project so the supplier can
            update shipping dates that flow to the customer.
          </p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); attemptSubmit(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Supplier *</span>
            {suppliers.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>No suppliers yet. Click "+ New supplier" first.</span>
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
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Project *</span>
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
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setTotal("");
                  setTotalEdited(false);
                }}
              >
                <option value="">Choose a project…</option>
                {projects.map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.code} {p.status ? `· ${p.status}` : ""}
                  </option>
                ))}
              </select>
            )}
          </label>

          {projectId && (
            prefill.isLoading ? (
              <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> Checking the price request…
              </div>
            ) : linkedPR ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 text-sm">
                <div className="flex items-center gap-2 text-emerald-800 font-medium">
                  <CheckCircle2 size={14} className="shrink-0" />
                  Linked to price request {prefill.data?.price_request_number ?? ""}
                </div>
                <p className="text-[11px] text-emerald-700/90 mt-0.5">
                  Buying prices below are pulled from purchasing's costing — no need to retype.
                </p>
                {prItems.length > 0 && (
                  <table className="w-full text-xs mt-2">
                    <thead className="text-ink-500">
                      <tr>
                        <th className="text-left font-medium py-1">Item</th>
                        <th className="text-right font-medium py-1">Qty</th>
                        <th className="text-right font-medium py-1">Unit cost</th>
                        <th className="text-right font-medium py-1">Amount</th>
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
                        <td className="py-1" colSpan={3}>Total buying price</td>
                        <td className="py-1 text-right tabular-nums">{idr(prTotal)}</td>
                      </tr>
                    </tfoot>
                  </table>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2 text-[11px] muted">
                This project has no linked price request, so there's no buying price to pull in.
                Enter the line and total manually below.
              </div>
            )
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                PO number
              </span>
              <input
                className="input"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                placeholder="Auto-generated if blank (PO-YYMMDD-NNN)"
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                Leave blank to use the next sequential number.
              </span>
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                PO date <span className="text-red-500">*</span>
              </span>
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
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">Lead time (days)</span>
              <input
                type="number"
                min={0}
                className="input"
                value={leadDays}
                onChange={(e) => setLeadDays(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">Total (Rp)</span>
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
                  Pre-filled from the price request — override if you negotiated a different price.
                </span>
              )}
            </label>
          </div>

          {!(linkedPR && prItems.length > 0) && (
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">Description (optional)</span>
              <textarea
                rows={2}
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What's being purchased…"
              />
            </label>
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
                  Need: {!supplierId && <span className="font-semibold">supplier</span>}
                  {!supplierId && !projectId && " · "}
                  {!projectId && <span className="font-semibold">project</span>}
                </>
              )}
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
              <button
                type="submit"
                className="btn-primary"
                disabled={create.isPending}
              >
                {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                Issue PO
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
