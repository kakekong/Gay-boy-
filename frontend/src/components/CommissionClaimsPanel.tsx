import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgePercent, Check, Loader2, Pencil, Wallet, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { money } from "@/lib/money";
import { useAuthStore } from "@/store/auth";
import { t } from "@/store/lang";

interface Claim {
  id: string; status: "pending" | "approved" | "rejected" | "paid";
  project_code: string | null; beneficiary_name: string | null; claimed_by_name: string | null;
  rate_pct: number; basis_amount: number; amount: number;
  invoiced_basis?: number | null; basis_adjusted?: boolean;
  basis_note?: string | null; basis_set_by_name?: string | null;
  created_at?: string; decided_at?: string | null; paid_at?: string | null;
  decision_notes?: string | null; notes?: string | null;
}

const errText = (e: any, fb: string) =>
  e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? fb;
/** A typed amount: "7.000.000" and "7,000,000" (thousands), "7000000.5" and
 *  "7.000.000,5" (decimals) all read the way they're meant. */
const num = (raw: string) => {
  let s = String(raw).trim().replace(/\s|Rp/gi, "");
  if (s.includes(",") && s.includes(".")) {
    s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  } else if (/^\d{1,3}([.,]\d{3})+$/.test(s)) {
    s = s.replace(/[.,]/g, "");
  } else {
    s = s.replace(",", ".");
  }
  return Number(s);
};

/**
 * Commission claims — finance's queue.
 *
 * A rep claims commission on a job the customer has paid in full; the claim
 * lands here. Finance approves it — on the invoiced figure, or on the real
 * selling price when the customer asked for a higher figure on paper than the
 * company keeps (with the reason, which the rep sees) — and marks it paid,
 * picking the account it went out of, which books it: Beban Komisi Penjualan
 * Sales against that account. The director may also settle a different rate,
 * and correct the real price on an approved claim until it is paid.
 */
