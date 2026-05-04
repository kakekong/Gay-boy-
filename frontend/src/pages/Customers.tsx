import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";
import type { Customer } from "@/types";

export default function CustomersPage() {
  const q = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get("/customers").then((r) => r.data),
  });
  const rows: Customer[] = q.data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex justify-between">
        <h1 className="text-xl font-semibold">Customers</h1>
        <button className="bg-brand-500 hover:bg-brand-700 text-white px-3 py-1.5 rounded text-sm">
          + New customer
        </button>
      </div>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500 border-b">
            <tr>
              <th className="px-4 py-2">Company</th>
              <th className="px-4 py-2">Industry</th>
              <th className="px-4 py-2">PIC</th>
              <th className="px-4 py-2">Stage</th>
              <th className="px-4 py-2 text-right">LTV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b hover:bg-slate-50">
                <td className="px-4 py-2">
                  <Link to={`/customers/${c.id}`} className="text-brand-700 hover:underline">
                    {c.company_name}
                  </Link>
                </td>
                <td className="px-4 py-2">{c.industry}</td>
                <td className="px-4 py-2">{c.pic_name ?? "—"}</td>
                <td className="px-4 py-2"><StageBadge stage={c.stage} /></td>
                <td className="px-4 py-2 text-right">
                  {new Intl.NumberFormat("id-ID").format(c.lifetime_value ?? 0)}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No data</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
