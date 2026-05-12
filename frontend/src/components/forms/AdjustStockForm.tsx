import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";

const REASONS = [
  { value: "adjust",   label: "Manual adjust" },
  { value: "receive",  label: "Receive (in)" },
  { value: "issue",    label: "Issue (out)" },
  { value: "return",   label: "Return" },
  { value: "transfer", label: "Transfer" },
];

interface Props {
  item: any;
  onClose: () => void;
}

export function AdjustStockForm({ item, onClose }: Props) {
  const qc = useQueryClient();
  const [delta, setDelta] = useState(0);
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [reason, setReason] = useState("adjust");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => api.post(`/inventory/${item.id}/adjust`, {
      delta: direction === "in" ? Math.abs(delta) : -Math.abs(delta),
      reason, reference: reference || null, notes: notes || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["inventory-item", item.id] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to adjust");
    },
  });

  const projected = (item.current_stock || 0) + (direction === "in" ? delta : -delta);

  return (
    <form onSubmit={(e) => { e.preventDefault(); setErr(null); save.mutate(); }}
          className="space-y-4">
      <div className="rounded-xl bg-ink-50 border border-ink-100 p-3 text-sm">
        <div className="font-medium">{item.name}</div>
        <div className="muted text-xs">
          {item.sku} · current {item.current_stock} {item.uom}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Direction</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setDirection("in")}
              className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium border
                ${direction === "in" ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                                     : "border-ink-200 text-ink-600 hover:bg-ink-50"}`}>
              + Stock IN
            </button>
            <button type="button" onClick={() => setDirection("out")}
              className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium border
                ${direction === "out" ? "bg-red-50 border-red-200 text-red-700"
                                      : "border-ink-200 text-ink-600 hover:bg-ink-50"}`}>
              − Stock OUT
            </button>
          </div>
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Quantity</span>
          <input type="number" min={0} step="any" className="input" required
            value={delta} onChange={(e) => setDelta(parseFloat(e.target.value || "0"))} />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Reason</span>
          <select className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Reference</span>
          <input className="input" value={reference} placeholder="e.g. WO-2026-0012"
            onChange={(e) => setReference(e.target.value)} />
        </label>
      </div>
      <label className="block">
        <span className="block text-xs font-medium text-ink-600 mb-1">Notes</span>
        <textarea className="input min-h-[60px]" value={notes}
          onChange={(e) => setNotes(e.target.value)} />
      </label>

      <div className="rounded-lg bg-brand-50 border border-brand-100 px-3 py-2 text-sm">
        After this adjustment: <b className="tabular-nums">{projected} {item.uom}</b>
      </div>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={save.isPending || projected < 0}>
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          Save adjustment
        </button>
      </div>
    </form>
  );
}
