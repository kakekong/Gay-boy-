/**
 * One asset: what it is, what it is worth now, and what happened to it.
 *
 * The two schedules are the reason this page exists rather than a row in a
 * table. An asset is depreciated twice — once for the company's books over
 * the life it actually expects, and once for the tax return over the
 * statutory group's — and the two answers differ. Showing them side by side
 * makes the gap a thing you can point at, which is what a fiscal
 * reconciliation is.
 *
 * The three actions below are separate for the same reason they are separate
 * on the server: a move is not a revaluation is not a disposal. A move
 * changes only where it is. A cost change is money on the balance sheet and
 * posts an entry. A disposal takes the asset off and produces a gain or a
 * loss — the number that says whether it was worth what the books claimed.
 */
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Loader2, MapPin, Pencil, PackageX, AlertCircle, CheckCircle2,
  X, TrendingDown,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT } from "@/store/lang";

interface Entry {
  period_year: number; period_month: number; amount: number;
  book_value_after: number; journal_id: string | null;
}
interface Change {
  kind: string; changed_on: string;
  before_value: string | null; after_value: string | null;
  memo: string | null; journal_id: string | null;
}
interface AssetDetail {
  id: string; number: string; name: string;
  category_name: string | null; tax_category_name: string | null;
  tax_group: string | null;
  acquired_on: string; cost: number; salvage_value: number;
  useful_life_months: number; method: string;
  opening_accum: number; accumulated_depreciation: number; book_value: number;
  location: string | null; department: string | null; serial_no: string | null;
  supplier: string | null; notes: string | null;
  status: string; disposed_on: string | null; disposal_proceeds: number;
  disposal_reason: string | null;
  entries: Entry[]; changes: Change[];
  may: { edit: boolean; dispose: boolean; move: boolean; adjust: boolean;
         delete: boolean };
  locked_because?: string;
}
interface Schedule {
  scope: string; method: string; useful_life_months: number;
  tax_group: string | null; total: number;
  items: { period_year: number; period_month: number; month_index: number;
           amount: number; accumulated: number; book_value: number;
           already_written_off: boolean }[];
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);
const MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

