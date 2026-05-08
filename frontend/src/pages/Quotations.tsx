import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Plus, FileText, Send } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { NewQuotationForm } from "@/components/forms/NewQuotationForm";
import type { Quotation } from "@/types";

const STATUS: Record<string, string> = {
  draft:             "bg-ink-100 text-ink-700",
  pending_approval:  "bg-amber-50 text-amber-700",
  approved:          "bg-emerald-50 text-emerald-700",
  rejected:          "bg-red-50 text-red-700",
  sent:              "bg-blue-50 text-blue-700",
  won:               "bg-emerald-100 text-emerald-800",
  lost:              "bg-red-100 text-red-800",
};

export default function QuotationsPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [openNew, setOpenNew] = useState(false);

  const q = useQuery({
    queryKey: ["quotations"],
    queryFn: () => api.get("/quotations").then((r) => r.data as Quotation[]),
  });
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

  const submit = useMutation({
    mutationFn: (id: string) => api.post(`/quotations/${id}/submit`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quotations"] }),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Quotations</h1>
          <p className="text-sm muted">Price offers across every stage.</p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={15} /> New quotation
        </button>
      </div>

      <div className="table-shell">
        <table className="w-full">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Number</th>
              <th className="th">Variant</th>
              <th className="th">Status</th>
              <th className="th text-right">Discount</th>
              <th className="th text-right">Total</th>
              <th className="th text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((qt) => (
              <tr
                key={qt.id}
                className="tr-hover border-t border-ink-100 cursor-pointer"
                onClick={() => nav(`/quotations/${qt.id}`)}
              >
                <td className="td">
                  <div className="flex items-center gap-2">
                    <FileText size={14} className="text-ink-400" />
                    <Link
                      to={`/quotations/${qt.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="font-mono text-xs text-brand-700 hover:underline"
                    >
                      {qt.number}
                    </Link>
                  </div>
                </td>
                <td className="td capitalize muted">{qt.variant}</td>
                <td className="td">
                  <span className={clsx("chip", STATUS[qt.status] ?? "bg-ink-100 text-ink-600")}>
                    {qt.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{qt.discount_pct}%</td>
                <td className="td text-right font-medium tabular-nums">{idr(qt.total)}</td>
                <td className="td text-right">
                  {qt.status === "draft" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); submit.mutate(qt.id); }}
                      className="btn-ghost text-brand-700"
                      disabled={submit.isPending}
                    >
                      <Send size={13} /> Submit
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!q.data?.length && (
              <tr>
                <td colSpan={6} className="td text-center muted py-12">
                  No quotations yet — create your first one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Modal
        open={openNew}
        onClose={() => setOpenNew(false)}
        title="New quotation"
        subtitle="Pick a customer, add line items, set discount. Discount tier is auto-detected."
        size="xl"
      >
        <NewQuotationForm onClose={() => setOpenNew(false)} />
      </Modal>
    </div>
  );
}
