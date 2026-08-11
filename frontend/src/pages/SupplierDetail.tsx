import { Link, useNavigate, useParams } from "react-router-dom";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Building2, Star, Truck, Loader2, AlertCircle, Mail, Phone,
  Briefcase, PackageCheck, CheckCircle2, Paperclip, Eye, Download,
  MapPin, MessageCircle, Pencil, Save,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { ContactsSection } from "@/components/ContactsSection";
import { useAuthStore } from "@/store/auth";
import { useT, T, locale } from "@/store/lang";

interface Contact { name?: string; phone?: string; email?: string }

/** A named person at the supplier, with their own line — same row shape the
 *  customer's PICs use, because it is the same card rendering them. */
interface SupplierPIC {
  id: string;
  name: string;
  position: string | null;
  phone: string | null;
  whatsapp: string | null;
  email: string | null;
  is_primary: boolean;
  notes: string | null;
}

interface PO {
  id: string;
  number: string;
  status: string;
  po_date: string | null;
  total: number;
  project_id: string | null;
}

interface SupplierFile {
  id: string;
  filename: string;
  content_type: string | null;
  size: number;
  po_number: string | null;
  uploaded_at: string;
}

interface SupplierDetail {
  id: string;
  name: string;
  category: string | null;
  rating: number;
  lead_time_days_avg: number;
  qc_fail_rate: number;
  price_volatility: number;
  company_address: string | null;
  warehouse_address: string | null;
  phone: string | null;
  whatsapp: string | null;
  email: string | null;
  contacts: SupplierPIC[];
  contact: Contact;
  po_count: number;
  open_po_count: number;
  lifetime_value: number;
  purchase_orders: PO[];
  projects: { id: string; code: string; status: string; target_delivery: string | null }[];
  goods_receipts: { id: string; po_number: string | null; received_at: string | null; status: string; items: any[] }[];
  qc_reports: { id: string; po_number: string | null; pass_qty: number; fail_qty: number; decision: string; findings: string | null }[];
  files: SupplierFile[];
}

const POSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [preview, setPreview] = useState<SupplierFile | null>(null);
  const me = useAuthStore((st) => st.user);
  // Who maintains the directory: the same set the API accepts a PATCH from.
  // Sales can read a supplier (names, ratings) but does not keep its record.
  const canEdit = ["director", "manager", "admin", "purchasing"]
    .includes(me?.role ?? "");

  const q = useQuery({
    queryKey: ["supplier", id],
    queryFn: () => api.get(`/purchasing/suppliers/${id}`)
      .then((r) => r.data as SupplierDetail),
    enabled: !!id,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {T("Loading supplier…")}</div>
    );
  }
  if (q.error || !q.data) {
    const httpStatus = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {httpStatus === 404 ? T("Supplier not found") : T("Couldn't load supplier")}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {(q.error as any)?.response?.data?.detail ?? T("Try again.")}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchasing")}>
          <ArrowLeft size={14} /> {T("Back to Purchasing")}</button>
      </div>
    );
  }

  const s = q.data;
  const c = s.contact || {};
  // Defensive: an older API build may not return these arrays yet — never crash.
  const projects = s.projects ?? [];
  const goodsReceipts = s.goods_receipts ?? [];
  const qcReports = s.qc_reports ?? [];
  const files = s.files ?? [];

  return (
    <div className="space-y-5">
      <Link
        to="/purchasing"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> {T("Back to Purchasing")}</Link>

      <div className="card p-6 lg:p-8 space-y-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Building2 size={13} className="text-brand-600" /> {T("Supplier")}</div>
            <h1 className="text-2xl font-semibold tracking-tight mt-0.5">{s.name}</h1>
            <div className="text-xs muted mt-1">{s.category ?? T("Uncategorised")}</div>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Stat
              label={T("Rating")}
              value={
                <span className="inline-flex items-center gap-1 tabular-nums">
                  <Star size={13} className="text-amber-500" />
                  {s.rating.toFixed(2)}
                </span>
              }
            />
            <Stat label={T("Avg lead")} value={`${s.lead_time_days_avg.toFixed(1)} d`} />
            <Stat label={T("QC fail")} value={`${(s.qc_fail_rate * 100).toFixed(1)}%`} />
            <Stat label={T("Volatility")} value={s.price_volatility.toFixed(2)} />
          </div>
        </div>

        <CompanyCard supplier={s} legacy={c} canEdit={canEdit} onSaved={() => q.refetch()} />
      </div>

      {/* The people, and the vendor's own paperwork — the same two cards the
          customer page carries, for the same reasons. A supplier is not one
          phone number, and the company deed / NPWP / bank details have to
          live somewhere other than an inbox. */}
      <ContactsSection supplierId={s.id} />
      {canEdit && <AttachmentsSection ownerType="supplier" ownerId={s.id} />}

      {/* PO history */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
        <BigStat label={T("POs issued")} value={s.po_count} />
        <BigStat label={T("Open POs")} value={s.open_po_count} tone="amber" />
        <BigStat label={T("Lifetime spend")} value={idr(s.lifetime_value)} />
      </div>

      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
          <Truck size={15} className="text-brand-600" />
          <span className="font-semibold">{T("Purchase orders")}</span>
          <span className="text-[10px] uppercase tracking-wider muted ml-auto">
            {s.purchase_orders.length}
          </span>
        </header>
        {!s.purchase_orders.length ? (
          <div className="p-8 text-center text-sm muted">
            {T("No POs issued to this supplier yet.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("PO number")}</th>
                <th className="th">{T("PO date")}</th>
                <th className="th">{T("Project")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Total")}</th>
              </tr>
            </thead>
            <tbody>
              {s.purchase_orders.map((p) => (
                <tr key={p.id} className="border-t border-ink-100 tr-hover">
                  <td className="td">
                    <Link
                      to={`/purchase-orders/${p.id}`}
                      className="font-mono text-xs text-brand-700 hover:underline"
                    >
                      {p.number}
                    </Link>
                  </td>
                  <td className="td muted">{p.po_date ?? "—"}</td>
                  <td className="td font-mono text-xs muted">
                    {p.project_id ? p.project_id.slice(0, 8) : "—"}
                  </td>
                  <td className="td">
                    <span className={clsx(
                      "chip capitalize",
                      POSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
                    )}>
                      {T(p.status.replace(/_/g, " "))}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(p.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Projects supplied */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
          <Briefcase size={15} className="text-brand-600" />
          <span className="font-semibold">{T("Projects supplied")}</span>
          <span className="text-[10px] uppercase tracking-wider muted ml-auto">{projects.length}</span>
        </header>
        {!projects.length ? (
          <div className="p-8 text-center text-sm muted">{T("Not linked to any project yet.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr><th className="th">{T("Code")}</th><th className="th">{T("Status")}</th><th className="th">{T("Target delivery")}</th></tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-t border-ink-100 tr-hover cursor-pointer"
                  onClick={() => nav(`/projects/${p.id}`)}>
                  <td className="td font-mono text-xs">
                    <Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()}
                      className="text-brand-700 hover:underline">{p.code}</Link>
                  </td>
                  <td className="td capitalize">{T(p.status?.replace(/_/g, " "))}</td>
                  <td className="td muted">{p.target_delivery ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* GR + QC history */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
            <PackageCheck size={15} className="text-brand-600" />
            <span className="font-semibold">{T("Goods receipts")}</span>
            <span className="text-[10px] uppercase tracking-wider muted ml-auto">{goodsReceipts.length}</span>
          </header>
          {!goodsReceipts.length ? (
            <div className="p-6 text-center text-sm muted">{T("No receipts yet.")}</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr><th className="th">{T("PO")}</th><th className="th">{T("Received")}</th><th className="th">{T("Items")}</th><th className="th">{T("Status")}</th></tr>
              </thead>
              <tbody>
                {goodsReceipts.map((g) => (
                  <tr key={g.id} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{g.po_number ?? "—"}</td>
                    <td className="td muted">{g.received_at ?? "—"}</td>
                    <td className="td muted">{(g.items ?? []).length} {T("line(s)")}</td>
                    <td className="td capitalize">{g.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
            <CheckCircle2 size={15} className="text-brand-600" />
            <span className="font-semibold">{T("QC reports")}</span>
            <span className="text-[10px] uppercase tracking-wider muted ml-auto">{qcReports.length}</span>
          </header>
          {!qcReports.length ? (
            <div className="p-6 text-center text-sm muted">{T("No inspections yet.")}</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr><th className="th">{T("PO")}</th><th className="th text-right">{T("Pass")}</th><th className="th text-right">{T("Fail")}</th><th className="th">{T("Decision")}</th></tr>
              </thead>
              <tbody>
                {qcReports.map((r) => (
                  <tr key={r.id} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{r.po_number ?? "—"}</td>
                    <td className="td text-right tabular-nums text-emerald-700">{r.pass_qty}</td>
                    <td className="td text-right tabular-nums text-red-700">{r.fail_qty}</td>
                    <td className="td capitalize">
                      <span className={clsx("chip",
                        r.decision === "accepted" ? "bg-emerald-50 text-emerald-700"
                        : r.decision === "rejected" ? "bg-red-50 text-red-700"
                        : "bg-amber-50 text-amber-700")}>{r.decision}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Files uploaded against this supplier's POs */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
          <Paperclip size={15} className="text-brand-600" />
          <span className="font-semibold">{T("Files")}</span>
          <span className="text-[10px] uppercase tracking-wider muted ml-auto">{files.length}</span>
        </header>
        {!files.length ? (
          <div className="p-8 text-center text-sm muted">{T("No files uploaded for this supplier yet.")}</div>
        ) : (
          <ul className="divide-y divide-ink-100">
            {files.map((f) => (
              <li key={f.id} className="px-4 py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate">{f.filename}</div>
                  <div className="text-[11px] muted">
                    {f.po_number ? `PO ${f.po_number} · ` : ""}{new Date(f.uploaded_at).toLocaleString(locale())}
                  </div>
                </div>
                <button className="btn-ghost" title={T("View")} onClick={() => setPreview(f)}><Eye size={14} /></button>
                <button className="btn-ghost" title={T("Download")}
                  onClick={() => downloadFile(`/attachments/${f.id}/download`, f.filename)}>
                  <Download size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {preview && (
        <FilePreviewModal
          attachmentId={preview.id}
          filename={preview.filename}
          contentType={preview.content_type}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}

/**
 * Where the supplier is and how the company itself is reached.
 *
 * Company-level, deliberately: the switchboard and the sales@ mailbox outlive
 * whoever is answering them this year, and a named person's own number
 * belongs on their row in the Contacts card below. The record used to be
 * write-once — a typo in an address could only be fixed by creating a second
 * supplier, which splits the PO history — so this edits in place.
 *
 * The legacy `contact` blob is read as a fallback for rows created before the
 * columns existed, and never written back to.
 */
function CompanyCard({ supplier, legacy, canEdit, onSaved }: {
  supplier: SupplierDetail;
  legacy: Contact;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({
    company_address: supplier.company_address ?? "",
    warehouse_address: supplier.warehouse_address ?? "",
    phone: supplier.phone ?? "",
    whatsapp: supplier.whatsapp ?? "",
    email: supplier.email ?? "",
  });

  const save = useMutation({
    mutationFn: () => api.patch(`/purchasing/suppliers/${supplier.id}`, {
      company_address: form.company_address.trim() || null,
      warehouse_address: form.warehouse_address.trim() || null,
      phone: form.phone.trim() || null,
      whatsapp: form.whatsapp.trim() || null,
      email: form.email.trim() || null,
    }),
    onSuccess: () => { setEditing(false); setErr(null); onSaved(); },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("Save failed", "Gagal menyimpan")),
  });

  const phone = supplier.phone ?? legacy.phone ?? null;
  const email = supplier.email ?? legacy.email ?? null;
  const anything = supplier.company_address || supplier.warehouse_address
    || phone || supplier.whatsapp || email || legacy.name;

  return (
    <div className="border-t border-ink-100 pt-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider muted">
          {t("Company address & contact", "Alamat & kontak perusahaan")}
        </span>
        {canEdit && !editing && (
          <button className="btn-ghost text-xs ml-auto" onClick={() => {
            setForm({
              company_address: supplier.company_address ?? "",
              warehouse_address: supplier.warehouse_address ?? "",
              phone: supplier.phone ?? "",
              whatsapp: supplier.whatsapp ?? "",
              email: supplier.email ?? "",
            });
            setErr(null); setEditing(true);
          }}>
            <Pencil size={13} /> {anything ? t("Edit", "Ubah") : t("Add details", "Tambah detail")}
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t("Company address", "Alamat perusahaan")}
              </span>
              <textarea className="input min-h-[60px]" value={form.company_address}
                onChange={(e) => setForm({ ...form, company_address: e.target.value })} />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t("Warehouse / pickup address", "Alamat gudang / pengambilan")}
              </span>
              <textarea className="input min-h-[60px]" value={form.warehouse_address}
                onChange={(e) => setForm({ ...form, warehouse_address: e.target.value })}
                placeholder={t("Leave blank if goods are collected from the office address",
                               "Kosongkan jika barang diambil di alamat kantor")} />
            </label>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t("Company phone", "Telepon perusahaan")}
              </span>
              <input className="input" value={form.phone} placeholder="+62…"
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t("Company WhatsApp", "WhatsApp perusahaan")}
              </span>
              <input className="input" value={form.whatsapp} placeholder="+62…"
                onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t("Company email", "Email perusahaan")}
              </span>
              <input className="input" type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
          </div>
          <p className="text-[11px] muted">
            {t("A named person's own phone and email go on their row in Contacts below.",
               "Telepon dan email milik orang tertentu ditulis pada barisnya di Kontak di bawah.")}
          </p>
          {err && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}
          <div className="flex gap-2">
            <button className="btn-primary" disabled={save.isPending}
              onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {t("Save", "Simpan")}
            </button>
            <button className="btn-ghost" onClick={() => { setEditing(false); setErr(null); }}>
              {t("Cancel", "Batal")}
            </button>
          </div>
        </div>
      ) : !anything ? (
        <div className="text-sm muted">
          {canEdit
            ? t("No address or company contact yet.",
                "Belum ada alamat atau kontak perusahaan.")
            : t("No address on file.", "Alamat belum dicatat.")}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          {supplier.company_address && (
            <div>
              <div className="text-[10px] uppercase tracking-wider muted">
                {t("Company address", "Alamat perusahaan")}
              </div>
              <div className="mt-0.5 flex gap-1.5">
                <MapPin size={12} className="mt-1 shrink-0 text-ink-400" />
                <span className="whitespace-pre-wrap">{supplier.company_address}</span>
              </div>
            </div>
          )}
          {supplier.warehouse_address && (
            <div>
              <div className="text-[10px] uppercase tracking-wider muted">
                {t("Warehouse / pickup", "Gudang / pengambilan")}
              </div>
              <div className="mt-0.5 flex gap-1.5">
                <MapPin size={12} className="mt-1 shrink-0 text-ink-400" />
                <span className="whitespace-pre-wrap">{supplier.warehouse_address}</span>
              </div>
            </div>
          )}
          <div className="sm:col-span-2 flex flex-wrap gap-x-5 gap-y-1">
            {phone && (
              <a href={`tel:${phone}`}
                className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                <Phone size={12} /> {phone}
              </a>
            )}
            {supplier.whatsapp && (
              <a href={`https://wa.me/${supplier.whatsapp.replace(/[^\d]/g, "")}`}
                target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                <MessageCircle size={12} /> {supplier.whatsapp}
              </a>
            )}
            {email && (
              <a href={`mailto:${email}`}
                className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                <Mail size={12} /> {email}
              </a>
            )}
            {legacy.name && !supplier.contacts?.length && (
              <span className="muted">{t("Contact", "Kontak")}: {legacy.name}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function BigStat({ label, value, tone }: {
  label: string; value: React.ReactNode; tone?: "amber";
}) {
  return (
    <div className="card p-4">
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className={clsx(
        "text-2xl font-semibold tabular-nums mt-1",
        tone === "amber" && "text-amber-700",
      )}>
        {value}
      </div>
    </div>
  );
}
