import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus, Wallet, BookOpen, Undo2, CheckCircle, Trash2, Loader2, AlertCircle, RefreshCw,
  ChevronDown, ChevronRight, Calculator,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { NewSalaryForm } from "@/components/forms/NewSalaryForm";
import { PayslipBreakdown } from "@/components/PayslipBreakdown";
import { T, useT } from "@/store/lang";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  draft:  "bg-ink-100 text-ink-700",
  posted: "bg-amber-50 text-amber-700",
  paid:   "bg-emerald-50 text-emerald-700",
};

export default function SalaryPage() {
  const qc = useQueryClient();
  const t = useT();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [openNew, setOpenNew] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  // Rows opened to their full payslip breakdown.
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const toggleRow = (id: string) => setOpenRows((cur) => {
    const next = new Set(cur);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const salaries = useQuery({
    queryKey: ["salaries", period],
    queryFn: () =>
      api.get("/salaries", { params: { period: period || undefined } })
        .then((r) => r.data as any[]),
  });

  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["salaries"] });
  const errMsg = (e: any) =>
    e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? e?.message
      ?? "Request failed";

  const post = useMutation({
    mutationFn: (id: string) => api.post(`/salaries/${id}/post-ledger`),
    onSuccess: () => {
      refresh(); qc.invalidateQueries({ queryKey: ["accounts"] });
      setFlash({ kind: "ok", text: "Posted to ledger." });
    },
    onError: (e: any) => setFlash({ kind: "err", text: errMsg(e) }),
  });
  const reverse = useMutation({
    mutationFn: (id: string) => api.post(`/salaries/${id}/reverse-ledger`),
    onSuccess: () => {
      refresh(); qc.invalidateQueries({ queryKey: ["accounts"] });
      setFlash({ kind: "ok", text: "Reversed." });
    },
    onError: (e: any) => setFlash({ kind: "err", text: errMsg(e) }),
  });
  const pay = useMutation({
    mutationFn: (id: string) => api.post(`/salaries/${id}/mark-paid`),
    onSuccess: () => {
      refresh(); qc.invalidateQueries({ queryKey: ["accounts"] });
      setFlash({ kind: "ok", text: "Marked paid." });
    },
    onError: (e: any) => setFlash({ kind: "err", text: errMsg(e) }),
  });
  // Re-read the month's attendance into a draft — after HR marks a leave
  // day, or overtime is approved after the record was made.
  const refreshAtt = useMutation({
    mutationFn: (id: string) => api.post(`/salaries/${id}/refresh-attendance`),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Attendance re-read.", "Absensi dibaca ulang.") });
    },
    onError: (e: any) => setFlash({ kind: "err", text: errMsg(e) }),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/salaries/${id}`),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: "Salary entry deleted." });
    },
    onError: (e: any) => setFlash({ kind: "err", text: errMsg(e) }),
  });

  // Summary across the period
  const totals = (salaries.data ?? []).reduce(
    (acc, s) => ({
      count: acc.count + 1,
      gross: acc.gross + Number(s.gross_salary || 0),
      tax:   acc.tax + Number(s.pph21 || 0),
      net:   acc.net + Number(s.net_pay || 0),
    }),
    { count: 0, gross: 0, tax: 0, net: 0 }
  );

  return (
    <div className="space-y-5">
      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Wallet size={22} className="text-brand-600" /> {T("Salary")}</h1>
          <p className="text-sm muted">
            {T("Monthly payroll. Posting to ledger auto-updates Beban Gaji, Hutang Gaji, and Hutang PPh 21.")}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            className="input max-w-[180px]"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
          <button className="btn-primary" onClick={() => { setEditing(null); setOpenNew(true); }}>
            <Plus size={14} /> {T("New salary")}</button>
        </div>
      </div>

      {/* Period summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card label={T("Employees paid")} value={String(totals.count)} tone="brand" />
        <Card label={T("Gross")}      value={idr(totals.gross)} tone="brand" />
        <Card label={T("PPh 21 withheld")} value={idr(totals.tax)}   tone="amber" />
        <Card label={T("Net paid")}   value={idr(totals.net)}   tone="emerald" />
      </div>

      {/* Table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{T("Employee")}</th>
              <th className="th">{T("Period")}</th>
              <th className="th">{T("Status")}</th>
              <th className="th">{t("Attendance", "Absensi")}</th>
              <th className="th text-right">{T("Gross")}</th>
              <th className="th text-right">{T("PPh 21")}</th>
              <th className="th text-right">{T("Net")}</th>
              <th className="th text-right">{T("Actions")}</th>
            </tr>
          </thead>
          <tbody>
            {(salaries.data ?? []).map((s) => (
              <Fragment key={s.id}>
              <tr className="tr-hover border-t border-ink-100">
                <td className="td font-medium">
                  <button type="button" className="inline-flex items-center gap-1 hover:text-brand-700 whitespace-nowrap"
                    aria-expanded={openRows.has(s.id)}
                    onClick={() => toggleRow(s.id)}>
                    {openRows.has(s.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    {s.user_name ?? "—"}
                  </button>
                  <div className="text-[11px] muted pl-5">{t("Breakdown", "Rincian")}</div>
                </td>
                <td className="td muted">{s.period}</td>
                <td className="td">
                  <span className={clsx("chip uppercase", STATUS_CHIP[s.status] ?? "bg-ink-100")}>
                    {s.status}
                  </span>
                  {s.is_posted && (
                    <span className="ml-2 chip bg-brand-50 text-brand-700">{T("posted")}</span>
                  )}
                </td>
                <td className="td text-xs">
                  {/* What attendance did to this month's pay. */}
                  <div className="flex flex-col gap-0.5 tabular-nums whitespace-nowrap">
                    {Number(s.late_deduction) > 0 && (
                      <span className="text-red-700">
                        {t(`late ${s.late_minutes} min −${idr(s.late_deduction)}`,
                           `terlambat ${s.late_minutes} mnt −${idr(s.late_deduction)}`)}</span>
                    )}
                    {Number(s.absent_deduction) > 0 && (
                      <span className="text-red-700">
                        {t(`absent ${s.absent_days} d −${idr(s.absent_deduction)}`,
                           `absen ${s.absent_days} hr −${idr(s.absent_deduction)}`)}</span>
                    )}
                    {Number(s.overtime_pay) > 0 && (
                      <span className="text-emerald-700">
                        {t(`overtime ${s.overtime_hours} h +${idr(s.overtime_pay)}`,
                           `lembur ${s.overtime_hours} jam +${idr(s.overtime_pay)}`)}</span>
                    )}
                    {Number(s.attendance_breakdown?.overtime_pending) > 0 && (
                      <span className="text-amber-700">
                        {t(`${s.attendance_breakdown.overtime_pending} overtime waiting`,
                           `${s.attendance_breakdown.overtime_pending} lembur menunggu`)}</span>
                    )}
                    {!Number(s.late_deduction) && !Number(s.absent_deduction)
                      && !Number(s.overtime_pay) && (
                      <span className="muted">{s.attendance_breakdown?.working_days
                        ? t("on time, no absences", "tepat waktu, tanpa absen") : "—"}</span>
                    )}
                  </div>
                </td>
                <td className="td text-right tabular-nums whitespace-nowrap">{idr(s.gross_salary)}</td>
                <td className="td text-right tabular-nums">{idr(s.pph21)}</td>
                <td className="td text-right tabular-nums font-semibold whitespace-nowrap">{idr(s.net_pay)}</td>
                <td className="td text-right">
                  <div className="inline-flex gap-1">
                    {s.status === "draft" && (
                      <>
                        <button className="btn-ghost text-brand-700"
                          onClick={() => { setEditing(s); setOpenNew(true); }}>
                          {T("Edit")}</button>
                        <button className="btn-ghost"
                          title={t("Re-read this month's attendance", "Baca ulang absensi bulan ini")}
                          aria-label={t("Refresh from attendance", "Perbarui dari absensi")}
                          disabled={refreshAtt.isPending}
                          onClick={() => refreshAtt.mutate(s.id)}>
                          <RefreshCw size={13} /></button>
                        <button className="btn-success"
                          disabled={post.isPending}
                          onClick={() => post.mutate(s.id)}>
                          <BookOpen size={13} /> {T("Post")}</button>
                        <button className="btn-ghost text-red-600 hover:bg-red-50"
                          disabled={del.isPending}
                          onClick={() => {
                            if (window.confirm("Delete this salary?")) del.mutate(s.id);
                          }}>
                          <Trash2 size={13} />
                        </button>
                      </>
                    )}
                    {s.status === "posted" && (
                      <>
                        <button className="btn-success"
                          disabled={pay.isPending}
                          onClick={() => pay.mutate(s.id)}>
                          <CheckCircle size={13} /> {T("Mark paid")}</button>
                        <button className="btn-ghost text-red-600"
                          disabled={reverse.isPending}
                          onClick={() => {
                            if (window.confirm("Reverse the posting?")) reverse.mutate(s.id);
                          }}>
                          <Undo2 size={13} /> {T("Reverse")}</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
              {openRows.has(s.id) && (
                <tr className="bg-ink-50/40">
                  <td colSpan={8} className="px-5 py-4 overflow-x-auto">
                    <PayslipBreakdown slip={s} b={s.attendance_breakdown} />
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
            {!salaries.data?.length && (
              <tr>
                <td colSpan={8} className="td text-center muted py-12">
                  {T("No salary records for")}{" "}{period}{T(". Click \"+ New salary\" to create one.")}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <WorkedExamples />

      <div className="card p-4 flex items-start gap-3 text-sm">
        <AlertCircle size={18} className="text-amber-600 shrink-0 mt-0.5" />
        <div>
          <div className="font-medium">{T("How posting works")}</div>
          <p className="muted">
            {T("\"Post to ledger\" adds the gross salary to")}{" "}<b>{T("6000-04 Beban Gaji Karyawan")}</b>{T(", credits PPh 21 to")}{" "}<b>{T("2102-04 Hutang Pph 21")}</b>{T(", and credits the net amount to")}{" "}
            <b>{T("2102-02 Hutang Gaji Karyawan")}</b>{T(". \"Mark paid\" clears the salary liability and reduces the bank account (default")}{" "}<b>{T("1101-01 Bank BCA")}</b>{T("). \"Reverse\" rolls back the posting (only available before payment).")}</p>
        </div>
      </div>

      <Modal
        open={openNew}
        onClose={() => setOpenNew(false)}
        title={editing ? "Edit salary" : "New salary"}
        subtitle={editing ? `${editing.user_name} · ${editing.period}` : "Add a monthly payroll record."}
        size="xl"
      >
        <NewSalaryForm initial={editing} onClose={() => setOpenNew(false)} />
      </Modal>
    </div>
  );
}

/**
 * The three ways attendance moves pay — late, absent, a late clock-out —
 * each as a full month worked through on the payroll rules in force. The
 * server builds them on last month's calendar with the same calculation real
 * salaries use, so they read true whenever the schedule or grace changes.
 */
function WorkedExamples() {
  const t = useT();
  const [tab, setTab] = useState<"late" | "absent" | "overtime">("late");
  const ex = useQuery({
    queryKey: ["salary-examples"],
    queryFn: () => api.get("/salaries/examples").then((r) => r.data as {
      period: string; examples: any[];
    }),
    staleTime: 5 * 60_000,
  });
  const cur = ex.data?.examples.find((e) => e.key === tab);
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Calculator size={15} className="text-brand-600" />
            {t("How attendance changes pay — three worked examples",
               "Bagaimana absensi mengubah gaji — tiga contoh perhitungan")}
          </div>
          <div className="text-xs muted mt-0.5 max-w-3xl">
            {t(`One employee on a base salary of Rp 8.650.000 (Rp 50.000 an hour) plus Rp 900.000 transport and meal, through ${ex.data?.period ?? "last month"}. Worked out by the same rules as every real payslip — nothing here is saved.`,
               `Satu karyawan dengan gaji pokok Rp 8.650.000 (Rp 50.000 per jam) ditambah Rp 900.000 transport dan makan, selama ${ex.data?.period ?? "bulan lalu"}. Dihitung dengan aturan yang sama seperti slip gaji sebenarnya — tidak ada yang disimpan.`)}
          </div>
        </div>
        <div className="inline-flex rounded-lg border border-ink-200 overflow-hidden text-sm" role="tablist">
          {(["late", "absent", "overtime"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k}
              className={clsx("px-3 py-1.5", tab === k ? "bg-brand-600 text-white" : "hover:bg-ink-50")}
              onClick={() => setTab(k)}>
              {k === "late" ? t("Late", "Terlambat") : k === "absent" ? t("Absent", "Absen")
                : t("Late clock-out", "Pulang lewat jam")}
            </button>
          ))}
        </div>
      </div>
      <div className="p-5 space-y-3">
        {ex.isLoading ? (
          <div className="text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Working it out…", "Menghitung…")}</div>
        ) : !cur ? (
          <div className="text-sm muted">{t("Couldn't load the examples.", "Contoh tidak dapat dimuat.")}</div>
        ) : (
          <>
            <div className="text-sm"><b>{t(cur.title, cur.key === "late" ? "Terlambat" : cur.key === "absent" ? "Absen" : "Pulang lewat jam")}</b> — {t(cur.story, cur.story_id ?? cur.story)}</div>
            <PayslipBreakdown slip={cur} b={cur.breakdown} />
          </>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, tone }: {
  label: string; value: string;
  tone: "brand" | "amber" | "emerald";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    amber:   "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div className="text-[11px] uppercase tracking-wider muted">{T(label)}</div>
        <div className={`h-7 w-7 rounded ${cls} grid place-items-center`}>
          <Wallet size={13} />
        </div>
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
