/**
 * The whole chart of accounts, beside the screen you are posting from.
 *
 * Cash & Bank showed only the cash accounts, and the General Journal showed
 * no accounts at all — you had the picker and nothing else. Both are places
 * where the question "which account does this belong in" comes up while you
 * are mid-entry, and answering it meant leaving the page and losing what you
 * had typed.
 *
 * So this is a reference, not a second way to edit: numbers, names, types
 * and balances, searchable, collapsed until asked for. Headings are shown
 * too — a chart of accounts without its headings is a list, and the headings
 * are how anybody finds the account they want — but they read as headings
 * rather than as something you could post to.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronRight, Search } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface Account {
  account_no: string;
  name: string;
  account_type: string;
  balance: number;
  is_parent?: boolean;
  is_suspended?: boolean;
  level?: number;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);

export function ChartOfAccountsPanel({ defaultOpen = false }: {
  defaultOpen?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(defaultOpen);
  const [q, setQ] = useState("");

  const accounts = useQuery({
    queryKey: ["accounts", "panel"],
    queryFn: () => api.get("/accounts", { params: { limit: 500 } })
      .then((r) => (Array.isArray(r.data) ? r.data : r.data?.items ?? []) as Account[]),
    staleTime: 60_000,
    // Nothing is posted from here, so it need not be fetched until it is
    // opened — the pages this sits on are already making several calls.
    enabled: open,
  });

  const rows = useMemo(() => {
    const all = accounts.data ?? [];
    const needle = q.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((a) =>
      a.account_no.toLowerCase().includes(needle)
      || (a.name ?? "").toLowerCase().includes(needle)
      || (a.account_type ?? "").toLowerCase().includes(needle));
  }, [accounts.data, q]);

  return (
    <section className="table-shell">
      <button
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-ink-50"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <BookOpen size={14} className="text-brand-600" />
        <span className="overline flex-1">
          {t("Chart of accounts", "Bagan akun")}
        </span>
        <span className="text-[11px] muted">
          {open
            ? t("hide", "sembunyikan")
            : t("show every account and its balance",
                "lihat semua akun dan saldonya")}
        </span>
      </button>

      {open && (
        <div className="border-t border-ink-200">
          <div className="px-4 py-2 relative">
            <Search size={13}
              className="absolute left-6 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              className="input pl-8"
              value={q}
              aria-label="Search chart of accounts"
              placeholder={t("Search by number, name or type…",
                             "Cari nomor, nama, atau jenis akun…")}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          {accounts.isLoading ? (
            <p className="px-4 py-6 text-sm muted">{t("Loading…", "Memuat…")}</p>
          ) : !rows.length ? (
            <p className="px-4 py-6 text-sm muted">
              {t("No account matches that.", "Tidak ada akun yang cocok.")}
            </p>
          ) : (
            <div className="max-h-96 overflow-y-auto overflow-x-auto">
              <table className="w-full">
                <thead className="sticky top-0 bg-white">
                  <tr>
                    <th className="th">{t("Account", "Akun")}</th>
                    <th className="th">{t("Type", "Jenis")}</th>
                    <th className="th text-right">{t("Balance", "Saldo")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.account_no}
                      className={clsx("border-t border-ink-100",
                        a.is_parent && "bg-ink-50/60",
                        a.is_suspended && "opacity-50")}>
                      <td className="td">
                        <span
                          style={{ paddingLeft: `${Math.min(a.level ?? 0, 4) * 12}px` }}
                          className="inline-flex items-baseline gap-2"
                        >
                          <span className="spec">{a.account_no}</span>
                          <span className={clsx(a.is_parent && "font-semibold")}>
                            {a.name}
                          </span>
                          {a.is_suspended && (
                            <span className="chip bg-ink-100 text-ink-600">
                              {t("suspended", "nonaktif")}
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="td text-xs muted">{a.account_type}</td>
                      <td className="td text-right tabular-nums whitespace-nowrap">
                        {a.is_parent
                          // A heading is the sum of what sits under it, and it
                          // is not posted to — printing a figure here invites
                          // it to be read as an account balance.
                          ? <span className="muted">—</span>
                          : idr(a.balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