export default function AssetDetailPage() {
  const { assetId = "" } = useParams();
  const t = useT();
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const timer = useRef<number | null>(null);
  const [panel, setPanel] = useState<"move" | "adjust" | "dispose" | null>(null);
  const [scope, setScope] = useState<"commercial" | "tax">("commercial");

  const say = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setFlash(null), 8000);
  };
  const blame = (e: any) =>
    say("err", e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("That did not work.", "Gagal."));

  const q = useQuery({
    queryKey: ["asset", assetId],
    queryFn: () => api.get(`/assets/${assetId}`).then((r) => r.data as AssetDetail),
    enabled: !!assetId,
  });
  const a = q.data;

  const sched = useQuery({
    queryKey: ["asset-schedule", assetId, scope],
    queryFn: () => api.get(`/assets/${assetId}/schedule`, { params: { scope } })
      .then((r) => r.data as Schedule),
    enabled: !!assetId && (scope === "commercial" || !!a?.tax_category_name),
    retry: false,
  });

  const done = () => {
    setPanel(null);
    qc.invalidateQueries({ queryKey: ["asset", assetId] });
    qc.invalidateQueries({ queryKey: ["asset-schedule", assetId] });
    qc.invalidateQueries({ queryKey: ["assets"] });
  };

  // Move
  const [where, setWhere] = useState("");
  const move = useMutation({
    mutationFn: () => api.post(`/assets/${assetId}/move`, { location: where }),
    onSuccess: () => { say("ok", t("Moved.", "Dipindahkan.")); setWhere(""); done(); },
    onError: blame,
  });

  // Adjust
  const [adjustKind, setAdjustKind] = useState<"cost" | "life">("cost");
  const [newCost, setNewCost] = useState("");
  const [newLife, setNewLife] = useState("");
  const [counter, setCounter] = useState("");
  const [memo, setMemo] = useState("");
  const adjust = useMutation({
    mutationFn: () => api.post(`/assets/${assetId}/adjust`,
      adjustKind === "cost"
        ? { kind: "cost", new_cost: Number(newCost || 0),
            counter_account_no: counter, memo: memo || null }
        : { kind: "life", new_life_months: Number(newLife || 0),
            memo: memo || null }),
    onSuccess: () => {
      say("ok", t("Recorded.", "Tercatat."));
      setNewCost(""); setNewLife(""); setMemo(""); done();
    },
    onError: blame,
  });

  // Dispose
  const [proceeds, setProceeds] = useState("");
  const [proceedsAcc, setProceedsAcc] = useState("");
  const [gainAcc, setGainAcc] = useState("");
  const [reason, setReason] = useState("");
  const dispose = useMutation({
    mutationFn: () => api.post(`/assets/${assetId}/dispose`, {
      proceeds: Number(proceeds || 0),
      proceeds_account_no: proceedsAcc || null,
      gain_loss_account_no: gainAcc,
      reason: reason || null,
    }).then((r) => r.data),
    onSuccess: (d: any) => {
      say("ok", d.gain
        ? t(`Disposed. Gain of ${idr(d.gain)} — ${d.journal_number}.`,
            `Dilepas. Laba ${idr(d.gain)} — ${d.journal_number}.`)
        : d.loss
          ? t(`Disposed. Loss of ${idr(d.loss)} — ${d.journal_number}.`,
              `Dilepas. Rugi ${idr(d.loss)} — ${d.journal_number}.`)
          : t(`Disposed at book value — ${d.journal_number}.`,
              `Dilepas pada nilai buku — ${d.journal_number}.`));
      done();
    },
    onError: blame,
  });

  if (q.isLoading) {
    return <div className="p-8 flex justify-center"><Loader2 className="animate-spin" /></div>;
  }
  if (!a) {
    return <p className="p-6 text-sm muted">{t("Asset not found.", "Aset tidak ditemukan.")}</p>;
  }

  const pct = a.cost > 0
    ? Math.min(100, Math.round((a.accumulated_depreciation / a.cost) * 100))
    : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Link to="/assets" className="btn-ghost px-2 py-1">
          <ArrowLeft size={15} /> {t("Register", "Daftar aset")}
        </Link>
        <h1 className="section-title">{a.name}</h1>
        <span className="spec muted">{a.number}</span>
        {a.status === "disposed" && (
          <span className="chip bg-ink-100 text-ink-700">
            {t("disposed", "dilepas")} {a.disposed_on}
          </span>
        )}
      </div>

      {flash && (
        <div className={clsx(
          "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-rose-200 bg-rose-50 text-rose-800")}>
          {flash.kind === "ok" ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
                               : <AlertCircle size={15} className="mt-0.5 shrink-0" />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      {a.locked_because && (
        <p className="text-xs muted">{a.locked_because}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card p-4 lg:col-span-2 space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              [t("At cost", "Harga perolehan"), idr(a.cost)],
              [t("Depreciated", "Akumulasi"), idr(a.accumulated_depreciation)],
              [t("Book value", "Nilai buku"), idr(a.book_value)],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="overline">{label}</div>
                <div className="text-lg font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="h-2 rounded-full bg-ink-100 overflow-hidden">
              <div className="h-full bg-brand-500" style={{ width: `${pct}%` }}
                aria-label={`Depreciated ${pct}%`} />
            </div>
            <p className="text-[11px] muted mt-1">
              {t(`${pct}% written off since ${a.acquired_on}.`,
                 `${pct}% telah disusutkan sejak ${a.acquired_on}.`)}
              {a.salvage_value > 0 && " " + t(
                `Stops at a residual of ${idr(a.salvage_value)}.`,
                `Berhenti pada nilai residu ${idr(a.salvage_value)}.`)}
            </p>
          </div>

          <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 text-sm pt-1">
            {[
              [t("Category", "Kategori"), a.category_name],
              [t("Tax category", "Kategori pajak"), a.tax_category_name],
              [t("Acquired", "Perolehan"), a.acquired_on],
              [t("Useful life", "Masa manfaat"),
               `${a.useful_life_months} ${t("months", "bulan")}`],
              [t("Method", "Metode"), a.method === "declining_balance"
                ? t("Declining balance", "Saldo menurun")
                : t("Straight line", "Garis lurus")],
              [t("Location", "Lokasi"), a.location],
              [t("Serial no.", "Nomor seri"), a.serial_no],
              [t("Supplier", "Pemasok"), a.supplier],
            ].map(([label, value]) => (
              <div key={label} className="flex gap-2">
                <dt className="muted min-w-[9rem]">{label}</dt>
                <dd className="flex-1">{value || <span className="muted">—</span>}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="card p-4 space-y-2 h-fit">
          <h2 className="overline">{t("Actions", "Tindakan")}</h2>
          <button className="btn-ghost w-full justify-start" disabled={!a.may.move}
            onClick={() => setPanel(panel === "move" ? null : "move")}>
            <MapPin size={14} /> {t("Move", "Pindah aset")}
          </button>
          <button className="btn-ghost w-full justify-start" disabled={!a.may.adjust}
            onClick={() => setPanel(panel === "adjust" ? null : "adjust")}>
            <Pencil size={14} /> {t("Change cost or life", "Perubahan aset tetap")}
          </button>
          <button className="btn-ghost w-full justify-start text-rose-700"
            disabled={!a.may.dispose}
            onClick={() => setPanel(panel === "dispose" ? null : "dispose")}>
            <PackageX size={14} /> {t("Dispose", "Disposisi aset")}
          </button>

          {panel === "move" && (
            <div className="pt-2 space-y-2 border-t border-ink-100">
              <label className="block">
                <span className="label">{t("Moved to", "Dipindahkan ke")}</span>
                <input className="input" value={where} aria-label="New location"
                  onChange={(e) => setWhere(e.target.value)} />
              </label>
              <p className="text-[11px] muted">
                {t("No entry — the company owns it either way.",
                   "Tanpa jurnal — kepemilikannya tidak berubah.")}
              </p>
              <button className="btn-primary w-full" aria-label="Confirm move"
                disabled={!where.trim() || move.isPending}
                onClick={() => move.mutate()}>
                {move.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
                {t("Move it", "Pindahkan")}
              </button>
            </div>
          )}

          {panel === "adjust" && (
            <div className="pt-2 space-y-2 border-t border-ink-100">
              <div className="flex gap-1">
                {([["cost", t("Cost", "Nilai")],
                   ["life", t("Life", "Masa manfaat")]] as const).map(([k, label]) => (
                  <button key={k}
                    className={clsx("px-2.5 py-1 text-xs rounded-lg border",
                      adjustKind === k ? "border-brand-500 bg-brand-50 text-brand-700"
                                       : "border-ink-200 muted")}
                    onClick={() => setAdjustKind(k)}>{label}</button>
                ))}
              </div>
              {adjustKind === "cost" ? (
                <>
                  <label className="block">
                    <span className="label">{t("New cost", "Nilai baru")}</span>
                    <input className="input" type="number" value={newCost}
                      aria-label="New cost"
                      onChange={(e) => setNewCost(e.target.value)} />
                  </label>
                  <div>
                    <span className="label">{t("Against", "Akun lawan")}</span>
                    <AccountPicker value={counter} onChange={setCounter}
                      ariaLabel="Akun lawan" />
                  </div>
                  <p className="text-[11px] muted">
                    {t("Real money on the balance sheet, so it posts an entry.",
                       "Menambah nilai di neraca, jadi ada jurnalnya.")}
                  </p>
                </>
              ) : (
                <>
                  <label className="block">
                    <span className="label">
                      {t("New life (months)", "Masa manfaat baru (bulan)")}
                    </span>
                    <input className="input" type="number" value={newLife}
                      aria-label="New life"
                      onChange={(e) => setNewLife(e.target.value)} />
                  </label>
                  <p className="text-[11px] muted">
                    {t("An estimate being corrected — no entry, but every month after it is a different number.",
                       "Perubahan estimasi — tanpa jurnal, tapi penyusutan berikutnya berubah.")}
                  </p>
                </>
              )}
              <label className="block">
                <span className="label">{t("Why", "Keterangan")}</span>
                <input className="input" value={memo} aria-label="Adjust memo"
                  onChange={(e) => setMemo(e.target.value)} />
              </label>
              <button className="btn-primary w-full" aria-label="Confirm change"
                disabled={adjust.isPending}
                onClick={() => adjust.mutate()}>
                {adjust.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
                {t("Record", "Simpan")}
              </button>
            </div>
          )}

          {panel === "dispose" && (
            <div className="pt-2 space-y-2 border-t border-ink-100">
              <label className="block">
                <span className="label">{t("Proceeds", "Hasil pelepasan")}</span>
                <input className="input" type="number" min="0" value={proceeds}
                  aria-label="Proceeds"
                  onChange={(e) => setProceeds(e.target.value)} />
              </label>
              {Number(proceeds || 0) > 0 && (
                <div>
                  <span className="label">{t("Received into", "Diterima di")}</span>
                  <AccountPicker value={proceedsAcc} onChange={setProceedsAcc}
                    ariaLabel="Akun penerimaan" />
                </div>
              )}
              <div>
                <span className="label">
                  {t("Gain/loss account", "Akun laba/rugi pelepasan")}
                </span>
                <AccountPicker value={gainAcc} onChange={setGainAcc}
                  ariaLabel="Akun Laba/Rugi Pelepasan" />
              </div>
              <label className="block">
                <span className="label">{t("Why", "Alasan")}</span>
                <input className="input" value={reason} aria-label="Disposal reason"
                  onChange={(e) => setReason(e.target.value)} />
              </label>
              <p className="text-[11px] muted">
                {t(`Book value now is ${idr(a.book_value)}. Anything above it is a gain, anything below a loss.`,
                   `Nilai buku sekarang ${idr(a.book_value)}. Di atasnya laba, di bawahnya rugi.`)}
              </p>
              <button className="btn-danger w-full" aria-label="Confirm disposal"
                disabled={!gainAcc || dispose.isPending}
                onClick={() => dispose.mutate()}>
                {dispose.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
                {t("Take it off the books", "Lepaskan")}
              </button>
            </div>
          )}
        </section>
      </div>

      <section className="table-shell">
        <div className="px-4 py-2 flex items-center gap-2 border-b border-ink-200">
          <span className="overline flex-1">
            {t("Depreciation schedule", "Jadwal penyusutan")}
          </span>
          {([["commercial", t("Commercial", "Komersial")],
             ["tax", t("Tax", "Fiskal")]] as const).map(([k, label]) => (
            <button key={k}
              className={clsx("px-2.5 py-1 text-xs rounded-lg border",
                scope === k ? "border-brand-500 bg-brand-50 text-brand-700"
                            : "border-ink-200 muted")}
              onClick={() => setScope(k)}>{label}</button>
          ))}
        </div>
        {scope === "tax" && !a.tax_category_name ? (
          <p className="p-6 text-sm muted">
            {t("This asset has no tax category, so there is no fiscal schedule to show.",
               "Aset ini belum punya kategori pajak, jadi belum ada jadwal fiskal.")}
          </p>
        ) : sched.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !sched.data?.items.length ? (
          <p className="p-6 text-sm muted">
            {t("Nothing to depreciate.", "Tidak ada yang disusutkan.")}
          </p>
        ) : (
          <>
            <p className="px-4 py-2 text-xs muted flex items-center gap-1.5">
              <TrendingDown size={13} />
              {sched.data.method === "declining_balance"
                ? t("Declining balance — heavier early, and the rate applies to the value at the start of each year.",
                    "Saldo menurun — lebih besar di awal; tarif dihitung dari nilai awal tahun.")
                : t("Straight line — the same amount every month.",
                    "Garis lurus — jumlahnya sama setiap bulan.")}
              {" · "}{sched.data.useful_life_months} {t("months", "bulan")}
              {" · "}{t("total", "total")} {idr(sched.data.total)}
            </p>
            <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
              <table className="w-full">
                <thead className="sticky top-0 bg-white">
                  <tr>
                    <th className="th">{t("Period", "Periode")}</th>
                    <th className="th text-right">{t("Amount", "Penyusutan")}</th>
                    <th className="th text-right">{t("Accumulated", "Akumulasi")}</th>
                    <th className="th text-right">{t("Book value", "Nilai buku")}</th>
                  </tr>
                </thead>
                <tbody>
                  {sched.data.items.map((row) => (
                    <tr key={`${row.period_year}-${row.period_month}`}
                      className={clsx("border-t border-ink-100",
                        row.already_written_off && "opacity-50")}>
                      <td className="td text-xs">
                        {MONTHS_ID[row.period_month - 1]} {row.period_year}
                        {row.already_written_off && (
                          <span className="ml-1.5 chip bg-ink-100 text-ink-500">
                            {t("before this system", "sebelum sistem ini")}
                          </span>
                        )}
                      </td>
                      <td className="td text-right tabular-nums">{idr(row.amount)}</td>
                      <td className="td text-right tabular-nums muted">
                        {idr(row.accumulated)}
                      </td>
                      <td className="td text-right tabular-nums">{idr(row.book_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="table-shell">
          <div className="px-4 py-2 overline border-b border-ink-200">
            {t("Posted", "Sudah diposting")}
          </div>
          {!a.entries.length ? (
            <p className="p-4 text-sm muted">
              {t("No month has been posted against it yet.",
                 "Belum ada penyusutan yang diposting.")}
            </p>
          ) : (
            <table className="w-full">
              <tbody>
                {a.entries.map((e) => (
                  <tr key={`${e.period_year}-${e.period_month}`}
                    className="border-t border-ink-100">
                    <td className="td text-xs">
                      {MONTHS_ID[e.period_month - 1]} {e.period_year}
                    </td>
                    <td className="td text-right tabular-nums">{idr(e.amount)}</td>
                    <td className="td text-right tabular-nums muted">
                      {idr(e.book_value_after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="table-shell">
          <div className="px-4 py-2 overline border-b border-ink-200">
            {t("What happened to it", "Riwayat perubahan")}
          </div>
          {!a.changes.length ? (
            <p className="p-4 text-sm muted">
              {t("Nothing has changed since it was entered.",
                 "Belum ada perubahan.")}
            </p>
          ) : (
            <ul className="divide-y divide-ink-100">
              {a.changes.map((ch, i) => (
                <li key={i} className="px-4 py-2 text-sm">
                  <div className="flex gap-2 items-baseline">
                    <span className="chip bg-ink-100 text-ink-700">
                      {ch.kind === "move" ? t("moved", "pindah")
                        : ch.kind === "life" ? t("life", "masa manfaat")
                        : ch.kind === "cost" ? t("cost", "nilai")
                        : ch.kind}
                    </span>
                    <span className="text-xs muted">{ch.changed_on}</span>
                  </div>
                  <div className="text-xs mt-0.5">
                    <span className="muted line-through">
                      {ch.before_value ?? "—"}
                    </span>
                    {" → "}
                    <span className="font-medium">{ch.after_value ?? "—"}</span>
                    {ch.memo && <span className="muted"> · {ch.memo}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
