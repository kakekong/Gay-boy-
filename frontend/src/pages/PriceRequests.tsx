import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Tag, Plus, Trash2, Send, Check, X, Loader2, ArrowLeft, FileText,
  Pencil, ClipboardList,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { UnitSelect } from "@/components/UnitSelect";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, T, locale } from "@/store/lang";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { LogActivityForm } from "@/components/forms/LogActivityForm";
import { Modal } from "@/components/Modal";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

// The four units goods are counted in. A dropdown rather than a text box on
// purpose: this is the field that quietly corrupts a quantity, because 30
// metres of cable recorded as 30 pieces looks entirely plausible. The server
// keeps the same list and maps the older spellings ("EA", "m") onto it.
const emptyLine = () => ({
  // No line_no: this row is new, and the server reads its absence as "nobody
  // has priced this yet". Rows loaded from an existing request carry theirs,
  // which is what lets a description be reworded without losing its price.
  line_no: undefined as number | undefined,
  sku: "", description: "", category: "", qty: 1, uom: "", link: "", spec: "",
});

/**
 * The lists a line is built from, straight from the server.
 *
 * Shared across every line on the page — react-query dedupes it to one
 * request — and long-lived, because a fixed list does not move.
 */
function usePrCatalog() {
  const q = useQuery({
    queryKey: ["pr-catalog"],
    queryFn: () => api.get("/price-requests/catalog")
      .then((r) => r.data as { categories: { value: string; label: string }[] }),
    staleTime: 30 * 60_000,
  });
  return q.data?.categories ?? FALLBACK_CATEGORIES;
}

/**
 * How a stored category reads. Values written before the list existed are
 * free text and are shown as they are rather than hidden behind a guess.
 */
function categoryLabel(
  value: string | null | undefined,
  options: { value: string; label: string }[],
): string {
  if (!value) return "—";
  return options.find((o) => o.value === value)?.label ?? value;
}

/** The six the server accepts, as a fallback until the catalog loads. */
const FALLBACK_CATEGORIES = [
  { value: "conveyor_chain",  label: "Conveyor chain" },
  { value: "roller_chain",    label: "Roller chain" },
  { value: "connecting_link", label: "Connecting link" },
  { value: "sprocket",        label: "Sprocket" },
  { value: "roller_conveyor", label: "Roller conveyor" },
  { value: "others",          label: "Others" },
];

/**
 * The category of a line — a fixed list, not a text box.
 *
 * It was free text, which produced "sprocket", "Sprockets" and
 * "SPROCKET 12T" for one kind of thing, so nothing could be counted or
 * filtered by it. The list is fetched rather than hardcoded here so the form
 * and the server cannot come to offer different things.
 *
 * A line written before the list existed keeps whatever free text it was
 * given, and that value is offered back as its own option: the server allows
 * an unchanged legacy value through, so somebody correcting a typo elsewhere
 * on an old request is not forced to reclassify it in the same breath.
 */
