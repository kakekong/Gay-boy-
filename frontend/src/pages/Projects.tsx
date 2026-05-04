import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function ProjectsPage() {
  const q = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data),
  });
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Projects</h1>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500 border-b">
            <tr>
              <th className="px-4 py-2">Code</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">PO Value</th>
              <th className="px-4 py-2 text-right">Margin (est / act)</th>
              <th className="px-4 py-2">Target delivery</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((p: any) => (
              <tr key={p.id} className="border-b">
                <td className="px-4 py-2 font-mono text-xs">{p.code}</td>
                <td className="px-4 py-2">{p.status}</td>
                <td className="px-4 py-2 text-right">
                  {new Intl.NumberFormat("id-ID").format(p.po_value)}
                </td>
                <td className="px-4 py-2 text-right">
                  {(p.margin_estimate * 100).toFixed(1)}% / {(p.margin_actual * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-2">{p.target_delivery ?? "—"}</td>
              </tr>
            ))}
            {!q.data?.length && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No projects</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
