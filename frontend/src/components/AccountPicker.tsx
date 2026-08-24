/**
 * "Cari/Pilih Akun Perkiraan…" — pick an account by typing part of it.
 *
 * A chart of accounts has a hundred-odd lines, so a `<select>` is a scroll
 * hunt and a bare text field means memorising numbers. This is the third
 * thing: type "bca" or "1101" and pick from what matches, with the number
 * and the name both visible because people know accounts by either.
 *
 * Headings are shown but not selectable. A heading is the sum of what sits
 * under it — posting to one is how a chart of accounts stops adding up —
 * and the server refuses it anyway, so it says so here rather than letting
 * somebody find out on save.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

export interface PickableAccount {
  account_no: string;
  name: string;
  account_type: string;
  is_parent?: boolean;
  is_suspended?: boolean;
}

interface Props {
  value: string;
  onChange: (accountNo: string) => void;
  ariaLabel?: string;
  placeholder?: string;
  /** Limit the list, e.g. to Cash & Bank for a payment form. */
  onlyTypes?: string[];
  disabled?: boolean;
}

export function AccountPicker({
  value, onChange, ariaLabel, placeholder, onlyTypes, disabled,
}: Props) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const accounts = useQuery({
    queryKey: ["accounts", "picker"],
    queryFn: () => api.get("/accounts", { params: { limit: 500 } })
      .then((r) => (Array.isArray(r.data) ? r.data : r.data?.items ?? []) as PickableAccount[]),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!open) return;
    const away = (ev: MouseEvent) => {
      if (box.current && !box.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const all = accounts.data ?? [];
  const chosen = all.find((a) => a.account_no === value) ?? null;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all
      .filter((a) => !onlyTypes?.length || onlyTypes.includes(a.account_type))
      .filter((a) => !a.is_suspended)
      .filter((a) => !q
        || a.account_no.toLowerCase().includes(q)
        || (a.name ?? "").toLowerCase().includes(q))
      .slice(0, 40);
  }, [all, query, onlyTypes]);

  return (
    <div className="relative" ref={box}>
      {chosen && !open ? (
        <button type="button" disabled={disabled}
          className="input flex items-center gap-2 text-left w-full disabled:opacity-60"
          aria-label={ariaLabel}
          onClick={() => { setQuery(""); setOpen(true); }}>
          <span className="font-mono text-xs shrink-0">{chosen.account_no}</span>
          <span className="truncate flex-1">{chosen.name}</span>
          <X size={12} className="opacity-50 shrink-0"
            onClick={(e) => { e.stopPropagation(); onChange(""); }} />
        </button>
      ) : (
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            className="input pl-8"
            aria-label={ariaLabel}
            disabled={disabled}
            value={query}
            placeholder={placeholder
              ?? t("Search/select an account…", "Cari/pilih akun perkiraan…")}
            onFocus={() => setOpen(true)}
            onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          />
        </div>
      )}

      {open && !disabled && (
        <div className="absolute z-30 mt-1 w-full max-h-72 overflow-y-auto rounded-lg border border-ink-200 bg-white shadow-card">
          {!matches.length ? (
            <div className="px-3 py-3 text-xs muted">
              {t("No account matches that.", "Tidak ada akun yang cocok.")}
            </div>
          ) : matches.map((a) => (
            <button key={a.account_no} type="button"
              disabled={a.is_parent}
              className={clsx(
                "w-full text-left px-3 py-1.5 text-sm flex items-center gap-2",
                a.is_parent
                  ? "bg-ink-50/60 font-semibold cursor-default"
                  : "hover:bg-brand-50",
              )}
              onClick={() => {
                if (a.is_parent) return;
                onChange(a.account_no);
                setOpen(false);
              }}>
              <span className="font-mono text-xs shrink-0 w-16">{a.account_no}</span>
              <span className="truncate flex-1">{a.name}</span>
              <span className="text-[10px] uppercase muted shrink-0">
                {a.account_type}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
