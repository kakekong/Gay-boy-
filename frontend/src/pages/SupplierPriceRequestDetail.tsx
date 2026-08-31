/**
 * One supplier's answer to "what do you charge for this".
 *
 * The page is a form for a phone call. Purchasing rings the vendor, types what
 * they hear into the lines, and — when this is the quote they are taking —
 * presses one button to make it the cost on the price request it was raised
 * against. Before this existed the last step was retyping a number into a
 * different screen, and the quote it came from was never written down at all.
 *
 * The comparison strip at the top is the reason several vendors are asked at
 * once: the same job, every answer, cheapest complete quote first.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ClipboardList, Loader2, AlertCircle, Send, Save, CheckCircle2,
  Archive, Trash2, Truck, Building2, CalendarDays, Pencil, X,
} from "lucide-react";
import clsx from "clsx";
import { CURRENCIES, money } from "@/lib/currency";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { useT, T } from "@/store/lang";

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const CHIP: Record<string, string> = {
  draft:     "bg-ink-100 text-ink-700",
  sent:      "bg-amber-50 text-amber-700",
  quoted:    "bg-blue-50 text-blue-700",
  closed:    "bg-emerald-50 text-emerald-700",
  cancelled: "bg-red-50 text-red-700",
};

interface Line {
  line_no: number;
  description: string;
  qty: number;
  uom: string | null;
  quoted_price?: number | null;
  lead_days?: number | null;
  note?: string | null;
  /** Where this line came from. Survives the job being split between vendors
   *  and several jobs being combined onto one, which is what lets a quote be
   *  applied back to exactly the right line of the right request. */
  source_pr_id?: string | null;
  source_pr_number?: string | null;
  source_line_no?: number | null;
}

interface SourceRef {
  id: string;
  number: string;
  status: string;
  lines: number[];
}

interface SPR {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  price_request_id: string | null;
  price_request_number: string | null;
  source_price_requests: SourceRef[];
  is_joint: boolean;
  items: Line[];
  notes: string | null;
  currency: string;
  fx_rate: number | null;
  valid_until: string | null;
  quoted_lead_days: number | null;
  sent_at: string | null;
  quoted_at: string | null;
  applied_at: string | null;
  quoted_total: number | null;
  lines_quoted: number;
  lines_total: number;
}