function CategorySelect({ value, onChange, label, className }: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  className?: string;
}) {
  const options = usePrCatalog();
  const legacy = value && !options.some((o) => o.value === value) ? value : null;
  return (
    <select
      className={className ?? "input w-44"}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{tt("Category…", "Kategori…")}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{tt(o.label, o.label)}</option>
      ))}
      {legacy && (
        <option value={legacy}>{legacy} {tt("(old)", "(lama)")}</option>
      )}
    </select>
  );
}

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
  const [items, setItems] = useState<any[]>([emptyLine()]);
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
        <div className="text-[11px] uppercase muted mb-1">
          {t("Goods needed (no prices)", "Barang yang dibutuhkan (tanpa harga)")}
        </div>
        <p className="text-[11px] muted mb-2">
          {t("Each line becomes a catalogue item when this is submitted — the product only, never the quantity. Stock arrives on a purchase order and leaves on a delivery order.",
             "Setiap baris menjadi item inventaris saat permintaan ini dikirim — produknya saja, bukan jumlahnya. Stok masuk lewat PO pembelian dan keluar lewat surat jalan.")}
        </p>
        <div className="space-y-3">
          {items.map((it, i) => (
            <div key={i} className="rounded-lg border border-ink-200 p-2 space-y-2">
              <div className="flex gap-2 items-center">
                <input className="input w-32" placeholder={t("SKU no.", "No. SKU")}
                  aria-label={`SKU ${i + 1}`} value={it.sku}
                  onChange={(e) => setItem(i, "sku", e.target.value)} />
                <input className="input flex-1"
                  placeholder={t("Product name", "Nama produk")}
                  aria-label={`Product name ${i + 1}`} value={it.description}
                  onChange={(e) => setItem(i, "description", e.target.value)} />
                <button className="btn-ghost text-red-600"
                  aria-label={`Remove line ${i + 1}`}
                  onClick={() => setItems((arr) => arr.filter((_, idx) => idx !== i))}>
                  <Trash2 size={14} />
                </button>
              </div>
              <div className="flex gap-2 items-center flex-wrap">
                <CategorySelect
                  label={`Category ${i + 1}`}
                  value={it.category}
                  onChange={(v) => setItem(i, "category", v)} />
                <input className="input w-20" type="number"
                  placeholder={t("Qty", "Jml")} aria-label={`Qty ${i + 1}`}
                  value={it.qty}
                  onChange={(e) => setItem(i, "qty", Number(e.target.value))} />
                <UnitSelect
                  className="input w-28"
                  label={`Unit ${i + 1}`}
                  value={it.uom}
                  onChange={(v) => setItem(i, "uom", v)} />
                <input className="input flex-1" placeholder="https://…"
                  aria-label={`Link ${i + 1}`} value={it.link}
                  onChange={(e) => setItem(i, "link", e.target.value)} />
              </div>
              <input className="input"
                placeholder={t("Spec / notes", "Spesifikasi / catatan")}
                aria-label={`Spec ${i + 1}`} value={it.spec}
                onChange={(e) => setItem(i, "spec", e.target.value)} />
            </div>
          ))}
        </div>
        <button className="btn-ghost mt-2"
          onClick={() => setItems((a) => [...a, emptyLine()])}>
          <Plus size={14} /> {t("Add line", "Tambah baris")}
        </button>
        <p className="text-[11px] muted mt-1">
          {t("Leave the SKU blank and one is issued from the company's own series.",
             "Kosongkan SKU dan nomor akan dibuat otomatis dari seri perusahaan.")}
        </p>
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
  const categories = usePrCatalog();
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
  // Repricing keeps its own working copy. On a request sitting at
  // pending_director the ordinary cost/approve editors are live at the same
  // time, and sharing one draft between them would let a half-finished
  // correction leak into an approval.
  const [reprice, setReprice] = useState<
    Record<number, { cost?: number; sell?: number; costBasis?: string; sellBasis?: string }> | null
  >(null);
  const [repriceWhy, setRepriceWhy] = useState("");
  const [repriceDone, setRepriceDone] = useState<any | null>(null);
  // Purchasing correcting a cost on a request that has already been approved.
  // Same inline cells as the director's reprice, but it files a revision
  // instead of applying one — the director decides, every time.
  const [costRev, setCostRev] = useState<
    Record<number, { cost?: number; costBasis?: string }> | null
  >(null);
  const [costRevWhy, setCostRevWhy] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [editingNumber, setEditingNumber] = useState(false);
  const [numberDraft, setNumberDraft] = useState("");
  const [activityOpen, setActivityOpen] = useState(false);
  // What the last save did to the quotations built off this request. Shown
  // rather than swallowed: editing a request whose quotation is already won
  // looks, from this screen, exactly like nothing happening — which is how a
  // working rule gets reported as a broken feature.
  const [syncNote, setSyncNote] = useState<any[] | null>(null);
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
    { line_no?: number; sku: string; description: string; category: string;
      qty: number | string; uom: string; link: string; spec: string }[] | null
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
        // Which line this is. Sent so the server can tell a reworded line
        // from a new one, instead of guessing from the description and
        // resetting the price of everything renamed.
        line_no: row.line_no ?? null,
        sku: row.sku.trim() || null,
        description: row.description.trim(),
        category: row.category.trim() || null,
        qty: Number(row.qty) || 0,
        uom: row.uom.trim() || null,
        link: row.link.trim() || null,
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
        // Which line this is. Sent so the server can tell a reworded line
        // from a new one, instead of guessing from the description and
        // resetting the price of everything renamed.
        line_no: row.line_no ?? null,
        sku: row.sku.trim() || null,
        description: row.description.trim(),
        category: row.category.trim() || null,
        qty: Number(row.qty) || 0,
        uom: row.uom.trim() || null,
        link: row.link.trim() || null,
        spec: row.spec.trim() || null,
      })),
    }).then((r) => r.data),
    onSuccess: (data: any) => {
      setEditItems(null);
      setSyncNote(data?.quotations ?? []);
      refresh();
      qc.invalidateQueries({ queryKey: ["quotations"] });
    },
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

  // Anyone who can open the request can add to its notes, at any stage.
  const addNote = useMutation({
    mutationFn: () => api.post(`/price-requests/${id}/note`,
                               { text: noteDraft.trim() }).then((r) => r.data),
    onSuccess: () => { setNoteDraft(""); refresh(); },
    onError: onErr,
  });

  // Only the lines actually typed into are sent: an untouched line has no
  // entry in the draft, so it is never quietly re-stated at its own value.
  const saveReprice = useMutation({
    mutationFn: () => api.post(`/price-requests/${id}/reprice`, {
      items: Object.entries(reprice ?? {}).map(([ln, v]) => ({
        line_no: Number(ln),
        cost_price: v.cost, cost_basis: v.costBasis ?? "unit",
        sell_price: v.sell, sell_basis: v.sellBasis ?? "unit",
      })),
      reason: repriceWhy.trim(),
    }).then((r) => r.data),
    onSuccess: (d) => {
      setReprice(null); setRepriceWhy(""); setRepriceDone(d);
      qc.invalidateQueries({ queryKey: ["quotations"] });
      refresh();
    },
    onError: onErr,
  });

  const proposeCost = useMutation({
    // Every line goes up, not just the touched ones: the server matches lines
    // by description and carries across whatever a revision doesn't mention,
    // so sending the whole list is what keeps the untouched costs intact.
    mutationFn: () => api.post(`/price-requests/${id}/revise`, {
      items: (pr.items ?? []).map((it: any) => {
        const edit = (costRev ?? {})[it.line_no];
        return {
          description: it.description,
          qty: Number(it.qty) || 0,
          uom: it.uom || null,
          spec: it.spec || null,
          ...(edit?.cost !== undefined
            ? { cost_price: edit.cost, cost_basis: edit.costBasis ?? "unit" }
            : {}),
        };
      }),
      reason: costRevWhy.trim() || null,
    }).then((r) => r.data),
    onSuccess: () => {
      setCostRev(null); setCostRevWhy("");
      qc.invalidateQueries({ queryKey: ["pr-revisions", id] });
      refresh();
    },
    onError: onErr,
  });

  // Editable price cell with a per-line "/unit" vs "total" basis selector.
  // Storage is always per-unit; "total" just means the entered figure covers
  // the whole line, and we show the implied unit price (or vice-versa) live.
  const editCell = (
    it: any, kind: "cost" | "sell",
    which: "flow" | "reprice" | "costrev" = "flow",
  ) => {
    const book = which === "reprice" ? (reprice ?? {})
      : which === "costrev" ? (costRev ?? {}) : draft;
    const write = which === "reprice" ? setReprice
      : which === "costrev" ? setCostRev : setDraft;
    // One cell renderer over three books that hold different halves: the
    // cost-revision book has no sell side because purchasing never sets one.
    const v: { cost?: number; sell?: number; costBasis?: string; sellBasis?: string } =
      (book as any)[it.line_no] ?? {};
    const amount = kind === "cost" ? v.cost : v.sell;
    const basis = (kind === "cost" ? v.costBasis : v.sellBasis) ?? "unit";
    const qty = Number(it.qty) || 0;
    const unit = basis === "total" ? (qty ? Number(amount || 0) / qty : 0) : Number(amount || 0);
    const total = basis === "total" ? Number(amount || 0) : Number(amount || 0) * qty;
    const setVal = (patch: any) =>
      write((d: any) => ({ ...(d ?? {}), [it.line_no]: { ...(d ?? {})[it.line_no], ...patch } }));
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
  // A draft has no prices yet, so there is nothing to correct there. From
  // the moment it is submitted onwards the director can change either figure.
  // The notes blob is one tagged line per entry; the untagged first line is
  // whatever was typed on the create form.
  const noteLines = String(pr.notes || "")
    .split("\n")
    .map((raw: string) => raw.trim())
    .filter(Boolean)
    .map((raw: string) => {
      const m = raw.match(/^\[(purchasing|director|manager|admin|finance|sales)\]\s*(.*)$/i);
      return m ? { tag: m[1].toLowerCase(), text: m[2] } : { tag: "", text: raw };
    });
  const canReprice = isDirector && pr.status !== "draft";
  const repricing = reprice !== null;
  const revLeft = revisions.data?.left ?? 0;
  const revPending = (revisions.data?.revisions ?? []).some((r: any) => r.status === "pending");
  // Negotiation path: propose a change on a request that has already gone out.
  const canPropose = !stillDraft && !revPending && revLeft > 0
    && (role === "sales" || role === "manager" || role === "admin" || isDirector);
  // Purchasing's own path, for after the director has signed the request off
  // and `canCost` has closed: a supplier moving their price is not a reason to
  // go and ask somebody else to retype it. Uncapped — it spends none of the
  // negotiation budget — but every one goes to the director.
  const canProposeCost = isPurchasing && !stillDraft && !canCost && !revPending;
  const costRevising = costRev !== null;
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

        {syncNote !== null && (
          <div className={clsx(
            "mt-3 rounded-lg border px-3 py-2 text-xs flex items-start gap-2",
            syncNote.every((x: any) => x.synced)
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-amber-200 bg-amber-50 text-amber-900",
          )}>
            <div className="flex-1 space-y-0.5">
              {syncNote.length === 0 ? (
                <div>
                  {t("Saved. No quotation has been made from this request yet.",
                     "Tersimpan. Belum ada penawaran yang dibuat dari permintaan ini.")}
                </div>
              ) : syncNote.map((x: any) => (
                <div key={x.quotation_id}>
                  {x.synced ? (
                    <>
                      <b className="font-mono">{x.number}</b>{" "}
                      {t("was updated to match — it is still a draft, so it follows this request.",
                         "diperbarui agar sesuai — masih draf, jadi mengikuti permintaan ini.")}
                    </>
                  ) : (
                    <>
                      <b className="font-mono">{x.number}</b>{" "}
                      {t(`is ${sl(x.status)} and was left as it is — the customer may be holding it. It now comes to Rp ${new Intl.NumberFormat("id-ID").format(Math.round(x.new_total || 0))} against the Rp ${new Intl.NumberFormat("id-ID").format(Math.round(x.old_total || 0))} quoted. Revise the quotation if they should see the new figure.`,
                         `berstatus ${sl(x.status)} dan dibiarkan apa adanya — pelanggan mungkin sedang memegangnya. Sekarang menjadi Rp ${new Intl.NumberFormat("id-ID").format(Math.round(x.new_total || 0))} dibanding Rp ${new Intl.NumberFormat("id-ID").format(Math.round(x.old_total || 0))} yang ditawarkan. Revisi penawarannya bila pelanggan harus melihat angka baru.`)}
                    </>
                  )}
                </div>
              ))}
            </div>
            <button onClick={() => setSyncNote(null)}
              aria-label={t("Dismiss", "Tutup")}
              className="opacity-60 hover:opacity-100"><X size={13} /></button>
          </div>
        )}

        <div className="mt-4 flex items-center gap-2">
          <span className="overline">{t("Items", "Barang")}</span>
          {canEditItems && editItems === null && (
            <button
              className="btn-ghost ml-auto text-xs"
              onClick={() => { setEditMode("edit"); setEditItems((pr.items ?? []).map((it: any) => ({
                line_no: it.line_no,
                sku: it.sku ?? "",
                description: it.description ?? "",
                category: it.category ?? "",
                qty: it.qty ?? 1,
                uom: it.uom ?? "",
                link: it.link ?? "",
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
                  line_no: it.line_no,
                  sku: it.sku ?? "", description: it.description ?? "",
                  category: it.category ?? "", qty: it.qty ?? 1,
                  uom: it.uom ?? "", link: it.link ?? "",
                  spec: it.spec ?? "",
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
                  {t("Existing lines keep their cost and approved price, however you reword them. A line you add comes back unpriced and has to go through purchasing.",
                     "Baris yang sudah ada tetap membawa biaya dan harga yang disetujui, bagaimanapun Anda mengubah kalimatnya. Baris yang Anda tambahkan akan kosong dan harus melalui pembelian.")}
                </div>
                {pr.quotation_id && (
                  <div>
                    {t("The quotation made from this request follows it: still a draft, it is rewritten to match. Already submitted or sent, it is left alone and told that this changed.",
                       "Penawaran yang dibuat dari permintaan ini mengikutinya: bila masih draf, ditulis ulang agar sesuai. Bila sudah diajukan atau dikirim, dibiarkan dan diberi catatan bahwa ini berubah.")}
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

            {editItems.map((row, i) => {
              const set = (field: string, value: any) => setEditItems((rows) =>
                rows!.map((x, j) => (j === i ? { ...x, [field]: value } : x)));
              return (
              <div key={i} className="grid grid-cols-12 gap-2 rounded-lg
                                      border border-ink-200 p-2">
                <input
                  className="input col-span-5 sm:col-span-3"
                  placeholder={t("SKU no.", "No. SKU")}
                  aria-label={`Edit SKU ${i + 1}`}
                  value={row.sku}
                  onChange={(e) => set("sku", e.target.value)}
                />
                <input
                  className="input col-span-6 sm:col-span-8"
                  placeholder={t("Product name", "Nama produk")}
                  aria-label={`Edit product name ${i + 1}`}
                  value={row.description}
                  onChange={(e) => set("description", e.target.value)}
                />
                <button
                  className="col-span-1 grid place-items-center rounded-lg text-red-600
                             hover:bg-red-50"
                  aria-label={t("Remove line", "Hapus baris")}
                  onClick={() => setEditItems((rows) => rows!.filter((_, j) => j !== i))}
                >
                  <Trash2 size={14} />
                </button>
                <CategorySelect
                  className="input col-span-6 sm:col-span-3"
                  label={`Edit category ${i + 1}`}
                  value={row.category}
                  onChange={(v) => set("category", v)} />
                <input
                  className="input col-span-3 sm:col-span-2 text-right" type="number" min="0"
                  placeholder={t("Qty", "Jml")}
                  aria-label={`Edit qty ${i + 1}`}
                  value={row.qty}
                  onChange={(e) => set("qty", e.target.value)}
                />
                <UnitSelect
                  className="input col-span-3 sm:col-span-2"
                  label={`Edit unit ${i + 1}`}
                  value={row.uom}
                  onChange={(v) => set("uom", v)} />
                <input
                  className="input col-span-12 sm:col-span-5"
                  placeholder="https://…"
                  aria-label={`Edit link ${i + 1}`}
                  value={row.link}
                  onChange={(e) => set("link", e.target.value)}
                />
                <input
                  className="input col-span-12"
                  placeholder={t("Spec", "Spesifikasi")}
                  aria-label={`Edit spec ${i + 1}`}
                  value={row.spec}
                  onChange={(e) => set("spec", e.target.value)}
                />
              </div>
              );
            })}

            <button
              className="btn-ghost text-xs"
              onClick={() => setEditItems((rows) => [...(rows ?? []), emptyLine()])}
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
              <th className="th">#</th>
              <th className="th">{t("SKU", "SKU")}</th>
              <th className="th">{t("Product", "Produk")}</th>
              <th className="th">{t("Category", "Kategori")}</th>
              <th className="th text-right">{t("Qty", "Jml")}</th><th className="th">{t("Unit", "Satuan")}</th>
              <th className="th">{t("Spec", "Spesifikasi")}</th>
              {pr.items?.[0] && "cost_price" in pr.items[0] && <th className="th text-right">{t("Cost", "Biaya")}</th>}
              {pr.items?.[0] && "sell_price" in pr.items[0] && <th className="th text-right">{t("Sell", "Jual")}</th>}
            </tr>
          </thead>
          <tbody>
            {(pr.items ?? []).map((it: any) => (
              <tr key={it.line_no} className="border-t border-ink-100">
                <td className="td muted">{it.line_no}</td>
                <td className="td font-mono text-xs">
                  {it.sku || <span className="muted">{t("on submit", "saat dikirim")}</span>}
                </td>
                <td className="td">
                  {it.description}
                  {it.link && (
                    // rel=noreferrer: the link is typed by a person and points
                    // off our site, so the target learns nothing about where
                    // it was clicked from.
                    <a href={it.link} target="_blank" rel="noreferrer noopener"
                      className="ml-1.5 text-brand-700 hover:underline text-xs">
                      {t("link", "tautan")}
                    </a>
                  )}
                </td>
                <td className="td muted text-xs">
                  {categoryLabel(it.category, categories)}
                </td>
                <td className="td text-right tabular-nums">{it.qty}</td>
                <td className="td muted">{it.uom || "—"}</td>
                <td className="td muted text-xs">{it.spec || "—"}</td>
                {"cost_price" in it && (
                  <td className="td text-right">
                    {repricing ? editCell(it, "cost", "reprice")
                      : costRevising ? editCell(it, "cost", "costrev")
                      : canCost && (isPurchasing || isDirector)
                        ? editCell(it, "cost")
                        : readCell(it.cost_price, it.cost_total, it.qty)}
                  </td>
                )}
                {"sell_price" in it && (
                  <td className="td text-right">
                    {repricing ? editCell(it, "sell", "reprice")
                      : canApprove
                        ? editCell(it, "sell")
                        : readCell(it.sell_price, it.line_total, it.qty)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        )}

        {/* ── the director correcting a settled figure ──────────────────── */}
        {repricing && (
          <div className="mt-4 rounded-lg border border-violet-200 bg-violet-50 p-3 space-y-2">
            <div className="text-sm font-semibold text-violet-900 flex items-center gap-2">
              <Pencil size={14} />
              {t("Changing the agreed figures", "Mengubah angka yang sudah disepakati")}
            </div>
            <p className="text-xs text-violet-900">
              {t("Type over any cost or price above — leave the rest alone and they stay as they are. A quotation still in draft is updated to match; one already sent or approved is left as it went out.",
                 "Ketik ulang biaya atau harga di atas — yang tidak diubah tetap sama. Penawaran yang masih draf akan disesuaikan; yang sudah terkirim atau disetujui dibiarkan apa adanya.")}
            </p>
            <input className="input" value={repriceWhy} maxLength={200}
              onChange={(e) => setRepriceWhy(e.target.value)}
              placeholder={t("Why is it changing? e.g. supplier revised the quote",
                             "Mengapa berubah? mis. supplier merevisi penawarannya")} />
            <div className="flex items-center gap-2">
              <button className="btn-ghost"
                onClick={() => { setReprice(null); setRepriceWhy(""); }}>
                {t("Cancel", "Batal")}
              </button>
              <button className="btn-primary ml-auto"
                disabled={saveReprice.isPending || !repriceWhy.trim()
                          || !Object.keys(reprice ?? {}).length}
                onClick={() => saveReprice.mutate()}>
                <Check size={14} /> {t("Save new figures", "Simpan angka baru")}
              </button>
            </div>
          </div>
        )}
        {/* ── purchasing asking to move a cost that has already been signed ── */}
        {costRevising && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
            <div className="text-sm font-semibold text-amber-900 flex items-center gap-2">
              <Pencil size={14} />
              {t("Proposing a new cost", "Mengajukan biaya baru")}
            </div>
            <p className="text-xs text-amber-900">
              {t("Type over the costs above that have changed — the rest stay as they are. Nothing moves until the director approves it, and this doesn't use up the sales team's revisions.",
                 "Ketik ulang biaya di atas yang berubah — sisanya tetap. Tidak ada yang berubah sampai direktur menyetujui, dan ini tidak memakai jatah revisi tim penjualan.")}
            </p>
            <input className="input" value={costRevWhy} maxLength={200}
              onChange={(e) => setCostRevWhy(e.target.value)}
              placeholder={t("Why is it changing? e.g. supplier revised the quote",
                             "Mengapa berubah? mis. supplier merevisi penawarannya")} />
            <div className="flex items-center gap-2">
              <button className="btn-ghost"
                onClick={() => { setCostRev(null); setCostRevWhy(""); }}>
                {t("Cancel", "Batal")}
              </button>
              <button className="btn-primary ml-auto"
                disabled={proposeCost.isPending || !costRevWhy.trim()
                          || !Object.keys(costRev ?? {}).length}
                onClick={() => proposeCost.mutate()}>
                <Send size={14} /> {t("Send to director", "Kirim ke direktur")}
              </button>
            </div>
          </div>
        )}
        {repriceDone && (
          <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2
                          text-sm text-emerald-900">
            {repriceDone.changed_lines === 0
              ? t("Those are the same figures — nothing changed.",
                  "Angkanya sama — tidak ada yang berubah.")
              : t(`${repriceDone.changed_lines} line${repriceDone.changed_lines === 1 ? "" : "s"} updated.`,
                  `${repriceDone.changed_lines} baris diperbarui.`)}
            {repriceDone.quotation && (repriceDone.quotation.action === "updated"
              ? " " + t(`Quotation ${repriceDone.quotation.number} was still a draft and now matches.`,
                        `Penawaran ${repriceDone.quotation.number} masih draf dan kini sudah sesuai.`)
              : " " + t(`Quotation ${repriceDone.quotation.number} has already gone out (${repriceDone.quotation.status}) and was left as it is — issue a revision if the customer needs the new price.`,
                        `Penawaran ${repriceDone.quotation.number} sudah keluar (${repriceDone.quotation.status}) dan dibiarkan — terbitkan revisi bila pelanggan perlu harga baru.`))}
          </div>
        )}

        {canProposeCost && !costRevising && (
          <div className="mt-4 flex items-center gap-2 flex-wrap">
            <button className="btn-ghost border-ink-200"
              onClick={() => setCostRev({})}
              title={t("Ask the director to change a cost that has already been approved",
                       "Minta direktur mengubah biaya yang sudah disetujui")}>
              <Pencil size={14} /> {t("Propose a cost change", "Ajukan perubahan biaya")}
            </button>
            <span className="text-xs muted">
              {t("The director approves each one.", "Direktur menyetujui setiap perubahan.")}
            </span>
          </div>
        )}
        {isPurchasing && revPending && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {t("A change is already with the director. Wait for that decision before proposing another.",
               "Sebuah perubahan sudah berada di direktur. Tunggu keputusannya sebelum mengajukan lagi.")}
          </div>
        )}

        {(canCost || canApprove || canSubmit || canReprice) && (
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
            {canReprice && !repricing && (
              <button className="btn-ghost border-ink-200"
                onClick={() => { setReprice({}); setRepriceDone(null); }}
                title={t("Change a cost or a selling price that has already been set",
                         "Ubah biaya atau harga jual yang sudah ditetapkan")}>
                <Pencil size={14} /> {t("Change prices", "Ubah harga")}
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

      {/* Notes on the request.
          The blob is a running log of role-tagged lines, and the server has
          already removed the ones this reader is not entitled to — sales sees
          its own and the untagged original, never purchasing's costings. */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="overline">{t("Notes", "Catatan")}</span>
          <span className="text-xs muted ml-auto">
            {t("Anyone working this request can add one",
               "Siapa pun yang menangani permintaan ini bisa menambahkan")}
          </span>
        </div>
        {noteLines.length === 0 ? (
          <p className="text-sm muted">
            {t("No notes yet.", "Belum ada catatan.")}
          </p>
        ) : (
          <div className="space-y-1.5">
            {noteLines.map((ln, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                {ln.tag && (
                  <span className="chip bg-ink-100 text-ink-700 capitalize shrink-0">
                    {sl(ln.tag)}
                  </span>
                )}
                <span className="whitespace-pre-wrap">{ln.text}</span>
              </div>
            ))}
          </div>
        )}
        <div className="mt-3 flex items-center gap-2">
          <input className="input flex-1" value={noteDraft} maxLength={1000}
            placeholder={t("Add a note…", "Tambah catatan…")}
            onChange={(e) => setNoteDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && noteDraft.trim()) addNote.mutate();
            }} />
          <button className="btn-primary"
            disabled={addNote.isPending || !noteDraft.trim()}
            onClick={() => addNote.mutate()}>
            <Send size={14} /> {t("Add", "Tambah")}
          </button>
        </div>
      </div>

      {/* What the director changed after the fact. Distinct from the
          negotiation log above: that is sales asking, this is the decision
          already applied. Shown to everybody who can see the figure that
          moved — the server has already stripped the one they cannot. */}
      {(pr.price_history ?? []).length > 0 && (
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="overline">{t("Price changes", "Perubahan harga")}</span>
            <span className="text-xs muted ml-auto">
              {t("Made after the figures were first agreed",
                 "Dilakukan setelah angka pertama disepakati")}
            </span>
          </div>
          <div className="space-y-2">
            {[...(pr.price_history ?? [])].reverse().map((h: any, i: number) => (
              <div key={i} className="rounded-lg border border-ink-200 p-3">
                <div className="flex items-center gap-2 flex-wrap text-xs muted">
                  <b className="text-ink-900">{h.by}</b>
                  <span>{h.at ? new Date(h.at).toLocaleString(locale()) : ""}</span>
                  {h.status_then && (
                    <span className="chip bg-ink-100 text-ink-700">{sl(h.status_then)}</span>
                  )}
                </div>
                {h.reason && <div className="text-sm mt-1">{h.reason}</div>}
                <div className="mt-2 space-y-0.5">
                  {(h.lines ?? []).map((ln: any) => (
                    <div key={ln.line_no} className="text-xs flex flex-wrap gap-x-3">
                      <span className="muted">#{ln.line_no}</span>
                      <span className="font-medium">{ln.description}</span>
                      {"cost_to" in ln && (
                        <span className="tabular-nums">
                          {t("cost", "biaya")}{" "}
                          <span className="line-through muted">{idr(ln.cost_from ?? 0)}</span>
                          {" → "}<b>{idr(ln.cost_to)}</b>
                        </span>
                      )}
                      {"sell_to" in ln && (
                        <span className="tabular-nums">
                          {t("price", "harga")}{" "}
                          <span className="line-through muted">{idr(ln.sell_from ?? 0)}</span>
                          {" → "}<b>{idr(ln.sell_to)}</b>
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                {h.quotation && (
                  <div className="text-[11px] muted mt-2">
                    {h.quotation.action === "updated"
                      ? t(`Quotation ${h.quotation.number} was updated to match.`,
                          `Penawaran ${h.quotation.number} ikut disesuaikan.`)
                      : t(`Quotation ${h.quotation.number} had already gone out and was left as it was.`,
                          `Penawaran ${h.quotation.number} sudah keluar dan dibiarkan.`)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

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
                  {rv.kind === "cost" && (
                    <span className="chip bg-ink-100 text-ink-700"
                      title={t("A cost correction from purchasing — it doesn't use a negotiation revision",
                               "Koreksi biaya dari pembelian — tidak memakai jatah revisi negosiasi")}>
                      {t("cost", "biaya")}
                    </span>
                  )}
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
                        {ch.kind === "cost" && t(
                          `${ch.description}: cost ${idr(ch.from ?? 0)} → ${idr(ch.to ?? 0)}`,
                          `${ch.description}: biaya ${idr(ch.from ?? 0)} → ${idr(ch.to ?? 0)}`)}
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
