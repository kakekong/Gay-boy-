import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Tag, Plus, Trash2, Send, Check, X, Loader2, ArrowLeft, FileText } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt } from "@/store/lang";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  draft: "bg-ink-100 text-ink-700",
  pending_purchasing: "bg-amber-50 text-amber-700",
  pending_director: "bg-violet-50 text-violet-700",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
};

// Indonesian display labels for backend status keys. Display only —
// never sent back to the API.
const STATUS_LABEL_ID: Record<string, string> = {
  draft: "draf",
  pending_purchasing: "menunggu pembelian",
  pending_director: "menunggu direktur",
  approved: "disetujui",
  rejected: "ditolak",
};

// Display label for a backend status key: humanised English key, or the
// Indonesian label when the app is in Indonesian.
const sl = (key: string) => {
  const en = (key ?? "").replace(/_/g, " ");
  return tt(en, STATUS_LABEL_ID[key] ?? en);
};

const onErr = (e: any) =>
  alert(e?.response?.data?.detail ?? e?.response?.data?.errors?.[0]?.message ?? e?.message ?? tt("Failed", "Gagal"));

export default function PriceRequestsPage() {
  const t = useT();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // Landing here from a customer page? /price-requests?customer=<id>
  // auto-opens the create form with that customer preselected so sales
  // don't have to hunt through the customer picker again.
  const [searchParams, setSearchParams] = useSearchParams();
  const prefillCustomerId = searchParams.get("customer");
  useEffect(() => {
    if (prefillCustomerId) setCreating(true);
  }, [prefillCustomerId]);

  const list = useQuery({
    queryKey: ["price-requests"],
    queryFn: () => api.get("/price-requests").then((r) => r.data),
  });

  if (selected) {
    return <PriceRequestDetail id={selected} role={role} onBack={() => setSelected(null)} />;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Tag size={22} className="text-brand-600" /> {t("Price requests", "Permintaan harga")}
          </h1>
          <p className="text-sm muted">
            {role === "purchasing"
              ? t(
                  "Fill the procurement cost for each requested order, then send to the director.",
                  "Isi biaya pengadaan untuk setiap pesanan yang diminta, lalu kirim ke direktur."
                )
              : role === "director"
              ? t(
                  "Set the selling price per line and approve. Sales builds the quotation from this.",
                  "Tetapkan harga jual per baris lalu setujui. Sales membuat penawaran dari sini."
                )
              : t(
                  "List the goods a customer needs. Purchasing costs it, the director prices it — then your quotation auto-fills.",
                  "Daftarkan barang yang dibutuhkan pelanggan. Pembelian menghitung biayanya, direktur menetapkan harganya — lalu penawaran Anda terisi otomatis."
                )}
          </p>
        </div>
        {(role === "sales" || role === "director" || role === "manager" || role === "admin") && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} /> {t("New price request", "Permintaan harga baru")}
          </button>
        )}
      </div>

      {creating && (
        <CreateForm
          initialCustomerId={prefillCustomerId ?? ""}
          onClose={() => {
            setCreating(false);
            if (prefillCustomerId) {
              searchParams.delete("customer");
              setSearchParams(searchParams, { replace: true });
            }
          }}
          onCreated={(id) => { setCreating(false); setSelected(id); }}
        />
      )}

      <div className="card overflow-hidden">
        {list.isLoading ? <div className="p-8 muted text-sm">{t("Loading…", "Memuat…")}</div>
          : (list.data ?? []).length === 0 ? <div className="p-8 text-center muted text-sm">{t("No price requests yet.", "Belum ada permintaan harga.")}</div>
          : (
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("Number", "Nomor")}</th>
                  <th className="th">{role === "purchasing" ? t("Order", "Pesanan") : t("Customer", "Pelanggan")}</th>
                  <th className="th">{t("Lines", "Baris")}</th>
                  <th className="th">Status</th>
                  {role !== "purchasing" && <th className="th text-right">{t("Sell total", "Total jual")}</th>}
                </tr>
              </thead>
              <tbody>
                {(list.data ?? []).map((pr: any) => (
                  <tr key={pr.id} className="border-t border-ink-100 hover:bg-ink-50/40 cursor-pointer"
                    onClick={() => setSelected(pr.id)}>
                    <td className="td font-mono text-xs">{pr.number}</td>
                    <td className="td">{pr.customer_name}</td>
                    <td className="td muted">{pr.items?.length ?? 0}</td>
                    <td className="td">
                      <span className={clsx("chip capitalize", STATUS_CHIP[pr.status] ?? "bg-ink-100")}>
                        {sl(pr.status)}
                      </span>
                    </td>
                    {role !== "purchasing" && (
                      <td className="td text-right tabular-nums">
                        {pr.sell_total != null ? idr(pr.sell_total) : "—"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  );
}

function CreateForm({
  onClose, onCreated, initialCustomerId = "",
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
  initialCustomerId?: string;
}) {
  const [customerId, setCustomerId] = useState(initialCustomerId);
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<any[]>([{ description: "", qty: 1, uom: "", spec: "" }]);

  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get("/customers", { params: { page_size: 200 } }).then((r) => {
      // /customers returns a paginated envelope {data:[...]}; tolerate a bare array too.
      const body = r.data;
      if (Array.isArray(body)) return body;
      if (body && Array.isArray(body.data)) return body.data;
      return [];
    }),
  });

  const create = useMutation({
    mutationFn: () => api.post("/price-requests", {
      customer_id: customerId, notes,
      items: items.filter((it) => it.description.trim()),
    }).then((r) => r.data),
    onSuccess: (d) => onCreated(d.id),
    onError: onErr,
  });

  const setItem = (i: number, k: string, v: any) =>
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, [k]: v } : it)));

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold">New price request</div>
        <button className="btn-ghost" onClick={onClose}><X size={15} /></button>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        <div>
          <label className="block text-[11px] uppercase muted mb-1">Customer *</label>
          <select className="input" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">Select customer…</option>
            {(customers.data ?? []).map((c: any) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[11px] uppercase muted mb-1">Notes</label>
          <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
        </div>
      </div>

      <div>
        <div className="text-[11px] uppercase muted mb-1">Goods needed (no prices)</div>
        <div className="space-y-2">
          {items.map((it, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input className="input flex-1" placeholder="Description" value={it.description}
                onChange={(e) => setItem(i, "description", e.target.value)} />
              <input className="input w-20" type="number" placeholder="Qty" value={it.qty}
                onChange={(e) => setItem(i, "qty", Number(e.target.value))} />
              <input className="input w-24" placeholder="UoM" value={it.uom}
                onChange={(e) => setItem(i, "uom", e.target.value)} />
              <input className="input flex-1" placeholder="Spec / notes" value={it.spec}
                onChange={(e) => setItem(i, "spec", e.target.value)} />
              <button className="btn-ghost text-red-600"
                onClick={() => setItems((arr) => arr.filter((_, idx) => idx !== i))}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
        <button className="btn-ghost mt-2"
          onClick={() => setItems((a) => [...a, { description: "", qty: 1, uom: "", spec: "" }])}>
          <Plus size={14} /> Add line
        </button>
      </div>

      <div className="flex justify-end">
        <button className="btn-primary" disabled={!customerId || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create
        </button>
      </div>
    </div>
  );
}

function PriceRequestDetail({ id, role, onBack }: { id: string; role: string; onBack: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({
    queryKey: ["price-request", id],
    queryFn: () => api.get(`/price-requests/${id}`).then((r) => r.data),
  });
  const makeQuote = useMutation({
    mutationFn: () => api.post(`/quotations/from-price-request/${id}`).then((r) => r.data),
    onSuccess: (d) => nav(`/quotations/${d.id}`),
    onError: onErr,
  });
  const [draft, setDraft] = useState<
    Record<number, { cost?: number; sell?: number; costBasis?: string; sellBasis?: string }>
  >({});
  const [notes, setNotes] = useState("");

  const refresh = () => { qc.invalidateQueries({ queryKey: ["price-request", id] }); qc.invalidateQueries({ queryKey: ["price-requests"] }); };
  const mut = (fn: () => Promise<any>) => ({ mutationFn: fn, onSuccess: refresh, onError: onErr });

  const submit = useMutation(mut(() => api.post(`/price-requests/${id}/submit`)));
  const price = useMutation(mut(() => api.post(`/price-requests/${id}/price`, {
    items: Object.entries(draft).map(([ln, v]) => ({
      line_no: Number(ln), cost_price: v.cost ?? 0, basis: v.costBasis ?? "unit",
    })),
    notes: notes || undefined,
  })));
  const approve = useMutation(mut(() => api.post(`/price-requests/${id}/approve`, {
    items: Object.entries(draft).map(([ln, v]) => ({
      line_no: Number(ln), sell_price: v.sell ?? 0, basis: v.sellBasis ?? "unit",
      cost_price: v.cost, cost_basis: v.costBasis ?? "unit",
    })),
    notes: notes || undefined,
  })));
  const reject = useMutation(mut(() => api.post(`/price-requests/${id}/reject`, { notes: notes || undefined })));

  // Editable price cell with a per-line "/unit" vs "total" basis selector.
  // Storage is always per-unit; "total" just means the entered figure covers
  // the whole line, and we show the implied unit price (or vice-versa) live.
  const editCell = (it: any, kind: "cost" | "sell") => {
    const v = draft[it.line_no] ?? {};
    const amount = kind === "cost" ? v.cost : v.sell;
    const basis = (kind === "cost" ? v.costBasis : v.sellBasis) ?? "unit";
    const qty = Number(it.qty) || 0;
    const unit = basis === "total" ? (qty ? Number(amount || 0) / qty : 0) : Number(amount || 0);
    const total = basis === "total" ? Number(amount || 0) : Number(amount || 0) * qty;
    const setVal = (patch: any) =>
      setDraft((d) => ({ ...d, [it.line_no]: { ...d[it.line_no], ...patch } }));
    return (
      <div className="flex flex-col items-end gap-1">
        <div className="flex items-center gap-1">
          <input type="number" className="input w-28 text-right"
            defaultValue={(kind === "cost" ? it.cost_price : it.sell_price) ?? ""}
            onChange={(e) =>
              setVal(kind === "cost" ? { cost: Number(e.target.value) } : { sell: Number(e.target.value) })} />
          <select className="input w-[68px] px-1 text-xs" value={basis}
            onChange={(e) =>
              setVal(kind === "cost" ? { costBasis: e.target.value } : { sellBasis: e.target.value })}>
            <option value="unit">/unit</option>
            <option value="total">total</option>
          </select>
        </div>
        {amount != null && qty > 0 && (
          <span className="text-[10px] muted tabular-nums">
            {basis === "total" ? `${idr(unit)} /unit` : `= ${idr(total)} total`}
          </span>
        )}
      </div>
    );
  };

  const readCell = (unitPrice: any, lineTotal: any, qty: any) =>
    unitPrice == null ? "—" : (
      <div className="flex flex-col items-end leading-tight">
        <span className="tabular-nums">{idr(unitPrice)} <span className="muted text-[10px]">/unit</span></span>
        {Number(qty) > 1 && <span className="text-[10px] muted tabular-nums">{idr(lineTotal)} total</span>}
      </div>
    );

  if (q.isLoading) return <div className="muted text-sm">Loading…</div>;
  const pr = q.data;
  if (!pr) return <div className="muted text-sm">Not found.</div>;

  const isPurchasing = role === "purchasing";
  const isDirector = role === "director";
  const canCost = (role === "purchasing" || role === "director" || role === "manager" || role === "admin")
    && (pr.status === "pending_purchasing" || pr.status === "pending_director");
  const canApprove = isDirector && (pr.status === "pending_director" || pr.status === "pending_purchasing");
  const canSubmit = pr.status === "draft" || pr.status === "rejected";

  return (
    <div className="space-y-5">
      <button className="btn-ghost -ml-3" onClick={onBack}><ArrowLeft size={15} /> Back</button>
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold font-mono">{pr.number}</h1>
              <span className={clsx("chip capitalize", STATUS_CHIP[pr.status] ?? "bg-ink-100")}>
                {pr.status.replace(/_/g, " ")}
              </span>
            </div>
            <div className="text-sm muted mt-1">{pr.customer_name}</div>
          </div>
          {pr.status === "approved" && (
            pr.quotation_id ? (
              <button className="btn-ghost" onClick={() => nav(`/quotations/${pr.quotation_id}`)}>
                <FileText size={14} /> View quotation
              </button>
            ) : (role === "sales" || role === "director" || role === "manager" || role === "admin") ? (
              <button className="btn-primary" disabled={makeQuote.isPending} onClick={() => makeQuote.mutate()}>
                {makeQuote.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
                Create quotation
              </button>
            ) : null
          )}
        </div>

        <table className="w-full text-sm mt-4">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">#</th><th className="th">Description</th>
              <th className="th text-right">Qty</th><th className="th">UoM</th>
              <th className="th">Spec</th>
              {pr.items?.[0] && "cost_price" in pr.items[0] && <th className="th text-right">Cost</th>}
              {pr.items?.[0] && "sell_price" in pr.items[0] && <th className="th text-right">Sell</th>}
            </tr>
          </thead>
          <tbody>
            {(pr.items ?? []).map((it: any) => (
              <tr key={it.line_no} className="border-t border-ink-100">
                <td className="td muted">{it.line_no}</td>
                <td className="td">{it.description}</td>
                <td className="td text-right tabular-nums">{it.qty}</td>
                <td className="td muted">{it.uom || "—"}</td>
                <td className="td muted text-xs">{it.spec || "—"}</td>
                {"cost_price" in it && (
                  <td className="td text-right">
                    {canCost && (isPurchasing || isDirector)
                      ? editCell(it, "cost")
                      : readCell(it.cost_price, it.cost_total, it.qty)}
                  </td>
                )}
                {"sell_price" in it && (
                  <td className="td text-right">
                    {canApprove
                      ? editCell(it, "sell")
                      : readCell(it.sell_price, it.line_total, it.qty)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {(canCost || canApprove || canSubmit) && (
          <div className="mt-4 flex items-center gap-2 flex-wrap">
            {(canCost || canApprove) && (
              <input className="input flex-1 min-w-[200px]" placeholder="Notes (optional)"
                value={notes} onChange={(e) => setNotes(e.target.value)} />
            )}
            {canSubmit && (
              <button className="btn-primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
                <Send size={14} /> Submit to purchasing
              </button>
            )}
            {canCost && (isPurchasing || isDirector) && (
              <button className="btn-primary" disabled={price.isPending} onClick={() => price.mutate()}>
                <Check size={14} /> Submit costs
              </button>
            )}
            {canApprove && (
              <button className="btn-primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
                <Check size={14} /> Set prices &amp; approve
              </button>
            )}
            {(isDirector || isPurchasing || role === "manager") && pr.status !== "approved" && pr.status !== "draft" && (
              <button className="btn-ghost text-red-600" disabled={reject.isPending} onClick={() => reject.mutate()}>
                <X size={14} /> Send back
              </button>
            )}
          </div>
        )}
        {pr.decision_notes && <div className="mt-3 text-xs muted">Note: {pr.decision_notes}</div>}
      </div>
    </div>
  );
}
