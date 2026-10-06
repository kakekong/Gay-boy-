import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ArrowRight, Info } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, t as tt, useLangStore } from "@/store/lang";

/**
 * Does the rest of this deal still say what this document says?
 *
 * One deal is written down several times: price request, quotation, customer
 * PO, and on the buy side the supplier requests and POs. This card compares
 * them (server: `services/order_consistency.py`), shows each line and field
 * that disagrees, and offers the fix in either direction. The fix follows the
 * same rules as editing that document by hand, so a change to an approved
 * quotation by anyone but the director goes to the director.
 */

type Where = {
  price_request_id?: string; quotation_id?: string;
  customer_po_id?: string; project_id?: string;
};
interface DocRef { kind: string; id: string | null; number: string; status?: string | null;
  docs?: DocRef[] }
interface Field { field: string; left: any; right: any }
interface Line { line_no: number | null; change: string; description: string | null; fields?: Field[] }
interface Action { id: string; label: string; label_id: string; allowed: boolean;
  reason: string | null; how: string }
interface Check { key: string; left: DocRef; right: DocRef; lines: Line[]; actions: Action[];
  info_only?: boolean; partial?: boolean }
interface Report { documents: Record<string, any>; checks: Check[]; issues: number }

const KIND: Record<string, [string, string]> = {
  price_request: ["Price request", "Permintaan harga"],
  quotation: ["Quotation", "Penawaran"],
  customer_po: ["Customer PO", "PO pelanggan"],
  supplier_price_request: ["Supplier request", "Permintaan ke supplier"],
  supplier_po: ["Supplier PO", "PO supplier"],
  supplier_pos: ["Supplier POs", "PO supplier"],
};
const FIELD: Record<string, [string, string]> = {
  description: ["Description", "Deskripsi"], qty: ["Qty", "Qty"],
  uom: ["Unit", "Satuan"], price: ["Price", "Harga"],
};

function linkOf(d: DocRef): string | null {
  if (!d.id) return null;
  switch (d.kind) {
    case "price_request": return `/price-requests?open=${d.id}`;
    case "quotation": return `/quotations/${d.id}`;
    case "customer_po": return `/customer-pos/${d.id}`;
    case "supplier_price_request": return `/purchasing/price-requests/${d.id}`;
    case "supplier_po": return `/purchase-orders/${d.id}`;
    default: return null;
  }
}

function DocName({ d }: { d: DocRef }) {
  const t = useT();
  const k = KIND[d.kind];
  const href = linkOf(d);
  const label = <>{k ? t(k[0], k[1]) : d.kind} <span className="font-mono">{d.number}</span></>;
  return href ? <Link to={href} className="text-brand-700 hover:underline">{label}</Link> : <span>{label}</span>;
}

function fmt(field: string, v: any): string {
  if (v == null || v === "") return "—";
  if (field === "price") return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(Number(v)));
  if (field === "qty") return new Intl.NumberFormat("id-ID").format(Number(v));
  return String(v);
}

