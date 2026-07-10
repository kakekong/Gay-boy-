import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Users, Plus, Star, Trash2, Pencil, Save, X, Loader2, Phone, Mail,
  MessageCircle, AlertCircle, FileText, Upload,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";

interface Contact {
  id: string;
  customer_id: string;
  name: string;
  position: string | null;
  phone: string | null;
  whatsapp: string | null;
  email: string | null;
  is_primary: boolean;
  notes: string | null;
}

interface ContactForm {
  name: string;
  position: string;
  phone: string;
  whatsapp: string;
  email: string;
  is_primary: boolean;
  notes: string;
}

const EMPTY: ContactForm = {
  name: "", position: "", phone: "", whatsapp: "", email: "",
  is_primary: false, notes: "",
};

export function ContactsSection({ customerId }: { customerId: string }) {
  const t = useT();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<ContactForm>(EMPTY);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const list = useQuery({
    queryKey: ["customer-contacts", customerId],
    queryFn: () =>
      api.get(`/customers/${customerId}/contacts`).then((r) => r.data as Contact[]),
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["customer-contacts", customerId] });
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? tt("Save failed", "Gagal menyimpan"),
  });

  const create = useMutation({
    mutationFn: () => api.post(`/customers/${customerId}/contacts`, form),
    onSuccess: () => {
      refresh(); setAdding(false); setForm(EMPTY);
      setFlash({ kind: "ok", text: tt("Contact added.", "PIC ditambahkan.") });
    },
    onError: onErr,
  });
  const patch = useMutation({
    mutationFn: (id: string) => api.patch(`/customers/${customerId}/contacts/${id}`, form),
    onSuccess: () => {
      refresh(); setEditing(null); setForm(EMPTY);
      setFlash({ kind: "ok", text: tt("Contact updated.", "PIC diperbarui.") });
    },
    onError: onErr,
  });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/customers/${customerId}/contacts/${id}`),
    onSuccess: () => { refresh(); setFlash({ kind: "ok", text: tt("Contact removed.", "PIC dihapus.") }); },
    onError: onErr,
  });

  function startEdit(c: Contact) {
    setForm({
      name: c.name,
      position: c.position ?? "",
      phone: c.phone ?? "",
      whatsapp: c.whatsapp ?? "",
      email: c.email ?? "",
      is_primary: c.is_primary,
      notes: c.notes ?? "",
    });
    setEditing(c.id);
    setAdding(false);
  }

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Users size={15} /> {t("Contacts (PICs)", "Kontak (PIC)")}
          </div>
          <div className="text-xs muted">
            {t(
              "Every person at this company you talk to. Mark one as primary.",
              "Semua orang di perusahaan ini yang Anda hubungi. Tandai satu sebagai utama."
            )}
          </div>
        </div>
        {!adding && !editing && (
          <button
            className="btn-primary"
            onClick={() => { setForm(EMPTY); setAdding(true); }}
          >
            <Plus size={14} /> {t("Add contact", "Tambah PIC")}
          </button>
        )}
      </header>

      {flash && (
        <div className={clsx(
          "mx-5 mt-3 rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          {flash.kind === "ok"
            ? <Save size={14} className="mt-0.5 shrink-0" />
            : <AlertCircle size={14} className="mt-0.5 shrink-0" />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}

      {(adding || editing) && (
        <div className="mx-5 mt-3 rounded-xl border border-brand-200 bg-brand-50/40 p-4">
          <div className="text-xs font-semibold uppercase muted mb-2">
            {editing ? t("Edit contact", "Ubah PIC") : t("New contact", "PIC baru")}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={t("Full name *", "Nama lengkap *")}>
              <input className="input" required value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label={t("Position / title", "Posisi / jabatan")}>
              <input className="input" value={form.position}
                onChange={(e) => setForm({ ...form, position: e.target.value })}
                placeholder={t("Procurement Manager", "Manajer Pengadaan")} />
            </Field>
            <Field label={t("Phone", "Telepon")}>
              <input className="input" value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </Field>
            <Field label="WhatsApp">
              <input className="input" value={form.whatsapp}
                onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} />
            </Field>
            <Field label="Email">
              <input className="input" type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-sm self-end pb-2">
              <input
                type="checkbox"
                checked={form.is_primary}
                onChange={(e) => setForm({ ...form, is_primary: e.target.checked })}
                className="h-4 w-4 rounded border-ink-300 text-brand-600"
              />
              {t("Primary contact", "PIC utama")}
            </label>
            <div className="md:col-span-2">
              <Field label={t("Notes", "Catatan")}>
                <textarea className="input" rows={2} value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder={t(
                    "Best time to reach them, preferences, etc.",
                    "Waktu terbaik menghubungi, preferensi, dll."
                  )} />
              </Field>
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => {
              setAdding(false); setEditing(null); setForm(EMPTY);
            }}>
              {t("Cancel", "Batal")}
            </button>
            <button
              className="btn-primary"
              disabled={create.isPending || patch.isPending || !form.name.trim()}
              onClick={() => editing ? patch.mutate(editing) : create.mutate()}
            >
              {create.isPending || patch.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <Save size={14} />}
              {editing ? t("Save changes", "Simpan perubahan") : t("Add contact", "Tambah PIC")}
            </button>
          </div>
        </div>
      )}

      {list.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : !list.data?.length ? (
        <div className="p-8 text-center text-sm muted">
          {t(
            "No additional contacts yet. The primary PIC on the customer header is enough — add more people here.",
            "Belum ada kontak tambahan. PIC utama di header pelanggan sudah cukup — tambahkan orang lain di sini."
          )}
        </div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {list.data.map((c) => (
            <li key={c.id} className="p-4 flex items-start gap-3 flex-wrap">
              <div className="h-10 w-10 rounded-full bg-brand-100 text-brand-700 grid place-items-center font-semibold shrink-0">
                {c.name.slice(0, 1).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{c.name}</span>
                  {c.is_primary && (
                    <span className="chip bg-amber-50 text-amber-700 inline-flex items-center gap-1">
                      <Star size={11} /> {t("Primary", "Utama")}
                    </span>
                  )}
                  {c.position && <span className="text-xs muted">· {c.position}</span>}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600">
                  {c.phone && (
                    <a href={`tel:${c.phone}`} className="inline-flex items-center gap-1 hover:text-brand-700">
                      <Phone size={11} /> {c.phone}
                    </a>
                  )}
                  {c.whatsapp && (
                    <a
                      href={`https://wa.me/${c.whatsapp.replace(/[^\d]/g, "")}`}
                      target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1 hover:text-brand-700"
                    >
                      <MessageCircle size={11} /> {c.whatsapp}
                    </a>
                  )}
                  {c.email && (
                    <a href={`mailto:${c.email}`} className="inline-flex items-center gap-1 hover:text-brand-700">
                      <Mail size={11} /> {c.email}
                    </a>
                  )}
                </div>
                {c.notes && (
                  <div className="mt-1 text-xs muted">{c.notes}</div>
                )}
                <ContactIdCards contactId={c.id} />
              </div>
              <div className="flex gap-1 shrink-0">
                <button
                  className="btn-ghost"
                  onClick={() => startEdit(c)}
                  title={t("Edit", "Ubah")}
                >
                  <Pencil size={13} />
                </button>
                <button
                  className="btn-ghost text-red-600 hover:bg-red-50"
                  onClick={() => {
                    if (window.confirm(tt(
                      `Remove ${c.name} from this customer's contacts?`,
                      `Hapus ${c.name} dari daftar kontak pelanggan ini?`
                    ))) {
                      del.mutate(c.id);
                    }
                  }}
                  title={t("Remove", "Hapus")}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
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

