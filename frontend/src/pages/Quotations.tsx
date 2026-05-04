import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Quotation } from "@/types";

export default function QuotationsPage() {
  const q = useQuery({
    queryKey: ["quotations"],
    queryFn: () => api.get("/quotations").then((r) => r.data as Quotation[]),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-between">
        <h1 className="text-xl font-semibold">Quotations</h1>
        <button className="bg-brand-500 hover:bg-brand-700 text-white px-3 py-1.5 rounded text-sm">
          + New quotation
        </button>
      </div>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500 border-b">
            <tr>
              <th className="px-4 py-2">Number</th>
              <th className="px-4 py-2">Variant</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Discount</th>
              <th className="px-4 py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((qt) => (
              <tr key={qt.id} className="border-b">
                <td className="px-4 py-2 font-mono text-xs">{qt.number}</td>
                <td className="px-4 py-2">{qt.variant}</td>
                <td className="px-4 py-2">{qt.status}</td>
                <td className="px-4 py-2 text-right">{qt.discount_pct}%</td>
                <td className="px-4 py-2 text-right">
                  {new Intl.NumberFormat("id-ID").format(qt.total)}
                </td>
              </tr>
            ))}
            {!q.data?.length && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No quotations</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
