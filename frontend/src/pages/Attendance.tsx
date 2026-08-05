import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock, LogIn, LogOut, Loader2, Calendar as CalIcon, AlertCircle, CheckCircle2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import {
  DailyLogSection, DailyLogHistory, TeamDailyLogs,
} from "@/components/DailyLogSection";
import { T, locale, t as tt } from "@/store/lang";

interface AttendanceRow {
  id: string;
  user_id: string;
  user_name: string | null;
  date: string;
  clock_in: string | null;
  clock_out: string | null;
  hours: number;
  status: string;
  notes: string | null;
}

const STATUS_CHIP: Record<string, string> = {
  present:  "bg-emerald-50 text-emerald-700",
  absent:   "bg-red-50 text-red-700",
  half_day: "bg-amber-50 text-amber-700",
  leave:    "bg-violet-50 text-violet-700",
  wfh:      "bg-blue-50 text-blue-700",
  sick:     "bg-pink-50 text-pink-700",
  holiday:  "bg-ink-100 text-ink-700",
  not_started: "bg-ink-100 text-ink-700",
};

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function AttendancePage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const canManage = me && (me.role === "hr" || me.role === "director");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const today = useQuery({
    queryKey: ["attendance-today"],
    queryFn: () => api.get("/attendance/me/today").then((r) => r.data),
    refetchInterval: 30_000,
  });

  const myHistory = useQuery({
    queryKey: ["attendance-me"],
    queryFn: () => api.get("/attendance/me").then((r) => r.data as AttendanceRow[]),
  });

  const all = useQuery({
    queryKey: ["attendance-all"],
    queryFn: () => api.get("/attendance").then((r) => r.data as AttendanceRow[]),
    enabled: !!canManage,
  });

  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const summary = useQuery({
    queryKey: ["attendance-summary-all", period],
    queryFn: () => api.get("/attendance/summary-all", { params: { period } }).then((r) => r.data),
    enabled: !!canManage,
  });

  // One note box serving both buttons — whichever you press carries whatever
  // is typed. Cleared on success so the next punch starts blank.
  const [clockNote, setClockNote] = useState("");

  const clockIn = useMutation({
    mutationFn: () => api.post("/attendance/clock-in", { note: clockNote.trim() || null }),
    onSuccess: () => {
      setClockNote("");
      setFlash({ kind: "ok", text: "Clocked in. Have a great day!" });
      qc.invalidateQueries({ queryKey: ["attendance-today"] });
      qc.invalidateQueries({ queryKey: ["attendance-me"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to clock in",
    }),
  });
  const clockOut = useMutation({
    mutationFn: () => api.post("/attendance/clock-out", { note: clockNote.trim() || null }),
    onSuccess: () => {
      setClockNote("");
      setFlash({ kind: "ok", text: "Clocked out. See you tomorrow!" });
      qc.invalidateQueries({ queryKey: ["attendance-today"] });
      qc.invalidateQueries({ queryKey: ["attendance-me"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to clock out",
    }),
  });

  const t = today.data;
  const hasIn = !!t?.clock_in;
  const hasOut = !!t?.clock_out;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Clock size={22} className="text-brand-600" /> {T("Attendance")}</h1>
        <p className="text-sm muted">
          {T("Clock in when you start the day, out when you leave. Hours feed into your payroll.")}</p>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          {flash.kind === "ok"
            ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
            : <AlertCircle  size={16} className="mt-0.5 shrink-0" />}
          <div className="flex-1">{flash.text}</div>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}

      {/* Today card */}
      <div className="card p-5 lg:p-8">
        <div className="text-xs uppercase tracking-wider muted">{T("Today")}</div>
        <div className="mt-1 flex items-end gap-3 flex-wrap">
          <div className="text-3xl lg:text-4xl font-semibold tracking-tight">
            {new Date().toLocaleDateString(locale(),  { weekday: "long", day: "numeric", month: "long" })}
          </div>
          {t?.status && (
            <span className={clsx("chip uppercase",
              STATUS_CHIP[t.status] ?? "bg-ink-100 text-ink-700")}>
              {T(t.status.replace(/_/g, " "))}
            </span>
          )}
        </div>

        <div className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Card label={T("Clock in")}  value={fmtTime(t?.clock_in)} />
          <Card label={T("Clock out")} value={fmtTime(t?.clock_out)} />
          <Card label={T("Hours")}     value={t?.hours ? `${Number(t.hours).toFixed(2)}h` : "—"} />
        </div>

        <div className="mt-5">
          <label className="text-xs uppercase tracking-wider muted" htmlFor="clock-note">
            {T("Note (optional)")}</label>
          <textarea
            id="clock-note"
            className="input mt-1 w-full"
            rows={2}
            value={clockNote}
            onChange={(e) => setClockNote(e.target.value)}
            disabled={hasIn && hasOut}
            placeholder={T("e.g. Late — traffic on the toll road. Leaving early for the PT Bara site visit.")}
          />
          <p className="mt-1 text-xs muted">
            {hasIn && hasOut
              ? T("You are done for today — the note is closed.")
              : tt(`Saved against today's attendance when you press Clock ${hasIn ? "OUT" : "IN"}.`,
                 `Tersimpan pada absensi hari ini saat Anda menekan ABSEN ${hasIn ? "KELUAR" : "MASUK"}.`)}
          </p>
        </div>

        {t?.notes && (
          <div className="mt-3 rounded-xl bg-ink-50 px-4 py-3 text-sm whitespace-pre-line">
            <div className="text-xs uppercase tracking-wider muted mb-1">{T("Today's note")}</div>
            {t.notes}
          </div>
        )}

        <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            onClick={() => clockIn.mutate()}
            disabled={hasIn || clockIn.isPending}
            className={clsx(
              "rounded-2xl p-5 text-left transition-all border-2",
              hasIn
                ? "bg-ink-50 border-ink-100 cursor-not-allowed opacity-60"
                : "bg-emerald-50 border-emerald-200 hover:bg-emerald-100 active:scale-[0.98]"
            )}
          >
            <div className="flex items-center gap-2">
              {clockIn.isPending
                ? <Loader2 size={22} className="animate-spin text-emerald-700" />
                : <LogIn size={22} className="text-emerald-700" />}
              <div>
                <div className="text-lg font-semibold">{T("Clock IN")}</div>
                <div className="text-xs muted">
                  {hasIn ? tt(`Done at ${fmtTime(t?.clock_in)}`, `Selesai pukul ${fmtTime(t?.clock_in)}`) : T("Start your work day")}
                </div>
              </div>
            </div>
          </button>
          <button
            onClick={() => clockOut.mutate()}
            disabled={!hasIn || hasOut || clockOut.isPending}
            className={clsx(
              "rounded-2xl p-5 text-left transition-all border-2",
              !hasIn || hasOut
                ? "bg-ink-50 border-ink-100 cursor-not-allowed opacity-60"
                : "bg-brand-50 border-brand-200 hover:bg-brand-100 active:scale-[0.98]"
            )}
          >
            <div className="flex items-center gap-2">
              {clockOut.isPending
                ? <Loader2 size={22} className="animate-spin text-brand-700" />
                : <LogOut size={22} className="text-brand-700" />}
              <div>
                <div className="text-lg font-semibold">{T("Clock OUT")}</div>
                <div className="text-xs muted">
                  {hasOut ? tt(`Done at ${fmtTime(t?.clock_out)}`, `Selesai pukul ${fmtTime(t?.clock_out)}`)
                          : hasIn ? T("End your work day") : T("Clock in first")}
                </div>
              </div>
            </div>
          </button>
        </div>
      </div>

      {/* Daily log */}
      <DailyLogSection />
      <DailyLogHistory />

      {/* Team logs — HR / manager / director oversight */}
      {["hr", "manager", "director"].includes(me?.role ?? "") && <TeamDailyLogs />}

      {/* My history */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
          <div className="font-semibold flex items-center gap-2">
            <CalIcon size={15} /> {T("My recent attendance")}</div>
          <div className="text-xs muted">{T("last 30 days")}</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("Date")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th">{T("Clock in")}</th>
                <th className="th">{T("Clock out")}</th>
                <th className="th text-right">{T("Hours")}</th>
                <th className="th">{T("Note")}</th>
              </tr>
            </thead>
            <tbody>
              {(myHistory.data ?? []).map((r) => (
                <tr key={r.id} className="border-t border-ink-100">
                  <td className="td whitespace-nowrap">{r.date}</td>
                  <td className="td">
                    <span className={clsx("chip uppercase",
                      STATUS_CHIP[r.status] ?? "bg-ink-100 text-ink-700")}>
                      {T(r.status.replace(/_/g, " "))}
                    </span>
                  </td>
                  <td className="td muted whitespace-nowrap">{fmtTime(r.clock_in)}</td>
                  <td className="td muted whitespace-nowrap">{fmtTime(r.clock_out)}</td>
                  <td className="td text-right tabular-nums">{Number(r.hours).toFixed(2)}</td>
                  <td className="td"><AttendanceNote text={r.notes} /></td>
                </tr>
              ))}
              {!myHistory.data?.length && (
                <tr><td colSpan={6} className="td text-center muted py-8">{T("No attendance recorded yet.")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* HR / Director: monthly summary per employee */}
      {canManage && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-semibold">{T("Attendance summary")}</div>
              <div className="text-xs muted">
                {T("Per-employee roll-up ·")}{" "}{summary.data?.workdays_in_month ?? "—"} {T("workdays in month")}</div>
            </div>
            <input
              type="month"
              className="input w-auto"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{T("Employee")}</th>
                  <th className="th">{T("Role")}</th>
                  <th className="th text-right">{T("Present")}</th>
                  <th className="th text-right">{T("Absent")}</th>
                  <th className="th text-right">{T("Half day")}</th>
                  <th className="th text-right">{T("Leave/Sick")}</th>
                  <th className="th text-right">{T("Hours")}</th>
                </tr>
              </thead>
              <tbody>
                {(summary.data?.rows ?? []).map((r: any) => (
                  <tr key={r.user_id} className="border-t border-ink-100">
                    <td className="td font-medium">{r.user_name}</td>
                    <td className="td muted capitalize">{r.role}</td>
                    <td className="td text-right tabular-nums text-emerald-700">{r.present_like_days}</td>
                    <td className="td text-right tabular-nums text-red-700">{r.absent_days}</td>
                    <td className="td text-right tabular-nums">{r.half_days}</td>
                    <td className="td text-right tabular-nums">{r.leave_days}</td>
                    <td className="td text-right tabular-nums">{Number(r.total_hours).toFixed(1)}</td>
                  </tr>
                ))}
                {!summary.data?.rows?.length && (
                  <tr><td colSpan={7} className="td text-center muted py-8">
                    {summary.isLoading ? T("Loading…") : T("No data for this month.")}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* HR / Director: everyone */}
      {canManage && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold">{T("All employees · today + recent")}</div>
            <div className="text-xs muted">{T("HR / Director view")}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{T("Date")}</th>
                  <th className="th">{T("Employee")}</th>
                  <th className="th">{T("Status")}</th>
                  <th className="th">{T("Clock in")}</th>
                  <th className="th">{T("Clock out")}</th>
                  <th className="th text-right">{T("Hours")}</th>
                  <th className="th">{T("Note")}</th>
                </tr>
              </thead>
              <tbody>
                {(all.data ?? []).map((r) => (
                  <tr key={r.id} className="border-t border-ink-100">
                    <td className="td whitespace-nowrap">{r.date}</td>
                    <td className="td font-medium whitespace-nowrap">{r.user_name ?? "—"}</td>
                    <td className="td">
                      <span className={clsx("chip uppercase",
                        STATUS_CHIP[r.status] ?? "bg-ink-100 text-ink-700")}>
                        {T(r.status.replace(/_/g, " "))}
                      </span>
                    </td>
                    <td className="td muted whitespace-nowrap">{fmtTime(r.clock_in)}</td>
                    <td className="td muted whitespace-nowrap">{fmtTime(r.clock_out)}</td>
                    <td className="td text-right tabular-nums">{Number(r.hours).toFixed(2)}</td>
                    <td className="td"><AttendanceNote text={r.notes} /></td>
                  </tr>
                ))}
                {!all.data?.length && (
                  <tr><td colSpan={7} className="td text-center muted py-8">{T("No attendance recorded yet.")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** The day's note.
 *
 *  One column with up to three authors: clocking in and clocking out each
 *  append a labelled line (`In: …`, `Out: …`), while HR's manual entry
 *  overwrites the field with plain text. So show the labels as labels, let the
 *  rest wrap, and keep a long note from turning the row into a wall of text. */
function AttendanceNote({ text }: { text: string | null }) {
  const [open, setOpen] = useState(false);
  const lines = (text ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return <span className="muted">—</span>;
  const shown = open ? lines : lines.slice(0, 2);
  return (
    <div className="min-w-[13rem] max-w-[26rem] space-y-0.5">
      {shown.map((line, i) => {
        const m = /^(In|Out|HR):\s*(.*)$/i.exec(line);
        return (
          <div key={i} className="flex gap-1.5 items-baseline">
            {m && (
              <span className="text-[10px] font-semibold uppercase tracking-wider muted shrink-0">
                {m[1]}
              </span>
            )}
            <span className="whitespace-pre-wrap break-words">{m ? m[2] : line}</span>
          </div>
        );
      })}
      {lines.length > 2 && (
        <button
          className="text-xs text-brand-700 hover:underline"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? T("Show less") : tt(`+${lines.length - 2} more`, `+${lines.length - 2} lagi`)}
        </button>
      )}
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-ink-50 border border-ink-100 p-4">
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
