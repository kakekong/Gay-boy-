import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";

const TYPES = [
  "call", "presentation", "technical_meeting", "purchase_request",
  "quotation_sent", "negotiation", "follow_up", "whatsapp_out",
  "email", "note",
];

interface Props {
  customerId: string;
  onClose: () => void;
}

export function LogActivityForm({ customerId, onClose }: Props) {
  const qc = useQueryClient();
  const [type, setType] = useState("call");
  const [direction, setDirection] = useState("outbound");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.post(`/customers/${customerId}/activities`, {
      type, direction, notes,
    }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activities", customerId] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to log activity");
    },
  });

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}
      className="space-y-4"
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type">
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Direction">
          <select className="input" value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="outbound">outbound</option>
            <option value="inbound">inbound</option>
            <option value="internal">internal</option>
          </select>
        </Field>
      </div>
      <Field label="Notes">
        <textarea
          className="input min-h-[100px]"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What happened? Decisions, next steps…"
        />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          {create.isPending && <Loader2 size={14} className="animate-spin" />}
          {create.isPending ? "Saving…" : "Save activity"}
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
