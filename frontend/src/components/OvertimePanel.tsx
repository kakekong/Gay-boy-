import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Plus, Undo2, Trash2, Loader2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, locale } from "@/store/lang";

interface Entry {
  id: string; user_id: string; user_name: string | null; date: string;
  minutes: number; reason: string | null; status: "approved" | "revoked";
  entered_by_name: string | null; entered_at: string;
  revoked_by_name: string | null; revoked_at: string | null; revoke_reason: string | null;
  clock_out: string | null; clock_out_over_minutes: number | null;
}

const hm = (m: number) => {
  const h = Math.floor(m / 60), r = m % 60;
  return h ? (r ? `${h} h ${r} min` : `${h} h`) : `${r} min`;
};

/**
 * Overtime, recorded by the director.
 *
 * Not read off clock-outs any more: clock times carry too many human errors,
 * and a forgotten clock-out reads as hours of overtime. The director enters
 * what was worked, and that entry is the approval — payroll pays it. A
 * mistaken entry is revoked (kept with the reason, not paid); a test entry
 * is deleted. HR and managers see everyone's; anybody else sees their own.
 */
export function OvertimePanel() {
  const t = useT();
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const isDirector = role === "director";
  const seesAll = ["director", "hr", "manager"].includes(role);
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [err, setErr] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["overtime", period],
    queryFn: () => api.get("/attendance/overtime", { params: { period } })
      .then((r) => r.data as Entry[]),
  });
  const people = useQuery({
    queryKey: ["employees-all"],
    queryFn: () => api.get("/users", { params: { active_only: true } })
      .then((r) => r.data as { id: string; full_name: string; role: string }[]),
    enabled: isDirector,
  });

  const [form, setForm] = useState({ user_id: "", date: "", hours: "", mins: "", reason: "" });
  const total = (Number(form.hours) || 0) * 60 + (Number(form.mins) || 0);
  const errMsg = (e: any) => e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail ?? tt("Something went wrong", "Terjadi kesalahan");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["overtime"] });
    qc.invalidateQueries({ queryKey: ["salaries"] });
    qc.invalidateQueries({ queryKey: ["salary-attendance"] });
  };
  const record = useMutation({
    mutationFn: () => api.post("/attendance/overtime", {
      user_id: form.user_id, date: form.date, minutes: total, reason: form.reason || null,
    }),
    onSuccess: () => { setErr(null); setForm({ ...form, hours: "", mins: "", reason: "" }); refresh(); },
    onError: (e: any) => setErr(errMsg(e)),
  });
  const revoke = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/attendance/overtime/${v.id}/revoke`, { reason: v.reason }),
    onSuccess: () => { setErr(null); refresh(); },
    onError: (e: any) => setErr(errMsg(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/attendance/overtime/${id}`),
    onSuccess: () => { setErr(null); refresh(); },
    onError: (e: any) => setErr(errMsg(e)),
  });

  const rows = list.data ?? [];
  const paidMinutes = rows.filter((e) => e.status === "approved").reduce((n, e) => n + e.minutes, 0);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Clock size={15} className="text-brand-600" /> {t("Overtime", "Lembur")}
          </div>
          <div className="text-xs muted max-w-2xl mt-0.5">
            {t("Recorded by the director — not taken from clock-out times, which a forgotten clock-out would turn into hours of overtime. What is recorded here is paid on the month's salary (first hour 1.5×, each further hour 2× the hourly wage). A mistaken entry can be revoked; a test entry deleted.",
               "Dicatat oleh direktur — bukan dari jam absen pulang, yang bisa berubah jadi berjam-jam lembur jika lupa absen. Yang dicatat di sini dibayar di gaji bulan itu (jam pertama 1,5×, jam berikutnya 2× upah per jam). Catatan yang salah bisa dibatalkan; catatan uji bisa dihapus.")}
          </div>
        </div>
        <input type="month" className="input max-w-[170px]" value={period}
          aria-label={t("Month", "Bulan")} onChange={(e) => setPeriod(e.target.value)} />
      </div>

      {isDirector && (
        <form className="px-5 py-3 border-b border-ink-100 bg-ink-50/40 flex flex-wrap items-end gap-2"
          onSubmit={(e) => { e.preventDefault(); record.mutate(); }}>
          <label className="block">
            <span className="block text-[11px] uppercase muted mb-0.5">{t("Employee", "Karyawan")}</span>
            <select className="input w-56" required value={form.user_id}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}>
              <option value="">{t("— choose —", "— pilih —")}</option>
              {(people.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="block text-[11px] uppercase muted mb-0.5">{t("Date", "Tanggal")}</span>
            <input type="date" className="input w-40" required value={form.date}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setForm({ ...form, date: e.target.value })} />
          </label>
          <label className="block">
            <span className="block text-[11px] uppercase muted mb-0.5">{t("Hours", "Jam")}</span>
            <input type="number" min={0} max={24} className="input w-20" value={form.hours}
              onChange={(e) => setForm({ ...form, hours: e.target.value })} />
          </label>
          <label className="block">
            <span className="block text-[11px] uppercase muted mb-0.5">{t("Minutes", "Menit")}</span>
            <input type="number" min={0} max={59} className="input w-20" value={form.mins}
              onChange={(e) => setForm({ ...form, mins: e.target.value })} />
          </label>
          <label className="block flex-1 min-w-[200px]">
            <span className="block text-[11px] uppercase muted mb-0.5">{t("What it was for", "Untuk apa")}</span>
            <input className="input" value={form.reason} placeholder={t("e.g. stock-take after hours", "mis. stock opname setelah jam kerja")}
              onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </label>
          <button className="btn-primary" disabled={record.isPending || !form.user_id || !form.date || total <= 0}>
            {record.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {t("Record overtime", "Catat lembur")}
          </button>
        </form>
      )}

      {err && <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{err}</div>}

      {list.isLoading ? (
        <div className="p-6 text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}</div>
      ) : rows.length === 0 ? (
        <div className="p-6 text-center text-sm muted">
          {t("No overtime recorded this month.", "Belum ada lembur tercatat bulan ini.")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                {seesAll && <th className="th">{t("Employee", "Karyawan")}</th>}
                <th className="th">{t("Date", "Tanggal")}</th>
                <th className="th text-right">{t("Overtime", "Lembur")}</th>
                <th className="th">{t("What it was for", "Untuk apa")}</th>
                <th className="th">{t("Clock-out that day", "Absen pulang hari itu")}</th>
                <th className="th">{t("Status", "Status")}</th>
                {isDirector && <th className="th text-right">{t("Actions", "Aksi")}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className={clsx("border-t border-ink-100", e.status === "revoked" && "opacity-60")}>
                  {seesAll && <td className="td font-medium">{e.user_name ?? "—"}</td>}
                  <td className="td whitespace-nowrap tabular-nums">
                    {new Date(e.date).toLocaleDateString(locale())}
                  </td>
                  <td className={clsx("td text-right tabular-nums whitespace-nowrap", e.status === "revoked" && "line-through")}>
                    {hm(e.minutes)}
                  </td>
                  <td className="td">{e.reason ?? <span className="muted">—</span>}</td>
                  <td className="td text-xs muted whitespace-nowrap">
                    {e.clock_out
                      ? <>{new Date(e.clock_out).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta" })}
                          {e.clock_out_over_minutes ? <> · {t(`${e.clock_out_over_minutes} min past the end`, `lewat ${e.clock_out_over_minutes} mnt`)}</> : null}</>
                      : t("no clock-out", "tidak absen pulang")}
                  </td>
                  <td className="td text-xs">
                    {e.status === "approved" ? (
                      <span className="chip bg-emerald-50 text-emerald-700">{t("Paid", "Dibayar")}</span>
                    ) : (
                      <span className="chip bg-ink-100 text-ink-600" title={e.revoke_reason ?? ""}>{t("Revoked", "Dibatalkan")}</span>
                    )}
                    <div className="muted mt-0.5">
                      {e.status === "revoked"
                        ? t(`by ${e.revoked_by_name ?? "—"} · ${e.revoke_reason ?? ""}`, `oleh ${e.revoked_by_name ?? "—"} · ${e.revoke_reason ?? ""}`)
                        : t(`recorded by ${e.entered_by_name ?? "—"}`, `dicatat oleh ${e.entered_by_name ?? "—"}`)}
                    </div>
                  </td>
                  {isDirector && (
                    <td className="td text-right whitespace-nowrap">
                      {e.status === "approved" && (
                        <button className="btn-ghost text-xs" disabled={revoke.isPending}
                          title={t("Approved by mistake — keep the record, stop paying it", "Salah setuju — simpan catatan, hentikan pembayaran")}
                          onClick={() => {
                            const reason = window.prompt(tt("Why is this overtime being revoked? (kept on the record)",
                              "Kenapa lembur ini dibatalkan? (tetap tercatat)"));
                            if (reason && reason.trim()) revoke.mutate({ id: e.id, reason: reason.trim() });
                          }}>
                          <Undo2 size={12} /> {t("Revoke", "Batalkan")}
                        </button>
                      )}
                      <button className="btn-ghost text-xs text-red-600" disabled={del.isPending}
                        title={t("Remove outright — for test entries", "Hapus sepenuhnya — untuk catatan uji")}
                        onClick={() => {
                          if (window.confirm(tt(`Delete this overtime entry for ${e.user_name}? It is removed completely — revoke instead if it was a real mistake.`,
                            `Hapus catatan lembur ${e.user_name} ini? Akan dihapus sepenuhnya — batalkan saja jika ini kesalahan nyata.`)))
                            del.mutate(e.id);
                        }}>
                        <Trash2 size={12} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5 py-2 text-xs muted border-t border-ink-100 tabular-nums">
            {t(`Paid this month: ${hm(paidMinutes)}`, `Dibayar bulan ini: ${hm(paidMinutes)}`)}
          </div>
        </div>
      )}
    </div>
  );
}
