import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link2, BookOpen, Undo2, Save, Loader2, CheckCircle, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, t as tt, T, locale } from "@/store/lang";

interface Props {
  quotationId: string;
}

interface AccountOption {
  id: string;
  account_no: string;
  name: string;
  account_type: string;
  is_parent: boolean;
  is_suspended: boolean;
}

interface LinkRow {
  role: "revenue" | "receivable" | "discount" | "tax";
  account_no: string | null;
  account_name: string | null;
  account_type: string | null;
  current_balance: number | null;
  amount_to_post: number;
}

const idr = (n: number | null | undefined) => {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "0";
  const abs = Math.abs(n);
  const s = new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(abs);
  return n < 0 ? `(${s})` : s;
};

export function LinkedAccountsPanel({ quotationId }: Props) {
  const t = useT();
  const qc = useQueryClient();

  const ROLE_META: Record<LinkRow["role"], { label: string; hint: string; tone: string }> = {
    receivable: { label: t("Receivable (DR)", "Piutang (DR)"),
                  hint: t("Customer owes you the total amount", "Pelanggan berutang jumlah total kepada Anda"),
                  tone: "bg-brand-50 text-brand-700" },
    revenue:    { label: t("Revenue (CR)", "Pendapatan (CR)"),
                  hint: t("Net sales after discount", "Penjualan bersih setelah diskon"),
                  tone: "bg-emerald-50 text-emerald-700" },
    discount:   { label: t("Discount (DR)", "Diskon (DR)"),
                  hint: t("Contra-revenue: the discount given", "Kontra-pendapatan: diskon yang diberikan"),
                  tone: "bg-amber-50 text-amber-700" },
    tax:        { label: t("Tax Payable (CR)", "Utang Pajak (CR)"),
                  hint: t("PPN/output tax owed to the state", "PPN/pajak keluaran yang terutang ke negara"),
                  tone: "bg-violet-50 text-violet-700" },
  };

  const links = useQuery({
    queryKey: ["account-links", quotationId],
    queryFn: () => api.get(`/quotations/${quotationId}/account-links`).then((r) => r.data as {
      links: LinkRow[];
      is_posted: boolean;
      posted_at: string | null;
      amounts: { revenue: number; receivable: number; discount: number; tax: number };
    }),
  });

  // CoA list, used for the dropdowns. Some users (sales/manager) won't have
  // permission to call /accounts; we fall back gracefully.
  const accounts = useQuery<AccountOption[]>({
    queryKey: ["accounts-min"],
    queryFn: async () => {
      try {
        const r = await api.get("/accounts", { params: { suspended: "active" } });
        return r.data as AccountOption[];
      } catch {
        return [];
      }
    },
  });

  const byType = useMemo(() => {
    const m: Record<string, AccountOption[]> = {};
    for (const a of accounts.data ?? []) {
      if (a.is_parent) continue;
      (m[a.account_type] ??= []).push(a);
    }
    return m;
  }, [accounts.data]);

  // Local edits before save
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (links.data) {
      const init: Record<string, string> = {};
      for (const l of links.data.links) init[l.role] = l.account_no ?? "";
      setDraft(init);
    }
  }, [links.data]);

  const dirty = useMemo(() => {
    if (!links.data) return false;
    return links.data.links.some((l) => (draft[l.role] ?? "") !== (l.account_no ?? ""));
  }, [draft, links.data]);

  const save = useMutation({
    mutationFn: () => api.patch(`/quotations/${quotationId}/account-links`, {
      account_revenue_no:    draft.revenue    || null,
      account_receivable_no: draft.receivable || null,
      account_discount_no:   draft.discount   || null,
      account_tax_no:        draft.tax        || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-links", quotationId] });
      qc.invalidateQueries({ queryKey: ["quotation", quotationId] });
    },
  });

  const post = useMutation({
    mutationFn: () => api.post(`/quotations/${quotationId}/post-ledger`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-links", quotationId] });
      qc.invalidateQueries({ queryKey: ["quotation", quotationId] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const reverse = useMutation({
    mutationFn: () => api.post(`/quotations/${quotationId}/reverse-ledger`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-links", quotationId] });
      qc.invalidateQueries({ queryKey: ["quotation", quotationId] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  if (links.isLoading) {
    return (
      <div className="card p-5 text-sm muted">{t("Loading account links…", "Memuat tautan akun…")}</div>
    );
  }

  const isPosted = !!links.data?.is_posted;
  const hasCoaAccess = (accounts.data ?? []).length > 0;

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Link2 size={15} className="text-brand-600" />
            {t("Linked Accounts", "Akun Tertaut")}
            {isPosted ? (
              <span className="chip bg-emerald-50 text-emerald-700">
                <CheckCircle size={11} /> {t("Posted", "Diposting")}
              </span>
            ) : (
              <span className="chip bg-amber-50 text-amber-700">
                <AlertCircle size={11} /> {t("Not posted", "Belum diposting")}
              </span>
            )}
          </div>
          <div className="text-xs muted">
            {isPosted
              ? `${t("Balances updated at", "Saldo diperbarui pada")} ${new Date(links.data!.posted_at!).toLocaleString(locale())}. ${t("Click Reverse to roll back.", "Klik Balik untuk membatalkannya.")}`
              : t(
                  "When this quotation is marked Won, the linked accounts auto-update. You can also post manually.",
                  "Saat penawaran ini ditandai Menang, akun tertaut diperbarui otomatis. Anda juga bisa memposting secara manual.",
                )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {dirty && !isPosted && (
            <button
              onClick={() => save.mutate()}
              className="btn-ghost text-brand-700"
              disabled={save.isPending}
            >
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {t("Save links", "Simpan tautan")}
            </button>
          )}
          {!isPosted && (
            <button
              onClick={() => post.mutate()}
              className="btn-success"
              disabled={post.isPending || dirty}
              title={dirty
                ? t("Save link changes first", "Simpan perubahan tautan terlebih dahulu")
                : t("Post amounts to the ledger", "Posting jumlah ke ledger")}
            >
              {post.isPending ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
              {t("Post to ledger", "Posting ke ledger")}
            </button>
          )}
          {isPosted && (
            <button
              onClick={() => {
                if (window.confirm(tt(
                  "Reverse this posting from the ledger?",
                  "Balik posting ini dari ledger?",
                )))
                  reverse.mutate();
              }}
              className="btn-ghost text-red-600 hover:bg-red-50"
              disabled={reverse.isPending}
            >
              {reverse.isPending ? <Loader2 size={14} className="animate-spin" /> : <Undo2 size={14} />}
              {t("Reverse posting", "Balik posting")}
            </button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Role", "Peran")}</th>
              <th className="th">{t("Account", "Akun")}</th>
              <th className="th text-right">{t("Current balance", "Saldo saat ini")}</th>
              <th className="th text-right">{t("Amount to post", "Jumlah diposting")}</th>
            </tr>
          </thead>
          <tbody>
            {(links.data?.links ?? []).map((l) => {
              const M = ROLE_META[l.role];
              const value = draft[l.role] ?? l.account_no ?? "";
              return (
                <tr key={l.role} className="border-t border-ink-100">
                  <td className="td">
                    <span className={clsx("chip uppercase", M.tone)}>{T(M.label)}</span>
                    <div className="text-[11px] muted mt-1">{T(M.hint)}</div>
                  </td>
                  <td className="td">
                    {hasCoaAccess ? (
                      <select
                        className="input max-w-md"
                        value={value}
                        disabled={isPosted}
                        onChange={(e) => setDraft({ ...draft, [l.role]: e.target.value })}
                      >
                        <option value="">{t("— pick account —", "— pilih akun —")}</option>
                        {Object.entries(byType).map(([type, accs]) => (
                          <optgroup key={type} label={type}>
                            {accs.map((a) => (
                              <option key={a.account_no} value={a.account_no}>
                                {a.account_no} · {a.name}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    ) : (
                      <div className="text-sm">
                        <span className="font-mono text-xs text-ink-500">{l.account_no ?? "—"}</span>
                        <div>{l.account_name ?? <span className="muted italic">{t("CoA access restricted", "Akses CoA dibatasi")}</span>}</div>
                      </div>
                    )}
                  </td>
                  <td className="td text-right tabular-nums">
                    {idr(l.current_balance)}
                  </td>
                  <td className="td text-right tabular-nums font-medium">
                    {idr(l.amount_to_post)}
                  </td>
                </tr>
              );
            })}
          </tbody>
          {links.data && (
            <tfoot className="bg-ink-50/40">
              <tr>
                <td colSpan={3} className="td text-right text-xs uppercase tracking-wider muted">
                  {t("DR Receivable", "DR Piutang")} {idr(links.data.amounts.receivable)}
                  &nbsp;=&nbsp;
                  {t("CR Revenue", "CR Pendapatan")} {idr(links.data.amounts.revenue)} + {t("CR Tax", "CR Pajak")} {idr(links.data.amounts.tax)} + {t("DR Discount", "DR Diskon")} {idr(links.data.amounts.discount)}
                </td>
                <td className="td text-right font-semibold">
                  {idr(links.data.amounts.receivable)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
