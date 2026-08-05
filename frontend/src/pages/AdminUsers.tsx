import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Shield, Plus, Loader2, Trash2, Pencil, Save, X, KeyRound, UserCheck, UserX,
  AlertCircle, ExternalLink, Eye,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { startViewAs } from "@/lib/viewAs";
import { T } from "@/store/lang";

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  custom_role_id?: string | null;
  custom_role_name?: string | null;
  pages?: string[];
  phone?: string | null;
  is_active: boolean;
}

interface CustomRole {
  id: string;
  name: string;
  base_role: string;
  pages: string[];
  description?: string | null;
}

const ROLE_CHIP: Record<string, string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  finance:  "bg-lime-50 text-lime-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
  purchasing: "bg-orange-50 text-orange-700",
  customer: "bg-cyan-50 text-cyan-700",
  supplier: "bg-teal-50 text-teal-700",
};

const ROLES = ["sales", "admin", "hr", "finance", "manager", "director", "purchasing", "customer", "supplier"];

interface Customer { id: string; company_name: string; }
interface Supplier { id: string; name: string; }

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const [openNew, setOpenNew] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Form state
  const [form, setForm] = useState({
    email: "", full_name: "", role: "sales", password: "",
    phone: "", linked_customer_id: "", linked_supplier_id: "",
    custom_role_id: "",
  });

  const customRoles = useQuery({
    queryKey: ["custom-roles"],
    queryFn: () => api.get("/custom-roles").then((r) => r.data as CustomRole[]),
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
      custom_role_id: form.custom_role_id || null,
      phone: form.phone || null,
    }),
    onSuccess: () => {
      setOpenNew(false);
      setForm({ email: "", full_name: "", role: "sales", password: "",
                phone: "", linked_customer_id: "", linked_supplier_id: "",
                custom_role_id: "" });
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

  const hardDel = useMutation({
    mutationFn: (id: string) => api.delete(`/users/${id}`, { params: { hard: true } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setFlash({ kind: "ok", text: "User permanently deleted." });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Failed to delete",
    }),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Shield size={22} className="text-brand-600" /> {T("Users")}</h1>
          <p className="text-sm muted">{T("Create employees, customer-portal logins, and supplier-portal logins.")}</p>
        </div>
        <button className="btn-primary" onClick={() => setOpenNew(true)}>
          <Plus size={14} /> {T("New user")}</button>
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
              <th className="th">{T("Name")}</th>
              <th className="th">{T("Email")}</th>
              <th className="th">{T("Role")}</th>
              <th className="th">{T("Phone")}</th>
              <th className="th">{T("Status")}</th>
              <th className="th text-right">{T("Actions")}</th>
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
                  {u.custom_role_name ? (
                    <span className="chip bg-indigo-50 text-indigo-700" title={`Base role: ${u.role}`}>
                      {u.custom_role_name}
                    </span>
                  ) : (
                    <span className={clsx("chip uppercase",
                      ROLE_CHIP[u.role] ?? "bg-ink-100 text-ink-700")}>{u.role}</span>
                  )}
                </td>
                <td className="td muted">{u.phone ?? "—"}</td>
                <td className="td">
                  {u.is_active ? (
                    <span className="chip bg-emerald-50 text-emerald-700">{T("active")}</span>
                  ) : (
                    <span className="chip bg-ink-100 text-ink-600">{T("inactive")}</span>
                  )}
                </td>
                <td className="td text-right">
                  <div className="inline-flex gap-1">
                    <button className="btn-ghost" onClick={() => setEditing(u)}>
                      <Pencil size={13} />
                    </button>
                    {u.is_active && u.id !== me?.id && (
                      <button
                        className="btn-ghost text-brand-700 hover:bg-brand-50"
                        title={`View the app as ${u.full_name}`}
                        onClick={async () => {
                          if (window.confirm(
                            `View the app as ${u.full_name}?\n\n` +
                            `You'll see exactly what they see (their data + sidebar). ` +
                            `A banner stays up the whole time — click "Exit view-as" to return to your own account.`
                          )) {
                            try { await startViewAs(u.id); }
                            catch { window.alert("Couldn't switch to that user."); }
                          }
                        }}
                      ><Eye size={13} /></button>
                    )}
                    {u.is_active ? (
                      <button
                        className="btn-ghost text-red-600 hover:bg-red-50"
                        title={T("Deactivate (keeps history)")}
                        onClick={() => {
                          if (window.confirm(`Deactivate ${u.full_name}? They won't be able to log in. Records they created stay intact.`))
                            del.mutate(u.id);
                        }}
                      ><UserX size={13} /></button>
                    ) : (
                      <>
                        <button
                          className="btn-ghost text-emerald-700"
                          title={T("Reactivate")}
                          onClick={() => patch.mutate({ id: u.id, body: { is_active: true } })}
                        ><UserCheck size={13} /></button>
                        <button
                          className="btn-ghost text-red-700 hover:bg-red-50"
                          title={T("Permanently delete (removes the user row entirely)")}
                          onClick={() => {
                            if (window.confirm(
                              `PERMANENTLY delete ${u.full_name}?\n\n` +
                              `This removes the user row from the database. Customers / quotations they created stay but the 'created by' field will become empty.\n\n` +
                              `This cannot be undone.`
                            )) {
                              hardDel.mutate(u.id);
                            }
                          }}
                        ><Trash2 size={13} /></button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!users.data?.length && (
              <tr><td colSpan={6} className="td text-center muted py-10">{T("No users.")}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* New user modal */}
      {openNew && (
        <Modal title={T("New user")} subtitle={T("Director can create any role — employees, customer portal, supplier portal.")}
               onClose={() => setOpenNew(false)}>
          <UserForm
            form={form} setForm={setForm}
            customRoles={customRoles}
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

      {/* Custom roles manager */}
      <CustomRolesManager />

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

function CustomRolesManager() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CustomRole | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const roles = useQuery({
    queryKey: ["custom-roles"],
    queryFn: () => api.get("/custom-roles").then((r) => r.data as CustomRole[]),
  });
  const catalog = useQuery({
    queryKey: ["custom-roles-catalog"],
    queryFn: () => api.get("/custom-roles/catalog").then((r) => r.data as {
      pages: { path: string; label: string }[]; base_roles: string[];
    }),
    enabled: open || !!editing,
  });

  const [form, setForm] = useState<{ name: string; base_role: string; pages: string[]; description: string }>(
    { name: "", base_role: "sales", pages: [], description: "" },
  );

  function startNew() {
    setForm({ name: "", base_role: "sales", pages: [], description: "" });
    setEditing(null);
    setOpen(true);
    setErr(null);
  }
  function startEdit(r: CustomRole) {
    setForm({ name: r.name, base_role: r.base_role, pages: [...r.pages], description: r.description ?? "" });
    setEditing(r);
    setOpen(true);
    setErr(null);
  }

  const save = useMutation({
    mutationFn: () => editing
      ? api.patch(`/custom-roles/${editing.id}`, form)
      : api.post("/custom-roles", form),
    onSuccess: () => {
      setOpen(false); setEditing(null);
      qc.invalidateQueries({ queryKey: ["custom-roles"] });
    },
    onError: (e: any) => setErr(e?.response?.data?.detail ?? "Couldn't save role"),
  });
  const del = useMutation({
    mutationFn: (rid: string) => api.delete(`/custom-roles/${rid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["custom-roles"] }),
  });

  function togglePage(path: string) {
    setForm((f) => ({
      ...f,
      pages: f.pages.includes(path) ? f.pages.filter((p) => p !== path) : [...f.pages, path],
    }));
  }

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-4 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Shield size={15} className="text-brand-600" /> {T("Custom roles")}</div>
          <div className="text-xs muted">
            {T("Build your own roles — pick a name, a base access tier, and the pages they can see.")}</div>
        </div>
        <button className="btn-primary" onClick={startNew}>
          <Plus size={14} /> {T("New custom role")}</button>
      </header>

      {roles.isLoading ? (
        <div className="p-6 text-center text-sm muted">{T("Loading…")}</div>
      ) : !roles.data?.length ? (
        <div className="p-8 text-center text-sm muted">
          {T("No custom roles yet. Create one, then assign it to a user above.")}</div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {roles.data.map((r) => (
            <li key={r.id} className="px-5 py-3 flex items-center gap-3 flex-wrap">
              <span className="chip bg-indigo-50 text-indigo-700">{r.name}</span>
              <span className="text-[11px] uppercase muted">{T("base:")}{" "}{r.base_role}</span>
              <span className="text-xs muted flex-1">{r.pages.length} {T("page(s)")}</span>
              <button className="btn-ghost" onClick={() => startEdit(r)} title={T("Edit")}>
                <Pencil size={13} />
              </button>
              <button
                className="btn-ghost text-red-600 hover:bg-red-50"
                title={T("Delete (users keep their base role)")}
                onClick={() => {
                  if (window.confirm(`Delete custom role "${r.name}"? Users on it revert to their base role.`))
                    del.mutate(r.id);
                }}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <Modal
          title={editing ? `Edit role: ${editing.name}` : "New custom role"}
          subtitle={T("Name it, pick the base access tier, tick the pages it can open.")}
          onClose={() => setOpen(false)}
        >
          <div className="space-y-3">
            <Field label={T("Role name *")}>
              <input className="input" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={T("e.g. Finance Manager")} />
            </Field>
            <Field label={T("Base access tier *")}>
              <select className="input" value={form.base_role}
                onChange={(e) => setForm({ ...form, base_role: e.target.value })}>
                {(catalog.data?.base_roles ?? ["sales", "admin", "hr", "finance", "purchasing", "manager", "director"])
                  .map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <span className="block text-[11px] text-ink-400 mt-1">
                {T("Controls what the API allows. Pages below control what they see.")}</span>
            </Field>
            <Field label={T("Description")}>
              <input className="input" value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <div>
              <span className="block text-xs font-medium text-ink-600 mb-1">{T("Pages they can access")}</span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-[280px] overflow-y-auto rounded-lg border border-ink-200 p-2">
                {(catalog.data?.pages ?? []).map((p) => (
                  <label key={p.path} className="flex items-center gap-2 text-sm px-2 py-1 rounded hover:bg-ink-50">
                    <input
                      type="checkbox"
                      checked={form.pages.includes(p.path)}
                      onChange={() => togglePage(p.path)}
                      className="h-4 w-4 rounded border-ink-300 text-brand-600"
                    />
                    {T(p.label)}
                  </label>
                ))}
              </div>
            </div>
            {err && (
              <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
                {err}
              </div>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button className="btn-ghost" onClick={() => setOpen(false)}>{T("Cancel")}</button>
              <button className="btn-primary" disabled={save.isPending || !form.name.trim()}
                onClick={() => { setErr(null); save.mutate(); }}>
                {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {editing ? T("Save role") : T("Create role")}
              </button>
            </div>
          </div>
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
  form, setForm, customRoles, customers, customersLoading, customersError, customersRefetch,
  suppliers, suppliersLoading, suppliersError, suppliersRefetch,
  isPending, submitLabel, onSubmit, onCancel,
}: any) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label={T("Full name *")}>
          <input className="input" required value={form.full_name}
            onChange={(e: any) => setForm({ ...form, full_name: e.target.value })} />
        </Field>
        <Field label={T("Email *")}>
          <input className="input" type="email" required value={form.email}
            onChange={(e: any) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label={T("Role *")}>
          <select className="input" value={form.role}
            disabled={!!form.custom_role_id}
            onChange={(e: any) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>
        <Field label={T("Custom role")}>
          <select className="input" value={form.custom_role_id}
            onChange={(e: any) => {
              const cr = (customRoles.data ?? []).find((x: CustomRole) => x.id === e.target.value);
              setForm({
                ...form,
                custom_role_id: e.target.value,
                // Pin the base role to the custom role's tier.
                role: cr ? cr.base_role : form.role,
              });
            }}>
            <option value="">{T("— none (use base role) —")}</option>
            {(customRoles.data ?? []).map((cr: CustomRole) => (
              <option key={cr.id} value={cr.id}>{cr.name} {T("(base:")}{" "}{cr.base_role})</option>
            ))}
          </select>
        </Field>
        <Field label={T("Password *")}>
          <input className="input" type="text" required value={form.password}
            onChange={(e: any) => setForm({ ...form, password: e.target.value })}
            placeholder={T("min 6 chars")} />
        </Field>
        <Field label={T("Phone")}>
          <input className="input" value={form.phone}
            onChange={(e: any) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        {form.role === "customer" && (
          <div className="md:col-span-2">
            <SearchablePicker
              label={T("Link to customer *")}
              placeholder={T("Search customers by name…")}
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
                  {T("Open CRM and create a customer first")}{" "}<ExternalLink size={12} />
                </Link>
              }
            />
          </div>
        )}
        {form.role === "supplier" && (
          <div className="md:col-span-2">
            <SearchablePicker
              label={T("Link to supplier *")}
              placeholder={T("Search suppliers by name…")}
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
                  {T("Open Purchasing and add a supplier first")}{" "}<ExternalLink size={12} />
                </Link>
              }
            />
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="btn-ghost" onClick={onCancel}>{T("Cancel")}</button>
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
        <span className="block text-xs font-medium text-ink-600">{T(label)}</span>
        {!loading && !error && (
          <span className="text-[10px] muted">{items.length} {T("available")}</span>
        )}
      </div>

      {loading ? (
        <div className="rounded-lg border border-ink-200 px-3 py-2 text-sm muted flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              {T("Couldn't load list")}{errStatus ? ` (HTTP ${errStatus})` : ""}.
            </div>
            <div className="text-xs mt-0.5 break-all">{String(errText)}</div>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 text-xs underline hover:no-underline"
              >
                {T("Retry")}</button>
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
                {T("Refresh")}</button>
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
                aria-label={T("Clear selection")}
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
              <li className="px-3 py-2 text-xs muted">{T("No matches.")}</li>
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
  const [customRoleId, setCustomRoleId] = useState<string>(user.custom_role_id ?? "");
  // Per-user page override: when overrideOn is true the user sees exactly
  // the ticked pages (wins over role / custom-role defaults). Off = clear
  // the override and fall back to the role's pages.
  const [overrideOn, setOverrideOn] = useState<boolean>(!!(user.pages && user.pages.length));
  const [pages, setPages] = useState<string[]>(user.pages ?? []);

  const customRoles = useQuery({
    queryKey: ["custom-roles"],
    queryFn: () => api.get("/custom-roles").then((r) => r.data as CustomRole[]),
  });
  const catalog = useQuery({
    queryKey: ["custom-roles-catalog"],
    queryFn: () =>
      api.get("/custom-roles/catalog").then(
        (r) => r.data as { pages: { path: string; label: string }[] },
      ),
  });

  function togglePage(p: string) {
    setPages((cur) => cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]);
  }

  function save() {
    const body: any = {
      full_name: name, role, phone: phone || null,
      custom_role_id: customRoleId || null,
      // Empty list clears the override on the backend; otherwise send what
      // was ticked. If override is OFF, send an empty list to clear.
      pages: overrideOn ? pages : [],
    };
    if (pwd) body.password = pwd;
    patch.mutate({ id: user.id, body });
  }
  return (
    <div className="space-y-3">
      <Field label={T("Full name")}>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={T("Role")}>
        <select className="input" value={role} disabled={!!customRoleId}
          onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </Field>
      <Field label={T("Custom role")}>
        <select className="input" value={customRoleId}
          onChange={(e) => {
            const cr = (customRoles.data ?? []).find((x) => x.id === e.target.value);
            setCustomRoleId(e.target.value);
            if (cr) setRole(cr.base_role);
          }}>
          <option value="">{T("— none (use base role) —")}</option>
          {(customRoles.data ?? []).map((cr) => (
            <option key={cr.id} value={cr.id}>{cr.name} {T("(base:")}{" "}{cr.base_role})</option>
          ))}
        </select>
      </Field>
      <Field label={T("Phone")}>
        <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </Field>
      <Field label={T("Reset password (leave blank to keep)")}>
        <input className="input" type="text" value={pwd} onChange={(e) => setPwd(e.target.value)}
          placeholder={T("new password (optional)")} />
      </Field>

      <div className="rounded-xl border border-ink-200 bg-ink-50/40 p-3 space-y-3">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            checked={overrideOn}
            onChange={(e) => {
              const on = e.target.checked;
              setOverrideOn(on);
              // First time switching on with nothing selected, seed with the
              // pages this user currently has, so the director sees a sane
              // starting point rather than an empty sidebar.
              if (on && pages.length === 0 && user.pages?.length) {
                setPages(user.pages);
              }
            }}
          />
          <div className="flex-1">
            <div className="text-sm font-medium">{T("Override sidebar pages for this user")}</div>
            <div className="text-[11px] muted">
              {T("When on, this user sees only the ticked pages (plus Help) — overrides their role / custom-role defaults. Off = fall back to the role's pages.")}</div>
          </div>
        </label>
        {overrideOn && (
          <>
            <div className="flex items-center justify-between text-[11px]">
              <span className="muted">
                {pages.length} {T("of")}{" "}{catalog.data?.pages.length ?? 0} {T("pages selected")}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="text-brand-700 hover:underline"
                  onClick={() => setPages((catalog.data?.pages ?? []).map((p) => p.path))}
                >
                  {T("Select all")}</button>
                <button
                  type="button"
                  className="text-brand-700 hover:underline"
                  onClick={() => setPages([])}
                >
                  {T("Clear")}</button>
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-lg border border-ink-200 bg-white p-2 grid grid-cols-1 sm:grid-cols-2 gap-1">
              {(catalog.data?.pages ?? []).map((p) => (
                <label
                  key={p.path}
                  className="flex items-center gap-2 px-2 py-1 rounded hover:bg-ink-50 cursor-pointer text-sm"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                    checked={pages.includes(p.path)}
                    onChange={() => togglePage(p.path)}
                  />
                  <span className="flex-1 truncate">{T(p.label)}</span>
                  <span className="text-[10px] text-ink-400 font-mono">{p.path}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button className="btn-primary" disabled={patch.isPending} onClick={save}>
          {patch.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {T("Save changes")}</button>
      </div>
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
