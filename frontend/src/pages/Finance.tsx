import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Banknote, LineChart, BarChart3, CheckCircle, FileText, Loader2, XCircle,
  Download, ReceiptText,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

const BUCKETS = [
  { key: "current", label: "Current",    color: "bg-emerald-500" },
  { key: "0-30",    label: "0–30 days",  color: "bg-amber-400" },
  { key: "31-60",   label: "31–60 days", color: "bg-orange-500" },
  { key: "61-90",   label: "61–90 days", color: "bg-red-500" },
  { key: "90+",     label: "90+ days",   color: "bg-red-700" },
];

export default function FinancePage() {
  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Banknote size={22} className="text-brand-600" /> Finance · AR Aging
          </h1>
          <p className="text-sm muted">Outstanding receivables grouped by days past due.</p>
        </div>
        <div className="flex gap-2">
          <Link to="/finance/reports" className="btn-ghost">
            <BarChart3 size={15} /> Financial reports
          </Link>
          <Link to="/finance/estimated" className="btn-ghost">
            <LineChart size={15} /> Estimated finance
          </Link>
        </div>
      </div>

      <EFakturExport />
      <PendingInvoiceApprovals />
      <PendingPaymentClaims />
      <ArAging />
    </div>
  );
}

function EFakturExport() {
  const now = new Date();
  const [period, setPeriod] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`,
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function download() {
    setBusy(true); setErr(null);
    try {
      const resp = await api.get("/finance/efaktur.csv", {
        params: { period }, responseType: "blob",
      });
      const url = URL.createObjectURL(new Blob([resp.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url; a.download = `efaktur-${period}.csv`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: any) {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-4 flex items-center gap-3 flex-wrap">
      <div className="flex-1 min-w-[220px]">
        <div className="font-semibold flex items-center gap-2">
          <ReceiptText size={15} className="text-brand-600" /> e-Faktur export
        </div>
        <div className="text-xs muted">
          Approved invoices with a faktur pajak number, as an e-Faktur import CSV for the chosen masa pajak.
        </div>
      </div>
      <input
        type="month"
        value={period}
        max={`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`}
        onChange={(e) => setPeriod(e.target.value)}
        className="input max-w-[170px]"
      />
      <button className="btn-primary" onClick={download} disabled={busy || !period}>
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        Export CSV
      </button>
      {err && <div className="w-full text-sm text-red-700">{err}</div>}
    </div>
  );
}

function PendingPaymentClaims() {
  // Complements the invoice-approval queue above with the second thing
  // finance actually has to do: verify customer payment claims. Landing
  // on /finance with zero-pending on both is what tells finance the desk
  // is clean. If claims are pending, one click jumps to the full
  // Payment verification page to act on them.
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const pending = useQuery({
    queryKey: ["pending-claims", "finance-dashboard"],
    queryFn: () => api
      .get("/payments/claims", { params: { status_eq: "pending" } })
      .then((r) => r.data as any[]),
  });
  const rows = pending.data ?? [];
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Banknote size={15} className="text-brand-600" /> Pending payment claims
          </div>
          <div className="text-xs muted">
            Customers submitted these payments — verify them to advance the
            project to paid/closed. Approving the invoice above isn't enough
            on its own; this is the actual money-in step.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="chip bg-amber-50 text-amber-700">{rows.length} pending</span>
          <Link to="/finance/payment-verification" className="btn-ghost text-xs">
            Open verification queue
          </Link>
        </div>
      </div>
      {pending.isLoading ? (
        <div className="p-6 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="p-6 text-center text-sm muted">
          No customer payments waiting for verification.
        </div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {rows.slice(0, 5).map((c: any) => (
            <li key={c.id} className="p-4 flex items-center justify-between gap-3 flex-wrap">
              <div className="text-sm">
                <span className="font-mono font-medium">{c.invoice_number ?? "—"}</span>
                <span className="muted"> · {c.customer_user_name ?? "—"}</span>
                {c.method && <span className="muted"> · {c.method}</span>}
                {c.reference && <span className="muted"> · ref {c.reference}</span>}
              </div>
              <div className="flex items-center gap-3">
                <div className="text-sm font-semibold tabular-nums">{idr(c.amount)}</div>
                <Link
                  to="/finance/payment-verification"
                  className="btn-primary text-xs"
                >
                  <CheckCircle size={12} /> Verify
                </Link>
              </div>
            </li>
          ))}
          {rows.length > 5 && (
            <li className="px-4 py-2 text-xs muted text-center">
              + {rows.length - 5} more claim(s) in the verification queue.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function PendingInvoiceApprovals() {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  // Only finance + director see the approval action. Manager/admin can view
  // the queue (read-only) so they know what's pending.
  const canApprove = role === "finance" || role === "director";
  const pending = useQuery({
    queryKey: ["pending-invoices"],
    queryFn: () => api.get("/finance/invoices/pending").then((r) => r.data as any[]),
  });
  const [forms, setForms] = useState<Record<string, {
    no: string; file?: File | null; reason?: string;
  }>>({});
  const [err, setErr] = useState<string | null>(null);

  const approve = useMutation({
    mutationFn: (body: { invoiceId: string; fpNo: string; fpFile?: File | null }) => {
      const fd = new FormData();
      fd.append("faktur_pajak_no", body.fpNo);
      if (body.fpFile) fd.append("faktur_pajak_file", body.fpFile);
      return api.post(`/finance/invoices/${body.invoiceId}/approve`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-invoices"] });
      qc.invalidateQueries({ queryKey: ["ar-aging"] });
      setErr(null);
    },
    onError: (e: any) => setErr(
      e?.response?.data?.detail ?? e?.response?.data?.errors?.[0]?.message
      ?? e?.message ?? "Approval failed",
    ),
  });

  const reject = useMutation({
    mutationFn: (body: { invoiceId: string; reason: string }) => {
      const fd = new FormData();
      fd.append("reason", body.reason);
      return api.post(`/finance/invoices/${body.invoiceId}/reject`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-invoices"] });
      setErr(null);
    },
    onError: (e: any) => setErr(
      e?.response?.data?.detail ?? e?.response?.data?.errors?.[0]?.message
      ?? e?.message ?? "Reject failed",
    ),
  });

  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const rows = pending.data ?? [];

  // The approvals queue is the headline thing this page should show — render
  // even an empty state so finance knows it's empty (not broken).
  const viewFile = async (url: string) => {
    try {
      const resp = await api.get(url.replace(/^\/api\/v1/, ""), { responseType: "blob" });
      const blob = URL.createObjectURL(resp.data as Blob);
      window.open(blob, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(blob), 60_000);
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "Could not open file");
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <FileText size={15} className="text-brand-600" /> Pending invoice approvals
          </div>
          <div className="text-xs muted">
            {canApprove
              ? "Enter the faktur pajak number (and optionally upload the FP file), then approve."
              : "Invoices waiting on finance to enter the faktur pajak and approve."}
          </div>
        </div>
        <span className="chip bg-amber-50 text-amber-700">{rows.length} pending</span>
      </div>

      {err && (
        <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {pending.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="p-8 text-center text-sm muted">No invoices waiting for finance approval.</div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {rows.map((iv: any) => {
            const f = forms[iv.id] ?? { no: "", file: null };
            return (
              <li key={iv.id} className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="text-sm">
                    <span className="font-mono font-medium">{iv.number}</span>
                    <span className="muted"> · {iv.customer_name ?? "—"}</span>
                    {iv.project_code && (
                      <Link to={`/projects/${iv.project_id}`} className="ml-2 text-brand-700 hover:underline font-mono text-xs">
                        {iv.project_code}
                      </Link>
                    )}
                  </div>
                  <div className="text-sm font-semibold tabular-nums">{idr(iv.total)}</div>
                </div>
                {(iv.files ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-2 text-xs">
                    {iv.files.map((file: any) => (
                      <button key={file.id} type="button"
                        className="text-brand-700 hover:underline inline-flex items-center gap-1"
                        onClick={() => viewFile(file.download_url)}>
                        <FileText size={11} /> {file.filename}
                      </button>
                    ))}
                  </div>
                )}
                {canApprove && (
                  <div className="space-y-2 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-[2fr_2fr_auto] gap-2 items-end">
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">Faktur pajak no. *</span>
                        <input className="input" value={f.no}
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, no: e.target.value } }))} />
                      </label>
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">FP file (optional)</span>
                        <input type="file"
                          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-ink-700 file:text-xs hover:file:bg-ink-200"
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, file: e.target.files?.[0] ?? null } }))} />
                      </label>
                      <button className="btn-primary"
                        disabled={!f.no.trim() || approve.isPending}
                        onClick={() => approve.mutate({ invoiceId: iv.id, fpNo: f.no.trim(), fpFile: f.file })}>
                        <CheckCircle size={14} /> Approve
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 items-end">
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">
                          Rejection reason (required if rejecting)
                        </span>
                        <input className="input" value={f.reason ?? ""}
                          placeholder="e.g. wrong amount, invoice PDF unreadable, missing DO…"
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, reason: e.target.value } }))} />
                      </label>
                      <button className="btn-ghost text-red-600 border border-red-200 hover:bg-red-50"
                        disabled={!(f.reason ?? "").trim() || reject.isPending}
                        onClick={() => {
                          if (!window.confirm(
                            `Reject ${iv.number}? Admin will need to re-issue with corrections.`,
                          )) return;
                          reject.mutate({ invoiceId: iv.id, reason: (f.reason ?? "").trim() });
                        }}>
                        <XCircle size={14} /> Reject
                      </button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ArAging() {
  const aging = useQuery({
    queryKey: ["ar-aging"],
    queryFn: () => api.get("/finance/ar/aging").then((r) => r.data),
  });
  const buckets = aging.data ?? {};
  const fmt = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);
  const total = BUCKETS.reduce((acc, b) => acc + (buckets[b.key] || 0), 0);

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="text-xs uppercase tracking-wider muted">Total outstanding</div>
        <div className="text-3xl font-semibold tabular-nums mt-1">{fmt(total)}</div>
        <div className="mt-4 flex h-3 rounded-full overflow-hidden border border-ink-100">
          {BUCKETS.map((b) => {
            const w = total ? ((buckets[b.key] || 0) / total) * 100 : 0;
            return (
              <div
                key={b.key}
                className={clsx("h-full", b.color)}
                style={{ width: `${w}%` }}
                title={`${b.label}: ${fmt(buckets[b.key] || 0)}`}
              />
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {BUCKETS.map((b) => (
          <div key={b.key} className="card p-4">
            <div className="flex items-center gap-2 text-xs muted">
              <span className={clsx("h-2 w-2 rounded-full", b.color)} />
              {b.label}
            </div>
            <div className="text-xl font-semibold tabular-nums mt-1">
              {fmt(buckets[b.key] || 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
