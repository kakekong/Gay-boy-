import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Undo2, Loader2, History, AlertTriangle, CheckCircle2, Link2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, locale } from "@/store/lang";

interface Run {
  id: string; kind: string; filename: string | null;
  created_count: number; still_present: number;
  created_at: string; by: string; undone_at: string | null;
}
interface UndoPreview {
  id: string; kind: string; filename: string | null;
  created_count: number; still_present: number;
  removable: number; blocked: number;
  dependents: { type: string; type_label: string; id: string;
                number: string | null }[];
  counts: Record<string, number>;
  confirm_phrase: string;
}

const KIND: Record<string, [string, string]> = {
  customers: ["Customers", "Pelanggan"],
  items: ["Parts", "Barang"],
  accounts: ["Accounts", "Akun"],
  quotations: ["Quotations", "Penawaran"],
};

/**
 * Every import, and a way to take one back out.
 *
 * The record picker in Clear test data can already delete anything, but nobody
 * is going to tick 87 customers by hand because a column mapped wrong. So an
 * import is undoable as one act.
 *
 * The care is in what undo *refuses* to do. By the time somebody reaches for
 * it, staff may have filed work against the imported records — a price request
 * against a customer, a PO against a quotation. Those are kept and named, and
 * taking them needs a second, separate yes.
 */
