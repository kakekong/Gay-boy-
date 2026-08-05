import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Tag, Plus, Trash2, Send, Check, X, Loader2, ArrowLeft, FileText,
  Pencil, ClipboardList,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, T, locale } from "@/store/lang";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { LogActivityForm } from "@/components/forms/LogActivityForm";
import { Modal } from "@/components/Modal";

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
  // Deep link from a quotation / project: /price-requests?open=<id>
  // jumps straight into that PR's detail view.
  const openId = searchParams.get("open");
  useEffect(() => {
    if (openId) setSelected(openId);
  }, [openId]);

  const list = useQuery({
    queryKey: ["price-requests"],
    queryFn: () => api.get("/price-requests").then((r) => r.data),
  });

  if (selected) {
    return (
      <PriceRequestDetail
        id={selected}
        role={role}
        onBack={() => {
          setSelected(null);
          if (openId) {
            searchParams.delete("open");
            setSearchParams(searchParams, { replace: true });
          }
        }}
      />
    );
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
                  <th className="th">{T("Status")}</th>
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
  const t = useT();
  const [customerId, setCustomerId] = useState(initialCustomerId);
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<any[]>([{ description: "", qty: 1, uom: "", spec: "" }]);
  // Attach the customer's RFQ / spec sheets right at creation — they're
  // uploaded against the new PR as soon as it exists, so purchasing can
  // cost from the source documents.
  const [files, setFiles] = useState<File[]>([]);

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
    mutationFn: async () => {
      const d = await api.post("/price-requests", {
        customer_id: customerId, notes,
        items: items.filter((it) => it.description.trim()),
      }).then((r) => r.data);
      // The PR exists — now attach the chosen files to it. A failed upload
      // shouldn't lose the PR: warn and continue (files can be re-added on
      // the detail page).
      for (const f of files) {
        const fd = new FormData();
        fd.append("owner_type", "price_request");
        fd.append("owner_id", d.id);
        fd.append("description", "customer RFQ / spec");
        fd.append("file", f);
        try {
          await api.post("/attachments", fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch (e: any) {
          alert(tt(
            `"${f.name}" failed to upload — the price request was created; re-attach the file on its page.`,
            `"${f.name}" gagal diunggah — permintaan harga sudah dibuat; lampirkan ulang file di halamannya.`,
          ));
        }
      }
      return d;
    },
    onSuccess: (d) => onCreated(d.id),
    onError: onErr,
  });

  const setItem = (i: number, k: string, v: any) =>
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, [k]: v } : it)));

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold">{t("New price request", "Permintaan harga baru")}</div>
        <button className="btn-ghost" onClick={onClose}><X size={15} /></button>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        <div>
          <label className="block text-[11px] uppercase muted mb-1">{t("Customer", "Pelanggan")} *</label>
          <select className="input" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">{t("Select customer…", "Pilih pelanggan…")}</option>
            {(customers.data ?? []).map((c: any) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[11px] uppercase muted mb-1">{t("Notes", "Catatan")}</label>
          <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("Optional", "Opsional")} />
        </div>
      </div>

      <div>
        <div className="text-[11px] uppercase muted mb-1">{t("Goods needed (no prices)", "Barang yang dibutuhkan (tanpa harga)")}</div>
        <div className="space-y-2">
          {items.map((it, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input className="input flex-1" placeholder={t("Description", "Deskripsi")} value={it.description}
                onChange={(e) => setItem(i, "description", e.target.value)} />
              <input className="input w-20" type="number" placeholder={t("Qty", "Jml")} value={it.qty}
                onChange={(e) => setItem(i, "qty", Number(e.target.value))} />
              <input className="input w-24" placeholder={t("UoM", "Satuan")} value={it.uom}
                onChange={(e) => setItem(i, "uom", e.target.value)} />
              <input className="input flex-1" placeholder={t("Spec / notes", "Spesifikasi / catatan")} value={it.spec}
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
          <Plus size={14} /> {t("Add line", "Tambah baris")}
        </button>
      </div>

      <div>
        <div className="text-[11px] uppercase muted mb-1">
          {t("Attachments (customer RFQ / spec sheets — optional)",
             "Lampiran (RFQ pelanggan / lembar spesifikasi — opsional)")}
        </div>
        <label className="btn-ghost cursor-pointer inline-flex">
          <Plus size={14} /> {t("Add files", "Tambah file")}
          <input
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              const picked = Array.from(e.target.files ?? []);
              if (picked.length) setFiles((cur) => [...cur, ...picked]);
              e.target.value = "";
            }}
          />
        </label>
        {files.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-2">
                <FileText size={13} className="text-ink-400 shrink-0" />
                <span className="truncate">{f.name}</span>
                <span className="muted text-xs">({Math.ceil(f.size / 1024)} {T("KB)")}</span>
                <button
                  className="btn-ghost text-red-600 p-1 ml-auto"
                  onClick={() => setFiles((cur) => cur.filter((_, idx) => idx !== i))}
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-end">
        <button className="btn-primary" disabled={!customerId || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          {create.isPending && files.length
            ? t("Creating + uploading…", "Membuat + mengunggah…")
            : t("Create", "Buat")}
        </button>
      </div>
    </div>
  );
}

function PriceRequestDetail({ id, role, onBack }: { id: string; role: string; onBack: () => void }) {
  const t = useT();
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
  const [editingNumber, setEditingNumber] = useState(false);
  const [numberDraft, setNumberDraft] = useState("");
  const [activityOpen, setActivityOpen] = useState(false);
  const renumber = useMutation({
    mutationFn: (number: string) =>
      api.patch(`/price-requests/${id}`, { number }).then((r) => r.data),
    onSuccess: () => {
      setEditingNumber(false);
      qc.invalidateQueries({ queryKey: ["price-request", id] });
      qc.invalidateQueries({ queryKey: ["price-requests"] });
    },
    onError: onErr,
  });

  // Line-item editing. `null` = not editing; otherwise the working copy.
  const [editItems, setEditItems] = useState<
    { description: string; qty: number | string; uom: string; spec: string }[] | null
  >(null);
  // "edit" writes straight to the request (draft, or the director overriding).
  // "propose" files a revision for the director to decide — the negotiation path.
  const [editMode, setEditMode] = useState<"edit" | "propose">("edit");
  const [reviseReason, setReviseReason] = useState("");

  const refresh = () => { qc.invalidateQueries({ queryKey: ["price-request", id] }); qc.invalidateQueries({ queryKey: ["price-requests"] }); };
  const mut = (fn: () => Promise<any>) => ({ mutationFn: fn, onSuccess: refresh, onError: onErr });

  const revisions = useQuery({
    queryKey: ["pr-revisions", id],
    queryFn: () => api.get(`/price-requests/${id}/revisions`).then((r) => r.data),
  });

  const propose = useMutation({
    mutationFn: () => api.post(`/price-requests/${id}/revise`, {
      items: (editItems ?? []).map((row) => ({
        description: row.description.trim(),
        qty: Number(row.qty) || 0,
        uom: row.uom.trim() || null,
        spec: row.spec.trim() || null,
      })),
      reason: reviseReason.trim() || null,
    }).then((r) => r.data),
    onSuccess: () => {
      setEditItems(null); setReviseReason("");
      qc.invalidateQueries({ queryKey: ["pr-revisions", id] });
      refresh();
    },
    onError: onErr,
  });

  const saveItems = useMutation({
    mutationFn: () => api.patch(`/price-requests/${id}`, {
      items: (editItems ?? []).map((row) => ({
        description: row.description.trim(),
        qty: Number(row.qty) || 0,
        uom: row.uom.trim() || null,
        spec: row.spec.trim() || null,
      })),
    }).then((r) => r.data),
    onSuccess: () => { setEditItems(null); refresh(); },
    onError: onErr,
  });

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
            <option value="unit">{t("/unit", "/satuan")}</option>
            <option value="total">{t("total", "total")}</option>
          </select>
        </div>
        {amount != null && qty > 0 && (
          <span className="text-[10px] muted tabular-nums">
            {basis === "total"
              ? `${idr(unit)} ${t("/unit", "/satuan")}`
              : `= ${idr(total)} ${t("total", "total")}`}
          </span>
        )}
      </div>
    );
  };

  const readCell = (unitPrice: any, lineTotal: any, qty: any) =>
    unitPrice == null ? "—" : (
      <div className="flex flex-col items-end leading-tight">
        <span className="tabular-nums">{idr(unitPrice)} <span className="muted text-[10px]">{t("/unit", "/satuan")}</span></span>
        {Number(qty) > 1 && <span className="text-[10px] muted tabular-nums">{idr(lineTotal)} {t("total", "total")}</span>}
      </div>
    );

  if (q.isLoading) return <div className="muted text-sm">{t("Loading…", "Memuat…")}</div>;
  const pr = q.data;
  if (!pr) return <div className="muted text-sm">{t("Not found.", "Tidak ditemukan.")}</div>;

  const isPurchasing = role === "purchasing";
  const isDirector = role === "director";
  const canCost = (role === "purchasing" || role === "director" || role === "manager" || role === "admin")
    && (pr.status === "pending_purchasing" || pr.status === "pending_director");
  const canApprove = isDirector && (pr.status === "pending_director" || pr.status === "pending_purchasing");
  const canSubmit = pr.status === "draft" || pr.status === "rejected";
  // Past draft/rejected the request is a live commercial document — purchasing
  // has costed it. Only the director may still correct one; the backend
  // enforces the same rule.
  const stillDraft = pr.status === "draft" || pr.status === "rejected";
  const canEditItems = isDirector
    || (stillDraft && (role === "sales" || role === "manager" || role === "admin"));
  const revLeft = revisions.data?.left ?? 0;
  const revPending = (revisions.data?.revisions ?? []).some((r: any) => r.status === "pending");
  // Negotiation path: propose a change on a request that has already gone out.
  const canPropose = !stillDraft && !revPending && revLeft > 0
    && (role === "sales" || role === "manager" || role === "admin" || isDirector);
  const editingLocked = editItems !== null && !stillDraft;

  return (
    <div className="space-y-5">
      <button className="btn-ghost -ml-3" onClick={onBack}><ArrowLeft size={15} /> {t("Back", "Kembali")}</button>
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              {editingNumber ? (
                <>
                  <input
                    className="input w-56 font-mono"
                    value={numberDraft}
                    onChange={(e) => setNumberDraft(e.target.value)}
                    autoFocus
                  />
                  <button
                    className="btn-primary"
                    disabled={!numberDraft.trim() || renumber.isPending}
                    onClick={() => renumber.mutate(numberDraft.trim())}
                  >
                    {renumber.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                  </button>
                  <button className="btn-ghost" onClick={() => setEditingNumber(false)}>
                    <X size={14} />
                  </button>
                </>
              ) : (
                <>
                  <h1 className="text-xl font-semibold font-mono">{pr.number}</h1>
                  {role !== "purchasing" && (
                    <button
                      className="btn-ghost p-1.5"
                      title={tt("Edit the PR number (e.g. to match the customer's RFQ number)",
                                "Ubah nomor PR (mis. menyamakan dengan nomor RFQ pelanggan)")}
                      onClick={() => { setNumberDraft(pr.number); setEditingNumber(true); }}
                    >
                      <Pencil size={14} />
                    </button>
                  )}
                </>
              )}
              <span className={clsx("chip capitalize", STATUS_CHIP[pr.status] ?? "bg-ink-100")}>
                {sl(pr.status)}
              </span>
            </div>
            <div className="text-sm muted mt-1">{pr.customer_name}</div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {role !== "purchasing" && pr.customer_id && (
              <button className="btn-ghost" onClick={() => setActivityOpen(true)}>
                <ClipboardList size={14} /> {tt("Log activity", "Catat aktivitas")}
              </button>
            )}
            {pr.quotation_id ? (
              <button className="btn-ghost" onClick={() => nav(`/quotations/${pr.quotation_id}`)}>
                <FileText size={14} /> {tt("View quotation", "Lihat penawaran")}
              </button>
            ) : pr.status === "approved"
              && (role === "sales" || role === "director" || role === "manager" || role === "admin") ? (
              <button className="btn-primary" disabled={makeQuote.isPending} onClick={() => makeQuote.mutate()}>
                {makeQuote.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
                {tt("Create quotation", "Buat penawaran")}
              </button>
            ) : null}
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <span className="overline">{t("Items", "Barang")}</span>
          {canEditItems && editItems === null && (
            <button
              className="btn-ghost ml-auto text-xs"
              onClick={() => { setEditMode("edit"); setEditItems((pr.items ?? []).map((it: any) => ({
                description: it.description ?? "",
                qty: it.qty ?? 1,
                uom: it.uom ?? "",
                spec: it.spec ?? "",
              }))); }}
            >
              <Pencil size={13} /> {t("Edit items", "Ubah barang")}
            </button>
          )}
          {canPropose && editItems === null && (
            <button
              className="btn-ghost ml-auto text-xs"
              onClick={() => {
                setEditMode("propose");
                setEditItems((pr.items ?? []).map((it: any) => ({
                  description: it.description ?? "", qty: it.qty ?? 1,
                  uom: it.uom ?? "", spec: it.spec ?? "",
                })));
              }}
            >
              <Send size={13} /> {t(`Propose revision (${revLeft} left)`,
                                    `Ajukan revisi (sisa ${revLeft})`)}
            </button>
          )}
          {revPending && editItems === null && (
            <span className="ml-auto chip bg-amber-100 text-amber-800">
              {t("Revision waiting for the director", "Revisi menunggu direktur")}
            </span>
          )}
        </div>

        {editItems !== null ? (
          <div className="mt-2 space-y-2">
            {editingLocked && editMode === "edit" && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2
                              text-xs text-amber-900 space-y-1">
                <div className="font-semibold">
                  {t("This request has already been costed.",
                     "Permintaan ini sudah dihitung biayanya.")}
                </div>
                <div>
                  {t("Lines you leave alone keep their cost and approved price. A line you rename or add comes back unpriced and has to go through purchasing again.",
                     "Baris yang tidak diubah tetap membawa biaya dan harga yang disetujui. Baris yang Anda ganti namanya atau tambahkan akan kosong dan harus dihitung ulang oleh pembelian.")}
                </div>
                {pr.quotation_id && (
                  <div>
                    {t("A quotation has already been made from this request — changing it here does not change the quotation.",
                       "Penawaran sudah dibuat dari permintaan ini — mengubah di sini tidak mengubah penawarannya.")}
                  </div>
                )}
              </div>
            )}

            {editMode === "propose" && (
              <div className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-2
                              text-xs text-brand-900 space-y-1">
                <div className="font-semibold">
                  {t("This goes to the director as a revision.",
                     "Ini dikirim ke direktur sebagai revisi.")}
                </div>
                <div>
                  {t(`Nothing changes until it is approved. ${revLeft} of 3 revisions left — a rejected one doesn't count.`,
                     `Tidak ada yang berubah sampai disetujui. Sisa ${revLeft} dari 3 revisi — yang ditolak tidak dihitung.`)}
                </div>
              </div>
            )}

            {editItems.map((row, i) => (
              <div key={i} className="grid grid-cols-12 gap-2">
                <input
                  className="input col-span-12 sm:col-span-5"
                  placeholder={t("Description", "Deskripsi")}
                  value={row.description}
                  onChange={(e) => setEditItems((rows) => rows!.map(
                    (x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                />
                <input
                  className="input col-span-4 sm:col-span-2 text-right" type="number" min="0"
                  placeholder={t("Qty", "Jml")}
                  value={row.qty}
                  onChange={(e) => setEditItems((rows) => rows!.map(
                    (x, j) => (j === i ? { ...x, qty: e.target.value } : x)))}
                />
                <input
                  className="input col-span-4 sm:col-span-2"
                  placeholder={t("UoM", "Satuan")}
                  value={row.uom}
                  onChange={(e) => setEditItems((rows) => rows!.map(
                    (x, j) => (j === i ? { ...x, uom: e.target.value } : x)))}
                />
                <input
                  className="input col-span-3 sm:col-span-2"
                  placeholder={t("Spec", "Spesifikasi")}
                  value={row.spec}
                  onChange={(e) => setEditItems((rows) => rows!.map(
                    (x, j) => (j === i ? { ...x, spec: e.target.value } : x)))}
                />
                <button
                  className="col-span-1 grid place-items-center rounded-lg text-red-600
                             hover:bg-red-50"
                  aria-label={t("Remove line", "Hapus baris")}
                  onClick={() => setEditItems((rows) => rows!.filter((_, j) => j !== i))}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}

            <button
              className="btn-ghost text-xs"
              onClick={() => setEditItems((rows) => [
                ...(rows ?? []), { description: "", qty: 1, uom: "", spec: "" }])}
            >
              <Plus size={13} /> {t("Add line", "Tambah baris")}
            </button>

            {editMode === "propose" && (
              <input
                className="input"
                value={reviseReason}
                onChange={(e) => setReviseReason(e.target.value)}
                placeholder={t("Why is this changing? e.g. customer raised the quantity",
                               "Alasan perubahan? cth. pelanggan menambah jumlah")}
              />
            )}
            <div className="flex items-center gap-2 pt-1">
              <button
                className="btn-primary"
                disabled={(editMode === "propose" ? propose.isPending : saveItems.isPending)
                  || !editItems.length
                  || editItems.some((r) => !r.description.trim())}
                onClick={() => (editMode === "propose" ? propose.mutate() : saveItems.mutate())}
              >
                {(editMode === "propose" ? propose.isPending : saveItems.isPending)
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Check size={14} />}
                {editMode === "propose"
                  ? t("Send to director", "Kirim ke direktur")
                  : t("Save changes", "Simpan perubahan")}
              </button>
              <button className="btn-ghost" onClick={() => setEditItems(null)}>
                <X size={14} /> {t("Cancel", "Batal")}
              </button>
              {editItems.some((r) => !r.description.trim()) && (
                <span className="text-xs muted">
                  {t("Every line needs a description.", "Setiap baris perlu deskripsi.")}
                </span>
              )}
            </div>
          </div>
        ) : (
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">#</th><th className="th">{t("Description", "Deskripsi")}</th>
              <th className="th text-right">{t("Qty", "Jml")}</th><th className="th">{t("UoM", "Satuan")}</th>
              <th className="th">{t("Spec", "Spesifikasi")}</th>
              {pr.items?.[0] && "cost_price" in pr.items[0] && <th className="th text-right">{t("Cost", "Biaya")}</th>}
              {pr.items?.[0] && "sell_price" in pr.items[0] && <th className="th text-right">{t("Sell", "Jual")}</th>}
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
        )}

        {(canCost || canApprove || canSubmit) && (
          <div className="mt-4 flex items-center gap-2 flex-wrap">
            {(canCost || canApprove) && (
              <input className="input flex-1 min-w-[200px]" placeholder={t("Notes (optional)", "Catatan (opsional)")}
                value={notes} onChange={(e) => setNotes(e.target.value)} />
            )}
            {canSubmit && (
              <button className="btn-primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
                <Send size={14} /> {t("Submit to purchasing", "Kirim ke pembelian")}
              </button>
            )}
            {canCost && (isPurchasing || isDirector) && (
              <button className="btn-primary" disabled={price.isPending} onClick={() => price.mutate()}>
                <Check size={14} /> {t("Submit costs", "Kirim biaya")}
              </button>
            )}
            {canApprove && (
              <button className="btn-primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
                <Check size={14} /> {t("Set prices & approve", "Tetapkan harga & setujui")}
              </button>
            )}
            {(isDirector || isPurchasing || role === "manager") && pr.status !== "approved" && pr.status !== "draft" && (
              <button className="btn-ghost text-red-600" disabled={reject.isPending} onClick={() => reject.mutate()}>
                <X size={14} /> {t("Send back", "Kembalikan")}
              </button>
            )}
          </div>
        )}
        {pr.decision_notes && <div className="mt-3 text-xs muted">{t("Note:", "Catatan:")} {pr.decision_notes}</div>}
      </div>

      {(revisions.data?.revisions ?? []).length > 0 && (
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="overline">{t("Negotiation log", "Riwayat negosiasi")}</span>
            <span className="text-xs muted ml-auto">
              {t(`${revisions.data.applied} of ${revisions.data.limit} revisions used`,
                 `${revisions.data.applied} dari ${revisions.data.limit} revisi terpakai`)}
            </span>
          </div>
          <div className="space-y-2">
            {revisions.data.revisions.map((rv: any) => (
              <div key={rv.n} className={clsx(
                "rounded-lg border px-3 py-2 text-sm",
                rv.status === "approved" ? "border-emerald-200 bg-emerald-50/50"
                : rv.status === "rejected" ? "border-red-200 bg-red-50/50"
                : "border-amber-200 bg-amber-50/50",
              )}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">#{rv.n}</span>
                  <span className={clsx("chip",
                    rv.status === "approved" ? "bg-emerald-100 text-emerald-800"
                    : rv.status === "rejected" ? "bg-red-100 text-red-800"
                    : "bg-amber-100 text-amber-800")}>
                    {rv.status === "approved" ? t("approved", "disetujui")
                     : rv.status === "rejected" ? t("rejected", "ditolak")
                     : t("waiting", "menunggu")}
                  </span>
                  <span className="muted text-xs">{rv.requested_by_name}</span>
                  <span className="muted text-xs">
                    {rv.requested_at ? new Date(rv.requested_at).toLocaleString(locale()) : ""}
                  </span>
                  {rv.decided_by_name && (
                    <span className="muted text-xs ml-auto">
                      {t("decided by", "diputuskan")} {rv.decided_by_name}
                    </span>
                  )}
                </div>
                {rv.reason && <div className="mt-1">{rv.reason}</div>}
                {(rv.changes ?? []).length > 0 && (
                  <ul className="mt-1 text-xs muted list-disc pl-5">
                    {rv.changes.map((ch: any, i: number) => (
                      <li key={i}>
                        {ch.kind === "added" && t(`added ${ch.description} × ${ch.qty}`,
                                                  `tambah ${ch.description} × ${ch.qty}`)}
                        {ch.kind === "removed" && t(`removed ${ch.description}`,
                                                    `hapus ${ch.description}`)}
                        {ch.kind === "qty" && t(`${ch.description}: ${ch.from} → ${ch.to}`,
                                                `${ch.description}: ${ch.from} → ${ch.to}`)}
                      </li>
                    ))}
                  </ul>
                )}
                {rv.decision_notes && (
                  <div className="mt-1 text-xs muted">
                    {t("Note:", "Catatan:")} {rv.decision_notes}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Spec sheets / customer RFQ files ride on the PR so purchasing can
          cost from the source documents. */}
      <AttachmentsSection ownerType="price_request" ownerId={id} />

      {/* Internal discussion thread — sales ↔ purchasing ↔ director talk
          about the pricing without abusing the notes field. */}
      <CommentThread ownerType="price_request" ownerId={id} />

      {activityOpen && pr.customer_id && (
        <Modal open={activityOpen} onClose={() => setActivityOpen(false)}
          title={tt("Log activity", "Catat aktivitas")}>
          <LogActivityForm
            customerId={pr.customer_id}
            onClose={() => setActivityOpen(false)}
          />
        </Modal>
      )}
    </div>
  );
}
