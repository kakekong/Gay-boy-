/**
 * Recently deleted accounts — the director's way back.
 *
 * A deleted account and every line posted to it are saved to a file in the
 * document store (Cloudflare R2). For 7 days a copy is also kept in the
 * database; after that only the file is left — and the file restores the
 * account just the same. Each row says which of the two it would come from.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArchiveRestore, Download, Loader2, RotateCcw } from "lucide-react";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { useT, locale } from "@/store/lang";

interface Archived {
  id: string; account_no: string; name: string; account_type: string;
  balance: number; entry_count: number; reason: string | null;
  deleted_at: string; deleted_by: string | null; kept_until: string;
  in_database: boolean; has_file: boolean;
  restored_at: string | null; restored_by: string | null;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
const when = (s: string) =>
  new Date(s).toLocaleDateString(locale(), { day: "2-digit", month: "short", year: "numeric" });

export function DeletedAccounts() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["account-archives"],
    queryFn: () => api.get("/accounts/archives").then((r) => r.data as Archived[]),
  });
  const restore = useMutation({
    mutationFn: (id: string) => api.post(`/accounts/archives/${id}/restore`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-archives"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (e: any) => alert(e?.response?.data?.errors?.[0]?.message
      ?? t("Couldn't restore it", "Gagal memulihkan")),
  });

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-ink-100">
        <div className="font-semibold flex items-center gap-2">
          <ArchiveRestore size={16} className="text-brand-600" />
          {t("Recently deleted accounts", "Akun yang baru dihapus")}
        </div>
        <p className="text-xs muted mt-0.5">
          {t("Each deleted account is saved with its lines to a file in storage. For 7 days a copy is also kept here; after that it is restored from the file.",
             "Setiap akun yang dihapus disimpan beserta barisnya ke file di penyimpanan. Selama 7 hari salinannya juga disimpan di sini; sesudahnya dipulihkan dari file.")}
        </p>
      </div>
      {q.isLoading ? (
        <div className="p-6 flex justify-center"><Loader2 size={16} className="animate-spin" /></div>
      ) : !q.data?.length ? (
        <div className="p-6 text-center text-sm muted">
          {t("No account has been deleted.", "Belum ada akun yang dihapus.")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Account", "Akun")}</th>
                <th className="th">{t("Deleted", "Dihapus")}</th>
                <th className="th text-right">{t("Balance", "Saldo")}</th>
                <th className="th">{t("Kept", "Disimpan")}</th>
                <th className="th w-48" />
              </tr>
            </thead>
            <tbody>
              {q.data.map((a) => (
                <tr key={a.id} className="border-t border-ink-100 align-top">
                  <td className="td">
                    <span className="font-mono text-xs">{a.account_no}</span> {a.name}
                    <span className="block text-[11px] muted">
                      {a.account_type} · {a.entry_count} {t("lines", "baris")}
                      {a.reason && <> · “{a.reason}”</>}
                    </span>
                  </td>
                  <td className="td whitespace-nowrap">
                    {when(a.deleted_at)}
                    {a.deleted_by && <span className="block text-[11px] muted">{a.deleted_by}</span>}
                  </td>
                  <td className="td text-right tabular-nums whitespace-nowrap">{idr(a.balance)}</td>
                  <td className="td">
                    {a.restored_at ? (
                      <span className="chip bg-emerald-50 text-emerald-700">
                        {t("Restored", "Dipulihkan")} {when(a.restored_at)}
                      </span>
                    ) : a.in_database ? (
                      <span className="chip bg-brand-50 text-brand-700"
                        title={t("Then from the file", "Sesudahnya dari file")}>
                        {t("Here until", "Di sini sampai")} {when(a.kept_until)}
                      </span>
                    ) : (
                      <span className="chip bg-ink-100 text-ink-700">
                        {t("File only", "Hanya file")}
                      </span>
                    )}
                  </td>
                  <td className="td">
                    <div className="flex gap-1 justify-end">
                      {a.has_file && (
                        <button className="btn-ghost text-xs px-2"
                          title={t("Download the archive file", "Unduh file arsip")}
                          onClick={() => downloadFile(`/accounts/archives/${a.id}/file`,
                                                      `${a.account_no}-deleted.json`)}>
                          <Download size={13} />
                        </button>
                      )}
                      {!a.restored_at && (
                        <button className="btn-ghost text-xs"
                          disabled={restore.isPending}
                          onClick={() => {
                            if (confirm(t(`Restore ${a.account_no} ${a.name}, with its balance and lines?`,
                                          `Pulihkan ${a.account_no} ${a.name}, beserta saldo dan barisnya?`)))
                              restore.mutate(a.id);
                          }}>
                          {restore.isPending && restore.variables === a.id
                            ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
                          {a.in_database ? t("Restore", "Pulihkan") : t("Restore from file", "Pulihkan dari file")}
                        </button>
                      )}
                    </div>
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
