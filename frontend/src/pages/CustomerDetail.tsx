import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Building2, Mail, Phone, MessageCircle, MapPin, Sparkles, Activity,
} from "lucide-react";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({
    queryKey: ["customer", id],
    queryFn: () => api.get(`/customers/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const score = useQuery({
    queryKey: ["lead-score", id],
    queryFn: () => api.get(`/ai/lead-score/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const c = q.data;
  if (!c) return <div className="muted">Loading…</div>;

  const s: number = score.data?.score ?? 0;
  const ring = `conic-gradient(#3a5cf5 ${s * 3.6}deg, #eef0f4 0deg)`;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div className="h-14 w-14 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white flex items-center justify-center text-xl font-semibold">
              {c.company_name.slice(0, 1).toUpperCase()}
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{c.company_name}</h1>
              <div className="text-sm muted flex items-center gap-2 mt-1 capitalize">
                <Building2 size={14} /> {c.industry}
                <span className="muted">·</span>
                <StageBadge stage={c.stage} />
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="btn-ghost"><MessageCircle size={15} /> WhatsApp</button>
            <button className="btn-primary"><Sparkles size={15} /> AI suggest</button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6 text-sm">
          <Field icon={<Phone size={14} />} label="Phone" value={c.phone} />
          <Field icon={<MessageCircle size={14} />} label="WhatsApp" value={c.whatsapp} />
          <Field icon={<Mail size={14} />} label="Email" value={c.email} />
          <Field icon={<MapPin size={14} />} label="Address" value={c.company_address} />
        </div>
      </div>

      {/* AI strip */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Sparkles size={12} /> AI Lead score
          </div>
          <div className="mt-3 flex items-center gap-4">
            <div
              className="h-20 w-20 rounded-full grid place-items-center"
              style={{ background: ring }}
            >
              <div className="h-15 w-15 rounded-full bg-white px-3 py-2 text-center">
                <div className="text-2xl font-semibold leading-none">{s}</div>
                <div className="text-[9px] uppercase muted tracking-widest">/ 100</div>
              </div>
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium">{score.data?.recommended_action ?? "—"}</div>
              <div className="text-xs muted mt-1">Model {score.data?.model_version ?? "—"}</div>
            </div>
          </div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Activity size={12} /> Top score drivers
          </div>
          <ul className="mt-3 space-y-2">
            {(score.data?.drivers ?? []).slice(0, 5).map((d: any) => (
              <li key={d.feature} className="flex items-center gap-3 text-sm">
                <span className="w-44 truncate text-ink-700">{d.feature.replace(/_/g, " ")}</span>
                <div className="flex-1 h-1.5 bg-ink-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-brand-500"
                    style={{ width: `${Math.min(100, d.contribution * 5)}%` }}
                  />
                </div>
                <span className="muted w-14 text-right tabular-nums">+{d.contribution}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Activity timeline */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="font-semibold text-ink-900">Activity timeline</div>
          <button className="btn-ghost"><Activity size={15} /> Log activity</button>
        </div>
        <div className="rounded-xl border border-dashed border-ink-200 p-8 text-center text-sm muted">
          No activity yet — incoming WhatsApp will appear here automatically.
        </div>
      </div>
    </div>
  );
}

function Field({ icon, label, value }: {
  icon: React.ReactNode;
  label: string;
  value?: string | null;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900 truncate">{value ?? "—"}</div>
    </div>
  );
}