// KTP / passport / other ID cards attached to a specific contact. Reuses the
// generic /attachments endpoints with owner_type='customer_contact'.
function ContactIdCards({ contactId }: { contactId: string }) {
  const t = useT();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const list = useQuery({
    queryKey: ["contact-idcards", contactId],
    queryFn: () => api.get("/attachments", {
      params: { owner_type: "customer_contact", owner_id: contactId },
    }).then((r) => r.data as any[]),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["contact-idcards", contactId] });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("owner_type", "customer_contact");
      fd.append("owner_id", contactId);
      fd.append("description", "id_card");
      fd.append("file", file);
      return api.post("/attachments", fd);
    },
    onSuccess: refresh,
    onError: (e: any) => alert(e?.response?.data?.detail ?? tt("Upload failed", "Gagal mengunggah")),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/attachments/${id}`),
    onSuccess: refresh,
    onError: (e: any) => alert(e?.response?.data?.detail ?? tt("Delete failed", "Gagal menghapus")),
  });

  const viewFile = async (id: string) => {
    try {
      const resp = await api.get(`/attachments/${id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data as Blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? tt("Could not open file", "Tidak dapat membuka berkas"));
    }
  };

  const files = list.data ?? [];
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
      <span className="uppercase tracking-wider muted">{t("ID cards", "Kartu identitas")}</span>
      {files.map((f: any) => (
        <span key={f.id}
          className="inline-flex items-center gap-1 rounded-full bg-ink-50 border border-ink-200 px-2 py-0.5">
          <button type="button" onClick={() => viewFile(f.id)}
            className="text-brand-700 hover:underline inline-flex items-center gap-1">
            <FileText size={10} /> {f.filename}
          </button>
          <button type="button" title={t("Remove", "Hapus")}
            className="text-red-600 hover:opacity-80"
            onClick={() => {
              if (window.confirm(tt(`Remove ${f.filename}?`, `Hapus ${f.filename}?`))) del.mutate(f.id);
            }}>
            <X size={10} />
          </button>
        </span>
      ))}
      <input ref={inputRef} type="file" className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload.mutate(f);
          if (inputRef.current) inputRef.current.value = "";
        }} />
      <button type="button"
        className="inline-flex items-center gap-1 text-brand-700 hover:underline"
        disabled={upload.isPending}
        onClick={() => inputRef.current?.click()}>
        {upload.isPending ? <Loader2 size={10} className="animate-spin" /> : <Upload size={10} />}
        {t("Upload ID", "Unggah KTP/ID")}
      </button>
    </div>
  );
}
