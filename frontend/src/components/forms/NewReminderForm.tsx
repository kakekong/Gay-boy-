import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { fetchAllCustomers } from "@/lib/fetchAll";
import type { Customer } from "@/types";
import { T, useT } from "@/store/lang";
import { localDay, localTime } from "@/lib/localDate";

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

/** A reminder as the calendar sends it, for editing in place. */
export interface ReminderRow {
  id: string;
  kind: string;
  due_at: string;
  channel: string;
  message: string | null;
  customer_id: string | null;
  customer_name?: string | null;
  recurs: string;
  recurs_until: string | null;
  editable: boolean;
}

interface Props {
  defaultDate?: string;        // YYYY-MM-DD
  preselectCustomerId?: string;
  /** Given, the form edits this reminder instead of making a new one. */
  editing?: ReminderRow;
  onClose: () => void;
}

export function NewReminderForm({ defaultDate, preselectCustomerId, editing, onClose }: Props) {
  const qc = useQueryClient();
  const t = useT();
  // The day and time are read in the viewer's own clock (WIB in the office),
  // never sliced off a UTC string — that put a 06:00 plan on the day before.
  const due = editing ? new Date(editing.due_at) : null;
  const customers = useQuery({
    queryKey: ["customers", "all"],
    queryFn: () => fetchAllCustomers<Customer>().then((r) => r.data),
  });

  const [customerId, setCustomerId] = useState(editing?.customer_id ?? preselectCustomerId ?? "");
  const [kind, setKind] = useState(editing?.kind ?? "follow_up");
  const [channel, setChannel] = useState(editing?.channel ?? "dashboard");
  const [message, setMessage] = useState(editing?.message ?? "");
  const [date, setDate] = useState(due ? localDay(due) : (defaultDate ?? localDay(new Date())));
  const [time, setTime] = useState(due ? localTime(due) : "09:00");
  const [recurs, setRecurs] = useState(editing?.recurs ?? "none");
  const [recursUntil, setRecursUntil] = useState(editing?.recurs_until ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const done = () => {
    qc.invalidateQueries({ queryKey: ["calendar-events"] });
    onClose();
  };
  const failed = (fallback: string) => (e: any) =>
    setErr(e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? fallback);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        customer_id: customerId || null,
        kind,
        due_at: new Date(`${date}T${time}:00`).toISOString(),
        channel,
        message: message.trim() || null,
        recurs,
        recurs_until: recurs === "none" ? null : (recursUntil || null),
      };
      return editing
        ? api.patch(`/calendar/reminders/${editing.id}`, body)
        : api.post("/calendar/reminders", body);
    },
    onSuccess: done,
    onError: failed(editing ? "Failed to save the reminder" : "Failed to create reminder"),
  });

  const remove = useMutation({
    mutationFn: () => api.delete(`/calendar/reminders/${editing!.id}`),
    onSuccess: done,
    onError: failed("Failed to delete the reminder"),
  });

  const customerOptions = customers.data ?? [];
  const customerMissing = !!editing?.customer_id
    && !customerOptions.some((c) => c.id === editing.customer_id);

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); setErr(null); save.mutate(); }}
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
          {customerMissing && (
            <option value={editing!.customer_id!}>{editing!.customer_name ?? "…"}</option>
          )}
          {customerOptions.map((c) => (
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

      {editing && confirmDelete ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2">
          <span className="text-sm text-red-700">
            {t("Delete this reminder? This can't be undone.", "Hapus pengingat ini? Tidak bisa dibatalkan.")}
          </span>
          <div className="flex gap-2 shrink-0">
            <button type="button" className="btn-ghost" onClick={() => setConfirmDelete(false)}>
              {t("Keep it", "Batal")}
            </button>
            <button type="button" className="btn-primary bg-red-600 hover:bg-red-700"
              disabled={remove.isPending} onClick={() => { setErr(null); remove.mutate(); }}>
              {remove.isPending && <Loader2 size={14} className="animate-spin" />}
              {t("Delete", "Hapus")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-2">
          {editing && (
            <button type="button" className="btn-ghost mr-auto text-red-700"
              onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} /> {t("Delete", "Hapus")}
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending && <Loader2 size={14} className="animate-spin" />}
            {save.isPending ? T("Saving…")
              : editing ? t("Save changes", "Simpan perubahan") : T("Save reminder")}
          </button>
        </div>
      )}
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
