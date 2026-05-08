import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";

const INDUSTRIES = [
  "mining", "pltu", "fertilizer", "sugar", "cement",
  "pulp_paper", "food", "other",
];
const STAGES = ["lead", "presentation", "engineering", "quotation"];

interface Props {
  onClose: () => void;
}

export function NewCustomerForm({ onClose }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
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
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (body: typeof form) => api.post("/customers", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customers"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to create customer");
    },
  });

  const update = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <form
      id="new-customer-form"
      onSubmit={(e) => {
        e.preventDefault();
        setErr(null);
        if (!form.company_name.trim()) {
          setErr("Company name is required.");
          return;
        }
        create.mutate(form);
      }}
      className="space-y-4"
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Company name *">
          <input className="input" required value={form.company_name}
            onChange={(e) => update("company_name", e.target.value)} />
        </Field>
        <Field label="Industry">
          <select className="input" value={form.industry}
            onChange={(e) => update("industry", e.target.value)}>
            {INDUSTRIES.map((i) => <option key={i}>{i}</option>)}
          </select>
        </Field>
        <Field label="PIC name">
          <input className="input" value={form.pic_name}
            onChange={(e) => update("pic_name", e.target.value)} />
        </Field>
        <Field label="PIC position">
          <input className="input" value={form.pic_position}
            onChange={(e) => update("pic_position", e.target.value)} />
        </Field>
        <Field label="Phone">
          <input className="input" value={form.phone}
            onChange={(e) => update("phone", e.target.value)} placeholder="+62…" />
        </Field>
        <Field label="WhatsApp">
          <input className="input" value={form.whatsapp}
            onChange={(e) => update("whatsapp", e.target.value)} placeholder="+62…" />
        </Field>
        <Field label="Email">
          <input className="input" type="email" value={form.email}
            onChange={(e) => update("email", e.target.value)} />
        </Field>
        <Field label="Stage">
          <select className="input" value={form.stage}
            onChange={(e) => update("stage", e.target.value)}>
            {STAGES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Company address">
        <textarea className="input min-h-[60px]" value={form.company_address}
          onChange={(e) => update("company_address", e.target.value)} />
      </Field>
      <Field label="Delivery address">
        <textarea className="input min-h-[60px]" value={form.delivery_address}
          onChange={(e) => update("delivery_address", e.target.value)} />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          {create.isPending && <Loader2 size={14} className="animate-spin" />}
          {create.isPending ? "Creating…" : "Create customer"}
        </button>
      </div>
    </form>
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
