import { useEffect, useRef, useState } from "react";
import { ModalCloseX } from "@/components/ModalCloseX";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardList, Send, Truck, PackageCheck, CheckCircle2, ArrowRight,
  ShoppingCart, Plus, Loader2, Star, AlertCircle, X, Save, ChevronRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { T, t } from "@/store/lang";
import { CURRENCIES } from "@/lib/currency";
import { PriceRequestLines, lineAmount } from "@/components/PriceRequestLines";

interface PStage {
  key: string;
  label: string;
  icon: typeof ClipboardList;
  hint: string;
  to: string | null;
}

// The procurement chain — the separate Purchase Request stage was dropped as
// redundant with the upstream Price Request → Director approval (no RFQ
// comparison in this flow). The supplier PO is the trigger that moves the
// project to the purchasing stage.
const STAGES: PStage[] = [
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

/** A price request addressed to one supplier — the buy side. */
interface SPR {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  price_request_id: string | null;
  price_request_number: string | null;
  items: any[];
  notes: string | null;
  currency: string;
  valid_until: string | null;
  quoted_lead_days: number | null;
  sent_at: string | null;
  quoted_at: string | null;
  applied_at: string | null;
  quoted_total: number | null;
  lines_quoted: number;
  lines_total: number;
}

const SPR_CHIP: Record<string, string> = {
  draft:     "bg-ink-100 text-ink-700",
  sent:      "bg-amber-50 text-amber-700",
  quoted:    "bg-blue-50 text-blue-700",
  closed:    "bg-emerald-50 text-emerald-700",
  cancelled: "bg-red-50 text-red-700",
};

export default function PurchasingPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";
  // Admin reach this page for the supplier directory, and nothing else on it.
  // What a vendor charges us is not theirs to read — the buy-side price
  // request is that and only that, so the tab does not exist for them.
  const seesBuySide = me?.role !== "admin";

  const [openNew, setOpenNew] = useState(false);
  const [openPO, setOpenPO] = useState(false);
  const [openSPR, setOpenSPR] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  // Tab persisted across sessions so the user lands back where they left off.
  const [tab, setTab] = useState<"suppliers" | "prices" | "pos">(() => {
    const stored = localStorage.getItem("purchasing-tab");
    // A remembered tab this role can no longer open would land them on a blank
    // page with no way to tell why.
    if (stored === "prices" && me?.role === "admin") return "suppliers";
    if (stored === "pos" || stored === "prices") return stored;
    return "suppliers";
  });
  function pickTab(t: "suppliers" | "prices" | "pos") {
    setTab(t);
    localStorage.setItem("purchasing-tab", t);
  }

  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as Supplier[]),
    retry: false,
  });

  // The buy side of a price request: what we asked vendors to charge. Same
  // audience as this page, so no extra gate — sales never reaches it at all.
  const priceReqs = useQuery({
    queryKey: ["supplier-price-requests"],
    queryFn: () => api.get("/purchasing/price-requests").then((r) => r.data as SPR[]),
    enabled: seesBuySide,
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
  const grList  = useQuery({ queryKey: ["gr-list"],  queryFn: () => api.get("/purchasing/gr").then((r) => r.data as any[]),  enabled: seesBuySide, retry: false });
  const qcList  = useQuery({ queryKey: ["qc-list"],  queryFn: () => api.get("/purchasing/qc").then((r) => r.data as any[]),  enabled: seesBuySide, retry: false });

  const stageCount = (key: string): number => {
    switch (key) {
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
            <ShoppingCart size={22} className="text-brand-600" /> {T("Purchasing")}</h1>
          <p className="text-sm muted">{T("Track every document along the procurement chain.")}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => setOpenNew(true)}>
            <Plus size={15} /> {T("New supplier")}</button>
          {seesBuySide && (
            <button className="btn-ghost" onClick={() => setOpenSPR(true)}>
              <Plus size={15} /> {T("Ask suppliers for a price")}</button>
          )}
          {isDirector && (
            <button className="btn-primary" onClick={() => setOpenPO(true)}>
              <Plus size={15} /> {T("New PO")}</button>
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
          <Star size={14} /> {T("Suppliers")}{suppliers.data && (
            <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
              {suppliers.data.length}
            </span>
          )}
        </button>
        {seesBuySide && (
        <button
          onClick={() => pickTab("prices")}
          className={clsx(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
            tab === "prices" ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
          )}
        >
          <ClipboardList size={14} /> {T("Price requests")}{priceReqs.data && (
            <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
              {priceReqs.data.length}
            </span>
          )}
        </button>
        )}
        {isDirector && (
          <button
            onClick={() => pickTab("pos")}
            className={clsx(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              tab === "pos" ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
            )}
          >
            <Truck size={14} /> {T("Purchase Orders")}{pos.data && (
              <span className="ml-1 text-[10px] font-semibold tabular-nums opacity-60">
                {pos.data.length}
              </span>
            )}
          </button>
        )}
      </div>

      {/* Supplier PO → goods receipt → QC. All three endpoints are closed to
          admin now, so for them the strip would be three cards reading zero
          that 403 on click. */}
      {seesBuySide && (
      <div className="card p-4 lg:p-6 overflow-x-auto">
        <div className="flex items-stretch gap-3 min-w-[700px]">
          {STAGES.map((s, i) => {
            const count = stageCount(s.key);
            const inner = (
              <div className="flex-1 rounded-xl border border-ink-200 hover:border-brand-300 transition-colors p-4 bg-white relative">
                <div className="flex items-center gap-2 text-ink-800">
                  <s.icon size={16} className="text-brand-600" />
                  <span className="font-semibold">{T(s.label)}</span>
                </div>
                <div className="mt-1 text-xs muted">{T(s.hint)}</div>
                <div className="mt-3 text-2xl font-semibold tabular-nums text-ink-900">
                  {count}
                </div>
                <div className="text-[11px] muted">{T("open documents")}</div>
                <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-brand-700 font-semibold">
                  {T("Open")}{" "}<ChevronRight size={11} />
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
      )}

      {tab === "suppliers" && (
      <div className="card overflow-hidden">
        <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-semibold text-ink-900">{T("Suppliers")}</div>
            <div className="text-xs muted">
              {T("Vendors you buy from. Rating averages lead-time, QC pass rate, and price volatility.")}</div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted">
            {suppliers.data?.length ?? 0} {T("total")}</div>
        </header>

        {suppliers.error ? (
          <div className="px-5 py-6 text-sm text-red-700 flex items-start gap-2">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <div className="flex-1">
              <div className="font-medium">
                {T("Couldn't load suppliers")}{(suppliers.error as any)?.response?.status
                  ? ` (HTTP ${(suppliers.error as any).response.status})` : ""}.
              </div>
              <div className="text-xs mt-0.5 break-all">
                {(suppliers.error as any)?.response?.data?.errors?.[0]?.message
                  ?? (suppliers.error as any)?.response?.data?.detail
                  ?? (suppliers.error as any)?.message
                  ?? T("Request failed")}
              </div>
              <button
                onClick={() => suppliers.refetch()}
                className="mt-2 text-xs underline hover:no-underline"
              >
                {T("Retry")}</button>
            </div>
          </div>
        ) : suppliers.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
        ) : !suppliers.data?.length ? (
          <div className="px-5 py-12 text-center">
            <div className="text-sm muted mb-3">{T("No suppliers yet.")}</div>
            <button className="btn-primary" onClick={() => setOpenNew(true)}>
              <Plus size={14} /> {T("Add your first supplier")}</button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("Name")}</th>
                <th className="th">{T("Category")}</th>
                <th className="th text-right">{T("Rating")}</th>
                <th className="th text-right">{T("Avg lead time")}</th>
                <th className="th text-right">{T("QC fail rate")}</th>
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

      {/* Price requests to suppliers — the buy side of the sell-side PR.
          Purchasing used to ask two or three vendors on WhatsApp and type the
          winning number into the cost field; the losing quotes, the lead times
          and how long each price held went nowhere. */}
      {tab === "prices" && seesBuySide && (
      <div className="card overflow-hidden">
        <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-semibold text-ink-900">{T("Price requests to suppliers")}</div>
            <div className="text-xs muted">
              {T("What you asked each vendor to charge, and what they answered. Apply the one you take as the cost on the price request it is costing.")}</div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted">
            {priceReqs.data?.length ?? 0} {T("total")}</div>
        </header>

        {priceReqs.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
        ) : !priceReqs.data?.length ? (
          <div className="px-5 py-12 text-center">
            <div className="text-sm muted mb-3">{T("Nothing asked yet.")}</div>
            <button className="btn-primary" onClick={() => setOpenSPR(true)}>
              <Plus size={14} /> {T("Ask suppliers for a price")}</button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("Number")}</th>
                <th className="th">{T("Supplier")}</th>
                <th className="th">{T("Costing")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Lines answered")}</th>
                <th className="th text-right">{T("Quoted total")}</th>
              </tr>
            </thead>
            <tbody>
              {priceReqs.data.map((r) => (
                <tr key={r.id} className="tr-hover border-t border-ink-100 cursor-pointer"
                  onClick={() => nav(`/purchasing/price-requests/${r.id}`)}>
                  <td className="td font-mono text-xs">{r.number}</td>
                  <td className="td">{r.supplier_name ?? "—"}</td>
                  <td className="td font-mono text-xs muted">
                    {r.price_request_number ?? T("standalone")}
                  </td>
                  <td className="td">
                    <span className={clsx("chip uppercase", SPR_CHIP[r.status] ?? "bg-ink-100 text-ink-700")}>
                      {r.status}
                    </span>
                    {r.applied_at && (
                      <span className="chip bg-emerald-50 text-emerald-700 ml-1">
                        {T("used as cost")}
                      </span>
                    )}
                  </td>
                  <td className="td text-right tabular-nums">
                    {r.lines_quoted}/{r.lines_total}
                  </td>
                  <td className="td text-right tabular-nums">
                    {r.quoted_total == null ? "—" : idr(r.quoted_total)}
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
            <div className="font-semibold text-ink-900">{T("Supplier purchase orders")}</div>
            <div className="text-xs muted">
              {T("Director-only. Every PO must reference a supplier and a project. Suppliers see them in their portal and update dates that flow to the customer.")}</div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted">
            {pos.data?.length ?? 0} {T("total")}</div>
        </header>

        {pos.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
        ) : !pos.data?.length ? (
          <div className="px-5 py-12 text-center">
            <div className="text-sm muted mb-3">{T("No purchase orders yet.")}</div>
            <button className="btn-primary" onClick={() => setOpenPO(true)}>
              <Plus size={14} /> {T("Issue your first PO")}</button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("Number")}</th>
                <th className="th">{T("Supplier")}</th>
                <th className="th">{T("Project")}</th>
                <th className="th">{T("PO date")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Total")}</th>
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

      {openSPR && (
        <AskSuppliersModal
          suppliers={suppliers.data ?? []}
          onClose={() => setOpenSPR(false)}
          onCreated={(n) => {
            qc.invalidateQueries({ queryKey: ["supplier-price-requests"] });
            setOpenSPR(false);
            pickTab("prices");
            setFlash({ kind: "ok", text: `Asked ${n} supplier(s) for a price.` });
          }}
          onError={(msg) => setFlash({ kind: "err", text: msg })}
        />
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

/**
 * A supplier you can actually use, filed in one pass.
 *
 * It used to take a name, a category, a rating and one loose phone number,
 * which is not enough to raise a PO against: you still have to know where the
 * goods are collected from, who to ring when the delivery slips, and which of
 * the three people at that company signs the invoice. Those all lived in
 * somebody's phone. Same shape as the customer wizard, for the same reason.
 *
 * Files are uploaded after the row exists — they need an id to hang from —
 * so the supplier is created first and the queue is drained onto it. A file
 * that fails to upload does not undo the supplier: the row is the valuable
 * part and the upload can be retried on its page.
 */
interface DraftContact {
  name: string;
  position: string;
  phone: string;
  whatsapp: string;
  email: string;
}

const EMPTY_CONTACT: DraftContact = {
  name: "", position: "", phone: "", whatsapp: "", email: "",
};

function NewSupplierModal({ onClose, onCreated, onError }: {
  onClose: () => void;
  onCreated: (name: string) => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [rating, setRating] = useState("");
  const [companyAddress, setCompanyAddress] = useState("");
  const [warehouseAddress, setWarehouseAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [whatsapp, setWhatsapp] = useState("");
  const [email, setEmail] = useState("");
  const [contacts, setContacts] = useState<DraftContact[]>([{ ...EMPTY_CONTACT }]);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);

  const updateContact = (i: number, patch: Partial<DraftContact>) =>
    setContacts((cur) => cur.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  const create = useMutation({
    mutationFn: async () => {
      const filled = contacts.filter((c) => c.name.trim());
      const res = await api.post("/purchasing/suppliers", {
        name: name.trim(),
        category: category.trim() || null,
        rating: rating ? Number(rating) : 0,
        company_address: companyAddress.trim() || null,
        warehouse_address: warehouseAddress.trim() || null,
        phone: phone.trim() || null,
        whatsapp: whatsapp.trim() || null,
        email: email.trim() || null,
        contacts: filled.map((c, i) => ({
          name: c.name.trim(),
          position: c.position.trim() || null,
          phone: c.phone.trim() || null,
          whatsapp: c.whatsapp.trim() || null,
          email: c.email.trim() || null,
          // The first person typed is the one to ring first, unless somebody
          // says otherwise later on the supplier's page.
          is_primary: i === 0,
        })),
      });
      const id = res.data?.id as string | undefined;
      if (id && files.length) {
        setUploading(true);
        for (const f of files) {
          const fd = new FormData();
          fd.append("owner_type", "supplier");
          fd.append("owner_id", id);
          fd.append("file", f);
          await api.post("/attachments", fd);
        }
      }
      return res.data;
    },
    onSuccess: () => onCreated(name.trim()),
    onError: (e: any) => {
      setUploading(false);
      onError(
        e?.response?.data?.errors?.[0]?.message
          ?? e?.response?.data?.detail
          ?? e?.message
          ?? "Failed to create supplier",
      );
    },
  });

  const busy = create.isPending || uploading;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      {/* No onClick: a stray click beside the box must not throw away
          what has been typed into it. The X and Escape close it. */}
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <ModalCloseX onClose={onClose} />
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">{T("New supplier")}</h2>
          <p className="text-sm muted mt-0.5">{T("Add a vendor so you can issue POs against them.")}</p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-4"
        >
          <Field label={T("Name *")}>
            <input
              className="input" required
              value={name} onChange={(e) => setName(e.target.value)}
              placeholder={T("PT Sumber Logam Indonesia")}
            />
          </Field>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={T("Category")}>
              <input
                className="input"
                value={category} onChange={(e) => setCategory(e.target.value)}
                placeholder={T("raw_material / fabrication / shipping…")}
              />
            </Field>
            <Field label={T("Initial rating (0–5)")}>
              <input
                className="input" type="number" min={0} max={5} step="0.1"
                value={rating} onChange={(e) => setRating(e.target.value)}
                placeholder="0"
              />
            </Field>
          </div>

          {/* ── the company: where it is, and how the switchboard answers ── */}
          <div className="rounded-xl border border-ink-100 p-3 space-y-3">
            <div className="text-[10px] uppercase tracking-wider muted">
              {T("Company address & contact")}
            </div>
            <Field label={T("Company address")}>
              <textarea
                className="input min-h-[60px]"
                value={companyAddress} onChange={(e) => setCompanyAddress(e.target.value)}
                placeholder={T("Jl. Industri Raya No. 12, Kawasan Industri Jababeka, Cikarang")}
              />
            </Field>
            <Field label={T("Warehouse / pickup address")}>
              <textarea
                className="input min-h-[50px]"
                value={warehouseAddress} onChange={(e) => setWarehouseAddress(e.target.value)}
                placeholder={T("Leave blank if goods are collected from the office address")}
              />
            </Field>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Field label={T("Company phone")}>
                <input className="input" value={phone}
                  onChange={(e) => setPhone(e.target.value)} placeholder="+62…" />
              </Field>
              <Field label={T("Company WhatsApp")}>
                <input className="input" value={whatsapp}
                  onChange={(e) => setWhatsapp(e.target.value)} placeholder="+62…" />
              </Field>
              <Field label={T("Company email")}>
                <input className="input" type="email" value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="sales@pemasok.co.id" />
              </Field>
            </div>
          </div>

          {/* ── the people, each with their own line ── */}
          <div className="rounded-xl border border-ink-100 p-3 space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div>
                <div className="text-[10px] uppercase tracking-wider muted">
                  {T("Contacts (PIC)")}
                </div>
                <div className="text-[11px] muted">
                  {T("Their own phone and email, separate from the company's above.")}
                </div>
              </div>
              <button type="button" className="btn-ghost text-xs"
                onClick={() => setContacts((c) => [...c, { ...EMPTY_CONTACT }])}>
                <Plus size={13} /> {T("Add another PIC")}
              </button>
            </div>
            {contacts.map((c, i) => (
              <div key={i} className="rounded-lg border border-ink-100 p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium muted">
                    {i === 0 ? T("Primary PIC") : `${T("PIC")} ${i + 1}`}
                  </span>
                  {contacts.length > 1 && (
                    <button type="button" className="text-red-600 hover:opacity-80"
                      title={T("Remove")}
                      onClick={() => setContacts((cur) => cur.filter((_, idx) => idx !== i))}>
                      <X size={13} />
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label={T("PIC name")}>
                    <input className="input" value={c.name}
                      onChange={(e) => updateContact(i, { name: e.target.value })} />
                  </Field>
                  <Field label={T("Position / title")}>
                    <input className="input" value={c.position}
                      onChange={(e) => updateContact(i, { position: e.target.value })}
                      placeholder={T("Sales Engineer")} />
                  </Field>
                  <Field label={T("PIC phone")}>
                    <input className="input" value={c.phone}
                      onChange={(e) => updateContact(i, { phone: e.target.value })} />
                  </Field>
                  <Field label={T("PIC WhatsApp")}>
                    <input className="input" value={c.whatsapp}
                      onChange={(e) => updateContact(i, { whatsapp: e.target.value })} />
                  </Field>
                  <div className="md:col-span-2">
                    <Field label={T("PIC email")}>
                      <input className="input" type="email" value={c.email}
                        onChange={(e) => updateContact(i, { email: e.target.value })} />
                    </Field>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* ── the paperwork ── */}
          <div className="rounded-xl border border-ink-100 p-3 space-y-2">
            <div className="text-[10px] uppercase tracking-wider muted">{T("Files")}</div>
            <div className="text-[11px] muted">
              {T("Company deed, NPWP, bank details, price list — anything you would otherwise email yourself.")}
            </div>
            <input
              type="file" multiple className="text-xs"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length > 0 && (
              <ul className="text-xs muted space-y-0.5">
                {files.map((f) => <li key={f.name}>· {f.name}</li>)}
              </ul>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {uploading ? T("Uploading files…") : T("Create supplier")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * Ask suppliers what they charge — for a whole job, or line by line.
 *
 * Three shapes, one form, because they are the same act with different line
 * lists:
 *
 *  - **Ask them all.** Pick a price request, tick the vendors. Most jobs.
 *  - **Split the job** (scenario 1). Nobody makes the whole basket: the chain
 *    comes from one vendor and the sprockets from another. Turn on "split by
 *    line" and each vendor gets only the lines they can actually quote.
 *  - **Combine the jobs** (scenario 2). One vendor filling three customers'
 *    orders on one truck is one conversation, so it is one request — with
 *    each line still pointing back at the job it belongs to.
 *
 * The customer is never named here, on any of the three paths. This form ends
 * in a document that goes to an outside company.
 */
interface DraftLine { prId: string; prNumber: string; lineNo: number; description: string; qty: number; uom: string }

function AskSuppliersModal({ suppliers, onClose, onCreated, onError }: {
  suppliers: Supplier[];
  onClose: () => void;
  onCreated: (count: number) => void;
  onError: (msg: string) => void;
}) {
  const [prIds, setPrIds] = useState<string[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [split, setSplit] = useState(false);
  // supplier id → the "prId:lineNo" keys they are being asked about
  const [assign, setAssign] = useState<Record<string, string[]>>({});
  const [notes, setNotes] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [lines, setLines] = useState([{ description: "", qty: 1, uom: "pcs" }]);
  const [search, setSearch] = useState("");

  // Only requests still waiting on a cost — asking a vendor about a job the
  // director already priced is answering a question nobody asked.
  const openPrs = useQuery({
    queryKey: ["price-requests-costable"],
    queryFn: () => api.get("/price-requests").then((r) => {
      const rows = Array.isArray(r.data) ? r.data : (r.data?.data ?? []);
      return rows.filter((x: any) =>
        ["pending_purchasing", "pending_director"].includes(x.status));
    }),
    retry: false,
  });

  const chosen = (openPrs.data ?? []).filter((p: any) => prIds.includes(p.id));
  const allLines: DraftLine[] = chosen.flatMap((p: any) =>
    (p.items ?? []).map((it: any) => ({
      prId: p.id, prNumber: p.number, lineNo: it.line_no,
      description: it.description, qty: it.qty, uom: it.uom ?? "",
    })));
  const keyOf = (l: DraftLine) => `${l.prId}:${l.lineNo}`;

  const toggleLine = (sid: string, key: string) =>
    setAssign((cur) => {
      const held = cur[sid] ?? [];
      return { ...cur, [sid]: held.includes(key)
        ? held.filter((k) => k !== key) : [...held, key] };
    });

  // In split mode every picked supplier needs at least one line, or the ask
  // is empty for them and the vendor gets a blank sheet.
  const splitReady = picked.length > 0
    && picked.every((sid) => (assign[sid] ?? []).length > 0);
  const ready = split
    ? splitReady
    : picked.length > 0 && (prIds.length > 0 || lines.some((l) => l.description.trim()));

  const create = useMutation({
    mutationFn: () => {
      if (split) {
        return api.post("/purchasing/price-requests", {
          price_request_ids: prIds,
          notes: notes.trim() || null,
          valid_until: validUntil || null,
          assignments: picked.map((sid) => ({
            supplier_id: sid,
            lines: (assign[sid] ?? []).map((k) => {
              const [prId, lineNo] = k.split(":");
              return { price_request_id: prId, line_no: Number(lineNo) };
            }),
          })),
        });
      }
      return api.post("/purchasing/price-requests", {
        supplier_ids: picked,
        price_request_ids: prIds,
        items: prIds.length ? [] : lines
          .filter((l) => l.description.trim())
          .map((l, i) => ({
            line_no: i + 1, description: l.description.trim(),
            qty: Number(l.qty) || 0, uom: l.uom || null,
          })),
        notes: notes.trim() || null,
        valid_until: validUntil || null,
      });
    },
    onSuccess: () => onCreated(picked.length),
    onError: (e: any) => onError(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to send the request"),
  });

  const shown = suppliers.filter((s) =>
    !search.trim() || s.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      {/* No onClick: a stray click beside the box must not throw away
          what has been typed into it. The X and Escape close it. */}
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-3xl bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <ModalCloseX onClose={onClose} />
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">{T("Ask suppliers for a price")}</h2>
          <p className="text-sm muted mt-0.5">
            {T("One request per supplier, so you can put their answers side by side.")}</p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-4"
        >
          {/* ── what is in scope ── */}
          <div className="rounded-xl border border-ink-100 p-3 space-y-2">
            <div className="text-[10px] uppercase tracking-wider muted">
              {T("Which price requests are you costing?")}
            </div>
            <div className="text-[11px] muted">
              {T("Tick more than one to send a vendor several jobs as a single order — they arrive on one truck, so they are one conversation.")}
            </div>
            <div className="max-h-40 overflow-auto divide-y divide-ink-100">
              {(openPrs.data ?? []).map((p: any) => (
                <label key={p.id} className="flex items-center gap-2 py-1.5 text-sm cursor-pointer">
                  <input type="checkbox" className="h-4 w-4 rounded border-ink-300 text-brand-600"
                    checked={prIds.includes(p.id)}
                    onChange={(ev) => setPrIds((cur) => ev.target.checked
                      ? [...cur, p.id] : cur.filter((x) => x !== p.id))} />
                  <span className="font-mono text-xs">{p.number}</span>
                  <span className="text-[11px] muted">
                    {(p.items ?? []).length} {T("lines")}
                  </span>
                </label>
              ))}
              {!(openPrs.data ?? []).length && (
                <div className="py-3 text-center text-sm muted">
                  {T("Nothing is waiting for a cost right now.")}
                </div>
              )}
            </div>
          </div>

          {/* ...or a list typed by hand */}
          {!prIds.length && (
            <div className="rounded-xl border border-ink-100 p-3 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wider muted">
                  {T("Or ask about something with no job behind it")}
                </span>
                <button type="button" className="btn-ghost text-xs"
                  onClick={() => setLines((l) => [...l, { description: "", qty: 1, uom: "pcs" }])}>
                  <Plus size={13} /> {T("Add line")}
                </button>
              </div>
              {lines.map((l, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-7">
                    <Field label={T("Description")}>
                      <input className="input" value={l.description}
                        onChange={(e) => setLines((cur) => cur.map((x, idx) =>
                          idx === i ? { ...x, description: e.target.value } : x))} />
                    </Field>
                  </div>
                  <div className="col-span-2">
                    <Field label={T("Qty")}>
                      <input className="input" type="number" min={0} value={l.qty}
                        onChange={(e) => setLines((cur) => cur.map((x, idx) =>
                          idx === i ? { ...x, qty: Number(e.target.value) } : x))} />
                    </Field>
                  </div>
                  <div className="col-span-2">
                    <Field label={T("UoM")}>
                      <input className="input" value={l.uom}
                        onChange={(e) => setLines((cur) => cur.map((x, idx) =>
                          idx === i ? { ...x, uom: e.target.value } : x))} />
                    </Field>
                  </div>
                  <div className="col-span-1 pb-2">
                    {lines.length > 1 && (
                      <button type="button" className="text-red-600 hover:opacity-80"
                        onClick={() => setLines((cur) => cur.filter((_, idx) => idx !== i))}>
                        <X size={14} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── who to ask ── */}
          <div className="rounded-xl border border-ink-100 p-3 space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider muted">
                {T("Who are you asking?")}
              </span>
              <span className="text-[11px] muted">
                {picked.length} {T("selected")}
              </span>
            </div>
            <input className="input" placeholder={T("Search suppliers…")}
              value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="max-h-40 overflow-auto divide-y divide-ink-100">
              {shown.map((s) => (
                <label key={s.id} className="flex items-center gap-2 py-2 text-sm cursor-pointer">
                  <input type="checkbox" className="h-4 w-4 rounded border-ink-300 text-brand-600"
                    checked={picked.includes(s.id)}
                    onChange={(e) => setPicked((cur) => e.target.checked
                      ? [...cur, s.id] : cur.filter((x) => x !== s.id))} />
                  <span className="flex-1">{s.name}</span>
                  <span className="text-[11px] muted">{s.category ?? ""}</span>
                </label>
              ))}
              {!shown.length && (
                <div className="py-4 text-center text-sm muted">{T("No suppliers match.")}</div>
              )}
            </div>
          </div>

          {/* ── the split ── */}
          {allLines.length > 0 && picked.length > 0 && (
            <div className="rounded-xl border border-ink-100 p-3 space-y-3">
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input type="checkbox" className="h-4 w-4 rounded border-ink-300 text-brand-600 mt-0.5"
                  checked={split}
                  onChange={(e) => setSplit(e.target.checked)} />
                <span>
                  <span className="font-medium">{T("Split the lines between suppliers")}</span>
                  <span className="block text-[11px] muted">
                    {T("For when nobody makes the whole basket — each vendor is asked only about the lines they can actually quote.")}
                  </span>
                </span>
              </label>

              {split && picked.map((sid) => {
                const s = suppliers.find((x) => x.id === sid);
                const held = assign[sid] ?? [];
                return (
                  <div key={sid} className="rounded-lg border border-ink-100 p-3 space-y-1.5">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <span className="text-sm font-medium">{s?.name}</span>
                      <span className="text-[11px] muted">
                        {held.length} {T("of")} {allLines.length} {T("lines")}
                      </span>
                    </div>
                    {held.length === 0 && (
                      <div className="text-[11px] text-amber-700">
                        {T("Pick at least one line, or this vendor gets a blank sheet.")}
                      </div>
                    )}
                    {allLines.map((l) => {
                      const k = keyOf(l);
                      // A line already given to somebody else is still
                      // offered — two vendors quoting the same line is a
                      // comparison, not a mistake.
                      const takenBy = picked.filter(
                        (o) => o !== sid && (assign[o] ?? []).includes(k));
                      return (
                        <label key={k} className="flex items-start gap-2 text-xs cursor-pointer py-0.5">
                          <input type="checkbox"
                            className="h-3.5 w-3.5 rounded border-ink-300 text-brand-600 mt-0.5"
                            checked={held.includes(k)}
                            onChange={() => toggleLine(sid, k)} />
                          <span className="flex-1">
                            <span className="font-mono muted">{l.prNumber}#{l.lineNo}</span>{" "}
                            {l.description}{" "}
                            <span className="muted">({l.qty} {l.uom})</span>
                            {takenBy.length > 0 && (
                              <span className="ml-1 text-[10px] text-ink-400">
                                · {T("also asked of")}{" "}
                                {takenBy.map((o) => suppliers.find((x) => x.id === o)?.name).join(", ")}
                              </span>
                            )}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={T("Quote valid until")}>
              <input className="input" type="date" value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)} />
            </Field>
            <Field label={T("Note to yourself")}>
              <input className="input" value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={T("e.g. need the price before Friday")} />
            </Field>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
            <button type="submit" className="btn-primary" disabled={!ready || create.isPending}>
              {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              {T("Create requests")}</button>
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
  // Blank on purpose: an ETA guessed at PO time is worse than no ETA, because
  // the project page presents it as the date this shipment lands.
  const [eta, setEta] = useState("");
  // Rupiah unless told otherwise: most orders are local, and a default nobody
  // notices is only safe when it is the common case.
  const [currency, setCurrency] = useState("IDR");
  const [total, setTotal] = useState("");
  const [totalEdited, setTotalEdited] = useState(false);
  const [description, setDescription] = useState("");

  const [localErr, setLocalErr] = useState<string | null>(null);

  const [manualPrId, setManualPrId] = useState("");

  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

  // Pull the project's approved price request so the PO auto-fills the buying
  // (cost) price purchasing already entered. A manually-picked request
  // (manualPrId) takes precedence when a project isn't auto-linked.
  const prefill = useQuery({
    queryKey: ["po-prefill", projectId, manualPrId],
    queryFn: () => api.get("/purchasing/po/prefill", {
      params: manualPrId ? { price_request_id: manualPrId } : { project_id: projectId },
    }).then((r) => r.data),
    enabled: !!projectId,
  });
  const prOptions = useQuery({
    queryKey: ["pr-options"],
    queryFn: () => api.get("/purchasing/po/price-request-options").then((r) => r.data),
    enabled: !!projectId,
  });
  const linkedPR: string | null = prefill.data?.price_request_id ?? null;
  const prefillItems: any[] = prefill.data?.items ?? [];
  // A local copy, because the qty and the unit cost are editable here: what
  // purchasing costed and what this vendor actually quoted are not always the
  // same number. Seeded from the price request and reset when it changes.
  const [prItems, setPrItems] = useState<any[]>([]);
  const editLine = (i: number, patch: Record<string, any>) =>
    setPrItems((cur) => cur.map((it, j) => {
      if (j !== i) return it;
      const next = { ...it, ...patch };
      // Keep the line's own amount honest — it is what gets POSTed.
      next.amount = Number(next.qty ?? 0) * Number(next.unit_price ?? 0);
      return next;
    }));

  // Which lines go on THIS order — see PriceRequestLines. Everything starts
  // ticked except what another PO already covers.
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const prKey = `${linkedPR ?? ""}:${prefillItems.length}`;
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    if (!linkedPR || seededFor.current === prKey) return;
    seededFor.current = prKey;
    setPrItems(prefillItems.map((it) => ({ ...it })));
    setPicked(new Set(
      prefillItems.map((_, i) => i)
        .filter((i) => !(prefillItems[i].ordered_on ?? []).length),
    ));
  }, [prKey, linkedPR, prefillItems]);

  const pickedItems = prItems.filter((_, i) => picked.has(i));
  const prTotal: number = pickedItems.reduce((s, it) => s + lineAmount(it), 0);
  useEffect(() => {
    if (linkedPR && !totalEdited) setTotal(prTotal > 0 ? String(prTotal) : "");
  }, [prTotal, linkedPR, totalEdited]);

  const create = useMutation({
    mutationFn: () => api.post("/purchasing/po", {
      supplier_id: supplierId,
      project_id: projectId,
      number: poNumber.trim() || null,
      po_date: poDate || null,
      eta: eta || null,
      currency,
      quoted_lead_days: leadDays ? Number(leadDays) : null,
      total: total ? Number(total) : 0,
      price_request_id: linkedPR,
      items: prItems.length ? pickedItems : (description ? [{ description, qty: 1 }] : []),
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
    if (prItems.length > 0 && pickedItems.length === 0) {
      setLocalErr(t(
        "Tick at least one line for this supplier.",
        "Centang minimal satu baris untuk supplier ini.",
      ));
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
          <h2 className="text-lg font-semibold">{T("Issue purchase order")}</h2>
          <p className="text-sm muted mt-0.5">
            {T("The PO must reference a supplier and a project so the supplier can update shipping dates that flow to the customer.")}</p>
        </header>
        <form
          onSubmit={(e) => { e.preventDefault(); attemptSubmit(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{T("Supplier *")}</span>
            {suppliers.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{T("No suppliers yet. Click \"+ New supplier\" first.")}</span>
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
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{T("Project *")}</span>
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
          </label>

          {projectId && (
            prefill.isLoading ? (
              <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> {T("Checking the price request…")}</div>
            ) : linkedPR ? (
              <PriceRequestLines
                priceRequestId={linkedPR}
                priceRequestNumber={prefill.data?.price_request_number ?? ""}
                items={prItems}
                uncosted={prefill.data?.uncosted ?? 0}
                picked={picked}
                onPicked={setPicked}
                onEdit={editLine}
              />
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
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {T("PO number")}</span>
              <input
                className="input"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                placeholder={T("Auto-generated if blank (PO-YYMMDD-NNN)")}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("Leave blank to use the next sequential number.")}</span>
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {T("PO date")}{" "}<span className="text-red-500">*</span>
              </span>
              <input
                type="date"
                required
                className="input"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("The day the PO is issued.")}</span>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">{T("Expected arrival (ETA)")}</span>
              <input
                type="date"
                className="input"
                value={eta}
                onChange={(e) => setEta(e.target.value)}
              />
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("When this order lands. The project lists it as a shipment on this date; leave blank if the supplier hasn't said.")}</span>
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">{T("Lead time (days)")}</span>
              <input
                type="number"
                min={0}
                className="input"
                value={leadDays}
                onChange={(e) => setLeadDays(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">{T("Currency")}</span>
              <select className="input" value={currency}
                onChange={(e) => setCurrency(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c.code} value={c.code}>{c.code} — {T(c.name)}</option>
                ))}
              </select>
              <span className="block text-[10px] text-ink-400 mt-1">
                {T("Printed on the PO next to every price. An overseas supplier reads Rp figures as their own currency otherwise.")}</span>
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {T("Total")} ({currency})
              </span>
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
            </label>
          </div>

          {!(linkedPR && prItems.length > 0) && (
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">{T("Description (optional)")}</span>
              <textarea
                rows={2}
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={T("What's being purchased…")}
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
                  {T("Need:")}{" "}{!supplierId && <span className="font-semibold">{T("supplier")}</span>}
                  {!supplierId && !projectId && " · "}
                  {!projectId && <span className="font-semibold">{T("project")}</span>}
                </>
              )}
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
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
