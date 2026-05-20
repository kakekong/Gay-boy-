import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardList, Send, Truck, PackageCheck, CheckCircle2, ArrowRight,
  ShoppingCart, Plus, Loader2, Star, AlertCircle, X, Save,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

const STAGES = [
  { key: "PR",  label: "Purchase Request", icon: ClipboardList, hint: "Internal request" },
  { key: "RFQ", label: "RFQ",              icon: Send,          hint: "Quote suppliers" },
  { key: "PO",  label: "Supplier PO",      icon: Truck,         hint: "Order placed" },
  { key: "GR",  label: "Goods Receipt",    icon: PackageCheck,  hint: "Received" },
  { key: "QC",  label: "QC",               icon: CheckCircle2,  hint: "Quality check" },
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
  const [openNew, setOpenNew] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as Supplier[]),
    retry: false,
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <ShoppingCart size={22} className="text-brand-600" /> Purchasing
          </h1>
          <p className="text-sm muted">Track every document along the procurement chain.</p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={15} /> New supplier
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

      <div className="card p-4 lg:p-6 overflow-x-auto">
        <div className="flex items-stretch gap-3 min-w-[700px]">
          {STAGES.map((s, i) => (
            <div key={s.key} className="flex items-stretch gap-2 flex-1">
              <div className="flex-1 rounded-xl border border-ink-200 hover:border-brand-300 transition-colors p-4 bg-white">
                <div className="flex items-center gap-2 text-ink-800">
                  <s.icon size={16} className="text-brand-600" />
                  <span className="font-semibold">{s.label}</span>
                </div>
                <div className="mt-1 text-xs muted">{s.hint}</div>
                <div className="mt-3 text-2xl font-semibold tabular-nums text-ink-900">0</div>
                <div className="text-[11px] muted">open documents</div>
              </div>
              {i < STAGES.length - 1 && (
                <ArrowRight className="self-center text-ink-300 shrink-0" size={18} />
              )}
            </div>
          ))}
        </div>
      </div>

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
                <tr key={s.id} className="tr-hover border-t border-ink-100">
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
    </div>
  );
}

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
