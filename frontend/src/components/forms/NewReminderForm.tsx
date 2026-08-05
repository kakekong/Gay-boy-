import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";
import type { Customer } from "@/types";
import { T } from "@/store/lang";

const KINDS = [
  { value: "follow_up",   label: "Follow-up" },
  { value: "after_sales", label: "After-sales" },
  { value: "delivery",    label: "Delivery" },
  { value: "payment_due", label: "Payment due" },
];
const CHANNELS = [
  { value: "dashboard", label: "Dashboard" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "email",     label: "Email" },
];

interface Props {
  defaultDate?: string;        // YYYY-MM-DD
  preselectCustomerId?: string;
  onClose: () => void;
}

export function NewReminderForm({ defaultDate, preselectCustomerId, onClose }: Props) {
  const qc = useQueryClient();
  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () =>
      api.get("/customers", { params: { page_size: 200 } })
        .then((r) => r.data.data as Customer[]),
  });

  const [customerId, setCustomerId] = useState(preselectCustomerId ?? "");
  const [kind, setKind] = useState("follow_up");
  const [channel, setChannel] = useState("dashboard");
  const [message, setMessage] = useState("");
  const [date, setDate] = useState(defaultDate ?? new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [recurs, setRecurs] = useState("none");
  const [recursUntil, setRecursUntil] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      const dueAt = new Date(`${date}T${time}:00`).toISOString();
      return api.post("/calendar/reminders", {
        customer_id: customerId || null,
        kind,
        due_at: dueAt,
        channel,
        message: message || null,
        recurs,
        recurs_until: recurs === "none" ? null : (recursUntil || null),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to create reminder");
    },
  });

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}
      className="space-y-4"
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label={T("Date")}>
          <input type="date" className="input" value={date}
            onChange={(e) => setDate(e.target.value)} required />
        </Field>
        <Field label={T("Time")}>
          <input type="time" className="input" value={time}
            onChange={(e) => setTime(e.target.value)} required />
        </Field>
        <Field label={T("Kind")}>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <option key={k.value} value={k.value}>{T(k.label)}</option>)}
          </select>
        </Field>
        <Field label={T("Channel")}>
          <select className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
            {CHANNELS.map((c) => <option key={c.value} value={c.value}>{T(c.label)}</option>)}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label={T("Repeat")}>
          <select className="input" value={recurs} onChange={(e) => setRecurs(e.target.value)}>
            <option value="none">{T("Never")}</option>
            <option value="daily">{T("Every day")}</option>
            <option value="weekly">{T("Every week")}</option>
            <option value="biweekly">{T("Every 2 weeks")}</option>
            <option value="monthly">{T("Every month")}</option>
          </select>
        </Field>
        {recurs !== "none" && (
          <Field label={T("Repeat until (optional)")}>
            <input type="date" className="input" value={recursUntil}
              onChange={(e) => setRecursUntil(e.target.value)} />
          </Field>
        )}
      </div>

      <Field label={T("Customer (optional)")}>
        <select className="input" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
          <option value="">{T("— none —")}</option>
          {(customers.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
      </Field>
      <Field label={T("Message")}>
        <textarea
          className="input min-h-[80px]"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={T("What should happen at this time?")}
        />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          {create.isPending && <Loader2 size={14} className="animate-spin" />}
          {create.isPending ? T("Saving…") : T("Save reminder")}
        </button>
      </div>
    </form>
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