export function CommissionClaimsPanel() {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const isDirector = role === "director";
  const claims = useQuery({
    queryKey: ["commission-claims-finance"],
    queryFn: () => api.get("/commissions").then((r) => r.data as Claim[]),
  });
  const [paying, setPaying] = useState<string | null>(null);
  const [cashNo, setCashNo] = useState("1101-01");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [rate, setRate] = useState<Record<string, string>>({});
  // The real selling price and its reason, per claim, while it is decided
  // (pending) or corrected by the director (approved).
  const [real, setReal] = useState<Record<string, string>>({});
  const [why, setWhy] = useState<Record<string, string>>({});
  const [correcting, setCorrecting] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const done = (text: string) => {
    setMsg({ kind: "ok", text });
    qc.invalidateQueries({ queryKey: ["commission-claims-finance"] });
    qc.invalidateQueries({ queryKey: ["nav-badges"] });
  };
  const invoicedOf = (c: Claim) => Number(c.invoiced_basis ?? c.basis_amount ?? 0);
  const realOf = (c: Claim) => (real[c.id] ?? "").trim() === "" ? null : num(real[c.id]);
  const lowered = (c: Claim) => {
    const r = realOf(c);
    return r != null && Math.abs(r - invoicedOf(c)) > 0.005;
  };

  const approve = useMutation({
    mutationFn: (c: Claim) => api.post(`/commissions/${c.id}/approve`, {
      rate_pct: rate[c.id] ? Number(rate[c.id]) : null,
      basis_amount: lowered(c) ? realOf(c) : null,
      basis_note: lowered(c) ? (why[c.id] ?? "").trim() || null : null,
    }),
    onSuccess: () => done(t("Approved — ready to pay.", "Disetujui — siap dibayar.")),
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't approve it.", "Gagal menyetujui.")) }),
  });
  const correct = useMutation({
    mutationFn: (c: Claim) => api.post(`/commissions/${c.id}/basis`, {
      basis_amount: realOf(c) ?? invoicedOf(c), basis_note: (why[c.id] ?? "").trim() || null,
    }),
    onSuccess: () => { setCorrecting(null); done(t("Real selling price corrected.", "Harga jual sebenarnya dikoreksi.")); },
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't correct it.", "Gagal mengoreksi.")) }),
  });
  const reject = useMutation({
    mutationFn: (v: { id: string; notes: string }) => api.post(`/commissions/${v.id}/reject`, { notes: v.notes }),
    onSuccess: () => done(t("Rejected.", "Ditolak.")),
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't reject it.", "Gagal menolak.")) }),
  });
  const pay = useMutation({
    mutationFn: (id: string) => api.post(`/commissions/${id}/mark-paid`, { cash_account_no: cashNo, paid_on: paidOn })
      .then((r) => r.data),
    onSuccess: (d: any) => {
      setPaying(null);
      done(t(`Paid and booked${d?.journal_number ? ` as ${d.journal_number}` : ""}.`,
             `Dibayar dan dicatat${d?.journal_number ? ` sebagai ${d.journal_number}` : ""}.`));
    },
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't mark it paid.", "Gagal menandai dibayar.")) }),
  });

  const rows = claims.data ?? [];
  const open = rows.filter((c) => c.status === "pending" || c.status === "approved");
  const recent = rows.filter((c) => c.status === "paid").slice(0, 5);
  const due = open.reduce((s, c) => s + Number(c.amount || 0), 0);

  // What the commission comes to with the figures on screen.
  const preview = (c: Claim) => {
    const basis = realOf(c) ?? invoicedOf(c);
    const r = rate[c.id] ? Number(rate[c.id]) : c.rate_pct;
    return Math.round(basis * r) / 100;
  };

  function tryApprove(c: Claim) {
    setMsg(null);
    const r = realOf(c);
    if (r != null && lowered(c)) {
      if (!(r > 0)) return setMsg({ kind: "err", text: t("The real selling price must be more than zero.", "Harga jual sebenarnya harus lebih dari nol.") });
      if (r > invoicedOf(c)) return setMsg({ kind: "err", text: t("The real selling price can't be more than was invoiced.", "Harga jual sebenarnya tidak boleh lebih dari nilai faktur.") });
      if (!(why[c.id] ?? "").trim()) return setMsg({ kind: "err", text: t("Say why the real price is lower — the rep sees it.", "Tulis alasan harga sebenarnya lebih rendah — sales akan melihatnya.") });
    }
    approve.mutate(c);
  }

  const realInputs = (c: Claim) => (
    <div className="flex flex-col items-end gap-1">
      <input className="input w-36 text-right py-1 text-xs tabular-nums" inputMode="decimal"
        aria-label={t("Real selling price", "Harga jual sebenarnya")}
        placeholder={new Intl.NumberFormat("id-ID").format(invoicedOf(c))}
        value={real[c.id] ?? ""} onChange={(e) => setReal((m) => ({ ...m, [c.id]: e.target.value }))} />
      {lowered(c) && (
        <input className="input w-56 py-1 text-xs" aria-label={t("Why it's lower", "Alasan lebih rendah")}
          placeholder={t("Why it's lower (the rep sees this)", "Alasan lebih rendah (sales melihat ini)")}
          value={why[c.id] ?? ""} onChange={(e) => setWhy((m) => ({ ...m, [c.id]: e.target.value }))} />
      )}
    </div>
  );

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <BadgePercent size={15} className="text-brand-600" />
            {t("Commission claims", "Klaim komisi")}
            {open.length > 0 && <span className="chip bg-amber-50 text-amber-800 text-[11px]">{open.length}</span>}
          </div>
          <div className="text-[11px] text-ink-500 mt-0.5 max-w-3xl">
            {t("Claimed by sales on jobs paid in full. Approve — on the invoice, or on the real selling price if the customer asked for a higher figure on paper — then mark paid from the account it went out of; it's booked to Beban Komisi Penjualan Sales.",
               "Diklaim sales untuk pekerjaan yang sudah lunas. Setujui — atas nilai faktur, atau atas harga jual sebenarnya bila pelanggan meminta angka lebih tinggi di dokumen — lalu tandai dibayar dari rekening asalnya; tercatat ke Beban Komisi Penjualan Sales.")}
          </div>
        </div>
        {open.length > 0 && (
          <div className="text-sm"><span className="muted">{t("Waiting", "Menunggu")} </span>
            <span className="font-semibold tabular-nums">{money(due, "IDR")}</span></div>
        )}
      </div>
      {msg && (
        <div className={clsx("mx-5 mt-3 rounded-lg border px-3 py-2 text-sm",
          msg.kind === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800")}>
          {msg.text}
        </div>
      )}
      {claims.isLoading ? (
        <div className="p-5 text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}</div>
      ) : open.length === 0 ? (
        <div className="p-5 text-sm muted">{t("No claims waiting.", "Tidak ada klaim yang menunggu.")}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Sales", "Sales")}</th>
                <th className="th">{t("Job", "Proyek")}</th>
                <th className="th text-right">{t("Invoiced (before PPN)", "Faktur (sebelum PPN)")}</th>
                <th className="th text-right">{t("Real selling price", "Harga jual sebenarnya")}</th>
                <th className="th text-right">{t("Rate", "Tarif")}</th>
                <th className="th text-right">{t("Commission", "Komisi")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th text-right" />
              </tr>
            </thead>
            <tbody>
              {open.map((c) => (
                <tr key={c.id} className="border-t border-ink-100 align-top">
                  <td className="td">{c.beneficiary_name ?? "—"}
                    {c.claimed_by_name && c.claimed_by_name !== c.beneficiary_name && (
                      <span className="block text-[11px] muted">{t("filed by", "diajukan oleh")} {c.claimed_by_name}</span>)}
                  </td>
                  <td className="td font-mono text-xs">{c.project_code ?? "—"}</td>
                  <td className="td text-right tabular-nums">{money(invoicedOf(c), "IDR")}</td>
                  <td className="td text-right tabular-nums">
                    {c.status === "pending" ? realInputs(c)
                      : correcting === c.id ? (
                        <div className="flex flex-col items-end gap-1">
                          {realInputs(c)}
                          <div className="flex gap-1">
                            <button className="btn-primary text-xs px-2 py-1" disabled={correct.isPending}
                              onClick={() => correct.mutate(c)}><Check size={12} /> {t("Save", "Simpan")}</button>
                            <button className="btn-ghost text-xs px-2 py-1" onClick={() => setCorrecting(null)}>{t("Cancel", "Batal")}</button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <span className={clsx(c.basis_adjusted && "font-semibold text-accent-700")}>{money(c.basis_amount, "IDR")}</span>
                          {c.basis_adjusted && c.basis_note && (
                            <span className="block text-[11px] muted max-w-[14rem] ml-auto">
                              {c.basis_set_by_name ? `${c.basis_set_by_name}: ` : ""}{c.basis_note}</span>)}
                          {isDirector && (
                            <button className="mt-0.5 text-[11px] text-brand-700 hover:underline inline-flex items-center gap-1"
                              onClick={() => {
                                setReal((m) => ({ ...m, [c.id]: new Intl.NumberFormat("id-ID").format(c.basis_amount) }));
                                setWhy((m) => ({ ...m, [c.id]: c.basis_note ?? "" }));
                                setCorrecting(c.id);
                              }}>
                              <Pencil size={10} /> {t("Correct", "Koreksi")}</button>)}
                        </div>
                      )}
                  </td>
                  <td className="td text-right tabular-nums">
                    {c.status === "pending" && isDirector ? (
                      <input className="input w-16 text-right py-1 text-xs" inputMode="decimal"
                        aria-label={t("Rate %", "Tarif %")} placeholder={String(c.rate_pct)}
                        value={rate[c.id] ?? ""} onChange={(e) => setRate((r) => ({ ...r, [c.id]: e.target.value }))} />
                    ) : `${c.rate_pct}%`}
                  </td>
                  <td className="td text-right tabular-nums font-medium">
                    {money(c.status === "pending" || correcting === c.id ? preview(c) : c.amount, "IDR")}
                    {(() => {
                      // What it was before the figures on screen: the invoice at
                      // the stated rate (pending), or the agreed amount (correcting).
                      if (c.status !== "pending" && correcting !== c.id) return null;
                      const was = c.status === "pending" ? Math.round(invoicedOf(c) * c.rate_pct) / 100 : c.amount;
                      return Math.abs(was - preview(c)) > 0.005
                        ? <span className="block text-[11px] muted line-through">{money(was, "IDR")}</span> : null;
                    })()}
                  </td>
                  <td className="td">
                    <span className={clsx("chip text-[11px]", c.status === "pending"
                      ? "bg-amber-50 text-amber-800" : "bg-blue-50 text-blue-700")}>
                      {c.status === "pending" ? t("to approve", "perlu disetujui") : t("approved · to pay", "disetujui · perlu dibayar")}
                    </span>
                  </td>
                  <td className="td text-right whitespace-nowrap">
                    {c.status === "pending" && (
                      <div className="inline-flex gap-1">
                        <button className="btn-primary text-xs px-2 py-1" disabled={approve.isPending}
                          onClick={() => tryApprove(c)}>
                          <Check size={12} /> {t("Approve", "Setujui")}
                        </button>
                        <button className="btn-ghost text-xs px-2 py-1 text-red-600" disabled={reject.isPending}
                          onClick={() => {
                            const w = window.prompt(t("Why is it refused? The rep sees this.", "Mengapa ditolak? Sales akan melihat ini."));
                            if (w && w.trim()) reject.mutate({ id: c.id, notes: w.trim() });
                          }}>
                          <X size={12} /> {t("Reject", "Tolak")}
                        </button>
                      </div>
                    )}
                    {c.status === "approved" && paying !== c.id && correcting !== c.id && (
                      <button className="btn-primary text-xs px-2 py-1" onClick={() => setPaying(c.id)}>
                        <Wallet size={12} /> {t("Mark paid", "Tandai dibayar")}
                      </button>
                    )}
                    {c.status === "approved" && paying === c.id && (
                      <div className="flex flex-col items-end gap-1.5 min-w-[16rem]">
                        <div className="w-64 text-left">
                          <AccountPicker value={cashNo} onChange={setCashNo} onlyTypes={["Cash & Bank"]}
                            ariaLabel={t("Paid from", "Dibayar dari")} />
                        </div>
                        <input type="date" className="input w-40 text-xs py-1" value={paidOn}
                          aria-label={t("Paid on", "Tanggal bayar")} onChange={(e) => setPaidOn(e.target.value)} />
                        <div className="flex gap-1">
                          <button className="btn-primary text-xs px-2 py-1" disabled={pay.isPending || !cashNo}
                            onClick={() => pay.mutate(c.id)}>
                            {pay.isPending ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                            {t(`Pay ${money(c.amount, "IDR")}`, `Bayar ${money(c.amount, "IDR")}`)}
                          </button>
                          <button className="btn-ghost text-xs px-2 py-1" onClick={() => setPaying(null)}>{t("Cancel", "Batal")}</button>
                        </div>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {recent.length > 0 && (
        <div className="px-5 py-2 border-t border-ink-100 text-[11px] muted">
          {t("Recently paid", "Baru dibayar")}:{" "}
          {recent.map((c) => `${c.beneficiary_name ?? "—"} ${c.project_code ?? ""} ${money(c.amount, "IDR")}`).join(" · ")}
        </div>
      )}
    </div>
  );
}
