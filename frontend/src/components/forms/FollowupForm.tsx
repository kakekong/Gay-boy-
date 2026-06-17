import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";
import { api } from "@/api/client";

interface Props {
  quotationId: string;
  customerId?: string;
  onClose: () => void;
}

const CHANNELS = [
  { value: "dashboard", label: "Dashboard" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "email",     label: "Email" },
];

export function FollowupForm({ quotationId, customerId, onClose }: Props) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [scheduleNext, setScheduleNext] = useState(false);
  const today = new Date();
  const t3 = new Date(today.getTime() + 3 * 24 * 60 * 60 * 1000);
  const [date, setDate] = useState(t3.toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [channel, setChannel] = useState("whatsapp");
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const create = useMutation({
    mutationFn: () => {
      const next_at = scheduleNext
        ? new Date(`${date}T${time}:00`).toISOString()
        : null;
      return api.post(`/quotations/${quotationId}/followup`, {
        notes,
        next_at,
        next_channel: channel,
      }).then((r) => r.data);
    },
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["followups", quotationId] });
      qc.invalidateQueries({ queryKey: ["activities", customerId] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      // Sales follow-ups are held for director approval — keep the modal open
      // and show why nothing appeared in the timeline yet.
      if (data?.status === "pending_approval") {
        setInfo(data?.message ?? "Follow-up sent to the director for approval.");
        return;
      }
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to save follow-up");
    },
  });

  async function aiSuggest() {
    if (!customerId) return;
    setAiLoading(true);
    setErr(null);
    try {
      const r = await api.post("/ai/assistant/suggest", {
        intent: "wa_followup",
        customer_id: customerId,
      });
      if (r.data?.output) setNotes(r.data.output);
    } catch (e: any) {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "AI suggestion failed");
    } finally {
      setAiLoading(false);
    }
  }

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}
      className="space-y-4"
    >
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="block text-xs font-medium text-ink-600">Notes *</span>
          {customerId && (
            <button
              type="button"
              onClick={aiSuggest}
              disabled={aiLoading}
              className="btn-ghost text-xs"
            >
              {aiLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              AI suggest
            </button>
          )}
        </div>
        <textarea
          className="input min-h-[120px]"
          value={notes}
          required
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What was discussed? Decisions, objections, next steps…"
        />
      </div>

      <div className="rounded-xl border border-ink-100 p-3">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            checked={scheduleNext}
            onChange={(e) => setScheduleNext(e.target.checked)}
          />
          <div className="flex-1">
            <div className="text-sm font-medium">Schedule next follow-up</div>
            <div className="text-[11px] muted">Creates a reminder for the customer.</div>
          </div>
        </label>
        {scheduleNext && (
          <div className="grid grid-cols-3 gap-2 mt-3">
            <div>
              <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Date</span>
              <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div>
              <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Time</span>
              <input type="time" className="input" value={time} onChange={(e) => setTime(e.target.value)} />
            </div>
            <div>
              <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Channel</span>
              <select className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
                {CHANNELS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
          </div>
        )}
      </div>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      {info && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-800">
          {info}
        </div>
      )}

      <div className="flex justify-end gap-2">
        {info ? (
          <button type="button" className="btn-primary" onClick={onClose}>Close</button>
        ) : (
          <>
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={create.isPending}>
              {create.isPending && <Loader2 size={14} className="animate-spin" />}
              {create.isPending ? "Saving…" : "Log follow-up"}
            </button>
          </>
        )}
      </div>
    </form>
  );
}
