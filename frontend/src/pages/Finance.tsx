import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Banknote, ShieldCheck, LineChart } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import PaymentVerificationPage from "@/pages/PaymentVerification";

const BUCKETS = [
  { key: "current", label: "Current",    color: "bg-emerald-500" },
  { key: "0-30",    label: "0–30 days",  color: "bg-amber-400" },
  { key: "31-60",   label: "31–60 days", color: "bg-orange-500" },
  { key: "61-90",   label: "61–90 days", color: "bg-red-500" },
  { key: "90+",     label: "90+ days",   color: "bg-red-700" },
];

export default function FinancePage() {
  const [tab, setTab] = useState<"aging" | "verification">("aging");

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Banknote size={22} className="text-brand-600" /> Finance
          </h1>
          <p className="text-sm muted">Receivables, payment verification, and estimates.</p>
        </div>
        <Link to="/finance/estimated" className="btn-ghost">
          <LineChart size={15} /> Estimated finance
        </Link>
      </div>

      <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
        <TabButton active={tab === "aging"} onClick={() => setTab("aging")} icon={Banknote}>
          AR Aging
        </TabButton>
        <TabButton active={tab === "verification"} onClick={() => setTab("verification")} icon={ShieldCheck}>
          Payment verification
        </TabButton>
      </div>

      {tab === "aging" ? <ArAging /> : <PaymentVerificationPage />}
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, children }: {
  active: boolean; onClick: () => void; icon: typeof Banknote; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
        active ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
      )}
    >
      <Icon size={14} /> {children}
    </button>
  );
}

function ArAging() {
  const aging = useQuery({
    queryKey: ["ar-aging"],
    queryFn: () => api.get("/finance/ar/aging").then((r) => r.data),
  });
  const buckets = aging.data ?? {};
  const fmt = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);
  const total = BUCKETS.reduce((acc, b) => acc + (buckets[b.key] || 0), 0);

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="text-xs uppercase tracking-wider muted">Total outstanding</div>
        <div className="text-3xl font-semibold tabular-nums mt-1">{fmt(total)}</div>
        <div className="mt-4 flex h-3 rounded-full overflow-hidden border border-ink-100">
          {BUCKETS.map((b) => {
            const w = total ? ((buckets[b.key] || 0) / total) * 100 : 0;
            return (
              <div
                key={b.key}
                className={clsx("h-full", b.color)}
                style={{ width: `${w}%` }}
                title={`${b.label}: ${fmt(buckets[b.key] || 0)}`}
              />
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {BUCKETS.map((b) => (
          <div key={b.key} className="card p-4">
            <div className="flex items-center gap-2 text-xs muted">
              <span className={clsx("h-2 w-2 rounded-full", b.color)} />
              {b.label}
            </div>
            <div className="text-xl font-semibold tabular-nums mt-1">
              {fmt(buckets[b.key] || 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
