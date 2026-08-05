import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Target, Plus, Loader2, Trash2, Pencil, Save, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { T } from "@/store/lang";

interface TargetRow {
  id: string;
  user_id: string;
  user_name: string | null;
  period: string;
  target_amount: number;
  achieved_amount: number;
  progress_pct: number;
  remaining: number;
  notes: string | null;
}

interface Employee { id: string; full_name: string; role: string; }

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function SalesTargetsPage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";

  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [editing, setEditing] = useState<string | null>(null);
  const [editAmount, setEditAmount] = useState(0);

  const [showNew, setShowNew] = useState(false);
  const [newUserId, setNewUserId] = useState("");
  const [newAmount, setNewAmount] = useState(0);
  const [newNotes, setNewNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const targets = useQuery({
    queryKey: ["sales-targets", period],
    queryFn: () => api.get("/sales-targets", { params: { period } })
      .then((r) => r.data as TargetRow[]),
  });

  const employees = useQuery({
    queryKey: ["employees-min"],
    queryFn: () => api.get("/users", { params: { role: "sales" } })
      .then((r) => r.data as Employee[]),
    enabled: isDirector,
  });

  const create = useMutation({
    mutationFn: () => api.post("/sales-targets", {
      user_id: newUserId, period, target_amount: newAmount, notes: newNotes || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-targets"] });
      setShowNew(false); setNewUserId(""); setNewAmount(0); setNewNotes("");
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed"),
  });

  const update = useMutation({
    mutationFn: (id: string) => api.patch(`/sales-targets/${id}`, { target_amount: editAmount }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-targets"] });
      setEditing(null);
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/sales-targets/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sales-targets"] }),
    onError: (e: any) => alert(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? "Failed to delete target"
    ),
  });

  const summary = (targets.data ?? []).reduce(
    (a, r) => ({
      count: a.count + 1,
      target: a.target + (r.target_amount || 0),
      achieved: a.achieved + (r.achieved_amount || 0),
    }),
    { count: 0, target: 0, achieved: 0 },
  );

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Target size={22} className="text-brand-600" /> {T("Sales Targets")}</h1>
          <p className="text-sm muted">
            {isDirector
              ? T("Set monthly revenue targets. Achievement is the sum of won quotations in the period.")
              : T("Your monthly target and live progress, based on won quotations.")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            className="input max-w-[180px]"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
          {isDirector && (
            <button className="btn-primary" onClick={() => setShowNew(true)}>
              <Plus size={14} /> {T("Set target")}</button>
          )}
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card label={T("Targets set")}  value={String(summary.count)} tone="brand" />
        <Card label={T("Total target")} value={idr(summary.target)}    tone="brand" />
        <Card label={T("Achieved")}     value={idr(summary.achieved)}  tone="emerald" />
        <Card
          label={T("Org progress")}
          value={summary.target ? `${Math.round((summary.achieved / summary.target) * 100)}%` : "—"}
          tone="amber"
        />
      </div>

      {/* New target row */}
      {isDirector && showNew && (
        <div className="card p-4 space-y-3">
          <div className="font-semibold text-sm">{T("New target for")}{" "}{period}</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-[11px] uppercase muted mb-0.5">{T("Salesperson")}</span>
              <select className="input" value={newUserId}
                onChange={(e) => setNewUserId(e.target.value)}>
                <option value="">{T("— pick someone —")}</option>
                {(employees.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="block text-[11px] uppercase muted mb-0.5">{T("Target (IDR)")}</span>
              <input type="number" min={0} step="any" className="input"
                value={newAmount}
                onChange={(e) => setNewAmount(parseFloat(e.target.value || "0"))} />
            </label>
            <label className="block">
              <span className="block text-[11px] uppercase muted mb-0.5">{T("Notes")}</span>
              <input className="input" value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)} placeholder={T("optional")} />
            </label>
          </div>
          {err && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => { setShowNew(false); setErr(null); }}>
              {T("Cancel")}</button>
            <button
              className="btn-primary"
              disabled={!newUserId || !newAmount || create.isPending}
              onClick={() => { setErr(null); create.mutate(); }}
            >
              {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {T("Save target")}</button>
          </div>
        </div>
      )}

      {/* Targets list */}
      <div className="space-y-3">
        {(targets.data ?? []).map((t) => {
          const pct = Math.min(100, t.progress_pct);
          const overshoot = t.progress_pct >= 100;
          const isEditing = editing === t.id;
          return (
            <div key={t.id} className="card p-4">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold">{t.user_name ?? "—"}</div>
                  <div className="text-xs muted">
                    {T("Target:")}{" "}<b className="tabular-nums">{idr(t.target_amount)}</b> {T("· Achieved:")}{" "}<b className="tabular-nums">{idr(t.achieved_amount)}</b> {T("· Remaining:")}{" "}<b className="tabular-nums">{idr(t.remaining)}</b>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={clsx(
                    "chip uppercase",
                    overshoot ? "bg-emerald-100 text-emerald-800"
                    : t.progress_pct >= 70 ? "bg-emerald-50 text-emerald-700"
                    : t.progress_pct >= 40 ? "bg-amber-50 text-amber-700"
                    : "bg-red-50 text-red-700"
                  )}>
                    {Math.round(t.progress_pct)}%
                  </span>
                  {isDirector && (
                    isEditing ? (
                      <>
                        <input type="number" className="input max-w-[160px]"
                          value={editAmount}
                          onChange={(e) => setEditAmount(parseFloat(e.target.value || "0"))} />
                        <button className="btn-success" onClick={() => update.mutate(t.id)}
                          disabled={update.isPending}>
                          <Save size={13} /> {T("Save")}</button>
                        <button className="btn-ghost" onClick={() => setEditing(null)}>
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="btn-ghost"
                          onClick={() => { setEditing(t.id); setEditAmount(t.target_amount); }}>
                          <Pencil size={13} />
                        </button>
                        <button className="btn-ghost text-red-600 hover:bg-red-50"
                          onClick={() => { if (window.confirm("Delete this target?")) del.mutate(t.id); }}>
                          <Trash2 size={13} />
                        </button>
                      </>
                    )
                  )}
                </div>
              </div>
              <div className="mt-3 h-2 rounded-full bg-ink-100 overflow-hidden">
                <div
                  className={clsx(
                    "h-full transition-all",
                    overshoot ? "bg-gradient-to-r from-emerald-500 to-emerald-300"
                    : t.progress_pct >= 70 ? "bg-emerald-500"
                    : t.progress_pct >= 40 ? "bg-amber-500"
                    : "bg-red-500"
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {t.notes && <div className="text-xs muted mt-2">{t.notes}</div>}
            </div>
          );
        })}
        {!targets.data?.length && (
          <div className="card p-12 text-center text-sm muted">
            {T("No targets set for")}{" "}{period}.
            {isDirector && (<>{" "}{T("Click")}{" "}<b>{T("+ Set target")}</b> {T("to add one.")}</>)}
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, tone }: {
  label: string; value: string; tone: "brand" | "amber" | "emerald";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    amber:   "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={`inline-block text-[11px] uppercase tracking-wider px-2 py-0.5 rounded ${cls}`}>
        {T(label)}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
