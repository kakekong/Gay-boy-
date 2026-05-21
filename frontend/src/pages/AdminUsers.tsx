import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Shield, Plus, Loader2, Trash2, Pencil, Save, X, KeyRound, UserCheck, UserX,
  AlertCircle, ExternalLink,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  phone?: string | null;
  is_active: boolean;
}

const ROLE_CHIP: Record<string, string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
  purchasing: "bg-orange-50 text-orange-700",
  customer: "bg-cyan-50 text-cyan-700",
  supplier: "bg-teal-50 text-teal-700",
};

const ROLES = ["sales", "admin", "hr", "manager", "director", "purchasing", "customer", "supplier"];

interface Customer { id: string; company_name: string; }
interface Supplier { id: string; name: string; }

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const [openNew, setOpenNew] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Form state
  const [form, setForm] = useState({
    email: "", full_name: "", role: "sales", password: "",
    phone: "", linked_customer_id: "", linked_supplier_id: "",
  });

  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get("/users", { params: { active_only: false } })
      .then((r) => r.data as User[]),
  });

  // Always load when either modal is open — the role might switch to
  // customer/supplier mid-form and we want the picker ready immediately.
  const formOpen = openNew || !!editing;
  const customers = useQuery({
    queryKey: ["customers-min"],
    queryFn: () => api.get("/customers", { params: { page_size: 200 } })
      .then((r) => {
        // Defensive: support both {data:[...]} and [...] shapes
        const body = r.data;
        if (Array.isArray(body)) return body as Customer[];
        if (body && Array.isArray(body.data)) return body.data as Customer[];
        return [] as Customer[];
      }),
    enabled: formOpen,
    retry: false,
    refetchOnMount: "always",
    staleTime: 0,
  });
  const suppliers = useQuery({
    queryKey: ["suppliers-min"],
    queryFn: () => api.get("/purchasing/suppliers")
      .then((r) => {
        const body = r.data;
        if (Array.isArray(body)) return body as Supplier[];
        if (body && Array.isArray(body.data)) return body.data as Supplier[];
        return [] as Supplier[];
      }),
    enabled: formOpen,
    retry: false,
    refetchOnMount: "always",
    staleTime: 0,
  });

  const create = useMutation({
    mutationFn: () => api.post("/users", {
      ...form,
      linked_customer_id: form.linked_customer_id || null,
      linked_supplier_id: form.linked_supplier_id || null,
      phone: form.phone || null,
    }),
    onSuccess: () => {
      setOpenNew(false);
      setForm({ email: "", full_name: "", role: "sales", password: "",
                phone: "", linked_customer_id: "", linked_supplier_id: "" });
      setFlash({ kind: "ok", text: "User created." });
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to create user",
    }),
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, any> }) =>
      api.patch(`/users/${id}`, body),
    onSuccess: () => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to update",
    }),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/users/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setFlash({ kind: "ok", text: "User deactivated." });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to deactivate",
    }),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Shield size={22} className="text-brand-600" /> Users
          </h1>
          <p className="text-sm muted">Create employees, customer-portal logins, and supplier-portal logins.</p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={14} /> New user
        </button>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100"><X size={14} /></button>
        </div>
      )}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Name</th>
              <th className="th">Email</th>
              <th className="th">Role</th>
              <th className="th">Phone</th>
              <th className="th">Status</th>
              <th className="th text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.id} className={clsx(
                "tr-hover border-t border-ink-100",
                !u.is_active && "opacity-50",
              )}>
                <td className="td font-medium">{u.full_name}</td>
                <td className="td muted">{u.email}</td>
                <td className="td">
                  <span className={clsx("chip uppercase",
                    ROLE_CHIP[u.role] ?? "bg-ink-100 text-ink-700")}>{u.role}</span>
                </td>
                <td className="td muted">{u.phone ?? "—"}</td>
                <td className="td">
                  {u.is_active ? (
                    <span className="chip bg-emerald-50 text-emerald-700">active</span>
                  ) : (
                    <span className="chip bg-ink-100 text-ink-600">inactive</span>
                  )}
                </td>
                <td className="td text-right">
                  <div className="inline-flex gap-1">
                    <button className="btn-ghost" onClick={() => setEditing(u)}>
                      <Pencil size={13} />
                    </button>
                    {u.is_active ? (
                      <button
                        className="btn-ghost text-red-600 hover:bg-red-50"
                        onClick={() => {
                          if (window.confirm(`Deactivate ${u.full_name}? They won't be able to log in.`))
                            del.mutate(u.id);
                        }}
                      ><UserX size={13} /></button>
                    ) : (
                      <button
                        className="btn-ghost text-emerald-700"
                        onClick={() => patch.mutate({ id: u.id, body: { is_active: true } })}
                      ><UserCheck size={13} /></button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!users.data?.length && (
              <tr><td colSpan={6} className="td text-center muted py-10">No users.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* New user modal */}
      {openNew && (
        <Modal title="New user" subtitle="Director can create any role — employees, customer portal, supplier portal."
               onClose={() => setOpenNew(false)}>
          <UserForm
            form={form} setForm={setForm}
            customers={customers.data ?? []}
            customersLoading={customers.isLoading}
            customersError={customers.error as any}
            customersRefetch={() => customers.refetch()}
            suppliers={suppliers.data ?? []}
            suppliersLoading={suppliers.isLoading}
            suppliersError={suppliers.error as any}
            suppliersRefetch={() => suppliers.refetch()}
            isPending={create.isPending}
            submitLabel="Create user"
            onSubmit={() => create.mutate()}
            onCancel={() => setOpenNew(false)}
          />
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title={`Edit ${editing.full_name}`} subtitle={editing.email}
               onClose={() => setEditing(null)}>
          <EditForm
            user={editing}
            onClose={() => setEditing(null)}
            patch={patch}
          />
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, subtitle, onClose, children }: {
  title: string; subtitle?: string; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm muted mt-0.5">{subtitle}</p>}
        </header>
        <div className="flex-1 overflow-auto p-5">{children}</div>
      </div>
    </div>
  );
}

function UserForm({
  form, setForm, customers, customersLoading, customersError, customersRefetch,
  suppliers, suppliersLoading, suppliersError, suppliersRefetch,
  isPending, submitLabel, onSubmit, onCancel,
}: any) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Full name *">
          <input className="input" required value={form.full_name}
            onChange={(e: any) => setForm({ ...form, full_name: e.target.value })} />
        </Field>
        <Field label="Email *">
          <input className="input" type="email" required value={form.email}
            onChange={(e: any) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Role *">
          <select className="input" value={form.role}
            onChange={(e: any) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>
        <Field label="Password *">
          <input className="input" type="text" required value={form.password}
            onChange={(e: any) => setForm({ ...form, password: e.target.value })}
            placeholder="min 6 chars" />
        </Field>
        <Field label="Phone">
          <input className="input" value={form.phone}
            onChange={(e: any) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        {form.role === "customer" && (
          <div className="md:col-span-2">
            <SearchablePicker
              label="Link to customer *"
              placeholder="Search customers by name…"
              items={customers}
              loading={customersLoading}
              error={customersError}
              onRetry={customersRefetch}
              value={form.linked_customer_id}
              onChange={(v) => setForm({ ...form, linked_customer_id: v })}
              getId={(c: Customer) => c.id}
              getLabel={(c: Customer) => c.company_name}
              emptyCta={
                <Link
                  to="/customers"
                  className="inline-flex items-center gap-1 text-brand-700 hover:underline"
                >
                  Open CRM and create a customer first <ExternalLink size={12} />
                </Link>
              }
            />
          </div>
        )}
        {form.role === "supplier" && (
          <div className="md:col-span-2">
            <SearchablePicker
              label="Link to supplier *"
              placeholder="Search suppliers by name…"
              items={suppliers}
              loading={suppliersLoading}
              error={suppliersError}
              onRetry={suppliersRefetch}
              value={form.linked_supplier_id}
              onChange={(v) => setForm({ ...form, linked_supplier_id: v })}
              getId={(s: Supplier) => s.id}
              getLabel={(s: Supplier) => s.name}
              emptyCta={
                <Link
                  to="/purchasing"
                  className="inline-flex items-center gap-1 text-brand-700 hover:underline"
                >
                  Open Purchasing and add a supplier first <ExternalLink size={12} />
                </Link>
              }
            />
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={isPending}>
          {isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

interface SearchablePickerProps<T> {
  label: string;
  placeholder: string;
  items: T[];
  loading: boolean;
  error?: any;
  onRetry?: () => void;
  value: string;
  onChange: (v: string) => void;
  getId: (item: T) => string;
  getLabel: (item: T) => string;
  emptyCta: React.ReactNode;
  extraInput?: React.ReactNode;
}

function SearchablePicker<T>({
  label, placeholder, items, loading, error, onRetry, value, onChange,
  getId, getLabel, emptyCta, extraInput,
}: SearchablePickerProps<T>) {
  const [query, setQuery] = useState("");
  const filtered = items.filter((it) =>
    getLabel(it).toLowerCase().includes(query.toLowerCase())
  );
  const selected = items.find((it) => getId(it) === value);

  const errText = error
    ? (error?.response?.data?.errors?.[0]?.message
        ?? error?.response?.data?.detail
        ?? error?.message
        ?? "Request failed")
    : null;
  const errStatus = error?.response?.status;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="block text-xs font-medium text-ink-600">{label}</span>
        {!loading && !error && (
          <span className="text-[10px] muted">{items.length} available</span>
        )}
      </div>

      {loading ? (
        <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              Couldn't load list{errStatus ? ` (HTTP ${errStatus})` : ""}.
            </div>
            <div className="text-xs mt-0.5 break-all">{String(errText)}</div>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 text-xs underline hover:no-underline"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            {emptyCta}
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="ml-2 text-xs underline hover:no-underline"
              >
                Refresh
              </button>
            )}
            {extraInput}
          </div>
        </div>
      ) : (
        <>
          {selected && (
            <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-brand-50 text-brand-700 px-3 py-1 text-sm">
              <span className="font-medium">{getLabel(selected)}</span>
              <button
                type="button"
                onClick={() => onChange("")}
                className="opacity-70 hover:opacity-100"
                aria-label="Clear selection"
              >
                <X size={12} />
              </button>
            </div>
          )}
          <input
            className="input"
            placeholder={placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ul className="mt-1 max-h-48 overflow-y-auto rounded-lg border border-ink-200 bg-white">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-xs muted">No matches.</li>
            ) : (
              filtered.map((it) => {
                const id = getId(it);
                const active = id === value;
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => onChange(id)}
                      className={clsx(
                        "w-full text-left px-3 py-1.5 text-sm",
                        active ? "bg-brand-50 text-brand-700"
                               : "hover:bg-ink-50",
                      )}
                    >
                      {getLabel(it)}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
          {extraInput}
        </>
      )}
    </div>
  );
}

function EditForm({ user, onClose, patch }: any) {
  const [name, setName] = useState(user.full_name);
  const [role, setRole] = useState(user.role);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [pwd, setPwd] = useState("");

  function save() {
    const body: any = { full_name: name, role, phone: phone || null };
    if (pwd) body.password = pwd;
    patch.mutate({ id: user.id, body });
  }
  return (
    <div className="space-y-3">
      <Field label="Full name">
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Role">
        <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </Field>
      <Field label="Phone">
        <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </Field>
      <Field label="Reset password (leave blank to keep)">
        <input className="input" type="text" value={pwd} onChange={(e) => setPwd(e.target.value)}
          placeholder="new password (optional)" />
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={patch.isPending} onClick={save}>
          {patch.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save changes
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{label}</span>
      {children}
    </label>
  );
}