export default function ImportRuns() {
  const t = useT();
  const qc = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");
  const [withDeps, setWithDeps] = useState(false);
  const [done, setDone] = useState<{ removed: number; left: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const runs = useQuery({
    queryKey: ["import-runs"],
    queryFn: () => api.get("/imports/runs").then((r) => r.data as Run[]),
  });

  const preview = useQuery({
    queryKey: ["import-undo", openId],
    queryFn: () => api.get(`/imports/runs/${openId}/undo-preview`)
      .then((r) => r.data as UndoPreview),
    enabled: !!openId,
  });

  const fail = (e: any) => setErr(
    e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail
    ?? t("Something went wrong", "Terjadi kesalahan"),
  );

  const undo = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("confirm", phrase);
      fd.append("include_dependents", String(withDeps));
      return api.post(`/imports/runs/${openId}/undo`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then((r) => r.data as { removed: number; left_alone: number });
    },
    onSuccess: (d) => {
      setDone({ removed: d.removed, left: d.left_alone });
      setPhrase(""); setWithDeps(false); setErr(null); setOpenId(null);
      qc.invalidateQueries({ queryKey: ["import-runs"] });
    },
    onError: fail,
  });

  const rows = runs.data ?? [];
  const p = preview.data;
  const armed = !!p && phrase === p.confirm_phrase && (p.removable > 0 || withDeps);

  return (
    <div className="card overflow-hidden">
      <header className="px-4 py-3 border-b border-ink-100 flex items-center gap-2">
        <History size={15} className="text-brand-600" />
        <span className="font-semibold">
          {t("Recent imports", "Impor terakhir")}
        </span>
        <span className="ml-auto text-xs muted">
          {t("Undo removes exactly what that run created.",
             "Batalkan menghapus tepat yang dibuat oleh proses itu.")}
        </span>
      </header>

      {err && (
        <div className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50
                        px-3 py-2 text-sm text-red-800">{err}</div>
      )}
      {done && (
        <div className="mx-4 mt-3 rounded-lg border border-emerald-200 bg-emerald-50
                        px-3 py-2 text-sm text-emerald-800 flex items-start gap-2">
          <CheckCircle2 size={14} className="shrink-0 mt-0.5" />
          <div>
            {t(`Removed ${done.removed} records.`, `${done.removed} data dihapus.`)}
            {done.left > 0 && " " + t(
              `${done.left} were left because work has been filed against them since.`,
              `${done.left} dibiarkan karena sudah ada pekerjaan yang terkait.`)}
          </div>
        </div>
      )}

      <div className="p-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th>{t("What", "Apa")}</th>
              <th>{t("File", "Berkas")}</th>
              <th className="text-right">{t("Created", "Dibuat")}</th>
              <th className="text-right">{t("Still there", "Masih ada")}</th>
              <th>{t("When", "Kapan")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-ink-100">
                <td className="py-2 font-medium">
                  {KIND[r.kind] ? t(KIND[r.kind][0], KIND[r.kind][1]) : r.kind}
                </td>
                <td className="py-2 text-[12px] muted max-w-[16rem] truncate">
                  {r.filename ?? "—"}
                </td>
                <td className="py-2 text-right spec">{r.created_count}</td>
                <td className="py-2 text-right spec">{r.still_present}</td>
                <td className="py-2 text-[11px] muted whitespace-nowrap">
                  {new Date(r.created_at).toLocaleString(locale(), {
                    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                  })}
                  <div>{r.by}</div>
                </td>
                <td className="py-2 text-right">
                  {r.still_present > 0 ? (
                    <button className="btn-ghost border-ink-200 text-xs"
                            onClick={() => {
                              setOpenId(r.id); setPhrase(""); setWithDeps(false);
                              setDone(null); setErr(null);
                            }}>
                      <Undo2 size={13} /> {t("Undo", "Batalkan")}
                    </button>
                  ) : (
                    <span className="text-[11px] muted">
                      {r.undone_at ? t("undone", "dibatalkan") : t("nothing left", "kosong")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {runs.isLoading && (
              <tr><td colSpan={6} className="py-6 text-center muted">
                <Loader2 size={14} className="animate-spin inline" /> {t("Loading…", "Memuat…")}
              </td></tr>
            )}
            {!runs.isLoading && !rows.length && (
              <tr><td colSpan={6} className="py-6 text-center muted">
                {t("No imports yet.", "Belum ada impor.")}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ── the undo dialog ─────────────────────────────────────────────── */}
      {openId && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4">
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
               onClick={() => setOpenId(null)} />
          <div className="relative w-full max-w-lg bg-white dark:bg-ink-800 rounded-2xl
                          shadow-card max-h-[85vh] overflow-y-auto">
            <header className="p-4 border-b border-ink-100 dark:border-white/10
                               flex items-center gap-2">
              <Undo2 size={16} className="text-accent-500" />
              <span className="text-lg font-semibold">
                {t("Undo this import", "Batalkan impor ini")}
              </span>
            </header>

            {preview.isLoading || !p ? (
              <div className="p-8 text-center muted">
                <Loader2 size={16} className="animate-spin inline" /> {t("Loading…", "Memuat…")}
              </div>
            ) : (
              <div className="p-4 space-y-3">
                <p className="text-sm">
                  {t(`This import created ${p.created_count} records; ${p.still_present} are still here.`,
                     `Impor ini membuat ${p.created_count} data; ${p.still_present} masih ada.`)}
                </p>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                    <div className="text-xl font-semibold spec">{p.removable}</div>
                    <div className="text-[11px] muted">{t("Will be removed", "Akan dihapus")}</div>
                  </div>
                  <div className={clsx("rounded-lg border px-3 py-2",
                    p.blocked ? "border-amber-200 bg-amber-50" : "border-ink-200")}>
                    <div className="text-xl font-semibold spec">{p.blocked}</div>
                    <div className="text-[11px] muted">{t("Kept back", "Dipertahankan")}</div>
                  </div>
                </div>

                {p.blocked > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50
                                  px-3 py-2 text-sm text-amber-900">
                    <div className="font-semibold flex items-center gap-2">
                      <Link2 size={14} />
                      {t("Somebody has worked on these since the import",
                         "Sudah ada pekerjaan terkait sejak impor")}
                    </div>
                    <div className="mt-1 space-y-0.5">
                      {p.dependents.slice(0, 8).map((x) => (
                        <div key={x.id} className="text-[12px]">
                          {x.type_label} <b>{x.number ?? x.id.slice(0, 8)}</b>
                        </div>
                      ))}
                      {p.dependents.length > 8 && (
                        <div className="text-[12px] muted">
                          {t(`…and ${p.dependents.length - 8} more`,
                             `…dan ${p.dependents.length - 8} lagi`)}
                        </div>
                      )}
                    </div>
                    <label className="mt-2 flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" className="mt-0.5" checked={withDeps}
                             onChange={(e) => setWithDeps(e.target.checked)} />
                      <span>
                        {t("Remove those too, along with everything filed against them.",
                           "Hapus itu juga, beserta semua yang terkait dengannya.")}
                      </span>
                    </label>
                  </div>
                )}

                <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={14} className="text-accent-500 shrink-0 mt-0.5" />
                    <span className="muted">
                      {t("Records added by hand, and anything from a different import, are not touched.",
                         "Data yang dibuat manual, dan dari impor lain, tidak tersentuh.")}
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <code className="rounded-lg bg-ink-100 dark:bg-white/10 px-2 py-1
                                   text-sm font-mono">{p.confirm_phrase}</code>
                  <input className="input max-w-[12rem] font-mono" value={phrase}
                         onChange={(e) => setPhrase(e.target.value)}
                         placeholder={p.confirm_phrase} autoComplete="off" />
                  <button className="btn-ghost ml-auto" onClick={() => setOpenId(null)}>
                    {t("Cancel", "Batal")}
                  </button>
                  <button
                    className={clsx(armed ? "btn-danger" : "btn-ghost border-ink-200")}
                    disabled={!armed || undo.isPending}
                    onClick={() => undo.mutate()}
                  >
                    {undo.isPending
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Undo2 size={14} />}
                    {t(`Remove ${withDeps ? p.still_present : p.removable}`,
                       `Hapus ${withDeps ? p.still_present : p.removable}`)}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
