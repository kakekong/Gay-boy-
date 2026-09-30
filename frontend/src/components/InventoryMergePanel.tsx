import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Combine, Loader2, AlertTriangle, ArrowRight, CheckCircle2, Plus, X, FileText,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { ProductSuggestInput, type CatalogueHit } from "@/components/ProductSuggestInput";
import { useT } from "@/store/lang";

interface Row {
  id: string; sku: string; name: string; category: string | null; uom: string;
  current_stock: number; movements: number;
}
interface Group { key: string; items: Row[]; keep: string; include: Set<string>; on: boolean }
interface Plan {
  keep: Row; merge: Row[];
  after: { sku: string; name: string; uom: string; current_stock: number; movements: number;
           fills: Record<string, any>; aliases: { sku?: string; name?: string }[] };
  documents: { type: string; number: string; link: string | null; lines: number }[];
  warnings: string[];
}

const FILL_LABEL: Record<string, [string, string]> = {
  category: ["Category", "Kategori"], link: ["Link", "Tautan"],
  location: ["Location", "Lokasi"], supplier_hint: ["Supplier", "Supplier"],
  notes: ["Notes", "Catatan"], unit_cost: ["Unit cost", "Harga satuan"],
  cost_currency: ["Cost currency", "Mata uang harga"], cost_fx_rate: ["Rate", "Kurs"],
  reorder_point: ["Reorder at", "Titik pesan ulang"], reorder_qty: ["Reorder qty", "Jumlah pesan ulang"],
};

const fmt = (n: number) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 4 }).format(n);

/**
 * Merge catalogue items that are the same part typed differently.
 *
 * Three steps, like deleting records: choose, preview, confirm. The groups
 * are the server's guess (same letters and digits once case, spacing and
 * punctuation are ignored); each can be switched off, its kept item changed,
 * and members left out. A pair the guess missed is added by hand. The preview
 * is computed by the same code that runs the merge, and nothing is written
 * until the phrase is typed.
 */
