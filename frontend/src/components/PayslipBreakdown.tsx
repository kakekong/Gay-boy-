import clsx from "clsx";
import { useT } from "@/store/lang";

/** Rupiah with cents where there are any — a per-minute wage is Rp 833,33. */
const rp = (n: number | null | undefined) => {
  // Two decimals or none — never "8.520.238,1" for ,10.
  const v = Math.round(Number(n || 0) * 100) / 100;
  const cents = Math.abs(v % 1) > 0.0001;
  return "Rp " + new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2,
  }).format(v);
};

export interface Slip {
  base_salary: number; transport?: number; meal?: number; bonus?: number; thr?: number;
  other_allowance?: number; overtime_pay?: number;
  pph21?: number; bpjs?: number; other_deduction?: number;
  late_deduction?: number; absent_deduction?: number;
  gross_salary: number; net_pay: number;
}

/**
 * A payslip with its working shown: every earning and deduction, the rates
 * attendance is priced at, and each day that moved the pay with the sum
 * behind it ("20 min × Rp 833,33 = Rp 16.666,67"). Used for real salary
 * records and for the worked examples, which come from the same calculation.
 */
export function PayslipBreakdown({ slip, b }: { slip: Slip; b: any }) {
  const t = useT();
  const n = (v: any) => Number(v || 0);
  const earnings: [string, number, string?][] = [
    [t("Base salary", "Gaji pokok"), n(slip.base_salary)],
    [t("Transport", "Transport"), n(slip.transport)],
    [t("Meal", "Makan"), n(slip.meal)],
    [t("Bonus", "Bonus"), n(slip.bonus)],
    [t("THR", "THR"), n(slip.thr)],
    [t("Other allowance", "Tunjangan lain"), n(slip.other_allowance)],
    [t("Overtime (approved)", "Lembur (disetujui)"), n(slip.overtime_pay),
     b ? t(`${b.overtime_hours} h`, `${b.overtime_hours} jam`) : undefined],
  ];
  const deductions: [string, number, string?][] = [
    [t("Late", "Terlambat"), n(slip.late_deduction),
     b ? t(`${b.late_minutes} min × ${rp(b.minute_wage)}`, `${b.late_minutes} mnt × ${rp(b.minute_wage)}`) : undefined],
    [t("Absent", "Absen"), n(slip.absent_deduction),
     b ? t(`${b.absent_days} day(s) × ${rp(b.day_wage)}`, `${b.absent_days} hari × ${rp(b.day_wage)}`) : undefined],
    [t("PPh 21", "PPh 21"), n(slip.pph21)],
    [t("BPJS", "BPJS"), n(slip.bpjs)],
    [t("Other deduction", "Potongan lain"), n(slip.other_deduction)],
  ];
  const ded = deductions.reduce((s, [, v]) => s + v, 0);

  return (
    <div className="grid lg:grid-cols-[minmax(300px,5fr)_minmax(0,7fr)] gap-5 text-sm">
      {/* ── the payslip ── */}
      <div>
        <div className="text-[11px] uppercase tracking-wider muted mb-1">{t("Payslip", "Slip gaji")}</div>
        <table className="w-full tabular-nums">
          <tbody>
            {earnings.filter(([, v], i) => v || i === 0).map(([label, v, how]) => (
              <tr key={label}>
                <td className="py-0.5">{label}{how && <span className="muted text-xs"> · {how}</span>}</td>
                <td className="py-0.5 text-right whitespace-nowrap">{rp(v)}</td>
              </tr>
            ))}
            <tr className="border-t border-ink-200 font-semibold">
              <td className="py-1">{t("Gross", "Bruto")}</td>
              <td className="py-1 text-right whitespace-nowrap">{rp(slip.gross_salary)}</td>
            </tr>
            {deductions.filter(([, v]) => v).map(([label, v, how]) => (
              <tr key={label} className="text-red-700">
                <td className="py-0.5">{label}{how && <span className="text-xs opacity-80"> · {how}</span>}</td>
                <td className="py-0.5 text-right whitespace-nowrap">− {rp(v)}</td>
              </tr>
            ))}
            {!ded && (
              <tr><td className="py-0.5 muted text-xs" colSpan={2}>{t("No deductions.", "Tanpa potongan.")}</td></tr>
            )}
            <tr className="border-t-2 border-ink-300 font-semibold text-base">
              <td className="py-1">{t("Net pay", "Gaji bersih")}</td>
              <td className="py-1 text-right whitespace-nowrap text-emerald-700">{rp(slip.net_pay)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* ── how attendance was priced ── */}
      <div>
        <div className="text-[11px] uppercase tracking-wider muted mb-1">
          {t("How attendance was worked out", "Perhitungan dari absensi")}
        </div>
        {!b?.working_days ? (
          <div className="text-xs muted">{t("This record was made without attendance.", "Data ini dibuat tanpa absensi.")}</div>
        ) : (
          <>
            <div className="rounded-lg bg-ink-50/70 px-3 py-2 text-xs space-y-0.5 tabular-nums">
              <div>{t(`Working day ${b.schedule.start}–${b.schedule.end}, ${b.schedule.grace_minutes} min grace`,
                      `Jam kerja ${b.schedule.start}–${b.schedule.end}, toleransi ${b.schedule.grace_minutes} mnt`)}</div>
              <div>{t("Day's wage", "Upah harian")} = {rp(slip.base_salary)} ÷ {b.working_days} {t("working days", "hari kerja")} = <b>{rp(b.day_wage)}</b></div>
              <div>{t("Hourly wage", "Upah per jam")} = {rp(slip.base_salary)} ÷ {b.monthly_hours ?? 173} = <b>{rp(b.hourly_wage)}</b></div>
              <div>{t("Per minute", "Per menit")} = {rp(b.hourly_wage)} ÷ 60 = <b>{rp(b.minute_wage ?? b.hourly_wage / 60)}</b></div>
            </div>
            {(b.days ?? []).length === 0 ? (
              <div className="text-xs muted mt-2">{t("Every working day on time, nothing late, absent or overtime.",
                "Semua hari kerja tepat waktu, tanpa terlambat, absen, atau lembur.")}</div>
            ) : (
              <table className="w-full text-xs mt-2 tabular-nums">
                <thead>
                  <tr className="text-[10px] uppercase muted text-left">
                    <th className="py-1 font-medium">{t("Date", "Tanggal")}</th>
                    <th className="py-1 font-medium">{t("What happened", "Kejadian")}</th>
                    <th className="py-1 font-medium">{t("Worked out", "Perhitungan")}</th>
                    <th className="py-1 font-medium text-right">{t("Amount", "Jumlah")}</th>
                  </tr>
                </thead>
                <tbody>
                  {b.days.map((d: any, i: number) => {
                    const { what, how, amount, sign } = describe(d, b, t);
                    return (
                      <tr key={i} className="border-t border-ink-100 align-top">
                        <td className="py-1 whitespace-nowrap">{d.date}</td>
                        <td className="py-1">{what}</td>
                        <td className="py-1 muted">{how}</td>
                        <td className={clsx("py-1 text-right whitespace-nowrap",
                          sign === "-" ? "text-red-700" : sign === "+" ? "text-emerald-700" : "muted")}>
                          {amount != null ? `${sign === "-" ? "− " : sign === "+" ? "+ " : ""}${rp(amount)}` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function describe(d: any, b: any, t: (en: string, id: string) => string) {
  if (d.kind === "late") {
    return {
      what: t(`Late — in at ${d.clock_in}`, `Terlambat — masuk ${d.clock_in}`),
      how: `${d.minutes} ${t("min", "mnt")} × ${rp(b.minute_wage ?? b.hourly_wage / 60)}`,
      amount: d.amount, sign: "-",
    };
  }
  if (d.kind === "absent") {
    return { what: t("Absent — no clock-in", "Absen — tidak absen masuk"),
             how: `1 × ${rp(b.day_wage)}`, amount: d.amount, sign: "-" };
  }
  if (d.kind === "grace") {
    return { what: t(`In at ${d.clock_in}, ${d.minutes} min late`, `Masuk ${d.clock_in}, terlambat ${d.minutes} mnt`),
             how: t(`within the ${b.schedule?.grace_minutes ?? 15}-min grace — no deduction`,
                    `masih dalam toleransi ${b.schedule?.grace_minutes ?? 15} mnt — tanpa potongan`),
             amount: null, sign: "" };
  }
  if (d.kind === "excused") {
    const label: Record<string, [string, string]> = {
      sick: ["Sick", "Sakit"], leave: ["Leave", "Cuti"], holiday: ["Holiday", "Libur"], wfh: ["Work from home", "Kerja dari rumah"],
    };
    const [en, id] = label[d.status] ?? [d.status, d.status];
    return { what: t(`${en} (marked by HR)`, `${id} (dicatat HR)`), how: t("excused — no deduction", "dimaafkan — tanpa potongan"),
             amount: null, sign: "" };
  }
  if (d.kind === "half_day") {
    return { what: t("Half day", "Setengah hari"), how: `0.5 × ${rp(b.day_wage)}`,
             amount: d.amount, sign: "-" };
  }
  // overtime
  const out = t(`Out at ${d.clock_out}, ${d.minutes} min over`, `Pulang ${d.clock_out}, lebih ${d.minutes} mnt`);
  if (d.status === "approved") {
    const h = Number(d.hours || 0);
    const how = h <= 1
      ? `${h} h → 1.5 × ${rp(b.hourly_wage)}`
      : `${h} h → 1.5 × ${rp(b.hourly_wage)} + ${h - 1} × 2 × ${rp(b.hourly_wage)}`;
    return { what: `${out} · ${t("approved", "disetujui")}`, how, amount: d.amount, sign: "+" };
  }
  if (d.status === "rejected") {
    return { what: `${out} · ${t("not approved", "tidak disetujui")}`, how: t("not paid", "tidak dibayar"),
             amount: null, sign: "" };
  }
  if (d.status === "pending") {
    return { what: `${out} · ${t("waiting for approval", "menunggu persetujuan")}`,
             how: t("paid once approved", "dibayar setelah disetujui"), amount: null, sign: "" };
  }
  return { what: out, how: t("too short to file", "terlalu singkat untuk diajukan"), amount: null, sign: "" };
}
