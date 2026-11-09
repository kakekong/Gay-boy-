import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Hash, Loader2, Pencil, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface Row { id: string; name: string; old: string; new: string; changes: boolean; entered: string | null }
interface Group {
  customer_id: string; customer: string; code: string; items: Row[];
  changing: number; duplicates: number;
}
interface Plan {
  groups: Group[]; renaming: number; unowned: number;
  documents: { type: string; number: string; link: string | null; lines: number }[];
}

const errText = (e: any, fallback: string) =>
  e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? fallback;

/**
 * Part codes in one format, numbered by the order parts came in.
 *
 * Each customer has a series: MTP-0001, MTP-0002 … The first part that
 * customer's requests brought in is 0001, the next 0002 — so MTP-0010 and
 * mtp-010 typed for two different parts become MTP-0010 and MTP-0011.
 * Choose the customers, preview the documents it rewrites, confirm. Old
 * codes stay on each part, so a label or line typed from one still finds it.
 */
export function SkuRecodePanel({ onClose }: { onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const plan = useQuery({
    queryKey: ["inventory-recode"],
    queryFn: () => api.get("/inventory/recode").then((r) => r.data as Plan),
  });
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<Plan | null>(null);
  const [done, setDone] = useState<{ renamed: number; documents: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [code, setCode] = useState("");

  // Start with every series that has something to change.
  useEffect(() => {
    if (plan.data) setChosen(new Set(plan.data.groups.filter((g) => g.changing).map((g) => g.customer_id)));
  }, [plan.data]);
  useEffect(() => { setPreview(null); }, [chosen]);

  const ids = useMemo(() => [...chosen], [chosen]);
  const renaming = (plan.data?.groups ?? []).filter((g) => chosen.has(g.customer_id))
    .reduce((n, g) => n + g.changing, 0);

  const doPreview = useMutation({
    mutationFn: () => api.post("/inventory/recode/preview", { customer_ids: ids }).then((r) => r.data as Plan),
    onSuccess: (d) => { setPreview(d); setErr(null); },
    onError: (e) => setErr(errText(e, t("Couldn't preview", "Gagal pratinjau"))),
  });
  const apply = useMutation({
    mutationFn: () => api.post("/inventory/recode", { customer_ids: ids }).then((r) => r.data),
    onSuccess: (d) => {
      setDone(d); setPreview(null); setErr(null);
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["inventory-recode"] });
    },
    onError: (e) => setErr(errText(e, t("Couldn't renumber", "Gagal menomori ulang"))),
  });
  const saveCode = useMutation({
    mutationFn: ({ id, c }: { id: string; c: string }) => api.post(`/customers/${id}/sku-code`, { code: c }),
    onSuccess: () => { setEditing(null); setErr(null); qc.invalidateQueries({ queryKey: ["inventory-recode"] }); },
    onError: (e) => setErr(errText(e, t("Couldn't change the code", "Gagal mengubah kode"))),
  });

  const toggle = (set: Set<string>, id: string) => {
    const n = new Set(set);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Hash size={15} className="text-brand-600" />
            {t("Reorganize part codes", "Rapikan kode barang")}
          </div>
          <div className="text-[11px] text-ink-500 mt-1 max-w-2xl leading-relaxed">
            {t("Each customer's parts are numbered in one format — its code, a dash, four digits — in the order they came into the system: the first is 0001, the next 0002. Two parts under one number (MTP-0010 and mtp-010) become MTP-0010 and MTP-0011. Every document line with an old code gets the new one; the old code stays on the part, so a label or a line typed from it still finds it.",
               "Barang tiap pelanggan dinomori dalam satu format — kodenya, tanda hubung, empat digit — sesuai urutan masuk ke sistem: yang pertama 0001, berikutnya 0002. Dua barang dengan satu nomor (MTP-0010 dan mtp-010) menjadi MTP-0010 dan MTP-0011. Setiap baris dokumen dengan kode lama diganti kode baru; kode lama tetap tersimpan di barangnya, jadi label atau baris yang memakainya tetap ketemu.")}
          </div>
        </div>
        <button className="btn-ghost" onClick={onClose} aria-label={t("Close", "Tutup")}><X size={15} /></button>
      </div>

      {err && <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 text-red-800 text-sm px-3 py-2">{err}</div>}
      {done && (
        <div className="mx-5 mt-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-sm px-3 py-2 flex items-center gap-2">
          <CheckCircle2 size={14} />
          {t(`Renumbered ${done.renamed} parts; ${done.documents} documents now carry the new codes.`,
             `${done.renamed} barang dinomori ulang; ${done.documents} dokumen kini memakai kode baru.`)}
        </div>
      )}

      {plan.isLoading ? (
        <div className="p-6 text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Reading the codes…", "Membaca kode…")}</div>
      ) : (
        <div className="divide-y divide-ink-100">
          {(plan.data?.groups ?? []).map((g) => {
            const isOpen = open.has(g.customer_id);
            const rows = isOpen ? g.items : g.items.filter((r) => r.changes).slice(0, 5);
            return (
              <div key={g.customer_id} className="px-5 py-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <input type="checkbox" className="accent-brand-600" disabled={!g.changing}
                    aria-label={t(`Renumber ${g.customer}`, `Nomori ulang ${g.customer}`)}
                    checked={chosen.has(g.customer_id)}
                    onChange={() => setChosen((s) => toggle(s, g.customer_id))} />
                  {editing === g.customer_id ? (
                    <span className="inline-flex items-center gap-1.5">
                      <input className="input text-xs w-24 font-mono uppercase" value={code} autoFocus
                        aria-label={t("Customer code", "Kode pelanggan")}
                        onChange={(e) => setCode(e.target.value.toUpperCase())} />
                      <button className="btn-primary text-xs px-2 py-1" disabled={!code || saveCode.isPending}
                        onClick={() => saveCode.mutate({ id: g.customer_id, c: code })}>{t("Save", "Simpan")}</button>
                      <button className="btn-ghost text-xs px-2 py-1" onClick={() => setEditing(null)}>{t("Cancel", "Batal")}</button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <span className="font-mono text-sm font-semibold">{g.code}</span>
                      <button className="text-ink-400 hover:text-brand-700" title={t("Change this customer's code", "Ubah kode pelanggan ini")}
                        onClick={() => { setEditing(g.customer_id); setCode(g.code); }}><Pencil size={11} /></button>
                    </span>
                  )}
                  <span className="text-sm">{g.customer}</span>
                  <span className="text-[11px] muted">{g.items.length} {t("parts", "barang")}</span>
                  {g.duplicates > 0 && (
                    <span className="chip bg-amber-50 text-amber-800 text-[11px]">
                      {g.duplicates} {t("share a number", "bernomor sama")}
                    </span>
                  )}
                  <span className={clsx("ml-auto text-[11px]", g.changing ? "text-brand-700" : "text-emerald-700")}>
                    {g.changing ? t(`${g.changing} codes change`, `${g.changing} kode berubah`)
                                : t("Already in order", "Sudah rapi")}
                  </span>
                </div>
                {rows.length > 0 && (
                  <div className="mt-2 ml-7 overflow-x-auto">
                    <table className="text-xs w-full">
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.id} className={clsx(!r.changes && "text-ink-400")}>
                            <td className="py-0.5 pr-3 font-mono whitespace-nowrap">{r.old}</td>
                            <td className="py-0.5 pr-3"><ArrowRight size={11} className="text-ink-400" /></td>
                            <td className={clsx("py-0.5 pr-4 font-mono whitespace-nowrap", r.changes && "font-semibold text-brand-700")}>{r.new}</td>
                            <td className="py-0.5 pr-4 truncate max-w-[22rem]">{r.name}</td>
                            <td className="py-0.5 muted whitespace-nowrap tabular-nums">
                              {r.entered ? new Date(r.entered).toLocaleDateString("id-ID") : ""}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <button className="ml-7 mt-1 text-[11px] text-ink-500 hover:text-brand-700 inline-flex items-center gap-1"
                  onClick={() => setOpen((s) => toggle(s, g.customer_id))}>
                  {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {isOpen ? t("Show only what changes", "Tampilkan yang berubah saja")
                          : t(`Show all ${g.items.length}, in order`, `Tampilkan semua ${g.items.length}, berurutan`)}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="px-5 py-3 border-t border-ink-100 bg-ink-50/50 space-y-2">
        {(plan.data?.unowned ?? 0) > 0 && (
          <div className="text-[11px] muted">
            {t(`${plan.data!.unowned} parts belong to no customer (stock, or imported) and keep their codes.`,
               `${plan.data!.unowned} barang tidak milik pelanggan mana pun (stok, atau hasil impor) dan tetap memakai kodenya.`)}
          </div>
        )}
        {preview && (
          <div className="text-xs space-y-1">
            <div className="font-medium">
              {t(`${preview.renaming} parts renumbered; ${preview.documents.length} documents rewritten:`,
                 `${preview.renaming} barang dinomori ulang; ${preview.documents.length} dokumen diubah:`)}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 max-h-32 overflow-y-auto">
              {preview.documents.map((d, i) => (
                <span key={i} className="whitespace-nowrap">
                  <span className="muted">{d.type}</span>{" "}
                  {d.link ? <Link to={d.link} className="font-mono text-brand-700 hover:underline">{d.number}</Link>
                          : <span className="font-mono">{d.number}</span>}
                  <span className="muted"> ×{d.lines}</span>
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="flex gap-2 justify-end">
          {!preview ? (
            <button className="btn-ghost" disabled={!ids.length || !renaming || doPreview.isPending}
              onClick={() => doPreview.mutate()}>
              {doPreview.isPending && <Loader2 size={13} className="animate-spin" />}
              {t(`Preview ${renaming} changes`, `Pratinjau ${renaming} perubahan`)}
            </button>
          ) : (
            <button className="btn-primary" disabled={apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending && <Loader2 size={13} className="animate-spin" />}
              {t(`Renumber ${preview.renaming} parts`, `Nomori ulang ${preview.renaming} barang`)}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
