import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileText, Loader2, MapPin, User as UserIcon, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { useT, useLangStore, T } from "@/store/lang";

export interface AddressOption {
  key: string; label: string; label_id?: string; address: string;
}
export interface PicOption {
  id: string | null; name: string; position: string;
  phone: string; email: string; primary: boolean;
}
export interface PrintOptions {
  customer_name?: string;
  addresses?: AddressOption[];
  ship_to?: AddressOption[];          // the customer PO calls it this
  pics?: PicOption[];
  default_address?: string;
}

/**
 * Ask which address to print on, then download.
 *
 * A customer holds three addresses and they are different places — the office
 * that signs, the site the goods go to, and the one registered for tax. Which
 * belongs on a document is a decision about *that document*, not a property of
 * the customer, so it is asked at download time rather than guessed from a
 * default nobody chose.
 *
 * The same dialog serves the quotation and the customer PO. They disagree
 * about the sensible default — a quotation goes to the office, a delivery
 * sheet to the site — so the server says which, and only the query-parameter
 * name differs.
 */
export function ExportAddressDialog({
  open, onClose, title, optionsUrl, downloadUrl, filename, addressParam = "address",
  extraParams,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  optionsUrl: string;
  downloadUrl: string;
  filename: string;
  /** `address` for quotations, `ship_to` for the customer PO sheet. */
  addressParam?: string;
  extraParams?: Record<string, string | number | undefined>;
}) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const [addr, setAddr] = useState<string | null>(null);
  const [picIdx, setPicIdx] = useState(0);
  const [busy, setBusy] = useState(false);

  const opts = useQuery({
    queryKey: ["print-options", optionsUrl],
    queryFn: () => api.get(optionsUrl).then((r) => r.data as PrintOptions),
    enabled: open,
  });

  if (!open) return null;

  const addresses = opts.data?.addresses ?? opts.data?.ship_to ?? [];
  const pics = opts.data?.pics ?? [];
  const chosenPic = pics[picIdx];
  // Until the options land there is nothing to pre-select; once they do, the
  // server's default wins unless the user has picked something.
  const selected = addr ?? opts.data?.default_address ?? addresses[0]?.key ?? "office";
  const selectedHasText = !!addresses.find((a) => a.key === selected)?.address;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white dark:bg-ink-800 rounded-2xl
                      shadow-card max-h-[85vh] overflow-y-auto">
        <header className="p-4 border-b border-ink-100 dark:border-white/10 flex items-center gap-2">
          <FileText size={16} className="text-brand-600" />
          <div className="min-w-0">
            <div className="text-lg font-semibold truncate">{title}</div>
            {opts.data?.customer_name && (
              <div className="text-xs muted truncate">{opts.data.customer_name}</div>
            )}
          </div>
          <button className="ml-auto text-ink-400 hover:text-ink-800"
                  onClick={onClose} aria-label={T("Close")}><X size={16} /></button>
        </header>

        {opts.isLoading ? (
          <div className="p-8 text-center muted">
            <Loader2 size={16} className="animate-spin inline" /> {t("Loading…", "Memuat…")}
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <div>
              <div className="overline mb-2 flex items-center gap-1">
                <MapPin size={12} /> {t("Which address goes on it", "Alamat mana yang dipakai")}
              </div>
              <div className="space-y-2">
                {addresses.map((a) => (
                  <label key={a.key} className={clsx(
                    "block rounded-lg border px-3 py-2 cursor-pointer",
                    selected === a.key
                      ? "border-brand-400 bg-brand-50/60 dark:bg-brand-500/15"
                      : "border-ink-200 dark:border-white/10",
                    !a.address && "opacity-60",
                  )}>
                    <div className="flex items-center gap-2">
                      <input type="radio" name="print-address"
                             checked={selected === a.key}
                             onChange={() => setAddr(a.key)} />
                      <span className="text-sm font-medium">
                        {lang === "id" && a.label_id ? a.label_id : a.label}
                      </span>
                    </div>
                    <div className="text-xs muted whitespace-pre-wrap mt-1 pl-6">
                      {a.address || t("Not filled in on the customer — the office address is used instead.",
                                      "Belum diisi pada pelanggan — alamat kantor yang dipakai.")}
                    </div>
                  </label>
                ))}
                {!addresses.length && (
                  <p className="text-sm muted">
                    {t("This customer has no addresses on file yet.",
                       "Pelanggan ini belum punya alamat tersimpan.")}
                  </p>
                )}
              </div>
              {!selectedHasText && !!addresses.length && (
                <p className="mt-2 text-xs text-amber-700">
                  {t("That one is empty, so the office address will be printed instead.",
                     "Yang itu kosong, jadi alamat kantor yang akan dicetak.")}
                </p>
              )}
            </div>

            <div>
              <div className="overline mb-2 flex items-center gap-1">
                <UserIcon size={12} /> {t("Addressed to", "Ditujukan kepada")}
              </div>
              {pics.length ? (
                <select className="input" value={picIdx}
                        onChange={(e) => setPicIdx(Number(e.target.value))}>
                  {pics.map((p, i) => (
                    <option key={i} value={i}>
                      {p.name}{p.position ? ` — ${p.position}` : ""}
                      {p.primary ? t(" (primary)", " (utama)") : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-sm muted">
                  {t("This customer has no contacts yet — add one on the customer page.",
                     "Pelanggan ini belum punya kontak — tambahkan di halaman pelanggan.")}
                </p>
              )}
              {chosenPic && (
                <div className="text-xs muted mt-1">
                  {[chosenPic.phone, chosenPic.email].filter(Boolean).join(" · ") || "—"}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button className="btn-ghost" onClick={onClose}>
                {t("Cancel", "Batal")}
              </button>
              <button
                className="btn-primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await downloadFile(downloadUrl, filename, {
                      [addressParam]: selected,
                      contact_id: chosenPic?.id ?? undefined,
                      ...(extraParams ?? {}),
                    });
                    onClose();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                {t("Download", "Unduh")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