export function InventoryMergePanel({ onClose }: { onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [preview, setPreview] = useState<{ plans: Plan[]; totals: any } | null>(null);
  const [phrase, setPhrase] = useState("");
  const [done, setDone] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const found = useQuery({
    queryKey: ["inventory-duplicates"],
    queryFn: () => api.get("/inventory/duplicates").then((r) => r.data.groups as
      { keep_id: string; items: Row[] }[]),
  });
  // The editable choice starts from the server's suggestion, and starts
  // over whenever that is re-read (after a merge, the merged groups are gone).
  useEffect(() => {
    if (!found.data) return;
    setGroups(found.data.map((g, i) => ({
      key: `auto-${i}`, items: g.items, keep: g.keep_id,
      include: new Set(g.items.map((x) => x.id)), on: true,
    })));
  }, [found.data, found.dataUpdatedAt]);

  const chosen = useMemo(() => (groups ?? []).filter((g) => g.on).map((g) => ({
    keep_id: g.keep,
    merge_ids: g.items.map((x) => x.id).filter((id) => id !== g.keep && g.include.has(id)),
  })).filter((g) => g.merge_ids.length), [groups]);

  const change = (key: string, fn: (g: Group) => Group) => {
    setPreview(null); setPhrase("");            // the plan is stale once the choice moves
    setGroups((gs) => (gs ?? []).map((g) => (g.key === key ? fn(g) : g)));
  };

  const errMsg = (e: any) => e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail ?? t("Something went wrong", "Terjadi kesalahan");
  const runPreview = useMutation({
    mutationFn: () => api.post("/inventory/merge/preview", { groups: chosen }).then((r) => r.data),
    onSuccess: (d) => { setErr(null); setPreview(d); setPhrase(""); },
    onError: (e: any) => setErr(errMsg(e)),
  });
  const run = useMutation({
    mutationFn: () => api.post("/inventory/merge", { groups: chosen }).then((r) => r.data),
    onSuccess: (d) => {
      setErr(null); setDone(d); setPreview(null);
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["inventory-summary"] });
      qc.invalidateQueries({ queryKey: ["inventory-history"] });
      qc.invalidateQueries({ queryKey: ["inventory-duplicates"] });
      setGroups(null);
    },
    onError: (e: any) => setErr(errMsg(e)),
  });

  const removing = chosen.reduce((n, g) => n + g.merge_ids.length, 0);
  const confirmPhrase = `MERGE ${removing}`;

  // ── adding a pair by hand ──
  const [manKeep, setManKeep] = useState<CatalogueHit | null>(null);
  const [manDup, setManDup] = useState<CatalogueHit | null>(null);
  const [manKeepText, setManKeepText] = useState("");
  const [manDupText, setManDupText] = useState("");
  const toRow = (h: CatalogueHit): Row => ({ id: h.id, sku: h.sku, name: h.name,
    category: h.category, uom: h.uom ?? "", current_stock: h.current_stock, movements: 0 });
  const addManual = () => {
    if (!manKeep || !manDup || manKeep.id === manDup.id) return;
    const used = new Set((groups ?? []).flatMap((g) => g.items.map((x) => x.id)));
    if (used.has(manKeep.id) || used.has(manDup.id)) {
      setErr(t("One of those items is already in a group below — change that group instead.",
               "Salah satu barang itu sudah ada di grup di bawah — ubah grup itu saja."));
      return;
    }
    setErr(null); setPreview(null); setPhrase("");
    setGroups((gs) => [...(gs ?? []), {
      key: `manual-${manKeep.id}-${manDup.id}`, items: [toRow(manKeep), toRow(manDup)],
      keep: manKeep.id, include: new Set([manKeep.id, manDup.id]), on: true,
    }]);
    setManKeep(null); setManDup(null); setManKeepText(""); setManDupText("");
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Combine size={15} className="text-brand-600" />
            {t("Merge duplicate items", "Gabungkan barang duplikat")}
          </div>
          <div className="text-[11px] text-ink-500 mt-1 max-w-2xl leading-relaxed">
            {t("The same part typed two ways became two items, each holding part of the stock and part of the history. Merging moves the history and stock onto the item you keep, puts its SKU on every document line that named the other one, and deletes the duplicate. Its old SKU and name are remembered, so a later line using them still lands on the kept item. Preview first — nothing changes until you confirm.",
               "Satu barang yang diketik dua cara menjadi dua item, masing-masing memegang sebagian stok dan riwayat. Penggabungan memindahkan riwayat dan stok ke item yang disimpan, memasang SKU-nya di setiap baris dokumen yang menyebut item lainnya, lalu menghapus duplikatnya. SKU dan nama lamanya diingat, sehingga baris berikutnya yang memakainya tetap masuk ke item yang disimpan. Pratinjau dulu — tidak ada yang berubah sebelum Anda konfirmasi.")}
          </div>
        </div>
        <button className="btn-ghost text-xs" onClick={onClose}>{t("Close", "Tutup")}</button>
      </div>

      {err && (
        <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{err}</div>
      )}
      {done && (
        <div className="mx-5 mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 flex items-center gap-2">
          <CheckCircle2 size={15} />
          {t(`Merged — ${done.items_removed} duplicate item(s) removed, ${done.documents} document(s) updated.`,
             `Digabung — ${done.items_removed} barang duplikat dihapus, ${done.documents} dokumen diperbarui.`)}
        </div>
      )}

      {/* ── 1. choose ─────────────────────────────────────────────── */}
      <div className="p-5 space-y-3">
        <div className="text-[11px] uppercase tracking-wide muted">
          {t("1 · Choose what to merge", "1 · Pilih yang digabung")}
        </div>
        {found.isLoading || groups === null ? (
          <div className="text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Looking for duplicates…", "Mencari duplikat…")}</div>
        ) : !(groups ?? []).length ? (
          <div className="text-sm muted">
            {t("No items look like duplicates of each other. If two are the same part under different names, add them by hand below.",
               "Tidak ada barang yang tampak duplikat. Jika dua barang sebenarnya sama dengan nama berbeda, tambahkan manual di bawah.")}
          </div>
        ) : (
          <div className="space-y-2">
            {(groups ?? []).map((g) => (
              <div key={g.key} className={clsx("rounded-lg border", g.on ? "border-ink-200" : "border-ink-100 opacity-60")}>
                <label className="flex items-center gap-2 px-3 py-2 border-b border-ink-100 text-sm cursor-pointer">
                  <input type="checkbox" checked={g.on}
                    onChange={(e) => change(g.key, (x) => ({ ...x, on: e.target.checked }))} />
                  <span className="font-medium">{g.items.find((x) => x.id === g.keep)?.name}</span>
                  <span className="text-xs muted">· {g.items.length} {t("items", "barang")}</span>
                  {g.key.startsWith("manual") && (
                    <button type="button" className="ml-auto text-ink-400 hover:text-red-600"
                      aria-label={t("Remove this group", "Hapus grup ini")}
                      onClick={(e) => { e.preventDefault(); setPreview(null);
                        setGroups((gs) => (gs ?? []).filter((x) => x.key !== g.key)); }}>
                      <X size={14} />
                    </button>
                  )}
                </label>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="text-[10px] uppercase muted">
                      <th className="px-3 py-1 text-left">{t("Keep", "Simpan")}</th>
                      <th className="px-3 py-1 text-left">{t("Merge", "Gabung")}</th>
                      <th className="px-3 py-1 text-left">SKU</th>
                      <th className="px-3 py-1 text-left">{t("Name", "Nama")}</th>
                      <th className="px-3 py-1 text-right">{t("Stock", "Stok")}</th>
                      <th className="px-3 py-1 text-right">{t("History", "Riwayat")}</th>
                    </tr></thead>
                    <tbody>
                      {g.items.map((x) => (
                        <tr key={x.id} className="border-t border-ink-100">
                          <td className="px-3 py-1.5">
                            <input type="radio" name={`keep-${g.key}`} checked={g.keep === x.id}
                              disabled={!g.on} aria-label={t(`Keep ${x.sku}`, `Simpan ${x.sku}`)}
                              onChange={() => change(g.key, (y) => ({ ...y, keep: x.id }))} />
                          </td>
                          <td className="px-3 py-1.5">
                            <input type="checkbox" disabled={!g.on || g.keep === x.id}
                              aria-label={t(`Merge ${x.sku}`, `Gabung ${x.sku}`)}
                              checked={g.keep !== x.id && g.include.has(x.id)}
                              onChange={(e) => change(g.key, (y) => {
                                const inc = new Set(y.include);
                                e.target.checked ? inc.add(x.id) : inc.delete(x.id);
                                return { ...y, include: inc };
                              })} />
                          </td>
                          <td className="px-3 py-1.5 font-mono text-xs">
                            <Link to={`/inventory/${x.id}`} className="text-brand-700 hover:underline">{x.sku}</Link>
                          </td>
                          <td className="px-3 py-1.5">{x.name}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmt(x.current_stock)} {x.uom}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums muted">{x.movements}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* By hand: two items the guess did not pair up. */}
        <div className="rounded-lg border border-dashed border-ink-200 p-3 space-y-2">
          <div className="text-xs font-medium">{t("Add two items by hand", "Tambah dua barang secara manual")}</div>
          <div className="grid md:grid-cols-[1fr_auto_1fr_auto] gap-2 items-center">
            <ProductSuggestInput value={manKeepText}
              placeholder={t("Keep this item — type the product or SKU", "Simpan barang ini — ketik produk atau SKU")}
              ariaLabel={t("Item to keep", "Barang yang disimpan")}
              onChange={(v) => { setManKeepText(v); setManKeep(null); }}
              onPick={(h) => { setManKeep(h); setManKeepText(`${h.sku} · ${h.name}`); }} />
            <span className="text-xs muted text-center">{t("absorbs", "menyerap")}</span>
            <ProductSuggestInput value={manDupText}
              placeholder={t("…this duplicate — type the product or SKU", "…duplikat ini — ketik produk atau SKU")}
              ariaLabel={t("Duplicate to merge in", "Duplikat yang digabung")}
              onChange={(v) => { setManDupText(v); setManDup(null); }}
              onPick={(h) => { setManDup(h); setManDupText(`${h.sku} · ${h.name}`); }} />
            <button className="btn-ghost" onClick={addManual}
              disabled={!manKeep || !manDup || manKeep.id === manDup.id}>
              <Plus size={14} /> {t("Add", "Tambah")}
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button className="btn-primary" disabled={!chosen.length || runPreview.isPending}
            onClick={() => runPreview.mutate()}>
            {runPreview.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
            {t("Preview the merge", "Pratinjau penggabungan")}
          </button>
          <span className="text-xs muted">
            {t(`${chosen.length} group(s) chosen · ${removing} item(s) would be merged away`,
               `${chosen.length} grup dipilih · ${removing} barang akan digabungkan`)}
          </span>
        </div>
      </div>

      {/* ── 2. preview ────────────────────────────────────────────── */}
      {preview && (
        <div className="p-5 border-t border-ink-100 space-y-4">
          <div className="text-[11px] uppercase tracking-wide muted">
            {t("2 · What will change", "2 · Yang akan berubah")}
          </div>
          <div className="grid grid-cols-3 gap-3">
            {[
              [preview.totals.items_removed, t("items deleted", "barang dihapus")],
              [preview.totals.movements_moved, t("history entries moved", "riwayat dipindah")],
              [preview.totals.documents, t("documents updated", "dokumen diperbarui")],
            ].map(([n, label], i) => (
              <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                <div className="text-xl font-semibold tabular-nums">{n}</div>
                <div className="text-[11px] muted">{label}</div>
              </div>
            ))}
          </div>

          {preview.plans.map((p) => (
            <div key={p.keep.id} className="rounded-lg border border-ink-200 overflow-hidden">
              <div className="px-3 py-2 bg-ink-50/60 text-sm font-medium flex items-center gap-2 flex-wrap">
                {p.merge.map((m) => (
                  <span key={m.id} className="line-through text-ink-500">
                    <span className="font-mono text-xs">{m.sku}</span> {m.name}
                  </span>
                ))}
                <ArrowRight size={13} className="text-ink-400" />
                <span><span className="font-mono text-xs">{p.keep.sku}</span> {p.keep.name}</span>
              </div>
              <div className="p-3 grid md:grid-cols-2 gap-4 text-sm">
                <div className="space-y-1">
                  <div className="text-[10px] uppercase muted">{t("Stock and history", "Stok dan riwayat")}</div>
                  <div className="tabular-nums">
                    {fmt(p.keep.current_stock)}
                    {p.merge.map((m) => <span key={m.id}> + {fmt(m.current_stock)}</span>)}
                    {" = "}<b>{fmt(p.after.current_stock)} {p.after.uom}</b>
                  </div>
                  <div className="text-xs muted">
                    {t(`${p.keep.movements} + ${p.merge.reduce((n, m) => n + m.movements, 0)} history entries, plus one noting the merge — all on ${p.keep.sku}`,
                       `${p.keep.movements} + ${p.merge.reduce((n, m) => n + m.movements, 0)} riwayat, ditambah satu catatan penggabungan — semua di ${p.keep.sku}`)}
                  </div>
                  {Object.keys(p.after.fills).length > 0 && (
                    <div className="text-xs">
                      <span className="muted">{t("Filled in from the duplicate:", "Diisi dari duplikat:")}</span>{" "}
                      {Object.entries(p.after.fills).filter(([, v]) => v != null).map(([k, v]) =>
                        `${t(...(FILL_LABEL[k] ?? [k, k]))}: ${v}`).join(" · ")}
                    </div>
                  )}
                  <div className="text-xs">
                    <span className="muted">{t("Remembered as aliases:", "Diingat sebagai alias:")}</span>{" "}
                    {p.after.aliases.map((a) => [a.sku, a.name].filter(Boolean).join(" ")).join(" · ")}
                  </div>
                  {p.warnings.map((w, i) => (
                    <div key={i} className="text-xs text-amber-800 flex items-start gap-1">
                      <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {w}
                    </div>
                  ))}
                </div>
                <div>
                  <div className="text-[10px] uppercase muted mb-1">
                    {t(`Documents switched to ${p.keep.sku}`, `Dokumen dialihkan ke ${p.keep.sku}`)}
                  </div>
                  {!p.documents.length ? (
                    <div className="text-xs muted">{t("None name the duplicate.", "Tidak ada yang menyebut duplikatnya.")}</div>
                  ) : (
                    <ul className="text-xs space-y-0.5 max-h-40 overflow-auto">
                      {p.documents.map((d, i) => (
                        <li key={i} className="flex items-center gap-2">
                          <span className="muted w-36 shrink-0">{d.type}</span>
                          {d.link ? (
                            <Link to={d.link} className="font-mono text-brand-700 hover:underline">{d.number}</Link>
                          ) : <span className="font-mono">{d.number}</span>}
                          <span className="muted">· {d.lines} {t("line(s)", "baris")}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* ── 3. confirm ──────────────────────────────────────────── */}
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 space-y-2">
            <div className="text-sm text-red-800">
              {t(`This deletes ${removing} item(s) and rewrites the documents listed above. Type the phrase to enable the button.`,
                 `Ini menghapus ${removing} barang dan mengubah dokumen di atas. Ketik frasa untuk mengaktifkan tombolnya.`)}
            </div>
            <div className="font-mono text-sm">{confirmPhrase}</div>
            <div className="flex gap-2 flex-wrap">
              <input className="input max-w-xs" value={phrase} placeholder={confirmPhrase}
                aria-label={t("Confirmation phrase", "Frasa konfirmasi")}
                onChange={(e) => setPhrase(e.target.value)} />
              <button className="btn-primary bg-red-600 hover:bg-red-700"
                disabled={phrase !== confirmPhrase || run.isPending}
                onClick={() => run.mutate()}>
                {run.isPending ? <Loader2 size={14} className="animate-spin" /> : <Combine size={14} />}
                {t("Merge", "Gabungkan")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
