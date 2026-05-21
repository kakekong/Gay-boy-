import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus, Wallet, BookOpen, Undo2, CheckCircle, Trash2, Loader2, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { NewSalaryForm } from "@/components/forms/NewSalaryForm";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  draft:  "bg-ink-100 text-ink-700",
  posted: "bg-amber-50 text-amber-700",
  paid:   "bg-emerald-50 text-emerald-700",
};

export default function SalaryPage() {
  const qc = useQueryClient();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [openNew, setOpenNew] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);

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
            <Wallet size={22} className="text-brand-600" /> Salary
          </h1>
          <p className="text-sm muted">
            Monthly payroll. Posting to ledger auto-updates Beban Gaji, Hutang Gaji, and Hutang PPh 21.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            className="input max-w-[180px]"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
          <button className="btn-primary" onClick={() => { setEditing(null); setOpenNew(true); }}>
            <Plus size={14} /> New salary
          </button>
        </div>
      </div>

      {/* Period summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card label="Employees paid" value={String(totals.count)} tone="brand" />
        <Card label="Gross"      value={idr(totals.gross)} tone="brand" />
        <Card label="PPh 21 withheld" value={idr(totals.tax)}   tone="amber" />
        <Card label="Net paid"   value={idr(totals.net)}   tone="emerald" />
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Employee</th>
              <th className="th">Period</th>
              <th className="th">Status</th>
              <th className="th text-right">Gross</th>
              <th className="th text-right">PPh 21</th>
              <th className="th text-right">Net</th>
              <th className="th text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(salaries.data ?? []).map((s) => (
              <tr key={s.id} className="tr-hover border-t border-ink-100">
                <td className="td font-medium">{s.user_name ?? "—"}</td>
                <td className="td muted">{s.period}</td>
                <td className="td">
                  <span className={clsx("chip uppercase", STATUS_CHIP[s.status] ?? "bg-ink-100")}>
                    {s.status}
                  </span>
                  {s.is_posted && (
                    <span className="ml-2 chip bg-brand-50 text-brand-700">posted</span>
                  )}
                </td>
                <td className="td text-right tabular-nums">{idr(s.gross_salary)}</td>
                <td className="td text-right tabular-nums">{idr(s.pph21)}</td>
                <td className="td text-right tabular-nums font-semibold">{idr(s.net_pay)}</td>
                <td className="td text-right">
                  <div className="inline-flex gap-1">
                    {s.status === "draft" && (
                      <>
                        <button className="btn-ghost text-brand-700"
                          onClick={() => { setEditing(s); setOpenNew(true); }}>
                          Edit
                        </button>
                        <button className="btn-success"
                          disabled={post.isPending}
                          onClick={() => post.mutate(s.id)}>
                          <BookOpen size={13} /> Post
                        </button>
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
                          <CheckCircle size={13} /> Mark paid
                        </button>
                        <button className="btn-ghost text-red-600"
                          disabled={reverse.isPending}
                          onClick={() => {
                            if (window.confirm("Reverse the posting?")) reverse.mutate(s.id);
                          }}>
                          <Undo2 size={13} /> Reverse
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!salaries.data?.length && (
              <tr>
                <td colSpan={7} className="td text-center muted py-12">
                  No salary records for {period}. Click "+ New salary" to create one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card p-4 flex items-start gap-3 text-sm">
        <AlertCircle size={18} className="text-amber-600 shrink-0 mt-0.5" />
        <div>
          <div className="font-medium">How posting works</div>
          <p className="muted">
            "Post to ledger" adds the gross salary to <b>6000-04 Beban Gaji Karyawan</b>,
            credits PPh 21 to <b>2102-04 Hutang Pph 21</b>, and credits the net amount to{" "}
            <b>2102-02 Hutang Gaji Karyawan</b>. "Mark paid" clears the salary liability
            and reduces the bank account (default <b>1101-01 Bank BCA</b>).
            "Reverse" rolls back the posting (only available before payment).
          </p>
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
        <div className="text-[11px] uppercase tracking-wider muted">{label}</div>
        <div className={`h-7 w-7 rounded ${cls} grid place-items-center`}>
          <Wallet size={13} />
        </div>
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
