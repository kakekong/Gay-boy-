/**
 * One person's attendance, day by day.
 *
 * The summary answers "how many days" and stops there. The question it
 * provokes is always the next one — *which* days, and what happened on them:
 * the fortnight somebody clocked 82 hours against a colleague's 118, the
 * month with a zero in it, the day that says half. Until now the only way to
 * find out was to read the all-employees table underneath and pick their rows
 * out by eye.
 *
 * So the name is a button, and behind it is their record: a month at a time
 * with arrows either side, or the whole thing at once. The roll-up at the top
 * counts whatever range is on screen, so it always describes what is below it
 * rather than a month somebody has since navigated away from.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, CalendarDays } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { useT, T, locale } from "@/store/lang";

interface Day {
  id: string;
  date: string;
  clock_in: string | null;
  clock_out: string | null;
  hours: number;
  status: string;
  notes: string | null;
}

interface Props {
  open: boolean;
  userId: string;
  name: string;
  role?: string;
  /** The month the summary was showing when the name was clicked. */
  period: string;
  onClose: () => void;
}

const CHIP: Record<string, string> = {
  present:  "bg-emerald-50 text-emerald-700",
  wfh:      "bg-cyan-50 text-cyan-700",
  half_day: "bg-amber-50 text-amber-700",
  leave:    "bg-blue-50 text-blue-700",
  sick:     "bg-violet-50 text-violet-700",
  absent:   "bg-red-50 text-red-700",
};

function shiftMonth(period: string, by: number): string {
  const [y, m] = period.split("-").map(Number);
  const d = new Date(y, (m - 1) + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(locale(), {
    hour: "2-digit", minute: "2-digit",
  }) : "—";

export function EmployeeAttendanceModal({
  open, userId, name, role, period, onClose,
}: Props) {
  const t = useT();
  const [month, setMonth] = useState(period);
  const [allTime, setAllTime] = useState(false);

  const days = useQuery({
    queryKey: ["attendance-of", userId, allTime ? "all" : month],
    queryFn: () => api.get("/attendance", {
      params: { user_id: userId, ...(allTime ? {} : { period: month }) },
    }).then((r) => r.data as Day[]),
    enabled: open && !!userId,
  });

  const rows = days.data ?? [];
  const tally = rows.reduce((acc, r) => {
    if (r.status === "present" || r.status === "wfh") acc.present += 1;
    else if (r.status === "absent") acc.absent += 1;
    else if (r.status === "half_day") acc.half += 1;
    else if (r.status === "leave" || r.status === "sick") acc.leave += 1;
    acc.hours += Number(r.hours || 0);
    return acc;
  }, { present: 0, absent: 0, half: 0, leave: 0, hours: 0 });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      dismissOnBackdrop
      title={name}
      subtitle={role
        ? `${t("Attendance record", "Catatan kehadiran")} · ${role}`
        : t("Attendance record", "Catatan kehadiran")}
    >
      <div className="space-y-4">
        {/* Which stretch of time is on screen */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            <button className="btn-ghost px-2" disabled={allTime}
              aria-label={t("Previous month", "Bulan sebelumnya")}
              onClick={() => setMonth((m) => shiftMonth(m, -1))}>
              <ChevronLeft size={15} />
            </button>
            <input type="month" className="input w-auto" value={month}
              disabled={allTime}
              aria-label={t("Month", "Bulan")}
              onChange={(e) => setMonth(e.target.value)} />
            <button className="btn-ghost px-2" disabled={allTime}
              aria-label={t("Next month", "Bulan berikutnya")}
              onClick={() => setMonth((m) => shiftMonth(m, 1))}>
              <ChevronRight size={15} />
            </button>
          </div>
          <label className="text-xs flex items-center gap-2">
            <input type="checkbox" checked={allTime}
              onChange={(e) => setAllTime(e.target.checked)} />
            {t("Everything on record", "Seluruh catatan")}
          </label>
        </div>

        {/* The roll-up for whatever is on screen */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {([
            [t("Present", "Hadir"), tally.present, "text-emerald-700"],
            [t("Absent", "Absen"), tally.absent, "text-red-700"],
            [t("Half day", "Setengah hari"), tally.half, ""],
            [t("Leave/Sick", "Cuti/Sakit"), tally.leave, ""],
            [t("Hours", "Jam"), tally.hours.toFixed(1), ""],
          ] as [string, number | string, string][]).map(([label, value, tone]) => (
            <div key={label} className="rounded-lg bg-ink-50/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
              <div className={clsx("text-lg font-semibold tabular-nums", tone)}>
                {value}
              </div>
            </div>
          ))}
        </div>

        {days.isLoading ? (
          <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-ink-200 p-8 text-center text-sm muted">
            <CalendarDays size={18} className="mx-auto mb-2 opacity-60" />
            {allTime
              ? t("Nothing on record for this person yet.",
                   "Belum ada catatan untuk orang ini.")
              : t("Nothing recorded in this month. Try another month, or tick “Everything on record”.",
                   "Tidak ada catatan pada bulan ini. Coba bulan lain, atau centang “Seluruh catatan”.")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("Date", "Tanggal")}</th>
                  <th className="th">{T("Status")}</th>
                  <th className="th">{t("Clock in", "Masuk")}</th>
                  <th className="th">{t("Clock out", "Pulang")}</th>
                  <th className="th text-right">{t("Hours", "Jam")}</th>
                  <th className="th">{t("Notes", "Catatan")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-ink-100 align-top">
                    <td className="td whitespace-nowrap">
                      {new Date(r.date).toLocaleDateString(locale(), {
                        weekday: "short", day: "2-digit", month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="td">
                      <span className={clsx("chip capitalize",
                        CHIP[r.status] ?? "bg-ink-100 text-ink-700")}>
                        {r.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="td tabular-nums">{clock(r.clock_in)}</td>
                    <td className="td tabular-nums">{clock(r.clock_out)}</td>
                    <td className="td text-right tabular-nums">
                      {Number(r.hours || 0).toFixed(1)}
                    </td>
                    <td className="td text-xs muted whitespace-pre-wrap">
                      {r.notes || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}
