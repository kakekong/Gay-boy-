import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Factory, FileText, Download, Loader2, FileSpreadsheet, Hammer, Receipt,
  Truck, Warehouse, AlertCircle, CheckCircle2, Save,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const UPLOAD_KINDS = [
  { value: "drawing",  label: "Drawing",          Icon: Hammer },
  { value: "invoice",  label: "Invoice",          Icon: Receipt },
  { value: "bill",     label: "Bill / Statement", Icon: FileSpreadsheet },
  { value: "delivery", label: "Delivery (landing)", Icon: Truck },
];

interface PO {
  id: string; number: string; status: string;
  po_date: string | null; quoted_lead_days: number | null;
  total: number; items: any[];
  project_id: string | null;
  project_code: string | null;
  est_arrive_our_warehouse: string | null;
  act_arrive_our_warehouse: string | null;
  act_ship_from_origin: string | null;
  has_drawing: boolean;
}

export default function SupplierPortalPage() {
  const qc = useQueryClient();

  const me = useQuery({
    queryKey: ["portal-supplier-me"],
    queryFn: () => api.get("/portal/supplier/me").then((r) => r.data),
  });
  const orders = useQuery({
    queryKey: ["portal-supplier-orders"],
    queryFn: () => api.get("/portal/supplier/orders").then((r) => r.data),
  });

  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-ink-900 via-teal-800 to-teal-600 text-white p-6 lg:p-8 shadow-hero">
        <div className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-teal-300/20 blur-3xl pointer-events-none" />
        <div className="relative flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-white/15 backdrop-blur grid place-items-center">
            <Factory size={22} />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-white/70">Supplier portal</div>
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight mt-0.5">
              {me.data?.name ?? "Loading…"}
            </h1>
            <p className="text-white/80 text-sm mt-1">
              See your open POs and upload invoices, drawings, bills, and delivery (landing) documents.
            </p>
          </div>
        </div>
      </div>

      {/* RFQs */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <FileText size={15} className="text-brand-600" /> Open RFQs
          </div>
        </div>
        {(orders.data?.rfqs ?? []).length === 0 ? (
          <div className="p-6 text-center text-sm muted">No RFQs right now.</div>
        ) : (
          <ul className="divide-y divide-ink-100">
            {orders.data!.rfqs.map((r: any) => (
              <li key={r.id} className="p-3 text-sm flex items-center gap-3 flex-wrap">
                <span className="chip bg-amber-50 text-amber-700">RFQ</span>
                <span className="muted">Lead time: {r.quoted_lead_days ?? "—"} days</span>
                <span className="muted">{(r.quoted_lines ?? []).length} line(s)</span>
                <span className="ml-auto text-xs text-ink-400">
                  {new Date(r.created_at).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* POs */}
      <div className="space-y-3">
        <div className="font-semibold text-lg">Purchase orders</div>
        {(orders.data?.purchase_orders ?? []).length === 0 && (
          <div className="card p-8 text-center text-sm muted">No POs yet.</div>
        )}
        {(orders.data?.purchase_orders ?? []).map((po: PO) => (
          <POCard key={po.id} po={po} />
        ))}
      </div>
    </div>
  );
}

function POCard({ po }: { po: PO }) {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<string>("drawing");
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const [estWh, setEstWh] = useState(po.est_arrive_our_warehouse ?? "");
  const [actShip, setActShip] = useState(po.act_ship_from_origin ?? "");
  const [actWh, setActWh] = useState(po.act_arrive_our_warehouse ?? "");

  const files = useQuery({
    queryKey: ["portal-supplier-attachments", po.id],
    queryFn: () => api.get("/portal/supplier/attachments", { params: { po_id: po.id } })
      .then((r) => r.data as any[]),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("po_id", po.id);
      form.append("kind", kind);
      form.append("file", file);
      return api.post("/portal/supplier/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portal-supplier-attachments", po.id] });
      qc.invalidateQueries({ queryKey: ["portal-supplier-orders"] });
      if (inputRef.current) inputRef.current.value = "";
      setErr(null);
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
             ?? e?.response?.data?.detail
             ?? "Upload failed"),
  });

  const saveEta = useMutation({
    mutationFn: () => {
      // Only send fields the supplier actually filled in. Empty strings
      // shouldn't null out existing dates, and the estimate alone is fine.
      const body: Record<string, string> = {};
      if (estWh) body.est_arrive_our_warehouse = estWh;
      if (actShip) body.act_ship_from_origin = actShip;
      if (actWh) body.act_arrive_our_warehouse = actWh;
      return api.post(`/portal/supplier/po/${po.id}/eta`, body).then((r) => r.data);
    },
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["portal-supplier-orders"] });
      const saved = data?.est_arrive_our_warehouse ?? estWh ?? "";
      setFlash(saved
        ? `Saved. Customer now sees expected arrival: ${saved}.`
        : "Saved. The customer can see the new dates immediately.");
      setErr(null);
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
             ?? e?.response?.data?.detail
             ?? "Couldn't save dates"),
  });

  function download(id: string, filename: string) {
    api.get(`/attachments/${id}/download`, { responseType: "blob" })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e) => {
        console.error("Download failed", e);
        const msg = e?.response?.status === 410
          ? "File missing from server storage — please re-upload."
          : (e?.response?.data?.detail ?? "Download failed");
        alert(msg);
      });
  }

  const needsDrawing = !po.has_drawing;
  const needsEta = !po.est_arrive_our_warehouse;
  const needsProject = !po.project_id;

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="font-mono text-sm">{po.number}</div>
          <div className="text-xs muted">
            PO date: {po.po_date ?? "—"} · Lead: {po.quoted_lead_days ?? "—"} days · {(po.items ?? []).length} line(s)
          </div>
          {po.project_code && (
            <div className="text-xs mt-0.5">
              Project: <span className="font-mono text-brand-700">{po.project_code}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-[10px] uppercase muted">Total</div>
            <div className="font-semibold tabular-nums">{idr(po.total)}</div>
          </div>
          <span className="chip bg-ink-100 text-ink-700 uppercase">{po.status}</span>
        </div>
      </div>

      {/* Required-action banner */}
      {(needsProject || needsDrawing || needsEta) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-900 flex flex-wrap gap-3">
          {needsProject && (
            <span className="inline-flex items-center gap-1">
              <AlertCircle size={12} /> Not linked to a project — ask the buyer to attach one
            </span>
          )}
          {needsDrawing && !needsProject && (
            <span className="inline-flex items-center gap-1">
              <AlertCircle size={12} /> Drawing PDF required
            </span>
          )}
          {needsEta && !needsProject && (
            <span className="inline-flex items-center gap-1">
              <AlertCircle size={12} /> Set the estimated arrival at our warehouse
            </span>
          )}
        </div>
      )}

      {/* Status checklist */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <StatusTile
          done={po.has_drawing}
          label="Drawing uploaded"
          hint={po.has_drawing ? "Visible to the customer for approval" : "Upload below"}
        />
        <StatusTile
          done={!!po.est_arrive_our_warehouse}
          label="Warehouse ETA"
          hint={po.est_arrive_our_warehouse
            ? `Customer sees: ${po.est_arrive_our_warehouse}`
            : "Just an estimate is enough — customer sees it instantly"}
        />
      </div>

      {/* Shipping date inputs */}
      <div className="rounded-xl border border-ink-200 bg-white p-3">
        <div className="text-xs font-semibold uppercase muted mb-1 flex items-center gap-1">
          <Warehouse size={12} /> Shipping dates (visible to the customer)
        </div>
        <div className="text-[11px] muted mb-3">
          Fill in any of these as soon as you know them — the customer sees
          updates straight away. <b>Just the estimate alone is enough</b>;
          you don't have to wait for the goods to actually arrive.
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Field label="Est. arrival at our warehouse">
            <input
              type="date"
              className="input"
              value={estWh ? estWh.slice(0, 10) : ""}
              onChange={(e) => setEstWh(e.target.value)}
              disabled={needsProject}
            />
          </Field>
          <Field label="Actual ship from origin">
            <input
              type="date"
              className="input"
              value={actShip ? actShip.slice(0, 10) : ""}
              onChange={(e) => setActShip(e.target.value)}
              disabled={needsProject}
            />
          </Field>
          <Field label="Actual arrival at warehouse">
            <input
              type="date"
              className="input"
              value={actWh ? actWh.slice(0, 10) : ""}
              onChange={(e) => setActWh(e.target.value)}
              disabled={needsProject}
            />
          </Field>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button
            className="btn-primary"
            disabled={saveEta.isPending || needsProject}
            onClick={() => saveEta.mutate()}
          >
            {saveEta.isPending
              ? <Loader2 size={14} className="animate-spin" />
              : <Save size={14} />}
            Save dates
          </button>
          {flash && <span className="text-xs text-emerald-700">{flash}</span>}
        </div>
      </div>

      {/* Upload row */}
      <div className="rounded-xl border border-ink-200 bg-ink-50/30 p-3">
        <div className="text-xs font-semibold uppercase muted mb-2">Upload a document</div>
        <div className="flex flex-wrap gap-2">
          {UPLOAD_KINDS.map((k) => (
            <button
              key={k.value}
              type="button"
              onClick={() => setKind(k.value)}
              className={clsx(
                "chip border ring-0 px-2.5 py-1 text-xs",
                kind === k.value
                  ? "bg-brand-50 text-brand-700 border-brand-200"
                  : "bg-white text-ink-600 border-ink-200 hover:bg-ink-50",
              )}
            >
              <k.Icon size={12} /> {k.label}
            </button>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
            }}
            className="text-sm"
          />
          {upload.isPending && <Loader2 size={14} className="animate-spin text-ink-400" />}
        </div>
        {err && <div className="mt-2 text-xs text-red-700">{err}</div>}
      </div>

      {/* Existing uploads */}
      {(files.data ?? []).length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase muted mb-2">Your uploads</div>
          <ul className="divide-y divide-ink-100">
            {files.data!.map((f: any) => (
              <li key={f.id} className="py-2 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate">{f.filename}</div>
                  <div className="text-[11px] muted">
                    {(f.size / 1024).toFixed(1)} KB · {new Date(f.uploaded_at).toLocaleString()}
                    {f.description && <> · {f.description}</>}
                  </div>
                </div>
                <button className="btn-ghost" onClick={() => download(f.id, f.filename)}>
                  <Download size={13} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatusTile({ done, label, hint }: {
  done: boolean; label: string; hint: string;
}) {
  return (
    <div className={clsx(
      "rounded-xl border p-3 flex items-start gap-3",
      done ? "border-emerald-200 bg-emerald-50/40" : "border-ink-200 bg-white",
    )}>
      <div className={clsx(
        "h-8 w-8 rounded-md grid place-items-center shrink-0",
        done ? "bg-emerald-100 text-emerald-700" : "bg-ink-100 text-ink-400",
      )}>
        {done ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
      </div>
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs muted">{hint}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wider muted mb-0.5">{label}</span>
      {children}
    </label>
  );
}
