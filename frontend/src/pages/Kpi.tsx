import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download } from "lucide-react";
import { api } from "@/api/client";

async function readBlobError(e: any): Promise<string> {
  const status = e?.response?.status;
  const blob: Blob | undefined = e?.response?.data;
  let detail = "";
  if (blob && typeof blob.text === "function") {
    try {
      const text = await blob.text();
      try {
        const parsed = JSON.parse(text);
        detail = parsed?.detail ?? parsed?.errors?.[0]?.message ?? text;
      } catch {
        detail = text;
      }
    } catch { /* fall through */ }
  }
  if (!detail) detail = e?.message ?? "Export failed";
  return status ? `Export failed (HTTP ${status}): ${detail}` : detail;
}

function exportKpi(ext: "pdf" | "xlsx") {
  api.get(`/kpi/export.${ext}`, { responseType: "blob" })
    .then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `kpi.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    })
    .catch(async (e) => {
      console.error("KPI export failed", e);
      alert(await readBlobError(e));
    });
}

export default function KpiPage() {
  const sales = useQuery({ queryKey: ["kpi-sales"],   queryFn: () => api.get("/kpi/sales").then(r => r.data) });
  const ops   = useQuery({ queryKey: ["kpi-ops"],     queryFn: () => api.get("/kpi/operation").then(r => r.data) });
  const fin   = useQuery({ queryKey: ["kpi-fin"],     queryFn: () => api.get("/kpi/finance").then(r => r.data) });
  const purch = useQuery({ queryKey: ["kpi-purch"],   queryFn: () => api.get("/kpi/purchasing").then(r => r.data) });

  const cards: { title: string; data: any; tone: string }[] = [
    { title: "Sales",       data: sales.data, tone: "from-brand-50 to-brand-100" },
    { title: "Operation",   data: ops.data,   tone: "from-emerald-50 to-emerald-100" },
    { title: "Purchasing",  data: purch.data, tone: "from-violet-50 to-violet-100" },
    { title: "Finance",     data: fin.data,   tone: "from-amber-50 to-amber-100" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <BarChart3 size={22} className="text-brand-600" /> KPIs
          </h1>
          <p className="text-sm muted">Performance across every department.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => exportKpi("pdf")}>
            <Download size={15} /> PDF
          </button>
          <button className="btn-ghost" onClick={() => exportKpi("xlsx")}>
            <Download size={15} /> Excel
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {cards.map((c) => (
          <div key={c.title} className="card overflow-hidden">
            <div className={`bg-gradient-to-br ${c.tone} px-5 py-3`}>
              <div className="font-semibold text-ink-900">{c.title}</div>
            </div>
            <div className="p-5">
              {c.data ? (
                <ul className="grid grid-cols-2 gap-3">
                  {Object.entries(c.data).map(([k, v]) => (
                    <li key={k} className="rounded-lg bg-ink-50 px-3 py-2">
                      <div className="text-[11px] uppercase muted tracking-wider">
                        {k.replace(/_/g, " ")}
                      </div>
                      <div className="font-semibold tabular-nums">
                        {typeof v === "number" ? v.toLocaleString("id-ID") : String(v ?? "—")}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="muted text-sm">Loading…</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
