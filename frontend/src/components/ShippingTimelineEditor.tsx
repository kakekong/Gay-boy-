import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt } from "@/store/lang";

const FIELDS: { key: string; label: string; label_id: string }[] = [
  { key: "est_ship_from_origin",      label: "Est. shipped from origin",               label_id: "Estimasi kirim dari asal" },
  { key: "act_ship_from_origin",      label: "Actual shipped from origin",             label_id: "Aktual kirim dari asal" },
  { key: "est_arrive_our_warehouse",  label: "Est. arrival at our warehouse",          label_id: "Estimasi tiba di gudang kami" },
  { key: "act_arrive_our_warehouse",  label: "Actual arrival at our warehouse",        label_id: "Aktual tiba di gudang kami" },
  { key: "est_arrive_customer",       label: "Est. arrival at customer's warehouse",   label_id: "Estimasi tiba di gudang pelanggan" },
  { key: "act_arrive_customer",       label: "Actual arrival at customer's warehouse", label_id: "Aktual tiba di gudang pelanggan" },
];

// Who may edit which shipping-timeline field.
// - Purchasing owns the origin leg: they book the supplier's shipment and
//   see the ETA come back, so they update Est. + Actual shipped-from-origin.
// - Admin owns both arrival legs end to end: they forecast when goods hit
//   our warehouse / the customer's site and stamp the actual dates when
//   they land — all four arrival fields.
// - Manager and director keep unrestricted edit rights so ops always has a
//   fallback to fix anything mid-flight.
function canEditField(role: string, key: string): boolean {
  if (role === "director" || role === "manager") return true;
  if (role === "purchasing") {
    return key === "est_ship_from_origin" || key === "act_ship_from_origin";
  }
  if (role === "admin") {
    return key === "est_arrive_our_warehouse" || key === "act_arrive_our_warehouse"
        || key === "est_arrive_customer" || key === "act_arrive_customer";
  }
  return false;
}

export function ShippingTimelineEditor({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const t = useT();
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
        text: tt(
          "Submitted to the director for approval — the dates apply once approved.",
          "Dikirim ke direktur untuk persetujuan — tanggal berlaku setelah disetujui.",
        ),
      } : {
        kind: "ok",
        text: tt(
          "Saved. The customer can see the new dates immediately.",
          "Tersimpan. Pelanggan langsung dapat melihat tanggal baru.",
        ),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text:
        e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? tt("Couldn't save timeline", "Gagal menyimpan linimasa"),
    }),
  });

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-semibold">{t("Edit shipping timeline", "Ubah linimasa pengiriman")}</div>
          <div className="text-xs muted">
            {t(
              "Visible to internal staff. The customer sees the same dates on their portal — ",
              "Terlihat oleh staf internal. Pelanggan melihat tanggal yang sama di portal mereka — ",
            )}
            <b>{t("you can save just the estimate", "Anda bisa menyimpan estimasinya saja")}</b>
            {t(", no need to wait for the actual arrival.", ", tidak perlu menunggu kedatangan aktual.")}
            {!isDirector && (
              <> {t(
                "Changes to shipping dates are sent to the director for approval.",
                "Perubahan tanggal pengiriman dikirim ke direktur untuk persetujuan.",
              )}</>
            )}
          </div>
        </div>
        <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {t("Save", "Simpan")}
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
            {t("This is an international import", "Ini impor internasional")}
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{t("Origin location", "Lokasi asal")}</span>
            <input className="input" value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder={t("e.g. Shanghai, China", "cth. Shanghai, Tiongkok")} />
          </label>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {FIELDS.map((f) => {
          const canEdit = canEditField(role, f.key);
          return (
            <label key={f.key} className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                {t(f.label, f.label_id)}
                {!canEdit && (
                  <span className="ml-2 text-[10px] uppercase tracking-wider muted">
                    {t("read-only", "hanya baca")}
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
        {t(
          "Tip: blank fields are ignored on save (they don't erase existing dates). Clearing a date you previously set: contact ops or use the API directly.",
          "Tips: kolom kosong diabaikan saat menyimpan (tidak menghapus tanggal yang sudah ada). Untuk mengosongkan tanggal yang pernah diisi: hubungi ops atau pakai API langsung.",
        )}
        {role === "purchasing" && (
          <> {t(
            "Purchasing edits the origin-shipment dates; arrival stamps are admin's job.",
            "Pembelian mengubah tanggal kirim dari asal; tanggal kedatangan adalah tugas admin.",
          )}</>
        )}
        {role === "admin" && (
          <> {t(
            "Admin owns the arrival legs — estimated and actual, at our warehouse and the customer's; origin-shipment dates are purchasing's.",
            "Admin memegang tahap kedatangan — estimasi dan aktual, di gudang kami dan gudang pelanggan; tanggal kirim dari asal milik pembelian.",
          )}</>
        )}
      </div>
    </div>
  );
}
