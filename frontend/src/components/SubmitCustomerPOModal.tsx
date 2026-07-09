import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, AlertCircle, Upload, Paperclip,
} from "lucide-react";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

interface WonQuoteLite {
  id: string;
  number: string;
  total: number;
}

interface DraftItem {
  description: string;
  qty: number;
  unit_price: number;
  uom?: string;
  selected: boolean;
}

interface Props {
  customerId: string;
  /** If set, this quotation is pre-picked and its items pre-loaded. */
  preselectQuotationId?: string;
  onClose: () => void;
  onCreated?: () => void;
}

/**
 * Customer PO submission. Three required pieces of info before this can
 * fire:
 *   1. A won quotation it's against.
 *   2. The PO number from the customer's paper PO.
 *   3. A copy of that PO file uploaded as an attachment.
 *
 * The flow is two requests under the hood: POST /customer-pos to file
 * the PO record (returns its id), then POST /attachments wiring the
 * uploaded file to the new PO so the director can open it from the
 * approvals queue. Both succeed before the modal closes.
 */
export function SubmitCustomerPOModal({
  customerId, preselectQuotationId, onClose, onCreated,
}: Props) {
  const t = useT();
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);

  const wonQuotes = useQuery({
    queryKey: ["customer-won-quotes", customerId],
    queryFn: () => api.get(`/customers/${customerId}/summary`)
      .then((r) => {
        const all = (r.data?.quotations ?? []) as Array<{
          id: string; number: string; status: string; total: number;
        }>;
        return all
          .filter((x) => x.status === "won")
          .map<WonQuoteLite>((x) => ({ id: x.id, number: x.number, total: x.total }));
      }),
  });

  const [quotationId, setQuotationId] = useState<string>(preselectQuotationId ?? "");
  const [poNumber, setPoNumber] = useState("");
  const [poDate, setPoDate] = useState(today);
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [isDp, setIsDp] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function loadQuotation(qid: string) {
    setQuotationId(qid);
    setItems([]);
    if (!qid) return;
    try {
      const res = await api.get(`/quotations/${qid}`);
      const rawItems = res.data?.items ?? [];
      setItems(rawItems.map((it: any) => ({
        description: it.description ?? "",
        qty: Number(it.qty ?? 1),
        unit_price: Number(it.unit_price ?? 0),
        uom: it.uom ?? undefined,
        selected: true,
      })));
    } catch {
      setErr("Couldn't fetch the quotation's items. Try picking it again.");
    }
  }

  // Auto-load items if a quotation was preselected on mount.
  useEffect(() => {
    if (preselectQuotationId) {
      loadQuotation(preselectQuotationId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = useMutation({
    mutationFn: async () => {
      // 1. Create the PO record.
      const poRes = await api.post("/customer-pos", {
        customer_id: customerId,
        quotation_id: quotationId,
        number: poNumber.trim(),
        po_date: poDate || null,
        items: items
          .filter((it) => it.selected && it.description.trim())
          .map((it) => ({
            description: it.description.trim(),
            qty: Number(it.qty || 0),
            unit_price: Number(it.unit_price || 0),
            uom: it.uom ?? null,
          })),
        notes: notes || null,
        is_downpayment: isDp,
      });
      const poId = poRes.data.id as string;
      // 2. Upload the PO file, scoped to the new PO record so the
      //    director can open it from the approvals queue and so the
      //    file lives alongside the PO on the customer page.
      if (file) {
        const form = new FormData();
        form.append("file", file);
        form.append("owner_type", "customer_po");
        form.append("owner_id", poId);
        form.append("description", "Customer PO document");
        try {
          await api.post("/attachments", form, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch (uploadErr: any) {
          // The PO exists — surface the upload error so the user can
          // either re-upload or accept that the file's missing.
          throw new Error(
            "Customer PO was filed, but the file upload failed: "
            + (uploadErr?.response?.data?.detail
                ?? uploadErr?.message
                ?? "unknown error")
            + ". Open the PO row to attach the file manually."
          );
        }
      }
      return poRes.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos", customerId] });
      qc.invalidateQueries({ queryKey: ["quotation", quotationId] });
      onCreated?.();
      onClose();
    },
    onError: (e: any) => {
      setErr(
        e?.message
          ?? e?.response?.data?.errors?.[0]?.message
          ?? e?.response?.data?.detail
          ?? "Failed to submit customer PO"
      );
    },
  });

  function submit() {
    setErr(null);
    if (!quotationId) {
      setErr("Pick the won quotation this PO is against — every customer PO must link to a quote.");
      return;
    }
    if (!poNumber.trim()) {
      setErr("Type the customer's PO number.");
      return;
    }
    if (!file) {
      setErr("Attach the customer's PO file. The director approves the PO based on the actual document.");
      return;
    }
    if (!items.some((it) => it.selected && it.description.trim())) {
      setErr("Pick at least one line item the customer ordered.");
      return;
    }
    create.mutate();
  }

  const total = items
    .filter((it) => it.selected)
    .reduce((s, it) => s + Number(it.qty || 0) * Number(it.unit_price || 0), 0);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">Submit customer PO</h2>
          <p className="text-sm muted mt-0.5">
            File the PO the customer sent you, attach the actual PO document,
            and pick the line items they ordered. The director approves the
            submission and the project is created automatically on approval.
          </p>
        </header>
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {/* Quotation picker (required) */}
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">
              Against quotation <span className="text-red-500">*</span>
            </span>
            <select
              className="input"
              value={quotationId}
              disabled={!!preselectQuotationId}
              onChange={(e) => loadQuotation(e.target.value)}
            >
              <option value="">— pick a Won quotation —</option>
              {(wonQuotes.data ?? []).map((qx) => (
                <option key={qx.id} value={qx.id}>
                  {qx.number} · {idr(qx.total)}
                </option>
              ))}
            </select>
            <span className="block text-[11px] text-ink-500 mt-1">
              Only Won quotations can have a customer PO. Picking one fills
              its line items below; untick the ones the customer didn't
              actually order in this PO.
            </span>
          </label>

          {/* Down-payment toggle */}
          <div className="rounded-xl border border-ink-200 bg-ink-50/40 p-3">
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isDp}
                onChange={(e) => setIsDp(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span className="block text-sm font-medium">
                  This PO is a down payment (DP)
                </span>
                <span className="block text-[11px] muted mt-0.5">
                  DP POs route to finance first (they issue the DP invoice and
                  verify the deposit landed). Once finance approves, you'll get
                  notified to confirm the deposit has cleared — that's what
                  spawns the project. Leave unchecked for a regular PO that goes
                  straight to the director.
                </span>
              </span>
            </label>
          </div>

          {/* PO number + date */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                PO number <span className="text-red-500">*</span>
              </span>
              <input
                className="input font-mono"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                placeholder="Whatever number the customer printed on the PO"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-600 mb-1">
                PO date
              </span>
              <input
                type="date"
                className="input"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
              />
            </label>
          </div>

          {/* PO file (required) */}
          <div>
            <span className="block text-xs font-medium text-ink-600 mb-1">
              PO file <span className="text-red-500">*</span>
            </span>
            <label
              className={
                "flex items-center gap-3 rounded-xl border-2 border-dashed px-4 py-3 cursor-pointer transition-colors "
                + (file
                  ? "border-emerald-300 bg-emerald-50/50"
                  : "border-ink-200 bg-ink-50/40 hover:border-brand-300")
              }
            >
              <input
                type="file"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <Paperclip size={18} className="text-emerald-700 shrink-0" />
              ) : (
                <Upload size={18} className="text-ink-500 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">
                  {file ? file.name : "Click to pick the customer's PO file"}
                </div>
                <div className="text-[11px] muted">
                  {file
                    ? `${(file.size / 1024).toFixed(1)} KB · ready to upload`
                    : "PDF, image, doc — max 20 MB"}
                </div>
              </div>
              <span className="text-xs font-semibold text-brand-700">
                {file ? "Change" : "Browse"}
              </span>
            </label>
          </div>

          {/* Items */}
          <div className="card overflow-hidden">
            <div className="px-3 py-2 border-b border-ink-100 bg-ink-50/60 text-xs font-semibold flex justify-between items-center">
              <span>Items ({items.filter((it) => it.selected).length} of {items.length} selected)</span>
              {quotationId && (
                <button
                  type="button"
                  className="text-brand-700 hover:underline"
                  onClick={() => loadQuotation(quotationId)}
                >
                  Reset to quotation
                </button>
              )}
            </div>
            {items.length === 0 ? (
              <div className="p-6 text-center text-sm muted">
                {quotationId
                  ? "This quotation has no line items."
                  : "Pick a quotation above to load its items."}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-[10px] uppercase muted">
                  <tr>
                    <th className="px-2 py-1 w-8"></th>
                    <th className="text-left px-2 py-1">Description</th>
                    <th className="text-right px-2 py-1 w-20">Qty</th>
                    <th className="text-right px-2 py-1 w-32">Unit price</th>
                    <th className="text-right px-2 py-1 w-32">Line total</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it, i) => (
                    <tr key={i} className="border-t border-ink-100">
                      <td className="px-2 py-1 text-center">
                        <input
                          type="checkbox"
                          checked={it.selected}
                          onChange={(e) => setItems((cur) => cur.map(
                            (x, j) => j === i ? { ...x, selected: e.target.checked } : x,
                          ))}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          className="input py-1"
                          value={it.description}
                          disabled={!it.selected}
                          onChange={(e) => setItems((cur) => cur.map(
                            (x, j) => j === i ? { ...x, description: e.target.value } : x,
                          ))}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          type="number"
                          min={0}
                          step="any"
                          className="input py-1 text-right"
                          value={it.qty}
                          disabled={!it.selected}
                          onChange={(e) => setItems((cur) => cur.map(
                            (x, j) => j === i ? { ...x, qty: parseFloat(e.target.value || "0") } : x,
                          ))}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          type="number"
                          min={0}
                          step="any"
                          className="input py-1 text-right"
                          value={it.unit_price}
                          disabled={!it.selected}
                          onChange={(e) => setItems((cur) => cur.map(
                            (x, j) => j === i ? { ...x, unit_price: parseFloat(e.target.value || "0") } : x,
                          ))}
                        />
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums muted">
                        {it.selected ? idr(it.qty * it.unit_price) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-ink-100 bg-ink-50/40">
                    <td colSpan={4} className="px-2 py-1 text-right font-semibold">PO total</td>
                    <td className="px-2 py-1 text-right font-semibold tabular-nums">
                      {idr(total)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            )}
          </div>

          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Notes</span>
            <textarea
              className="input min-h-[60px]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Special instructions, exclusions, delivery terms…"
            />
          </label>

          {err && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{err}</span>
            </div>
          )}
        </div>
        <footer className="px-5 py-3 border-t border-ink-100 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn-primary"
            onClick={submit}
            disabled={create.isPending}
          >
            {create.isPending
              ? <Loader2 size={14} className="animate-spin" />
              : <CheckCircle2 size={14} />}
            {isDp ? "Submit for finance approval" : "Submit for director approval"}
          </button>
        </footer>
      </div>
    </div>
  );
}
