import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";

interface Employee { id: string; full_name: string; role: string; }

interface Props {
  initial?: any;             // when set → edit mode
  onClose: () => void;
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export function NewSalaryForm({ initial, onClose }: Props) {
  const qc = useQueryClient();
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

  const totals = useMemo(() => {
    const n = (k: keyof typeof form) => Number(form[k]) || 0;
    const gross = n("base_salary") + n("transport") + n("meal") + n("bonus")
                + n("thr") + n("other_allowance");
    const ded = n("pph21") + n("bpjs") + n("other_deduction");
    return { gross, deductions: ded, net: gross - ded };
  }, [form]);

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
      <span className="block text-[11px] uppercase muted mb-0.5">{label}</span>
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
          <span className="block text-[11px] uppercase muted mb-0.5">Employee *</span>
          <select
            className="input" required disabled={editing}
            value={form.user_id}
            onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          >
            <option value="">— select employee —</option>
            {(employees.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="block text-[11px] uppercase muted mb-0.5">Period (YYYY-MM)</span>
          <input
            type="month" className="input" required disabled={editing}
            value={form.period}
            onChange={(e) => setForm({ ...form, period: e.target.value })}
          />
        </label>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">Earnings</div>
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
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">Deductions</div>
        <div className="grid grid-cols-3 gap-3">
          {num("pph21",           "PPh 21")}
          {num("bpjs",            "BPJS")}
          {num("other_deduction", "Other deduction")}
        </div>
      </div>

      <label className="block">
        <span className="block text-[11px] uppercase muted mb-0.5">Notes</span>
        <textarea
          className="input min-h-[60px]"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
      </label>

      <div className="card p-4 grid grid-cols-3 gap-3 text-sm">
        <Stat label="Gross" value={idr(totals.gross)} tone="brand" />
        <Stat label="Deductions" value={`− ${idr(totals.deductions)}`} tone="red" />
        <Stat label="Net pay" value={idr(totals.net)} tone="emerald" big />
      </div>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          {editing ? "Save changes" : "Create salary"}
        </button>
      </div>
    </form>
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
      <div className="text-[10px] uppercase tracking-wider">{label}</div>
      <div className={`tabular-nums font-semibold ${big ? "text-xl" : "text-base"}`}>{value}</div>
    </div>
  );
}
