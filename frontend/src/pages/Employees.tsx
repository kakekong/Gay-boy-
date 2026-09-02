/**
 * The employee register — everybody who works here, whether or not they can
 * sign in.
 *
 * This used to be a view of the users table, which meant somebody only
 * appeared here once IT had given them a password. That is the wrong way
 * round: a person is hired, given a staff number and a position, and then —
 * sometimes weeks later, sometimes never — gets a login. So the register is
 * now its own record, and the login is created against it from Users.
 *
 * Two roles were missing from the old list as well, finance and purchasing,
 * so anybody on those roles was invisible on the one page that is supposed to
 * be the whole company.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Users, Search, Tags, CalendarX, Plus, IdCard, KeyRound, Loader2, Save,
  Pencil, UserX, X,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { TagChip } from "@/components/TagChip";
import { TagManager, type TagRecord } from "@/components/TagManager";
import { useAuthStore } from "@/store/auth";
import { T, t } from "@/store/lang";

interface Employee {
  id: string;
  employee_no: string;
  full_name: string;
  position?: string | null;
  department?: string | null;
  intended_role?: string | null;
  join_date?: string | null;
  end_date?: string | null;
  phone?: string | null;
  personal_email?: string | null;
  is_active: boolean;
  notes?: string | null;
  has_login: boolean;
  user_id?: string | null;
  user_email?: string | null;
  user_role?: string | null;
  tags: { id: string; name: string; color: string; description?: string | null }[];
  missed_days_this_month?: number;
}

// Every internal role, finance and purchasing included. Anything not listed
// here still renders — it just falls back to a neutral chip rather than
// disappearing off the page, which is what happened before.
const ROLE_CHIP: Record<string, string> = {
  sales:      "bg-brand-50 text-brand-700",
  admin:      "bg-violet-50 text-violet-700",
  hr:         "bg-amber-50 text-amber-700",
  finance:    "bg-lime-50 text-lime-700",
  purchasing: "bg-orange-50 text-orange-700",
  manager:    "bg-emerald-50 text-emerald-700",
  director:   "bg-red-50 text-red-700",
};

const FALLBACK_ROLES = [
  "sales", "admin", "hr", "finance", "purchasing", "manager", "director",
];

const BLANK = {
  employee_no: "", full_name: "", position: "", department: "",
  intended_role: "", join_date: "", phone: "", personal_email: "", notes: "",
};

export default function EmployeesPage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [openTags, setOpenTags] = useState(false);
  const [form, setForm] = useState<typeof BLANK & { id?: string }>({ ...BLANK });
  const [openForm, setOpenForm] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const catalog = useQuery({
    queryKey: ["employee-catalog"],
    queryFn: () => api.get("/employees/catalog")
      .then((r) => r.data as { roles: string[] }),
    staleTime: 300_000,
  });
  const roles = catalog.data?.roles ?? FALLBACK_ROLES;

  const employees = useQuery({
    queryKey: ["employees", roleFilter, search],
    queryFn: () => api.get("/employees", {
      params: { role: roleFilter || undefined, q: search || undefined },
    }).then((r) => r.data as Employee[]),
  });

  const tags = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.get("/tags").then((r) => r.data as TagRecord[]),
  });

  const save = useMutation({
    mutationFn: () => {
      const body = {
        employee_no: form.employee_no.trim() || undefined,
        full_name: form.full_name.trim(),
        position: form.position.trim() || null,
        department: form.department.trim() || null,
        intended_role: form.intended_role || null,
        join_date: form.join_date || null,
        phone: form.phone.trim() || null,
        personal_email: form.personal_email.trim() || null,
        notes: form.notes.trim() || null,
      };
      return form.id
        ? api.patch(`/employees/${form.id}`, { ...body, employee_no: form.employee_no.trim() })
        : api.post("/employees", body);
    },
    onSuccess: () => {
      setOpenForm(false);
      setFlash({
        kind: "ok",
        text: form.id
          ? t("Record updated.", "Data diperbarui.")
          : t("Added to the register. Give them a login from Users when they need one.",
              "Ditambahkan ke daftar karyawan. Buat akun masuknya dari Pengguna bila diperlukan."),
      });
      setForm({ ...BLANK });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? t("Couldn't save that record.", "Tidak bisa menyimpan data itu."),
    }),
  });

  const leaver = useMutation({
    mutationFn: (id: string) => api.delete(`/employees/${id}`),
    onSuccess: () => {
      setFlash({ kind: "ok", text: t("Marked as a leaver.", "Ditandai keluar.") });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed",
    }),
  });

  const filtered = useMemo(() => {
    const arr = employees.data ?? [];
    if (!tagFilter) return arr;
    return arr.filter((e) => e.tags?.some((x) => x.id === tagFilter));
  }, [employees.data, tagFilter]);

  const grouped = useMemo(() => {
    const m = new Map<string, Employee[]>();
    for (const e of filtered) {
      // Group by the role they actually hold if they have a login, and by
      // the role they were hired into if they don't — otherwise everybody
      // still waiting on an account piles up under one heading.
      const key = e.user_role || e.intended_role || "unassigned";
      const arr = m.get(key) ?? [];
      arr.push(e);
      m.set(key, arr);
    }
    return m;
  }, [filtered]);

  // Every role that has somebody in it, in the catalogue's order, with any
  // role the server knows nothing about still shown at the end.
  const sections = useMemo(() => {
    const known = roles.filter((r) => grouped.get(r)?.length);
    const rest = [...grouped.keys()].filter((k) => !roles.includes(k));
    return [...known, ...rest.sort()];
  }, [roles, grouped]);

  const awaitingLogin = filtered.filter((e) => !e.has_login).length;

  function startNew() {
    setForm({ ...BLANK });
    setOpenForm(true);
  }
  function startEdit(e: Employee) {
    setForm({
      id: e.id,
      employee_no: e.employee_no,
      full_name: e.full_name,
      position: e.position ?? "",
      department: e.department ?? "",
      intended_role: e.intended_role ?? "",
      join_date: e.join_date ?? "",
      phone: e.phone ?? "",
      personal_email: e.personal_email ?? "",
      notes: e.notes ?? "",
    });
    setOpenForm(true);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Users size={22} className="text-brand-600" /> {T("Employees")}</h1>
          <p className="text-sm muted">
            {t("Everybody who works here, with or without a login. Add the person here first — a login is created against this record, never the other way round.",
               "Semua orang yang bekerja di sini, dengan atau tanpa akun masuk. Tambahkan orangnya di sini dulu — akun masuk dibuat dari data ini, bukan sebaliknya.")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost border border-ink-200" onClick={() => setOpenTags(true)}>
            <Tags size={14} /> {T("Manage tags")}</button>
          <button className="btn-primary" onClick={startNew}>
            <Plus size={14} /> {t("New employee", "Karyawan baru")}</button>
        </div>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search employees"
            placeholder={t("Search by name, staff number or position…",
                           "Cari nama, nomor karyawan, atau jabatan…")}
            className="input pl-9"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          aria-label="Filter by role"
          className="input max-w-[160px]"
        >
          <option value="">{T("All roles")}</option>
          {roles.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          aria-label="Filter by tag"
          className="input max-w-[200px]"
        >
          <option value="">{T("All tags")}</option>
          {(tags.data ?? []).map((x) => (
            <option key={x.id} value={x.id}>{x.name}</option>
          ))}
        </select>
        <span className="ml-auto text-xs font-semibold text-ink-500">
          {filtered.length}
        </span>
      </div>

      {awaitingLogin > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-2.5
                        text-sm text-amber-900 flex items-center gap-2 flex-wrap">
          <KeyRound size={14} />
          <span className="flex-1">
            {awaitingLogin}{" "}
            {t("on the register cannot sign in yet.",
               "orang di daftar belum bisa masuk ke sistem.")}
          </span>
          {isDirector && (
            <Link to="/admin/users" className="underline hover:no-underline">
              {t("Create their logins", "Buatkan akun masuknya")}
            </Link>
          )}
        </div>
      )}

      <div className="space-y-5">
        {sections.map((r) => (
          <div key={r}>
            <div className="flex items-center gap-2 mb-2">
              <span className={clsx("chip uppercase",
                ROLE_CHIP[r] ?? "bg-ink-100 text-ink-700")}>
                {r === "unassigned" ? t("no role yet", "belum ada peran") : r}
              </span>
              <span className="text-xs muted">
                {grouped.get(r)!.length} {T("person(s)")}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {grouped.get(r)!.map((e) => (
                <EmployeeCard
                  key={e.id} e={e} isDirector={isDirector}
                  onEdit={() => startEdit(e)}
                  onLeaver={() => {
                    if (window.confirm(
                      `Mark ${e.full_name} as a leaver? They stay on the register — ` +
                      `everything they signed still points at them — but they drop out ` +
                      `of the active list.`
                    )) leaver.mutate(e.id);
                  }}
                />
              ))}
            </div>
          </div>
        ))}
        {!employees.isLoading && !filtered.length && (
          <div className="card p-12 text-center muted text-sm">
            {t("Nobody on the register matches that.",
               "Tidak ada karyawan yang cocok.")}
          </div>
        )}
      </div>

      <Modal
        open={openForm}
        onClose={() => setOpenForm(false)}
        title={form.id ? t("Edit employee", "Ubah karyawan")
                       : t("New employee", "Karyawan baru")}
        subtitle={t("The person, not the login. A staff number is generated if you leave it blank.",
                    "Data orangnya, bukan akun masuknya. Nomor karyawan dibuat otomatis bila dikosongkan.")}
        size="lg"
      >
        <form
          className="space-y-3"
          onSubmit={(ev) => { ev.preventDefault(); setFlash(null); save.mutate(); }}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={t("Full name *", "Nama lengkap *")}>
              <input className="input" required value={form.full_name}
                onChange={(ev) => setForm({ ...form, full_name: ev.target.value })} />
            </Field>
            <Field label={t("Staff number", "Nomor karyawan")}>
              <input className="input" value={form.employee_no}
                placeholder={t("auto", "otomatis")}
                onChange={(ev) => setForm({ ...form, employee_no: ev.target.value })} />
            </Field>
            <Field label={t("Position", "Jabatan")}>
              <input className="input" value={form.position}
                placeholder={t("e.g. Sales Engineer", "mis. Sales Engineer")}
                onChange={(ev) => setForm({ ...form, position: ev.target.value })} />
            </Field>
            <Field label={t("Department", "Departemen")}>
              <input className="input" value={form.department}
                onChange={(ev) => setForm({ ...form, department: ev.target.value })} />
            </Field>
            <Field label={t("Role their login should get", "Peran untuk akun masuknya")}>
              <select className="input" value={form.intended_role}
                onChange={(ev) => setForm({ ...form, intended_role: ev.target.value })}>
                <option value="">{t("— decide later —", "— tentukan nanti —")}</option>
                {roles.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              <span className="block text-[11px] text-ink-400 mt-1">
                {t("What the director will grant when the login is created. It is a note here, not access.",
                   "Yang akan diberikan direktur saat akun dibuat. Di sini hanya catatan, bukan akses.")}
              </span>
            </Field>
            <Field label={t("Start date", "Tanggal mulai")}>
              <input className="input" type="date" value={form.join_date}
                onChange={(ev) => setForm({ ...form, join_date: ev.target.value })} />
            </Field>
            <Field label={T("Phone")}>
              <input className="input" value={form.phone}
                onChange={(ev) => setForm({ ...form, phone: ev.target.value })} />
            </Field>
            <Field label={t("Personal email", "Email pribadi")}>
              <input className="input" type="email" value={form.personal_email}
                onChange={(ev) => setForm({ ...form, personal_email: ev.target.value })} />
            </Field>
          </div>
          <Field label={T("Notes")}>
            <textarea className="input min-h-[70px]" value={form.notes}
              onChange={(ev) => setForm({ ...form, notes: ev.target.value })} />
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-ghost" onClick={() => setOpenForm(false)}>
              {T("Cancel")}
            </button>
            <button type="submit" className="btn-primary"
              disabled={save.isPending || !form.full_name.trim()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" />
                              : <Save size={14} />}
              {form.id ? t("Save record", "Simpan data")
                       : t("Add to register", "Tambahkan ke daftar")}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={openTags}
        onClose={() => setOpenTags(false)}
        title={T("Manage tags")}
        subtitle={T("Create, rename, and recolor employee tags. Deleting a tag removes it from everyone.")}
        size="lg"
      >
        <TagManager onClose={() => setOpenTags(false)} />
      </Modal>
    </div>
  );
}

function EmployeeCard({ e, isDirector, onEdit, onLeaver }: {
  e: Employee; isDirector: boolean; onEdit: () => void; onLeaver: () => void;
}) {
  const role = e.user_role || e.intended_role;
  const body = (
    <>
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-brand-100 text-brand-700
                        grid place-items-center font-semibold shrink-0">
          {(e.full_name ?? "U").slice(0, 1).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium truncate">{e.full_name}</div>
          <div className="text-xs muted truncate flex items-center gap-1">
            <IdCard size={11} className="shrink-0" />
            {e.employee_no}
            {e.position && <span className="truncate">· {e.position}</span>}
          </div>
        </div>
        {role && (
          <span className={clsx("chip uppercase shrink-0",
            ROLE_CHIP[role] ?? "bg-ink-100 text-ink-700")}>{role}</span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {e.has_login ? (
          <span className="chip bg-emerald-50 text-emerald-700 inline-flex items-center gap-1">
            <KeyRound size={11} /> {e.user_email}
          </span>
        ) : (
          <span className="chip bg-amber-50 text-amber-800 inline-flex items-center gap-1">
            <KeyRound size={11} /> {t("no login yet", "belum ada akun masuk")}
          </span>
        )}
        {e.department && (
          <span className="chip bg-ink-100 text-ink-600">{e.department}</span>
        )}
      </div>

      {(e.tags?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {e.tags.map((x) => <TagChip key={x.id} name={x.name} color={x.color} small />)}
        </div>
      )}
      {(e.missed_days_this_month ?? 0) > 0 && (
        <div className="flex items-center gap-1.5">
          <span
            className={clsx("chip inline-flex items-center gap-1",
              (e.missed_days_this_month ?? 0) >= 3
                ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700")}
            title={T("Missed days this month (absent + half-day×0.5)")}
          >
            <CalendarX size={11} />
            {e.missed_days_this_month} {T("missed this month")}
          </span>
        </div>
      )}
    </>
  );

  return (
    <div className="card p-4 flex flex-col gap-2">
      {/* Only somebody with a login has a profile to open — the detail page
          is built out of their pipeline, attendance and documents, all of
          which hang off the account. Without one the card is the record. */}
      {e.has_login ? (
        <Link to={`/employees/${e.user_id}`}
          className="flex flex-col gap-2 -m-1 p-1 rounded-lg hover:bg-ink-50">
          {body}
        </Link>
      ) : body}

      <div className="flex items-center gap-1 pt-1 border-t border-ink-100">
        <button className="btn-ghost text-xs" onClick={onEdit}
          aria-label={`Edit ${e.full_name}`}>
          <Pencil size={12} /> {T("Edit")}
        </button>
        {!e.has_login && isDirector && (
          <Link to={`/admin/users?employee=${e.id}`} className="btn-ghost text-xs text-brand-700">
            <KeyRound size={12} /> {t("Create login", "Buat akun masuk")}
          </Link>
        )}
        {isDirector && (
          <button className="btn-ghost text-xs text-red-600 hover:bg-red-50 ml-auto"
            onClick={onLeaver} aria-label={`Mark ${e.full_name} a leaver`}>
            <UserX size={12} /> {t("Leaver", "Keluar")}
          </button>
        )}
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
