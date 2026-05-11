import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Users, Search } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface Employee {
  id: string;
  email: string;
  full_name: string;
  role: "sales" | "admin" | "hr" | "manager" | "director";
  phone?: string | null;
  is_active: boolean;
}

const ROLE_CHIP: Record<Employee["role"], string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
};

const ROLES = ["sales", "admin", "hr", "manager", "director"] as const;

export default function EmployeesPage() {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("");

  const employees = useQuery({
    queryKey: ["employees", roleFilter, search],
    queryFn: () =>
      api.get("/users", {
        params: { role: roleFilter || undefined, q: search || undefined },
      }).then((r) => r.data as Employee[]),
  });

  const grouped = useMemo(() => {
    const m = new Map<string, Employee[]>();
    for (const e of employees.data ?? []) {
      const arr = m.get(e.role) ?? [];
      arr.push(e);
      m.set(e.role, arr);
    }
    return m;
  }, [employees.data]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Users size={22} className="text-brand-600" /> Employees
        </h1>
        <p className="text-sm muted">
          People in your organization. Click any sales person to see their pipeline,
          quotations, customers, and activity.
        </p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or email…"
            className="input pl-9"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="input max-w-[200px]"
        >
          <option value="">All roles</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <span className="ml-auto text-xs font-semibold text-ink-500">
          {(employees.data ?? []).length}
        </span>
      </div>

      {/* Group by role */}
      <div className="space-y-5">
        {ROLES.filter((r) => grouped.get(r)?.length).map((r) => (
          <div key={r}>
            <div className="flex items-center gap-2 mb-2">
              <span className={clsx("chip uppercase", ROLE_CHIP[r])}>{r}</span>
              <span className="text-xs muted">{grouped.get(r)!.length} person(s)</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {grouped.get(r)!.map((e) => (
                <Link
                  key={e.id}
                  to={`/employees/${e.id}`}
                  className="card card-hover p-4 flex items-center gap-3"
                >
                  <div className="h-10 w-10 rounded-full bg-brand-100 text-brand-700 grid place-items-center font-semibold">
                    {(e.full_name ?? "U").slice(0, 1).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{e.full_name}</div>
                    <div className="text-xs muted truncate">{e.email}</div>
                  </div>
                  <span className={clsx("chip uppercase", ROLE_CHIP[e.role])}>{e.role}</span>
                </Link>
              ))}
            </div>
          </div>
        ))}
        {!employees.isLoading && !(employees.data ?? []).length && (
          <div className="card p-12 text-center muted text-sm">
            No employees match your filter.
          </div>
        )}
      </div>
    </div>
  );
}