export default function SupplierPriceRequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  // What the supplier said, per line, as it is being typed. Kept separate from
  // the saved row so a half-finished call is never mistaken for a quote.
  const [draft, setDraft] = useState<Record<number, { price: string; lead: string }>>({});
  const [basis, setBasis] = useState<"unit" | "total">("unit");
  // What the supplier answered in, and what a unit of it costs in rupiah.
  // A vendor answers in whatever they like regardless of the sheet they were
  // sent, so both are stated here with the quote rather than up front.
  const [currency, setCurrency] = useState("IDR");
  const [fxRate, setFxRate] = useState("");
  const [leadDays, setLeadDays] = useState("");
  const [quoteNote, setQuoteNote] = useState("");
  // Correcting the sheet itself — the number on it and what it asks for —
  // which is only allowed while it is still a draft nobody has sent.
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<{ number: string; items: Line[] }>(
    { number: "", items: [] });

  const q = useQuery({
    queryKey: ["supplier-price-request", id],
    queryFn: () => api.get(`/purchasing/price-requests/${id}`).then((r) => r.data as SPR),
    enabled: !!id,
  });

  // Every vendor asked about the same job. Only meaningful when this request
  // is costing one.
  const compare = useQuery({
    queryKey: ["spr-compare", q.data?.price_request_id],
    queryFn: () => api.get(
      `/purchasing/price-requests/for-price-request/${q.data!.price_request_id}/compare`,
    ).then((r) => r.data as { price_request_number: string; requests: SPR[] }),
    enabled: !!q.data?.price_request_id,
  });

  useEffect(() => {
    if (!q.data) return;
    setDraft(Object.fromEntries(q.data.items.map((it) => [it.line_no, {
      price: it.quoted_price != null ? String(it.quoted_price) : "",
      lead: it.lead_days != null ? String(it.lead_days) : "",
    }])));
    setLeadDays(q.data.quoted_lead_days != null ? String(q.data.quoted_lead_days) : "");
    setCurrency(q.data.currency || "IDR");
    setFxRate(q.data.fx_rate != null ? String(q.data.fx_rate) : "");
  }, [q.data?.id, q.data?.quoted_at]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["supplier-price-request", id] });
    qc.invalidateQueries({ queryKey: ["supplier-price-requests"] });
    qc.invalidateQueries({ queryKey: ["spr-compare"] });
  };
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("Something went wrong.", "Terjadi kesalahan."),
  });

  const save = useMutation({
    mutationFn: () => api.patch(`/purchasing/price-requests/${id}`, {
      number: form.number.trim(),
      items: form.items.map((it) => ({
        line_no: it.line_no,
        description: it.description,
        qty: Number(it.qty) || 0,
        uom: it.uom?.trim() ? it.uom.trim() : null,
      })),
    }),
    onSuccess: () => {
      setEditing(false);
      refresh();
      setFlash({ kind: "ok", text: t("Request updated.", "Permintaan diperbarui.") });
    },
    onError: onErr,
  });
  const send = useMutation({
    mutationFn: () => api.post(`/purchasing/price-requests/${id}/send`),
    onSuccess: () => { refresh(); setFlash({ kind: "ok", text: t("Marked as sent.", "Ditandai terkirim.") }); },
    onError: onErr,
  });
  const quote = useMutation({
    mutationFn: () => api.post(`/purchasing/price-requests/${id}/quote`, {
      items: Object.entries(draft)
        .filter(([, v]) => v.price !== "")
        .map(([line_no, v]) => ({
          line_no: Number(line_no),
          quoted_price: Number(v.price),
          basis,
          lead_days: v.lead === "" ? null : Number(v.lead),
        })),
      quoted_lead_days: leadDays === "" ? null : Number(leadDays),
      notes: quoteNote.trim() || null,
      currency,
      fx_rate: currency === "IDR" || fxRate === "" ? null : Number(fxRate),
    }),
    onSuccess: () => {
      setQuoteNote("");
      refresh();
      setFlash({ kind: "ok", text: t("Quote recorded.", "Penawaran dicatat.") });
    },
    onError: onErr,
  });
  const apply = useMutation({
    mutationFn: () => api.post(`/purchasing/price-requests/${id}/apply`),
    onSuccess: (r: any) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["price-requests"] });
      setFlash({
        kind: "ok",
        text: t(
          `Cost applied to ${r.data?.price_request_number ?? "the price request"} — it is with the director now.`,
          `Biaya diterapkan ke ${r.data?.price_request_number ?? "permintaan harga"} — sekarang di direktur.`),
      });
    },
    onError: onErr,
  });
  const close = useMutation({
    mutationFn: (reason: string) =>
      api.post(`/purchasing/price-requests/${id}/close`, { reason: reason || null }),
    onSuccess: () => { refresh(); setFlash({ kind: "ok", text: t("Closed.", "Ditutup.") }); },
    onError: onErr,
  });
  const drop = useMutation({
    mutationFn: () => api.delete(`/purchasing/price-requests/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["supplier-price-requests"] });
      nav("/purchasing");
    },
    onError: onErr,
  });

  const editLine = (lineNo: number, patch: Partial<Line>) =>
    setForm((f) => ({
      ...f,
      items: f.items.map((it) => (it.line_no === lineNo ? { ...it, ...patch } : it)),
    }));

  const typedTotal = useMemo(() => {
    if (!q.data) return 0;
    return q.data.items.reduce((sum, it) => {
      const raw = Number(draft[it.line_no]?.price || 0);
      const perUnit = basis === "total" && it.qty ? raw / it.qty : raw;
      return sum + perUnit * (it.qty || 0);
    }, 0);
  }, [draft, basis, q.data]);

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
      </div>
    );
  }
  if (q.error || !q.data) {
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {t("Price request not found", "Permintaan harga tidak ditemukan")}
        </div>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchasing")}>
          <ArrowLeft size={14} /> {t("Back to Purchasing", "Kembali ke Pembelian")}
        </button>
      </div>
    );
  }

  const r = q.data;
  const editable = !["closed", "cancelled"].includes(r.status);
  // While the sheet itself is being corrected, the quote form stands down:
  // two Save buttons on one screen is an invitation to press the wrong one,
  // and a price typed against a line that is being reworded is a half-thought.
  const quoting = editable && !editing;
  const everyLineAnswered = r.lines_total > 0 && r.lines_quoted === r.lines_total;

  return (
    <div className="space-y-5">
      <Link to="/purchasing"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> {t("Back to Purchasing", "Kembali ke Pembelian")}
      </Link>

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

      <div className="card p-6 space-y-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <ClipboardList size={13} className="text-brand-600" />
              {t("Price request to supplier", "Permintaan harga ke pemasok")}
            </div>
            {editing ? (
              <label className="block mt-0.5">
                <span className="sr-only">{t("Request number", "Nomor permintaan")}</span>
                <input
                  className="input text-2xl font-semibold tracking-tight w-64"
                  aria-label={t("Request number", "Nomor permintaan")}
                  value={form.number}
                  onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))}
                />
              </label>
            ) : (
              <h1 className="text-2xl font-semibold tracking-tight mt-0.5">{r.number}</h1>
            )}
            <div className="mt-1 flex items-center gap-2 flex-wrap text-sm">
              <Link to={`/suppliers/${r.supplier_id}`}
                className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                <Building2 size={13} /> {r.supplier_name}
              </Link>
              <span className={clsx("chip uppercase", CHIP[r.status] ?? "bg-ink-100")}>
                {r.status}
              </span>
              {r.applied_at && (
                <span className="chip bg-emerald-50 text-emerald-700">
                  {t("used as the cost", "dipakai sebagai biaya")}
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {/* A draft has not gone anywhere yet, so the sheet itself is
                still purchasing's to correct: its number, the wording of a
                line, a quantity, a missing unit. Once it is sent the vendor
                is holding a copy, and the server refuses. */}
            {r.status === "draft" && !editing && (
              <>
                <button className="btn-ghost"
                  onClick={() => {
                    setForm({
                      number: r.number,
                      items: r.items.map((it) => ({ ...it })),
                    });
                    setEditing(true);
                  }}>
                  <Pencil size={14} /> {t("Edit request", "Ubah permintaan")}
                </button>
                <button className="btn-primary" disabled={send.isPending}
                  onClick={() => send.mutate()}>
                  {send.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {t("Mark sent", "Tandai terkirim")}
                </button>
                <button className="btn-ghost text-red-600"
                  onClick={() => {
                    if (window.confirm(t("Delete this draft?", "Hapus draf ini?"))) drop.mutate();
                  }}>
                  <Trash2 size={14} /> {t("Delete draft", "Hapus draf")}
                </button>
              </>
            )}
            {r.status === "draft" && editing && (
              <>
                <button className="btn-primary" disabled={save.isPending}
                  onClick={() => save.mutate()}>
                  {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {t("Save changes", "Simpan perubahan")}
                </button>
                <button className="btn-ghost" disabled={save.isPending}
                  onClick={() => setEditing(false)}>
                  <X size={14} /> {t("Cancel", "Batal")}
                </button>
              </>
            )}
            {editable && r.status !== "draft" && (
              <button className="btn-ghost"
                onClick={() => {
                  const why = window.prompt(t("Why are you closing this?",
                                              "Mengapa ditutup?")) ?? "";
                  close.mutate(why);
                }}>
                <Archive size={14} /> {t("Close", "Tutup")}
              </button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm border-t border-ink-100 pt-4">
          <Cell label={t("Costing", "Membiayai")}>
            {(r.source_price_requests ?? []).length ? (
              <span className="flex flex-wrap gap-1">
                {r.source_price_requests.map((s2) => (
                  <span key={s2.id} className="font-mono text-xs">
                    {s2.number}
                    <span className="muted">
                      {" "}({s2.lines.length})
                    </span>
                  </span>
                ))}
              </span>
            ) : r.price_request_number ? (
              <span className="font-mono text-xs">{r.price_request_number}</span>
            ) : (
              <span className="muted">{t("standalone enquiry", "permintaan mandiri")}</span>
            )}
          </Cell>
          <Cell label={t("Answered", "Dijawab")}>
            <span className="tabular-nums">{r.lines_quoted}/{r.lines_total}</span>
          </Cell>
          <Cell label={t("Quoted total", "Total penawaran")}>
            <span className="tabular-nums">
              {r.quoted_total == null ? "—" : idr(r.quoted_total)}
            </span>
          </Cell>
          <Cell label={t("Lead time", "Waktu kirim")}>
            {r.quoted_lead_days == null
              ? "—"
              : <span className="tabular-nums">{r.quoted_lead_days} {t("days", "hari")}</span>}
          </Cell>
        </div>
        {(r.valid_until || r.notes) && (
          <div className="border-t border-ink-100 pt-3 text-sm space-y-1">
            {r.valid_until && (
              <div className="flex items-center gap-1.5 muted text-xs">
                <CalendarDays size={12} />
                {t("Quote valid until", "Penawaran berlaku sampai")} {r.valid_until}
              </div>
            )}
            {r.notes && <div className="whitespace-pre-wrap text-ink-700">{r.notes}</div>}
          </div>
        )}
      </div>

      {/* What they said, line by line */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="font-semibold">{t("What they quoted", "Harga yang mereka berikan")}</div>
            <div className="text-xs muted">
              {editing
                ? t("Fix the wording, the quantity or the unit, then press Save changes above.",
                     "Perbaiki uraian, jumlah, atau satuannya, lalu tekan Simpan perubahan di atas.")
                : t("Type what the supplier said. Nothing leaves this page until you save it.",
                     "Ketik yang disampaikan pemasok. Tidak ada yang tersimpan sampai Anda menyimpannya.")}
            </div>
          </div>
          {quoting && (
            <div className="flex items-end gap-3 flex-wrap">
              <label className="text-xs flex items-center gap-2">
                {t("They quoted per", "Mereka memberi harga per")}
                <select className="input py-1" value={basis}
                  onChange={(e) => setBasis(e.target.value as "unit" | "total")}>
                  <option value="unit">{t("unit", "satuan")}</option>
                  <option value="total">{t("whole line", "total baris")}</option>
                </select>
              </label>
              <label className="text-xs flex items-center gap-2">
                {t("in", "dalam")}
                <select className="input py-1" value={currency}
                  aria-label="Quote currency"
                  onChange={(e) => setCurrency(e.target.value)}>
                  {CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.code}</option>
                  ))}
                </select>
              </label>
              {currency !== "IDR" && (
                <label className="text-xs flex items-center gap-2">
                  {t(`Rp per ${currency}`, `Rp per ${currency}`)}
                  <input className="input py-1 w-28" type="number" min="0"
                    step="0.000001" value={fxRate}
                    aria-label="Exchange rate"
                    placeholder="16.200"
                    onChange={(e) => setFxRate(e.target.value)} />
                </label>
              )}
            </div>
          )}
        </header>
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th w-10">#</th>
              <th className="th">{t("Description", "Deskripsi")}</th>
              {r.is_joint && <th className="th">{t("For", "Untuk")}</th>}
              <th className="th text-right">{t("Qty", "Jml")}</th>
              <th className="th">{t("UoM", "Satuan")}</th>
              <th className="th text-right">{t("Their price", "Harga mereka")}</th>
              <th className="th text-right">{t("Lead days", "Hari kirim")}</th>
              <th className="th text-right">{t("Line total", "Total baris")}</th>
            </tr>
          </thead>
          <tbody>
            {(editing ? form.items : r.items).map((it) => {
              const raw = Number(draft[it.line_no]?.price || 0);
              const perUnit = basis === "total" && it.qty ? raw / it.qty : raw;
              return (
                <tr key={it.line_no} className="border-t border-ink-100">
                  <td className="td font-mono text-xs muted">{it.line_no}</td>
                  <td className="td">
                    {editing ? (
                      <input
                        className="input w-full min-w-[12rem]"
                        aria-label={`${t("Description", "Deskripsi")} ${it.line_no}`}
                        value={it.description}
                        onChange={(e) => editLine(it.line_no, { description: e.target.value })}
                      />
                    ) : it.description}
                  </td>
                  {r.is_joint && (
                    <td className="td font-mono text-[11px] muted">
                      {it.source_pr_number
                        ? `${it.source_pr_number}#${it.source_line_no}`
                        : "—"}
                    </td>
                  )}
                  <td className="td text-right tabular-nums">
                    {editing ? (
                      <input
                        className="input text-right tabular-nums w-20 ml-auto"
                        type="number" min={0} step="any"
                        aria-label={`${t("Qty", "Jml")} ${it.line_no}`}
                        value={it.qty}
                        onChange={(e) => editLine(it.line_no, { qty: Number(e.target.value) })}
                      />
                    ) : it.qty}
                  </td>
                  <td className="td muted">
                    {editing ? (
                      <input
                        className="input w-24"
                        aria-label={`${t("UoM", "Satuan")} ${it.line_no}`}
                        value={it.uom ?? ""}
                        onChange={(e) => editLine(it.line_no, { uom: e.target.value })}
                      />
                    ) : (it.uom ?? "—")}
                  </td>
                  <td className="td text-right">
                    {quoting ? (
                      <input
                        className="input text-right tabular-nums w-36 ml-auto"
                        inputMode="numeric"
                        value={draft[it.line_no]?.price ?? ""}
                        onChange={(e) => setDraft((cur) => ({
                          ...cur,
                          [it.line_no]: { ...(cur[it.line_no] ?? { lead: "" }), price: e.target.value },
                        }))}
                      />
                    ) : (
                      <span className="tabular-nums">
                        {it.quoted_price == null ? "—" : idr(it.quoted_price)}
                      </span>
                    )}
                  </td>
                  <td className="td text-right">
                    {quoting ? (
                      <input
                        className="input text-right tabular-nums w-20 ml-auto"
                        inputMode="numeric"
                        value={draft[it.line_no]?.lead ?? ""}
                        onChange={(e) => setDraft((cur) => ({
                          ...cur,
                          [it.line_no]: { ...(cur[it.line_no] ?? { price: "" }), lead: e.target.value },
                        }))}
                      />
                    ) : (
                      <span className="tabular-nums">{it.lead_days ?? "—"}</span>
                    )}
                  </td>
                  <td className="td text-right tabular-nums font-medium">
                    {perUnit ? money(perUnit * (it.qty || 0), currency) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {quoting && (
          <div className="px-5 py-4 border-t border-ink-100 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="block">
                <span className="block text-xs font-medium text-ink-600 mb-1">
                  {t("Lead time for the whole order (days)", "Waktu kirim seluruh order (hari)")}
                </span>
                <input className="input" inputMode="numeric" value={leadDays}
                  onChange={(e) => setLeadDays(e.target.value)} />
              </label>
              <label className="block md:col-span-2">
                <span className="block text-xs font-medium text-ink-600 mb-1">
                  {t("Anything they said worth keeping", "Hal lain yang perlu dicatat")}
                </span>
                <input className="input" value={quoteNote}
                  onChange={(e) => setQuoteNote(e.target.value)}
                  placeholder={t("e.g. price holds 2 weeks, freight not included",
                                 "cth. harga berlaku 2 minggu, ongkir belum termasuk")} />
              </label>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <button className="btn-primary" disabled={quote.isPending}
                onClick={() => quote.mutate()}>
                {quote.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {t("Save their quote", "Simpan penawaran")}
              </button>
              <span className="text-sm muted tabular-nums">
                {t("Total as typed", "Total sesuai ketikan")}:{" "}
                {money(typedTotal, currency)}
                {currency !== "IDR" && Number(fxRate) > 0 && (
                  // What it becomes on the price request. Shown while it is
                  // being typed, because that is when a rate typed a decimal
                  // place out is still cheap to notice.
                  <span className="muted">
                    {" ≈ "}{money(typedTotal * Number(fxRate), "IDR")}
                  </span>
                )}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Making it the cost */}
      {r.price_request_id && (
        <div className="card p-5 space-y-3">
          <div className="font-semibold">
            {t("Use this as the cost", "Jadikan ini biaya")}
          </div>
          <p className="text-sm muted">
            {t("Writes these prices onto every matching line of the price request and sends it to the director. The quote stays on file as where the number came from.",
               "Menulis harga ini ke setiap baris yang cocok pada permintaan harga lalu mengirimkannya ke direktur. Penawaran ini tetap tersimpan sebagai asal angkanya.")}
          </p>
          {!everyLineAnswered && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              {t(`Only ${r.lines_quoted} of ${r.lines_total} lines have a price. The rest keep whatever cost they already had.`,
                 `Baru ${r.lines_quoted} dari ${r.lines_total} baris yang berharga. Sisanya tetap memakai biaya sebelumnya.`)}
            </div>
          )}
          <button
            className="btn-primary"
            disabled={apply.isPending || r.status !== "quoted" || r.lines_quoted === 0}
            title={r.status !== "quoted"
              ? t("Save their quote first", "Simpan penawaran mereka dulu") : undefined}
            onClick={() => apply.mutate()}
          >
            {apply.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {t("Apply to", "Terapkan ke")} {r.price_request_number}
          </button>
        </div>
      )}

      {/* The vendor's own quotation sheet, and the conversation about it —
          the same two cards the sell-side price request carries, so the
          screenshot of the WhatsApp reply lives on the request it answers
          rather than in somebody's inbox. */}
      <AttachmentsSection ownerType="supplier_price_request" ownerId={r.id} />
      <CommentThread ownerType="supplier_price_request" ownerId={r.id} />

      {/* The other vendors asked about the same job */}
      {(compare.data?.requests?.length ?? 0) > 1 && (
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <Truck size={15} className="text-brand-600" />
              {t("Everyone asked about", "Semua yang ditanya untuk")} {compare.data!.price_request_number}
            </div>
            <div className="text-xs muted">
              {t("Cheapest complete quote first. Incomplete ones sit at the bottom.",
                 "Penawaran lengkap termurah di atas. Yang belum lengkap di bawah.")}
            </div>
          </header>
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Supplier", "Pemasok")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th text-right">{t("Answered", "Dijawab")}</th>
                <th className="th text-right">{t("Lead days", "Hari kirim")}</th>
                <th className="th text-right">{t("Quoted total", "Total penawaran")}</th>
              </tr>
            </thead>
            <tbody>
              {compare.data!.requests.map((o) => (
                <tr key={o.id}
                  className={clsx("border-t border-ink-100",
                    o.id === r.id ? "bg-brand-50/40" : "tr-hover cursor-pointer")}
                  onClick={() => o.id !== r.id && nav(`/purchasing/price-requests/${o.id}`)}>
                  <td className="td">
                    {o.supplier_name}
                    {o.applied_at && (
                      <span className="chip bg-emerald-50 text-emerald-700 ml-2">
                        {t("taken", "dipakai")}
                      </span>
                    )}
                  </td>
                  <td className="td">
                    <span className={clsx("chip uppercase", CHIP[o.status] ?? "bg-ink-100")}>
                      {o.status}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{o.lines_quoted}/{o.lines_total}</td>
                  <td className="td text-right tabular-nums">{o.quoted_lead_days ?? "—"}</td>
                  <td className="td text-right tabular-nums font-medium">
                    {o.quoted_total == null ? "—" : idr(o.quoted_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}
