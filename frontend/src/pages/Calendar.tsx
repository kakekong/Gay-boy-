import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CalendarDays, ChevronLeft, ChevronRight, Plus, Bell, FileText,
  Truck, AlertCircle, CheckCircle2, ListChecks, Pencil, Check,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { NewReminderForm, type ReminderRow } from "@/components/forms/NewReminderForm";
import { localDay } from "@/lib/localDate";
import { useT } from "@/store/lang";

interface CalEvent {
  id: string;
  kind: "reminder" | "activity" | "quotation_expiry" | "payment_due" | "delivery" | "stage_task";
  title: string;
  subtype?: string;
  at: string;
  status?: string;
  link?: string | null;
  color: "brand" | "violet" | "emerald" | "amber" | "red" | "ink";
  /** Manual reminders only — what the edit form needs. */
  reminder?: ReminderRow;
}

const COLOR: Record<CalEvent["color"], string> = {
  brand:   "bg-brand-500 text-white",
  violet:  "bg-violet-500 text-white",
  emerald: "bg-emerald-500 text-white",
  amber:   "bg-amber-500 text-white",
  red:     "bg-red-500 text-white",
  ink:     "bg-ink-400 text-white",
};

const KIND_META: Record<CalEvent["kind"], { label: string; labelId: string; Icon: any; tone: string }> = {
  reminder:         { label: "Reminder",        labelId: "Pengingat",             Icon: Bell,           tone: "text-brand-700 bg-brand-50" },
  activity:         { label: "Activity",        labelId: "Aktivitas",             Icon: CheckCircle2,   tone: "text-ink-700 bg-ink-100" },
  quotation_expiry: { label: "Quote expires",   labelId: "Penawaran kedaluwarsa", Icon: FileText,       tone: "text-violet-700 bg-violet-50" },
  payment_due:      { label: "Payment due",     labelId: "Pembayaran jatuh tempo",Icon: AlertCircle,    tone: "text-amber-700 bg-amber-50" },
  delivery:         { label: "Delivery",        labelId: "Pengiriman",            Icon: Truck,          tone: "text-emerald-700 bg-emerald-50" },
  stage_task:       { label: "Stage task",      labelId: "Tugas tahap",           Icon: ListChecks,     tone: "text-red-700 bg-red-50" },
};

