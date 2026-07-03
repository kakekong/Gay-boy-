import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

const FIELDS: { key: string; label: string }[] = [
  { key: "est_ship_from_origin",      label: "Est. shipped from origin" },
  { key: "act_ship_from_origin",      label: "Actual shipped from origin" },
  { key: "est_arrive_our_warehouse",  label: "Est. arrival at our warehouse" },
  { key: "act_arrive_our_warehouse",  label: "Actual arrival at our warehouse" },
  { key: "est_arrive_customer",       label: "Est. arrival at customer's warehouse" },
  { key: "act_arrive_customer",       label: "Actual arrival at customer's warehouse" },
];

// Who may edit which shipping-timeline field.
// - Purchasing owns the origin leg: they book the supplier's shipment and
//   see the ETA come back, so they update Est. + Actual shipped-from-origin.
// - Admin owns the arrival legs: they're on the ground when goods hit our
//   warehouse and when they land at the customer's site, so they stamp the
//   Actual arrival dates.
// - Manager and director keep unrestricted edit rights so ops always has a
//   fallback to fix anything mid-flight.
function canEditField(role: string, key: string): boolean {
  if (role === "director" || role === "manager") return true;
  if (role === "purchasing") {
    return key === "est_ship_from_origin" || key === "act_ship_from_origin";
  }
  if (role === "admin") {
    return key === "act_arrive_our_warehouse" || key === "act_arrive_customer";
  }
  return false;
}

export function ShippingTimelineEditor({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const isDirector = role === "director";
  // is_import + origin location are metadata about the shipment as a whole;
  // purchasing books the leg from origin so they own those too. Admin
  // never touches them (their scope is arrival stamps only).
  const canEditMeta = role === "director" || role === "manager" || role === "purchasing";
  const editableCount = FIELDS.filter((f) => canEditField(role, f.key)).length;
  // Nothing this user may touch → don't render the editor at all.
  if (editableCount === 0 && !canEditMeta) return null;
  const q = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}`).then((r) => r.data),
  });

  const [form, setForm] = useState<Record<string, string>>({});
  const [isImport, setIsImport] = useState(false);
  const [origin, setOrigin] = useState("");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!q.data) return;
    const next: Record<string, string> = {};
    for (const f of FIELDS) {
      // `<input type="date">` only accepts a YYYY-MM-DD value. The API may
      // send the full ISO string — slice it down so the field pre-fills.
      const raw = q.data[f.key];
      next[f.key] = typeof raw === "string" ? raw.slice(0, 10) : "";
    }
    setForm(next);
    setIsImport(!!q.data.is_import);
    setOrigin(q.data.origin_location ?? "");
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => {
      // Only send fields the user actually filled in AND is permitted to
      // edit — empty strings would null out existing dates, and sending a
      // field the user can't edit would let purchasing overwrite an
      // arrival stamp they shouldn't touch.
      const body: Record<string, any> = {};
      if (canEditMeta) {
        body.is_import = isImport;
        body.origin_location = origin || null;
      }
      for (const f of FIELDS) {
        if (canEditField(role, f.key) && form[f.key]) {
          body[f.key] = form[f.key];
        }
      }
      return api.patch(`/operation/projects/${projectId}`, body).then((r) => r.data);
    },
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["project-timeline", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      setFlash(data?.pending_approval ? {
        kind: "ok",
        text: "Submitted to the director for approval — the dates apply once approved.",
      } : {
        kind: "ok",
        text: "Saved. The customer can see the new dates immediately.",
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text:
        e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Couldn't save timeline",
    }),
  });

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-semibold">Edit shipping timeline</div>
          <div className="text-xs muted">
            Visible to internal staff. The customer sees the same dates on
            their portal — <b>you can save just the estimate</b>, no need to
            wait for the actual arrival.
            {!isDirector && (
              <> Changes to shipping dates are sent to the director for approval.</>
            )}
          </div>
        </div>
        <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save
        </button>
      </div>

      {flash && (
        <div className={
          flash.kind === "ok"
            ? "mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 flex items-start gap-2"
            : "mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2"
        }>
          {flash.kind === "ok" ? <CheckCircle2 size={14} className="mt-0.5" /> : <AlertCircle size={14} className="mt-0.5" />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}

      {canEditMeta && (
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
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {FIELDS.map((f) => {
          const canEdit = canEditField(role, f.key);
          return (
            <label key={f.key} className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {f.label}
                {!canEdit && (
                  <span className="ml-2 text-[10px] uppercase tracking-wider muted">
                    read-only
                  </span>
                )}
              </span>
              <input
                type="date"
                className="input"
                value={form[f.key] ?? ""}
                disabled={!canEdit}
                onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              />
            </label>
          );
        })}
      </div>
      <div className="mt-3 text-[11px] muted">
        Tip: blank fields are ignored on save (they don't erase existing dates).
        Clearing a date you previously set: contact ops or use the API directly.
        {role === "purchasing" && (
          <> Purchasing edits the origin-shipment dates; arrival stamps are admin's job.</>
        )}
        {role === "admin" && (
          <> Admin stamps the actual arrival dates once goods land; forecast + origin dates are set by purchasing.</>
        )}
      </div>
    </div>
  );
}
