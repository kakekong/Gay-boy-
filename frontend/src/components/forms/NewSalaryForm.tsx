import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { T, useT } from "@/store/lang";

interface Employee { id: string; full_name: string; role: string; }

interface Props {
  initial?: any;             // when set → edit mode
  onClose: () => void;
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export function NewSalaryForm({ initial, onClose }: Props) {
  const qc = useQueryClient();
  const t = useT();
  const editing = !!initial?.id;

  const employees = useQuery({
    queryKey: ["employees-all"],
    queryFn: () => api.get("/users", { params: { active_only: true } })
      .then((r) => r.data as Employee[]),
  });

  const [form, setForm] = useState({
    user_id: initial?.user_id ?? "",
    period: initial?.period ?? new Date().toISOString().slice(0, 7),
    base_salary: initial?.base_salary ?? 0,
    transport: initial?.transport ?? 0,
    meal: initial?.meal ?? 0,
    bonus: initial?.bonus ?? 0,
    thr: initial?.thr ?? 0,
    other_allowance: initial?.other_allowance ?? 0,
    pph21: initial?.pph21 ?? 0,
    bpjs: initial?.bpjs ?? 0,
    other_deduction: initial?.other_deduction ?? 0,
    notes: initial?.notes ?? "",
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (initial?.id) {
      setForm({
        user_id: initial.user_id,
        period: initial.period,
        base_salary: initial.base_salary,
        transport: initial.transport,
        meal: initial.meal,
        bonus: initial.bonus,
        thr: initial.thr,
        other_allowance: initial.other_allowance,
        pph21: initial.pph21,
        bpjs: initial.bpjs,
        other_deduction: initial.other_deduction,
        notes: initial.notes ?? "",
      });
    }
  }, [initial]);

  // What the month's attendance does to pay, at the base salary typed in:
  // late minutes and absent days deducted, approved overtime paid. The server
  // works it out the same way when the record is saved.
  const [baseForPreview, setBaseForPreview] = useState(Number(form.base_salary) || 0);
  useEffect(() => {
    const h = setTimeout(() => setBaseForPreview(Number(form.base_salary) || 0), 300);
    return () => clearTimeout(h);
  }, [form.base_salary]);
  const att = useQuery({
    queryKey: ["salary-attendance", form.user_id, form.period, baseForPreview],
    queryFn: () => api.get("/salaries/attendance-preview", {
      params: { user_id: form.user_id, period: form.period, base_salary: baseForPreview },
    }).then((r) => r.data as any),
    enabled: !!form.user_id && /^\d{4}-\d{2}$/.test(form.period),
  });
  const a = att.data;

  const totals = useMemo(() => {
    const n = (k: keyof typeof form) => Number(form[k]) || 0;
    const ot = Number(a?.overtime_pay || 0);
    const late = Number(a?.late_deduction || 0);
    const absent = Number(a?.absent_deduction || 0);
    const gross = n("base_salary") + n("transport") + n("meal") + n("bonus")
                + n("thr") + n("other_allowance") + ot;
    const ded = n("pph21") + n("bpjs") + n("other_deduction") + late + absent;
    return { gross, deductions: ded, net: gross - ded };
  }, [form, a]);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? api.patch(`/salaries/${initial.id}`, form).then((r) => r.data)
        : api.post(`/salaries`, form).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["salaries"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to save");
    },
  });

  const num = (k: keyof typeof form, label: string) => (
    <label className="block">
      <span className="block text-[11px] uppercase muted mb-0.5">{T(label)}</span>
      <input
        type="number" min={0} step="any" className="input"
        value={form[k] as number}
        onChange={(e) => setForm({ ...form, [k]: parseFloat(e.target.value || "0") })}
      />
    </label>
  );

  return (
    <form onSubmit={(e) => { e.preventDefault(); setErr(null); save.mutate(); }}
          className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="block">
          <span className="block text-[11px] uppercase muted mb-0.5">{T("Employee *")}</span>
          <select
            className="input" required disabled={editing}
            value={form.user_id}
            onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          >
            <option value="">{T("— select employee —")}</option>
            {(employees.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="block text-[11px] uppercase muted mb-0.5">{T("Period (YYYY-MM)")}</span>
          <input
            type="month" className="input" required disabled={editing}
            value={form.period}
            onChange={(e) => setForm({ ...form, period: e.target.value })}
          />
        </label>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">{T("Earnings")}</div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {num("base_salary",     "Base salary")}
          {num("transport",       "Transport")}
          {num("meal",            "Meal")}
          {num("bonus",           "Bonus")}
          {num("thr",             "THR")}
          {num("other_allowance", "Other allowance")}
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">{T("Deductions")}</div>
        <div className="grid grid-cols-3 gap-3">
          {num("pph21",           "PPh 21")}
          {num("bpjs",            "BPJS")}
          {num("other_deduction", "Other deduction")}
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">
          {t("From attendance", "Dari absensi")}
        </div>
        {!form.user_id ? (
          <div className="text-xs muted">{t("Pick the employee to see their month.", "Pilih karyawan untuk melihat bulannya.")}</div>
        ) : att.isLoading ? (
          <div className="text-xs muted flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> {t("Reading attendance…", "Membaca absensi…")}</div>
        ) : a ? (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-3 text-sm">
              <AttLine label={t(`Late · ${a.late_minutes} min`, `Terlambat · ${a.late_minutes} mnt`)}
                value={a.late_deduction ? `− ${idr(a.late_deduction)}` : "—"} bad={!!a.late_deduction} />
              <AttLine label={t(`Absent · ${a.absent_days} day(s)`, `Absen · ${a.absent_days} hari`)}
                value={a.absent_deduction ? `− ${idr(a.absent_deduction)}` : "—"} bad={!!a.absent_deduction} />
              <AttLine label={t(`Overtime · ${a.overtime_hours} h approved`, `Lembur · ${a.overtime_hours} jam disetujui`)}
                value={a.overtime_pay ? `+ ${idr(a.overtime_pay)}` : "—"} />
            </div>
            <div className="text-[11px] muted">
              {t(`Working day ${a.schedule.start}–${a.schedule.end}, ${a.working_days} working days this month, ${a.schedule.grace_minutes} min grace. Day's wage ${idr(a.day_wage)}, hourly ${idr(a.hourly_wage)} (base ÷ 173).`,
                 `Jam kerja ${a.schedule.start}–${a.schedule.end}, ${a.working_days} hari kerja bulan ini, toleransi ${a.schedule.grace_minutes} mnt. Upah harian ${idr(a.day_wage)}, per jam ${idr(a.hourly_wage)} (gaji pokok ÷ 173).`)}
              {a.overtime_pending > 0 && (
                <span className="text-amber-700">{" "}{t(`${a.overtime_pending} overtime day(s) still waiting for approval — not paid until approved.`,
                  `${a.overtime_pending} hari lembur masih menunggu persetujuan — belum dibayar.`)}</span>
              )}
            </div>
            {(a.days ?? []).length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-brand-700">{t("Day by day", "Per hari")}</summary>
                <ul className="mt-1 space-y-0.5">
                  {a.days.map((d: any, i: number) => (
                    <li key={i} className="flex gap-3 tabular-nums">
                      <span className="w-24 muted">{d.date}</span>
                      <span className="w-36">
                        {d.kind === "late" ? t(`late — in ${d.clock_in}, ${d.minutes} min`, `terlambat — masuk ${d.clock_in}, ${d.minutes} mnt`)
                          : d.kind === "absent" ? t("absent", "absen")
                          : d.kind === "half_day" ? t("half day", "setengah hari")
                          : t(`overtime — out ${d.clock_out}, ${d.minutes} min, ${d.status}`,
                              `lembur — pulang ${d.clock_out}, ${d.minutes} mnt, ${d.status}`)}
                      </span>
                      <span className="ml-auto">{d.amount != null ? idr(d.amount) : ""}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ) : null}
      </div>

      <label className="block">
        <span className="block text-[11px] uppercase muted mb-0.5">{T("Notes")}</span>
        <textarea
          className="input min-h-[60px]"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
      </label>

      <div className="card p-4 grid grid-cols-3 gap-3 text-sm">
        <Stat label={T("Gross")} value={idr(totals.gross)} tone="brand" />
        <Stat label={T("Deductions")} value={`− ${idr(totals.deductions)}`} tone="red" />
        <Stat label={T("Net pay")} value={idr(totals.net)} tone="emerald" big />
      </div>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          {editing ? T("Save changes") : T("Create salary")}
        </button>
      </div>
    </form>
  );
}

function AttLine({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-lg border border-ink-200 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className={`tabular-nums font-semibold ${bad ? "text-red-700" : ""}`}>{value}</div>
    </div>
  );
}

function Stat({ label, value, tone, big }: {
  label: string; value: string;
  tone: "brand" | "red" | "emerald"; big?: boolean;
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    red:     "bg-red-50 text-red-700",
    emerald: "bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <div className={`rounded-lg px-3 py-2 ${cls}`}>
      <div className="text-[10px] uppercase tracking-wider">{T(label)}</div>
      <div className={`tabular-nums font-semibold ${big ? "text-xl" : "text-base"}`}>{value}</div>
    </div>
  );
}