function startOfMonth(d: Date) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function addDays(d: Date, n: number) { const x = new Date(d); x.setDate(d.getDate() + n); return x; }
// The cell's own day, in the viewer's clock — not toISOString(), which is UTC
// and in WIB names the day before for every cell (midnight local = 17:00 UTC).
const fmtIsoDay = localDay;
function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export default function CalendarPage() {
  const t = useT();
  const nav = useNavigate();
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [selected, setSelected] = useState<Date>(new Date());
  const [filters, setFilters] = useState<Record<CalEvent["kind"], boolean>>({
    reminder: true, activity: true, quotation_expiry: true, payment_due: true, delivery: true, stage_task: true,
  });
  const [openNew, setOpenNew] = useState<{ open: boolean; date?: string; editing?: ReminderRow }>({ open: false });

  // Build a 6-row × 7-col grid, Monday-first
  const grid = useMemo(() => {
    const first = startOfMonth(cursor);
    // Mon = 1 … Sun = 0 → shift so Monday = 0
    const offset = (first.getDay() + 6) % 7;
    const start = addDays(first, -offset);
    return Array.from({ length: 42 }, (_, i) => addDays(start, i));
  }, [cursor]);

  const range = { from: fmtIsoDay(grid[0]), to: fmtIsoDay(grid[grid.length - 1]) };

  const events = useQuery({
    queryKey: ["calendar-events", range.from, range.to],
    queryFn: () =>
      api.get("/calendar/events", { params: { from: range.from, to: range.to } })
        .then((r) => r.data as CalEvent[]),
  });

  const qc = useQueryClient();
  const markDone = useMutation({
    mutationFn: (id: string) => api.patch(`/calendar/reminders/${id}/done`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["my-queue"] });
    },
  });

  const filtered = (events.data ?? []).filter((e) => filters[e.kind]);

  // Index by the local YYYY-MM-DD the event falls on. Reminders come back in
  // UTC ("…T01:00:00Z" for 08:00 WIB), so the day is read after converting.
  const byDay = useMemo(() => {
    const m = new Map<string, CalEvent[]>();
    for (const e of filtered) {
      const k = fmtIsoDay(new Date(e.at));
      const arr = m.get(k) ?? [];
      arr.push(e);
      m.set(k, arr);
    }
    return m;
  }, [filtered]);

  const locale = t("en-US", "id-ID");
  const monthLabel = cursor.toLocaleDateString(locale, { month: "long", year: "numeric" });
  const today = new Date();
  const dayEvents = byDay.get(fmtIsoDay(selected)) ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <CalendarDays size={22} className="text-brand-600" /> {t("Calendar", "Kalender")}
          </h1>
          <p className="text-sm muted">
            {t(
              "Reminders · activities · quote expiries · payment dues · target deliveries — all in one place.",
              "Pengingat · aktivitas · penawaran kedaluwarsa · pembayaran jatuh tempo · target pengiriman — semua di satu tempat."
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={() => { setCursor(startOfMonth(new Date())); setSelected(new Date()); }}>
            {t("Today", "Hari ini")}
          </button>
          <button
            className="btn-primary"
            onClick={() => setOpenNew({ open: true, date: fmtIsoDay(selected) })}
          >
            <Plus size={15} /> {t("New reminder", "Pengingat baru")}
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex flex-wrap gap-2">
        {(Object.keys(KIND_META) as CalEvent["kind"][]).map((k) => {
          const M = KIND_META[k];
          const on = filters[k];
          return (
            <button
              key={k}
              onClick={() => setFilters((f) => ({ ...f, [k]: !f[k] }))}
              className={clsx(
                "chip border ring-0 transition-colors px-2.5 py-1 text-xs",
                on ? M.tone + " border-transparent"
                   : "bg-white text-ink-500 border-ink-200 line-through"
              )}
            >
              <M.Icon size={12} /> {t(M.label, M.labelId)}
            </button>
          );
        })}
      </div>

      {/* Month nav */}
      <div className="flex items-center gap-2">
        <button className="btn-ghost"
          onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>
          <ChevronLeft size={16} />
        </button>
        <div className="text-lg font-semibold">{monthLabel}</div>
        <button className="btn-ghost"
          onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Month grid */}
        <div className="card lg:col-span-2 overflow-hidden">
          <div className="grid grid-cols-7 border-b border-ink-100 bg-ink-50/60">
            {[
              t("Mon", "Sen"), t("Tue", "Sel"), t("Wed", "Rab"), t("Thu", "Kam"),
              t("Fri", "Jum"), t("Sat", "Sab"), t("Sun", "Min"),
            ].map((d) => (
              <div key={d} className="px-2 py-2 text-[10px] uppercase tracking-wider text-ink-500 font-semibold">
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 grid-rows-6">
            {grid.map((d, idx) => {
              const inMonth = d.getMonth() === cursor.getMonth();
              const isToday = sameDay(d, today);
              const isSelected = sameDay(d, selected);
              const dayKey = fmtIsoDay(d);
              const cellEvents = byDay.get(dayKey) ?? [];
              return (
                <button
                  key={idx}
                  onClick={() => setSelected(d)}
                  onDoubleClick={() => setOpenNew({ open: true, date: dayKey })}
                  className={clsx(
                    "h-24 lg:h-28 text-left p-1.5 border-r border-b border-ink-100 transition-colors",
                    "hover:bg-ink-50 focus:outline-none",
                    !inMonth && "bg-ink-50/40 text-ink-400",
                    isSelected && "ring-2 ring-inset ring-brand-400 bg-brand-50/40",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className={clsx(
                      "text-[11px] font-medium",
                      isToday && "h-5 w-5 grid place-items-center rounded-full bg-brand-600 text-white"
                    )}>
                      {d.getDate()}
                    </span>
                    {cellEvents.length > 0 && (
                      <span className="text-[10px] text-ink-500">{cellEvents.length}</span>
                    )}
                  </div>
                  <div className="mt-1 space-y-0.5">
                    {cellEvents.slice(0, 3).map((e) => (
                      <div
                        key={e.id}
                        className={clsx(
                          "truncate rounded px-1 py-0.5 text-[10px] font-medium",
                          COLOR[e.color]
                        )}
                        title={e.title}
                      >
                        {e.title}
                      </div>
                    ))}
                    {cellEvents.length > 3 && (
                      <div className="text-[10px] text-ink-500">+{cellEvents.length - 3} {t("more", "lagi")}</div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Day panel */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-xs uppercase tracking-wider muted">
                {selected.toLocaleDateString(locale, { weekday: "long" })}
              </div>
              <div className="text-2xl font-semibold tracking-tight">
                {selected.toLocaleDateString(locale, { day: "numeric", month: "long" })}
              </div>
            </div>
            <button
              className="btn-ghost"
              onClick={() => setOpenNew({ open: true, date: fmtIsoDay(selected) })}
            >
              <Plus size={14} />
            </button>
          </div>

          {dayEvents.length === 0 ? (
            <div className="rounded-xl border border-dashed border-ink-200 p-8 text-center text-sm muted">
              {t(
                "Nothing scheduled. Add a reminder or wait — incoming WhatsApp shows here too.",
                "Tidak ada jadwal. Tambahkan pengingat atau tunggu — WhatsApp masuk juga tampil di sini."
              )}
            </div>
          ) : (
            <ul className="space-y-2">
              {dayEvents.map((e) => {
                const M = KIND_META[e.kind];
                const rem = e.reminder;
                return (
                  <li
                    key={e.id}
                    className={clsx(
                      "rounded-xl border border-ink-100 p-3 hover:border-brand-300 hover:shadow-soft transition-all",
                      e.link && "cursor-pointer"
                    )}
                    onClick={() => e.link && nav(e.link)}
                  >
                    <div className="flex items-start gap-3">
                      <div className={clsx("h-8 w-8 rounded-lg grid place-items-center shrink-0", M.tone)}>
                        <M.Icon size={14} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{e.title}</div>
                        {rem?.message && rem.message.trim().includes("\n") && (
                          <div className="text-xs text-ink-600 mt-1 whitespace-pre-line line-clamp-4">
                            {rem.message.trim().split("\n").slice(1).join("\n")}
                          </div>
                        )}
                        <div className="text-[11px] muted mt-0.5 flex items-center gap-1.5">
                          {new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          <span>·</span>
                          <span className="capitalize">{t(M.label, M.labelId)}</span>
                          {e.status && <><span>·</span><span>{e.status}</span></>}
                        </div>
                      </div>
                      {rem?.editable && e.status === "pending" && (
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2 text-xs shrink-0 hover:text-emerald-700"
                          title={t("Mark as done", "Tandai selesai")}
                          disabled={markDone.isPending && markDone.variables === rem.id}
                          onClick={(ev) => { ev.stopPropagation(); markDone.mutate(rem.id); }}
                        >
                          <Check size={13} /> {t("Done", "Selesai")}
                        </button>
                      )}
                      {rem?.editable && (
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2 text-xs shrink-0"
                          title={t("Edit reminder", "Ubah pengingat")}
                          onClick={(ev) => { ev.stopPropagation(); setOpenNew({ open: true, editing: rem }); }}
                        >
                          <Pencil size={13} /> {t("Edit", "Ubah")}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      <Modal
        open={openNew.open}
        onClose={() => setOpenNew({ open: false })}
        title={openNew.editing ? t("Edit reminder", "Ubah pengingat") : t("New reminder", "Pengingat baru")}
        subtitle={openNew.editing
          ? t("Change the note, time or customer — no need to make a new one.",
              "Ubah catatan, waktu, atau pelanggan — tidak perlu membuat jadwal baru.")
          : t(
          "Schedule a follow-up, payment chase, or delivery check.",
          "Jadwalkan tindak lanjut, penagihan pembayaran, atau pengecekan pengiriman."
        )}
      >
        <NewReminderForm
          key={openNew.editing?.id ?? openNew.date ?? "new"}
          editing={openNew.editing}
          defaultDate={openNew.date}
          onClose={() => setOpenNew({ open: false })}
        />
      </Modal>
    </div>
  );
}
