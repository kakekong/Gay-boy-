import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Briefcase, Building2, FileText, Calendar, Truck, Receipt,
  ShoppingCart, Wrench, Plus, CheckCircle, Loader2, Hammer,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";

const STATUS_CHIP: Record<string, string> = {
  new:              "bg-ink-100 text-ink-700",
  drawing:          "bg-cyan-50 text-cyan-700",
  drawing_approved: "bg-cyan-100 text-cyan-800",
  purchasing:       "bg-teal-50 text-teal-700",
  production:       "bg-violet-50 text-violet-700",
  qc:               "bg-amber-50 text-amber-700",
  packaging:        "bg-yellow-50 text-yellow-700",
  delivered:        "bg-lime-50 text-lime-700",
  invoiced:         "bg-orange-50 text-orange-700",
  paid:             "bg-emerald-50 text-emerald-700",
  closed:           "bg-emerald-100 text-emerald-800",
};

const PIPELINE_STAGES = [
  "new", "drawing", "drawing_approved", "purchasing",
  "production", "qc", "packaging", "delivered", "invoiced", "paid", "closed",
];

const WO_STAGES = ["receiving", "warehousing", "qc", "packaging", "delivery"];

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();

  const data = useQuery({
    queryKey: ["project-full", id],
    queryFn: () => api.get(`/operation/projects/${id}/full`).then((r) => r.data),
    enabled: !!id,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["project-full", id] });

  const [newWoCode, setNewWoCode] = useState("");
  const [newWoStage, setNewWoStage] = useState("receiving");

  const addWO = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/work-orders`, {
      code: newWoCode, stage: newWoStage,
    }),
    onSuccess: () => { refresh(); setNewWoCode(""); },
  });
  const completeWO = useMutation({
    mutationFn: (woId: string) =>
      api.patch(`/operation/work-orders/${woId}`, null, { params: { completed: true } }),
    onSuccess: refresh,
  });
  const markDelivered = useMutation({
    mutationFn: (doId: string) => api.patch(`/operation/deliveries/${doId}/delivered`),
    onSuccess: refresh,
  });

  if (data.isLoading) return <div className="muted text-sm">Loading…</div>;
  if (!data.data)     return <div className="muted text-sm">Project not found.</div>;

  const p   = data.data.project;
  const cu  = data.data.customer;
  const qt  = data.data.quotation;
  const wos = data.data.work_orders ?? [];
  const dr  = data.data.drawings ?? [];
  const dos = data.data.deliveries ?? [];
  const inv = data.data.invoices ?? [];
  const prs = data.data.purchase_requests ?? [];

  const marginDelta = (p.margin_actual || 0) - (p.margin_estimate || 0);
  const stageIdx = PIPELINE_STAGES.indexOf(p.status);

  return (
    <div className="space-y-6">
      <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
        <ArrowLeft size={15} /> Back
      </button>

      {/* Header */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white grid place-items-center">
              <Briefcase size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-semibold tracking-tight font-mono">{p.code}</h1>
                <span className={clsx("chip capitalize",
                  STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700")}>
                  {p.status.replace(/_/g, " ")}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-sm flex-wrap">
                {cu && (
                  <Link to={`/customers/${cu.id}`}
                    className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700">
                    <Building2 size={13} /> {cu.company_name}
                  </Link>
                )}
                {qt && (
                  <Link to={`/quotations/${qt.id}`}
                    className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700">
                    <FileText size={13} /> {qt.number}
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Stage pipeline */}
        <div className="mt-6 flex flex-wrap items-center gap-1.5">
          {PIPELINE_STAGES.map((s, i) => (
            <span key={s}
              className={clsx(
                "chip capitalize",
                i < stageIdx        ? "bg-emerald-100 text-emerald-700"
                : i === stageIdx    ? STATUS_CHIP[s] ?? "bg-ink-100 text-ink-700"
                                    : "bg-ink-100/60 text-ink-400"
              )}
            >
              {i < stageIdx && <CheckCircle size={10} />}
              {s.replace(/_/g, " ")}
            </span>
          ))}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 text-sm">
          <Field label="PO Number" icon={<FileText size={13} />}>{p.po_number ?? "—"}</Field>
          <Field label="PO Date" icon={<Calendar size={13} />}>{p.po_date ?? "—"}</Field>
          <Field label="Target delivery" icon={<Truck size={13} />}>{p.target_delivery ?? "—"}</Field>
          <Field label="Actual delivery" icon={<Truck size={13} />}>{p.actual_delivery ?? "—"}</Field>
        </div>
      </div>

      {/* Profit / Margin */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="PO value"      value={idr(p.po_value)}              tone="brand"   />
        <Stat label="Margin (est)"  value={pct(p.margin_estimate)}       tone="amber"   />
        <Stat
          label="Margin (actual)"
          value={pct(p.margin_actual)}
          tone={marginDelta < -0.05 ? "red"
                : marginDelta < 0    ? "amber" : "emerald"}
        />
        <Stat
          label="Delta vs estimate"
          value={`${marginDelta >= 0 ? "+" : ""}${(marginDelta * 100).toFixed(1)} pp`}
          tone={marginDelta < -0.05 ? "red" : marginDelta < 0 ? "amber" : "emerald"}
        />
      </div>

      {/* Work orders */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
          <div>
            <div className="font-semibold flex items-center gap-2">
              <Wrench size={15} className="text-brand-600" /> Work orders
            </div>
            <div className="text-xs muted">{wos.length} step(s)</div>
          </div>
        </div>
        <div className="p-3 flex flex-wrap items-end gap-2 border-b border-ink-100 bg-ink-50/40">
          <div className="flex-1 min-w-[180px]">
            <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Code</span>
            <input className="input" value={newWoCode}
              onChange={(e) => setNewWoCode(e.target.value)}
              placeholder="e.g. WO-PRJ-2026-0042-02" />
          </div>
          <div>
            <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Stage</span>
            <select className="input" value={newWoStage}
              onChange={(e) => setNewWoStage(e.target.value)}>
              {WO_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <button className="btn-primary"
            disabled={!newWoCode || addWO.isPending}
            onClick={() => addWO.mutate()}>
            {addWO.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add work order
          </button>
        </div>
        {wos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No work orders yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Code</th>
                <th className="th">Stage</th>
                <th className="th">Started</th>
                <th className="th">Completed</th>
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {wos.map((w: any) => (
                <tr key={w.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{w.code}</td>
                  <td className="td">
                    <span className="chip bg-ink-100 text-ink-700 capitalize">{w.stage}</span>
                  </td>
                  <td className="td muted">{w.started_at ? new Date(w.started_at).toLocaleDateString() : "—"}</td>
                  <td className="td muted">
                    {w.completed_at
                      ? <span className="text-emerald-700">{new Date(w.completed_at).toLocaleDateString()}</span>
                      : "—"}
                  </td>
                  <td className="td text-right">
                    {!w.completed_at && (
                      <button className="btn-ghost text-emerald-700"
                        onClick={() => completeWO.mutate(w.id)}>
                        <CheckCircle size={13} /> Complete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Drawings */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Hammer size={15} className="text-brand-600" /> Drawings
          </div>
          <div className="text-xs muted">{dr.length} revision(s)</div>
        </div>
        {dr.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No drawings uploaded.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Rev</th>
                <th className="th">Status</th>
                <th className="th">Customer decision</th>
                <th className="th">File</th>
                <th className="th">Notes</th>
              </tr>
            </thead>
            <tbody>
              {dr.map((d: any) => (
                <tr key={d.id} className="border-t border-ink-100">
                  <td className="td font-mono">v{d.revision}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      d.status === "approved" ? "bg-emerald-50 text-emerald-700"
                      : d.status === "submitted" ? "bg-amber-50 text-amber-700"
                      : d.status === "revision_requested" ? "bg-red-50 text-red-700"
                      : "bg-ink-100 text-ink-700"
                    )}>
                      {d.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td muted">{d.customer_decision_at ? new Date(d.customer_decision_at).toLocaleDateString() : "—"}</td>
                  <td className="td">
                    {d.file_url ? (
                      <a href={d.file_url} target="_blank" rel="noreferrer"
                         className="text-brand-700 hover:underline">View</a>
                    ) : "—"}
                  </td>
                  <td className="td muted">{d.notes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Deliveries */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Truck size={15} className="text-brand-600" /> Deliveries
          </div>
          <div className="text-xs muted">{dos.length} shipment(s)</div>
        </div>
        {dos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No deliveries yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">DO</th>
                <th className="th">Split</th>
                <th className="th">Courier</th>
                <th className="th">Tracking</th>
                <th className="th">Status</th>
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {dos.map((d: any) => (
                <tr key={d.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{d.number}</td>
                  <td className="td muted">#{d.split_index}</td>
                  <td className="td">{d.courier ?? "—"}</td>
                  <td className="td font-mono text-xs">{d.tracking_no ?? "—"}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      d.status === "delivered" ? "bg-emerald-50 text-emerald-700"
                      : d.status === "in_transit" ? "bg-amber-50 text-amber-700"
                      : "bg-ink-100 text-ink-700"
                    )}>
                      {d.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td text-right">
                    {d.status !== "delivered" && (
                      <button className="btn-ghost text-emerald-700"
                        onClick={() => markDelivered.mutate(d.id)}>
                        <CheckCircle size={13} /> Mark delivered
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Invoices */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> Invoices
          </div>
          <div className="text-xs muted">{inv.length} invoice(s)</div>
        </div>
        {inv.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No invoices yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Type</th>
                <th className="th">Due</th>
                <th className="th">Status</th>
                <th className="th text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {inv.map((i: any) => (
                <tr key={i.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{i.number}</td>
                  <td className="td capitalize">{i.type}{i.termin_index ? ` #${i.termin_index}` : ""}</td>
                  <td className="td muted">{i.due_date ?? "—"}</td>
                  <td className="td"><span className="chip bg-ink-100 text-ink-700">{i.status}</span></td>
                  <td className="td text-right font-medium tabular-nums">{idr(i.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Purchase Requests */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <ShoppingCart size={15} className="text-brand-600" /> Purchase requests
          </div>
          <div className="text-xs muted">{prs.length} PR(s)</div>
        </div>
        {prs.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No purchase requests linked.</div>
        ) : (
          <ul className="divide-y divide-ink-100">
            {prs.map((pr: any) => (
              <li key={pr.id} className="p-3 flex items-center gap-3">
                <span className="font-mono text-xs">{pr.number}</span>
                <span className="chip bg-ink-100 text-ink-700">{pr.status}</span>
                <span className="text-xs muted">
                  {(pr.items ?? []).length} item(s)
                </span>
                <span className="ml-auto text-[11px] text-ink-400">
                  {new Date(pr.created_at).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Attachments */}
      <AttachmentsSection ownerType="project" ownerId={p.id} />
    </div>
  );
}

function Field({ icon, label, children }: {
  icon?: React.ReactNode; label: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}

function Stat({ label, value, tone }: {
  label: string; value: string;
  tone: "brand" | "emerald" | "amber" | "red";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    emerald: "bg-emerald-50 text-emerald-700",
    amber:   "bg-amber-50 text-amber-700",
    red:     "bg-red-50 text-red-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={`inline-block text-[11px] uppercase tracking-wider px-2 py-0.5 rounded ${cls}`}>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
