import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, ChevronLeft, ChevronRight, Check, Plus, Trash2, Star,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

const INDUSTRIES = [
  "mining", "pltu", "fertilizer", "sugar", "cement",
  "pulp_paper", "food", "other",
];
const STAGES = ["lead", "presentation", "engineering", "quotation"];

// Preset position categories. "Other" reveals a free-text input so we
// keep the existing string column on the backend without losing
// flexibility.
const POSITION_PRESETS = ["Maintenance", "Engineering", "Purchasing"] as const;

interface Contact {
  name: string;
  position: string;
  phone: string;
  whatsapp: string;
  email: string;
  is_primary: boolean;
  notes: string;
}

const EMPTY_CONTACT: Contact = {
  name: "", position: "", phone: "", whatsapp: "", email: "",
  is_primary: false, notes: "",
};

interface Props {
  onClose: () => void;
}

export function NewCustomerForm({ onClose }: Props) {
  const t = useT();
  const qc = useQueryClient();

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [basic, setBasic] = useState({
    company_name: "",
    industry: "mining",
    pic_name: "",
    pic_position: "",
    phone: "",
    whatsapp: "",
    email: "",
    company_address: "",
    delivery_address: "",
    stage: "lead",
  });
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [tax, setTax] = useState({
    tax_id: "",
    tax_name: "",
    tax_address: "",
    is_pkp: false,
    nppkp_no: "",
    tax_notes: "",
  });
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api.post("/customers", {
        ...basic,
        ...tax,
        contacts: contacts
          .filter((c) => c.name.trim())
          .map((c) => ({
            name: c.name.trim(),
            position: c.position || null,
            phone: c.phone || null,
            whatsapp: c.whatsapp || null,
            email: c.email || null,
            is_primary: c.is_primary,
            notes: c.notes || null,
          })),
      }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customers"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(
        e?.response?.data?.errors?.[0]?.message
          ?? e?.response?.data?.detail
          ?? t("Failed to create customer", "Gagal membuat pelanggan")
      );
    },
  });

  function next() {
    setErr(null);
    // No required-field gates between steps — users can browse all three
    // panels freely. Validation only happens when Create is clicked.
    if (step === 1) setStep(2);
    else if (step === 2) setStep(3);
  }
  function back() {
    setErr(null);
    if (step === 3) setStep(2);
    else if (step === 2) setStep(1);
  }
  function submit() {
    setErr(null);
    if (!basic.company_name.trim()) {
      setStep(1);
      setErr(t("Company name is required.", "Nama perusahaan wajib diisi."));
      return;
    }
    create.mutate();
  }

  function addContact() {
    setContacts((cs) => [...cs, { ...EMPTY_CONTACT }]);
  }
  function updateContact(idx: number, patch: Partial<Contact>) {
    setContacts((cs) => cs.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  }
  function removeContact(idx: number) {
    setContacts((cs) => cs.filter((_, i) => i !== idx));
  }

  const labels = [
    t("Basic info", "Data dasar"),
    t("Contacts (PIC)", "Kontak (PIC)"),
    t("Tax info", "Data pajak"),
  ];

  return (
    <div className="space-y-4">
      <Stepper step={step} labels={labels} />

      {step === 1 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label={t("Company name *", "Nama perusahaan *")}>
            <input className="input" required value={basic.company_name}
              onChange={(e) => setBasic({ ...basic, company_name: e.target.value })} />
          </Field>
          <Field label={t("Industry", "Industri")}>
            <select className="input" value={basic.industry}
              onChange={(e) => setBasic({ ...basic, industry: e.target.value })}>
              {INDUSTRIES.map((i) => <option key={i}>{i}</option>)}
            </select>
          </Field>
          <Field label={t("Primary PIC name", "Nama PIC utama")}>
            <input className="input" value={basic.pic_name}
              onChange={(e) => setBasic({ ...basic, pic_name: e.target.value })} />
          </Field>
          <Field label={t("PIC position", "Jabatan PIC")}>
            <PositionPicker
              value={basic.pic_position}
              onChange={(v) => setBasic({ ...basic, pic_position: v })}
            />
          </Field>
          <Field label={t("Phone", "Telepon")}>
            <input className="input" value={basic.phone}
              onChange={(e) => setBasic({ ...basic, phone: e.target.value })} placeholder="+62…" />
          </Field>
          <Field label="WhatsApp">
            <input className="input" value={basic.whatsapp}
              onChange={(e) => setBasic({ ...basic, whatsapp: e.target.value })} placeholder="+62…" />
          </Field>
          <Field label={t("Email", "Email")}>
            <input className="input" type="email" value={basic.email}
              onChange={(e) => setBasic({ ...basic, email: e.target.value })} />
          </Field>
          <Field label={t("Stage", "Tahap")}>
            <select className="input" value={basic.stage}
              onChange={(e) => setBasic({ ...basic, stage: e.target.value })}>
              {STAGES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </Field>
          <div className="md:col-span-2">
            <Field label={t("Company address", "Alamat perusahaan")}>
              <textarea className="input min-h-[60px]" value={basic.company_address}
                onChange={(e) => setBasic({ ...basic, company_address: e.target.value })} />
            </Field>
          </div>
          <div className="md:col-span-2">
            <Field label={t("Delivery address", "Alamat pengiriman")}>
              <textarea className="input min-h-[60px]" value={basic.delivery_address}
                onChange={(e) => setBasic({ ...basic, delivery_address: e.target.value })} />
            </Field>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3">
          <div className="text-sm muted">
            {t(
              "Add extra people you talk to at this company. WhatsApp and email are required to reach them fast; use Details for notes like best time to call.",
              "Tambahkan orang lain yang Anda hubungi di perusahaan ini. WhatsApp dan email memudahkan kontak cepat; pakai Detail untuk catatan seperti waktu terbaik menelepon."
            )}
          </div>

          {contacts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-ink-200 p-6 text-center text-sm muted">
              {t(
                "No extra contacts yet. The primary PIC from step 1 is already saved.",
                "Belum ada kontak tambahan. PIC utama dari langkah 1 sudah tersimpan."
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {contacts.map((c, idx) => (
                <div key={idx} className="rounded-xl border border-ink-200 bg-white p-3 space-y-2">
                  <div className="flex items-start gap-2">
                    <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-2">
                      <Field label={t("Full name *", "Nama lengkap *")}>
                        <input className="input" value={c.name}
                          onChange={(e) => updateContact(idx, { name: e.target.value })} />
                      </Field>
                      <Field label={t("Position", "Jabatan")}>
                        <PositionPicker
                          value={c.position}
                          onChange={(v) => updateContact(idx, { position: v })}
                        />
                      </Field>
                      <Field label={t("Phone", "Telepon")}>
                        <input className="input" value={c.phone}
                          onChange={(e) => updateContact(idx, { phone: e.target.value })} />
                      </Field>
                      <Field label="WhatsApp">
                        <input className="input" value={c.whatsapp}
                          onChange={(e) => updateContact(idx, { whatsapp: e.target.value })} />
                      </Field>
                      <Field label={t("Email", "Email")}>
                        <input className="input" type="email" value={c.email}
                          onChange={(e) => updateContact(idx, { email: e.target.value })} />
                      </Field>
                      <label className="flex items-center gap-2 text-sm self-end pb-2">
                        <input
                          type="checkbox"
                          checked={c.is_primary}
                          onChange={(e) => updateContact(idx, { is_primary: e.target.checked })}
                          className="h-4 w-4 rounded border-ink-300 text-brand-600"
                        />
                        <Star size={13} className="text-amber-500" />
                        {t("Primary contact", "Kontak utama")}
                      </label>
                      <div className="md:col-span-2">
                        <Field label={t("Details", "Detail")}>
                          <textarea className="input min-h-[44px]" value={c.notes}
                            onChange={(e) => updateContact(idx, { notes: e.target.value })}
                            placeholder={t(
                              "Best time to call, decision-maker?, preferred channel…",
                              "Waktu terbaik menelepon, pengambil keputusan?, kanal favorit…"
                            )} />
                        </Field>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn-ghost text-red-600 hover:bg-red-50 shrink-0"
                      onClick={() => removeContact(idx)}
                      title={t("Remove", "Hapus")}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <button type="button" className="btn-ghost" onClick={addContact}>
            <Plus size={14} /> {t("Add contact", "Tambah kontak")}
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          <div className="text-sm muted">
            {t(
              "Tax information for invoicing. NPWP is required if the customer is PKP (VAT-registered).",
              "Data pajak untuk penagihan. NPWP wajib jika pelanggan berstatus PKP."
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={t("Tax ID (NPWP)", "NPWP")}>
              <input className="input" value={tax.tax_id}
                onChange={(e) => setTax({ ...tax, tax_id: e.target.value })}
                placeholder="00.000.000.0-000.000" />
            </Field>
            <Field label={t("Name on NPWP", "Nama pada NPWP")}>
              <input className="input" value={tax.tax_name}
                onChange={(e) => setTax({ ...tax, tax_name: e.target.value })} />
            </Field>
            <div className="md:col-span-2">
              <Field label={t("Tax address (alamat NPWP)", "Alamat NPWP")}>
                <textarea className="input min-h-[60px]" value={tax.tax_address}
                  onChange={(e) => setTax({ ...tax, tax_address: e.target.value })} />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-sm self-end pb-2">
              <input
                type="checkbox"
                checked={tax.is_pkp}
                onChange={(e) => setTax({ ...tax, is_pkp: e.target.checked })}
                className="h-4 w-4 rounded border-ink-300 text-brand-600"
              />
              {t("Customer is PKP (VAT-registered)", "Pelanggan adalah PKP")}
            </label>
            <Field label={t("NPPKP number", "Nomor NPPKP")}>
              <input className="input" value={tax.nppkp_no}
                onChange={(e) => setTax({ ...tax, nppkp_no: e.target.value })}
                disabled={!tax.is_pkp}
                placeholder={tax.is_pkp ? "" : t("Enable PKP above", "Aktifkan PKP di atas")} />
            </Field>
            <div className="md:col-span-2">
              <Field label={t("Tax notes", "Catatan pajak")}>
                <textarea className="input min-h-[44px]" value={tax.tax_notes}
                  onChange={(e) => setTax({ ...tax, tax_notes: e.target.value })}
                  placeholder={t(
                    "e.g. tax exemption, withholding scheme, special instructions…",
                    "Misalnya pengecualian pajak, skema potong pajak, instruksi khusus…"
                  )} />
              </Field>
            </div>
          </div>
        </div>
      )}

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-between gap-2 pt-2 border-t border-ink-100">
        <button type="button" className="btn-ghost" onClick={onClose}>
          {t("Cancel", "Batal")}
        </button>
        <div className="flex gap-2">
          {step > 1 && (
            <button type="button" className="btn-ghost" onClick={back}>
              <ChevronLeft size={14} /> {t("Back", "Kembali")}
            </button>
          )}
          {step < 3 ? (
            <button type="button" className="btn-primary" onClick={next}>
              {t("Next", "Lanjut")} <ChevronRight size={14} />
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={submit}
              disabled={create.isPending}
            >
              {create.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <Check size={14} />}
              {create.isPending
                ? t("Creating…", "Menyimpan…")
                : t("Create customer", "Simpan pelanggan")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Stepper({ step, labels }: { step: 1 | 2 | 3; labels: string[] }) {
  return (
    <ol className="flex items-center gap-2">
      {labels.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3;
        const active = n === step;
        const done = n < step;
        return (
          <li key={label} className="flex items-center gap-2">
            <div className={clsx(
              "h-7 w-7 grid place-items-center rounded-full text-xs font-semibold border",
              done ? "bg-brand-600 text-white border-brand-600"
                : active ? "bg-brand-50 text-brand-700 border-brand-300"
                : "bg-white text-ink-400 border-ink-200"
            )}>
              {done ? <Check size={13} /> : n}
            </div>
            <span className={clsx(
              "text-sm",
              active ? "font-semibold text-ink-900"
                : done ? "text-ink-700"
                : "text-ink-400",
            )}>
              {label}
            </span>
            {n < 3 && (
              <span className={clsx("w-6 h-px",
                done ? "bg-brand-400" : "bg-ink-200")} />
            )}
          </li>
        );
      })}
    </ol>
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

function PositionPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useT();
  const isPreset = (POSITION_PRESETS as readonly string[]).includes(value);
  // "Other" sticks even when the free-text field is empty, so the user
  // can pick Other and start typing without the dropdown snapping back.
  const [otherMode, setOtherMode] = useState<boolean>(!!value && !isPreset);
  const selectValue = otherMode ? "other" : (isPreset ? value : "");

  return (
    <div className="flex flex-col gap-1.5">
      <select
        className="input"
        value={selectValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "other") {
            setOtherMode(true);
            // Clear the value so the previous preset doesn't sneak through.
            if (isPreset) onChange("");
          } else {
            setOtherMode(false);
            onChange(v);
          }
        }}
      >
        <option value="">{t("— Select —", "— Pilih —")}</option>
        <option value="Maintenance">{t("Maintenance", "Pemeliharaan")}</option>
        <option value="Engineering">{t("Engineering", "Teknik")}</option>
        <option value="Purchasing">{t("Purchasing", "Pembelian")}</option>
        <option value="other">{t("Other…", "Lainnya…")}</option>
      </select>
      {otherMode && (
        <input
          className="input"
          autoFocus
          placeholder={t("Type position", "Ketik jabatan")}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
