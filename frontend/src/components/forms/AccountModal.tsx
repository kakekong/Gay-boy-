import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { T } from "@/store/lang";

export interface AccountRow {
  id: string;
  account_no: string;
  name: string;
  name_en?: string | null;
  account_type: string;
  balance: number;
  parent_account_no?: string | null;
  is_parent: boolean;
  is_suspended: boolean;
  level: number;
  is_tax: boolean;
  description?: string | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  account?: AccountRow | null;        // null/undefined → create mode
  accountTypes: string[];
  allAccounts: AccountRow[];
}

const ACCOUNT_NO_RE = /^[A-Za-z0-9\-]+$/;

export function AccountModal({ open, onClose, account, accountTypes, allAccounts }: Props) {
  const qc = useQueryClient();
  const editing = !!account;

  const [form, setForm] = useState({
    account_no: "",
    name: "",
    name_en: "",
    account_type: "Cash & Bank",
    balance: 0,
    parent_account_no: "",
    is_parent: false,
    is_suspended: false,
    is_tax: false,
    description: "",
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open && account) {
      setForm({
        account_no: account.account_no,
        name: account.name,
        name_en: account.name_en ?? "",
        account_type: account.account_type,
        balance: Number(account.balance) || 0,
        parent_account_no: account.parent_account_no ?? "",
        is_parent: account.is_parent,
        is_suspended: account.is_suspended,
        is_tax: account.is_tax,
        description: account.description ?? "",
      });
    } else if (open) {
      setForm({
        account_no: "",
        name: "",
        name_en: "",
        account_type: "Cash & Bank",
        balance: 0,
        parent_account_no: "",
        is_parent: false,
        is_suspended: false,
        is_tax: false,
        description: "",
      });
    }
    setErr(null);
  }, [open, account]);

  const parentOptions = useMemo(
    () => allAccounts.filter((a) => a.is_parent && a.account_no !== account?.account_no),
    [allAccounts, account]
  );

  const save = useMutation({
    mutationFn: async () => {
      if (!editing) {
        if (!ACCOUNT_NO_RE.test(form.account_no)) {
          throw new Error("Account No must contain only letters, digits, and dashes.");
        }
        const body = {
          ...form,
          parent_account_no: form.parent_account_no || null,
          level: form.parent_account_no ? 1 : 0,
          name_en: form.name_en || null,
          description: form.description || null,
        };
        return api.post("/accounts", body).then((r) => r.data);
      }
      const patch: any = {
        name: form.name,
        name_en: form.name_en || null,
        account_type: form.account_type,
        balance: form.balance,
        parent_account_no: form.parent_account_no || null,
        is_parent: form.is_parent,
        is_suspended: form.is_suspended,
        is_tax: form.is_tax,
        description: form.description || null,
      };
      return api.patch(`/accounts/${account!.id}`, patch).then((r) => r.data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? e?.message ?? "Failed to save");
    },
  });

  const del = useMutation({
    mutationFn: () => api.delete(`/accounts/${account!.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to delete");
    },
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <form
        onSubmit={(e) => { e.preventDefault(); save.mutate(); }}
        className="relative w-full max-w-2xl bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col"
      >
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">
            {editing ? `Edit account · ${account!.account_no}` : T("New account")}
          </h2>
          <p className="text-sm muted mt-0.5">
            {editing ? T("Update or delete this Chart of Accounts entry.")
                     : T("Add a new entry to the Chart of Accounts.")}
          </p>
        </header>

        <div className="flex-1 overflow-auto p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={T("Account No *")}>
              <input
                className="input"
                required
                disabled={editing}
                value={form.account_no}
                onChange={(e) => setForm({ ...form, account_no: e.target.value })}
                placeholder="e.g. 1101-06"
              />
            </Field>
            <Field label={T("Account Type *")}>
              <select
                className="input"
                value={form.account_type}
                onChange={(e) => setForm({ ...form, account_type: e.target.value })}
              >
                {accountTypes.map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <Field label={T("Name (Indonesian) *")}>
              <input
                className="input"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={T("e.g. Bank Mandiri")}
              />
            </Field>
            <Field label={T("Name (English)")}>
              <input
                className="input"
                value={form.name_en}
                onChange={(e) => setForm({ ...form, name_en: e.target.value })}
                placeholder={T("optional")}
              />
            </Field>
            <Field label={T("Parent account")}>
              <select
                className="input"
                value={form.parent_account_no}
                onChange={(e) => setForm({ ...form, parent_account_no: e.target.value })}
              >
                <option value="">{T("— none —")}</option>
                {parentOptions.map((p) => (
                  <option key={p.account_no} value={p.account_no}>
                    {p.account_no} · {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={T("Opening balance")}>
              <input
                type="number"
                step="any"
                className="input"
                value={form.balance}
                onChange={(e) => setForm({ ...form, balance: parseFloat(e.target.value || "0") })}
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 border-t border-ink-100">
            <Toggle
              label={T("Parent account")}
              hint={T("Header row, no postings")}
              checked={form.is_parent}
              onChange={(v) => setForm({ ...form, is_parent: v })}
            />
            <Toggle
              label={T("Suspended")}
              hint={T("Hidden by default in lists")}
              checked={form.is_suspended}
              onChange={(v) => setForm({ ...form, is_suspended: v })}
            />
            <Toggle
              label={T("Tax account")}
              hint={T("Treats as a tax-related ledger")}
              checked={form.is_tax}
              onChange={(v) => setForm({ ...form, is_tax: v })}
            />
          </div>

          <Field label={T("Notes / description")}>
            <textarea
              className="input min-h-[80px]"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder={T("Optional. e.g. Holding bank account for project receipts.")}
            />
          </Field>

          {err && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}
        </div>

        <footer className="px-5 py-3 border-t border-ink-100 flex items-center justify-between gap-2 bg-ink-50/50 rounded-b-2xl">
          <div>
            {editing && (
              <button
                type="button"
                className="btn-ghost text-red-600 hover:bg-red-50"
                onClick={() => {
                  if (window.confirm("Delete this account?")) del.mutate();
                }}
                disabled={del.isPending}
              >
                <Trash2 size={14} /> {T("Delete")}</button>
            )}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
            <button type="submit" className="btn-primary" disabled={save.isPending}>
              {save.isPending && <Loader2 size={14} className="animate-spin" />}
              {editing ? T("Save changes") : T("Create account")}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{T(label)}</span>
      {children}
    </label>
  );
}

function Toggle({ label, hint, checked, onChange }: {
  label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="block text-sm font-medium">{T(label)}</span>
        {hint && <span className="block text-[11px] muted">{T(hint)}</span>}
      </span>
    </label>
  );
}
