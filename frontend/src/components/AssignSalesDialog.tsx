import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  UserCog, Loader2, X, CheckCircle2, ArrowRight, Users,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

export interface AssignTarget {
  id: string;
  company_name: string;
  sales_pic_name?: string | null;
}

interface Rep {
  id: string; full_name: string; email: string;
  role: string; customers: number;
}

/**
 * Hand one or more customers to a different sales rep.
 *
 * Ownership is not a label on the account — it is what decides who can see it,
 * so this dialog says out loud what else moves. The live price requests and
 * quotations follow the customer by default: without them the new rep inherits
 * an account whose open quote they cannot open. Anything already decided (won,
 * lost, rejected) stays with whoever closed it — that is their record, not a
 * property of the account.
 *
 * Each rep's current load is shown next to their name, because "give this to
 * Budi" and "give Budi his fifteenth account" are the same decision.
 */
export function AssignSalesDialog({
  open, onClose, customers, onDone,
}: {
  open: boolean;
  onClose: () => void;
  customers: AssignTarget[];
  onDone?: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [repId, setRepId] = useState<string | "">("");
  const [moveWork, setMoveWork] = useState(true);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<any | null>(null);

  const reps = useQuery({
    queryKey: ["assignable-reps"],
    queryFn: () => api.get("/customers/assignable-reps").then((r) => r.data),
    enabled: open,
  });

  const assign = useMutation({
    mutationFn: () =>
      api.post("/customers/reassign", {
        customer_ids: customers.map((c) => c.id),
        sales_pic_id: repId || null,
        move_open_work: moveWork,
        note: note.trim() || null,
      }).then((r) => r.data),
    onSuccess: (d) => {
      setDone(d);
      setErr(null);
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["customer"] });
      qc.invalidateQueries({ queryKey: ["assignable-reps"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      onDone?.();
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("Something went wrong", "Terjadi kesalahan"),
    ),
  });

  if (!open) return null;

  const list: Rep[] = reps.data?.reps ?? [];
  const chosen = list.find((r) => r.id === repId);
  const many = customers.length > 1;

  const close = () => {
    setDone(null); setErr(null); setNote(""); setRepId("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={close} />
      <div className="relative w-full max-w-lg bg-white dark:bg-ink-800 rounded-2xl
                      shadow-card max-h-[85vh] overflow-y-auto">
        <header className="p-4 border-b border-ink-100 dark:border-white/10 flex items-center gap-2">
          <UserCog size={16} className="text-brand-600" />
          <div className="min-w-0">
            <div className="text-lg font-semibold">
              {t("Who is in charge", "Siapa yang menangani")}
            </div>
            <div className="text-xs muted truncate">
              {many
                ? t(`${customers.length} customers selected`,
                     `${customers.length} pelanggan dipilih`)
                : customers[0]?.company_name}
            </div>
          </div>
          <button className="ml-auto text-ink-400 hover:text-ink-800"
                  onClick={close} aria-label={t("Close", "Tutup")}><X size={16} /></button>
        </header>

        {done ? (
          <div className="p-4 space-y-3">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2
                            text-sm text-emerald-900 flex items-start gap-2">
              <CheckCircle2 size={15} className="shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">
                  {t(`${done.moved} customer${done.moved === 1 ? "" : "s"} handed to ${done.to?.full_name ?? "nobody"}.`,
                     `${done.moved} pelanggan diserahkan ke ${done.to?.full_name ?? "tidak ada"}.`)}
                </div>
                <div className="mt-0.5">
                  {t(`${done.price_requests_moved} price request${done.price_requests_moved === 1 ? "" : "s"} and ${done.quotations_moved} quotation${done.quotations_moved === 1 ? "" : "s"} moved with them.`,
                     `${done.price_requests_moved} permintaan harga dan ${done.quotations_moved} penawaran ikut berpindah.`)}
                </div>
                {done.unchanged > 0 && (
                  <div className="mt-0.5">
                    {t(`${done.unchanged} were already theirs.`,
                       `${done.unchanged} memang sudah miliknya.`)}
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-end">
              <button className="btn-primary" onClick={close}>
                {t("Done", "Selesai")}
              </button>
            </div>
          </div>
        ) : (
          <div className="p-4 space-y-4">
            {err && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2
                              text-sm text-red-800">{err}</div>
            )}

            {!many && customers[0] && (
              <div className="flex items-center gap-2 text-sm">
                <span className="muted">
                  {customers[0].sales_pic_name || t("Nobody", "Belum ada")}
                </span>
                <ArrowRight size={14} className="text-ink-400" />
                <span className="font-medium">
                  {chosen?.full_name ?? t("choose below", "pilih di bawah")}
                </span>
              </div>
            )}

            <div>
              <div className="overline mb-2 flex items-center gap-1">
                <Users size={12} /> {t("Sales in charge", "Sales penanggung jawab")}
              </div>
              {reps.isLoading ? (
                <div className="py-6 text-center muted">
                  <Loader2 size={14} className="animate-spin inline" /> {t("Loading…", "Memuat…")}
                </div>
              ) : (
                <div className="space-y-1.5 max-h-[15rem] overflow-y-auto pr-1">
                  {list.map((r) => (
                    <label key={r.id} className={clsx(
                      "flex items-center gap-2 rounded-lg border px-3 py-2 cursor-pointer",
                      repId === r.id
                        ? "border-brand-400 bg-brand-50/60 dark:bg-brand-500/15"
                        : "border-ink-200 dark:border-white/10",
                    )}>
                      <input type="radio" name="assign-rep" checked={repId === r.id}
                             onChange={() => setRepId(r.id)} />
                      <span className="text-sm font-medium">{r.full_name}</span>
                      <span className="text-[11px] muted capitalize">{r.role}</span>
                      <span className="ml-auto text-[11px] muted">
                        {t(`${r.customers} customer${r.customers === 1 ? "" : "s"}`,
                           `${r.customers} pelanggan`)}
                      </span>
                    </label>
                  ))}
                  <label className={clsx(
                    "flex items-center gap-2 rounded-lg border px-3 py-2 cursor-pointer",
                    repId === ""
                      ? "border-brand-400 bg-brand-50/60 dark:bg-brand-500/15"
                      : "border-ink-200 dark:border-white/10",
                  )}>
                    <input type="radio" name="assign-rep" checked={repId === ""}
                           onChange={() => setRepId("")} />
                    <span className="text-sm">{t("Nobody — leave unassigned",
                                                  "Tidak ada — biarkan kosong")}</span>
                    <span className="ml-auto text-[11px] muted">
                      {t(`${reps.data?.unassigned ?? 0} unassigned`,
                         `${reps.data?.unassigned ?? 0} tanpa sales`)}
                    </span>
                  </label>
                </div>
              )}
            </div>

            <label className="flex items-start gap-2 cursor-pointer text-sm">
              <input type="checkbox" className="mt-0.5" checked={moveWork}
                     onChange={(e) => setMoveWork(e.target.checked)} />
              <span>
                {t("Move the open price requests and quotations too",
                   "Pindahkan juga permintaan harga dan penawaran yang masih berjalan")}
                <span className="block text-xs muted">
                  {t("Won, lost and rejected documents stay with the rep who closed them.",
                     "Dokumen yang sudah menang, kalah atau ditolak tetap pada sales yang menutupnya.")}
                </span>
              </span>
            </label>

            <div>
              <div className="overline mb-1">{t("Why (optional)", "Alasan (opsional)")}</div>
              <input className="input" value={note} maxLength={200}
                     onChange={(e) => setNote(e.target.value)}
                     placeholder={t("e.g. Budi is taking over the East Java area",
                                    "mis. Budi mengambil alih area Jawa Timur")} />
              <p className="text-xs muted mt-1">
                {t("Saved on the customer's timeline, and shown to the rep who receives it.",
                   "Disimpan di linimasa pelanggan, dan ditampilkan ke sales yang menerimanya.")}
              </p>
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button className="btn-ghost" onClick={close}>{t("Cancel", "Batal")}</button>
              <button className="btn-primary" disabled={assign.isPending}
                      onClick={() => assign.mutate()}>
                {assign.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <UserCog size={14} />}
                {many
                  ? t(`Assign ${customers.length} customers`,
                       `Tetapkan ${customers.length} pelanggan`)
                  : t("Assign", "Tetapkan")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AssignSalesDialog;