export function DealCheck({ where, compact = false }: { where: Where; compact?: boolean }) {
  const t = useT();
  const id = useLangStore((s) => s.lang) === "id";
  const qc = useQueryClient();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const key = ["consistency", where];
  const rep = useQuery({
    queryKey: key,
    queryFn: () => api.get("/consistency", { params: where }).then((r) => r.data as Report),
    retry: false,
  });
  const fix = useMutation({
    mutationFn: (b: { check: string; action: string }) =>
      api.post("/consistency/fix", { ...where, ...b }).then((r) => r.data),
    onSuccess: (data) => {
      setMsg({ ok: true, text: data.message });
      // A fix moves other documents than this one; refresh whatever is open.
      qc.invalidateQueries();
    },
    onError: (e: any) => setMsg({ ok: false, text: e?.response?.data?.detail ?? tt("Couldn't apply that.", "Gagal diterapkan.") }),
  });

  const r = rep.data;
  if (!r) return null;
  const docs = r.documents ?? {};
  const named: DocRef[] = [docs.price_request, docs.quotation, ...(docs.customer_pos ?? []),
    ...(docs.supplier_requests ?? []), ...(docs.supplier_pos ?? [])].filter(Boolean);
  // Nothing else to compare against — a quotation with no request and no PO.
  if (named.length < 2 && !r.checks.length) return null;

  const problems = r.checks.filter((c) => c.lines.length > 0);

  if (!problems.length) {
    if (compact) return null;
    return (
      <div className="card px-4 py-2.5 flex items-center gap-2 flex-wrap text-sm">
        <CheckCircle2 size={15} className="text-emerald-600 shrink-0" />
        <span className="text-emerald-700 font-medium">{t("This deal's documents agree", "Dokumen kesepakatan ini sudah sama")}</span>
        <span className="text-xs muted inline-flex items-center gap-1.5 flex-wrap">
          {named.map((d, i) => <span key={`${d.kind}-${d.id ?? i}`}><DocName d={d} /></span>)}
        </span>
        {msg && <span className={clsx("text-xs ml-auto", msg.ok ? "text-emerald-700" : "text-red-700")}>{msg.text}</span>}
      </div>
    );
  }

  return (
    <div className="card overflow-hidden border-amber-300">
      <div className="px-4 py-3 border-b border-amber-200 bg-amber-50/70 flex items-start gap-2">
        <AlertTriangle size={16} className="text-amber-600 mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="font-semibold text-amber-900">
            {r.issues} {t("difference(s) between this deal's documents", "perbedaan antar dokumen kesepakatan ini")}
          </div>
          <div className="text-xs text-amber-800">
            {t("Pick which side is right — the other is changed to match. A change to an approved quotation goes to the director.",
               "Pilih sisi yang benar — sisi lainnya disamakan. Perubahan pada penawaran yang sudah disetujui dikirim ke direktur.")}
          </div>
        </div>
      </div>
      {msg && (
        <div className={clsx("px-4 py-2 text-sm border-b", msg.ok
          ? "bg-emerald-50 text-emerald-800 border-emerald-100" : "bg-red-50 text-red-800 border-red-100")}>
          {msg.text}
        </div>
      )}
      <div className="divide-y divide-ink-100">
        {problems.map((c) => (
          <div key={c.key} className="p-4 space-y-2">
            <div className="text-sm flex items-center gap-2 flex-wrap">
              <DocName d={c.left} /> <ArrowRight size={13} className="text-ink-400" />
              {c.right.docs ? c.right.docs.map((d) => <DocName key={d.id} d={d} />) : <DocName d={c.right} />}
              {c.partial && (
                <span className="chip bg-ink-100 text-ink-600 text-[10px]"
                  title={tt("The customer ordered in parts, so quantities are not compared line by line.",
                            "Pelanggan memesan bertahap, jadi qty tidak dibandingkan per baris.")}>
                  {t("partial order", "pesanan sebagian")}
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wider muted">
                    <th className="text-left font-medium py-1 pr-3">#</th>
                    <th className="text-left font-medium py-1 pr-3">{t("Item", "Item")}</th>
                    <th className="text-left font-medium py-1 pr-3">{t("Field", "Kolom")}</th>
                    <th className="text-left font-medium py-1 pr-3 font-mono normal-case">{c.left.number}</th>
                    <th className="text-left font-medium py-1 font-mono normal-case">{c.right.docs ? t("ordered", "dipesan") : c.right.number}</th>
                  </tr>
                </thead>
                <tbody>
                  {c.lines.map((l, i) => l.change === "differs" ? (
                    (l.fields ?? []).map((f, j) => (
                      <tr key={`${i}-${j}`} className="border-t border-ink-50 align-top">
                        <td className="py-1 pr-3 tabular-nums muted">{j === 0 ? (l.line_no ?? "—") : ""}</td>
                        <td className="py-1 pr-3 max-w-[260px]">{j === 0 ? l.description : ""}</td>
                        <td className="py-1 pr-3 muted">{FIELD[f.field] ? t(FIELD[f.field][0], FIELD[f.field][1]) : f.field}</td>
                        <td className="py-1 pr-3 tabular-nums">{fmt(f.field, f.left)}</td>
                        <td className="py-1 tabular-nums font-semibold text-amber-800">{fmt(f.field, f.right)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr key={i} className="border-t border-ink-50">
                      <td className="py-1 pr-3 tabular-nums muted">{l.line_no ?? "—"}</td>
                      <td className="py-1 pr-3">{l.description}</td>
                      <td className="py-1 muted" colSpan={3}>
                        {l.change === "only_left"
                          ? t(`only on ${c.left.number}`, `hanya di ${c.left.number}`)
                          : t(`only on ${c.right.number}`, `hanya di ${c.right.number}`)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {c.info_only ? (
              <div className="text-xs muted flex items-start gap-1.5">
                <Info size={12} className="mt-0.5 shrink-0" />
                {t("A placed order is changed with the supplier — open the PO to adjust it.",
                   "Pesanan yang sudah dikirim diubah bersama supplier — buka PO untuk menyesuaikan.")}
              </div>
            ) : (
              <div className="flex items-center gap-2 flex-wrap pt-1">
                {c.actions.map((a) => (
                  <span key={a.id} className="inline-flex flex-col">
                    <button className={a.id === "use_left" ? "btn-primary" : "btn-ghost border border-ink-200"}
                      disabled={!a.allowed || fix.isPending}
                      title={a.reason ?? undefined}
                      onClick={() => {
                        const label = id ? a.label_id : a.label;
                        const extra = a.how === "approval"
                          ? tt(" It will be sent to the director for approval.", " Ini akan dikirim ke direktur untuk disetujui.")
                          : "";
                        if (window.confirm(`${label}?${extra}`)) {
                          setMsg(null);
                          fix.mutate({ check: c.key, action: a.id });
                        }
                      }}>
                      {id ? a.label_id : a.label}
                      {a.how === "approval" && a.allowed && (
                        <span className="text-[10px] opacity-80 ml-1">{t("(director approves)", "(disetujui direktur)")}</span>
                      )}
                    </button>
                    {!a.allowed && a.reason && <span className="text-[11px] muted mt-0.5 max-w-[320px]">{a.reason}</span>}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
