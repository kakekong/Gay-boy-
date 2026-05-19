import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Loader2 } from "lucide-react";
import { api } from "@/api/client";

const FIELDS: { key: string; label: string }[] = [
  { key: "est_ship_from_origin",      label: "Est. shipped from origin" },
  { key: "act_ship_from_origin",      label: "Actual shipped from origin" },
  { key: "est_arrive_our_warehouse",  label: "Est. arrival at our warehouse" },
  { key: "act_arrive_our_warehouse",  label: "Actual arrival at our warehouse" },
  { key: "est_arrive_customer",       label: "Est. arrival at customer's warehouse" },
  { key: "act_arrive_customer",       label: "Actual arrival at customer's warehouse" },
];

export function ShippingTimelineEditor({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}`).then((r) => r.data),
  });

  const [form, setForm] = useState<Record<string, string>>({});
  const [isImport, setIsImport] = useState(false);
  const [origin, setOrigin] = useState("");

  useEffect(() => {
    if (!q.data) return;
    const next: Record<string, string> = {};
    for (const f of FIELDS) next[f.key] = q.data[f.key] ?? "";
    setForm(next);
    setIsImport(!!q.data.is_import);
    setOrigin(q.data.origin_location ?? "");
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => api.patch(`/operation/projects/${projectId}`, {
      ...form,
      is_import: isImport,
      origin_location: origin || null,
      // Convert empty strings to null
      est_ship_from_origin: form.est_ship_from_origin || null,
      act_ship_from_origin: form.act_ship_from_origin || null,
      est_arrive_our_warehouse: form.est_arrive_our_warehouse || null,
      act_arrive_our_warehouse: form.act_arrive_our_warehouse || null,
      est_arrive_customer: form.est_arrive_customer || null,
      act_arrive_customer: form.act_arrive_customer || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-timeline", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-semibold">Edit shipping timeline</div>
          <div className="text-xs muted">
            Visible to internal staff. The customer sees the same dates on their portal.
          </div>
        </div>
        <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isImport} onChange={(e) => setIsImport(e.target.checked)}
            className="h-4 w-4 rounded border-ink-300 text-brand-600" />
          This is an international import
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Origin location</span>
          <input className="input" value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="e.g. Shanghai, China" />
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {FIELDS.map((f) => (
          <label key={f.key} className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{f.label}</span>
            <input type="date" className="input" value={form[f.key] ?? ""}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
          </label>
        ))}
      </div>
    </div>
  );
}
