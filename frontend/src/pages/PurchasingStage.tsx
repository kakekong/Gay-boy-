import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ClipboardList, Send, PackageCheck, CheckCircle2,
  Plus, Loader2, Save, X, AlertCircle, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { T } from "@/store/lang";

type StageKey = "pr" | "rfq" | "gr" | "qc";

const STAGES: Record<StageKey, {
  label: string;
  icon: typeof ClipboardList;
  tone: string;
  description: string;
}> = {
  pr: {
    label: "Purchase Request",
    icon: ClipboardList,
    tone: "bg-amber-50 text-amber-700",
    description:
      "An internal team requests materials they need against a project. A PR commits no money — it signals demand so purchasing can source it.",
  },
  rfq: {
    label: "Request for Quotation",
    icon: Send,
    tone: "bg-blue-50 text-blue-700",
    description:
      "Ask suppliers what they'd charge for the items on a PR. Each quote is a row here; compare price and lead time, then issue a PO to the winner.",
  },
  gr: {
    label: "Goods Receipt",
    icon: PackageCheck,
    tone: "bg-cyan-50 text-cyan-700",
    description:
      "Materials arrive from the supplier. Receiving confirms quantities against the PO and moves the PO to 'received' before QC.",
  },
  qc: {
    label: "QC (incoming)",
    icon: CheckCircle2,
    tone: "bg-violet-50 text-violet-700",
    description:
      "Quality check for materials we bought. Pass / fail counts roll up into the supplier's QC fail rate on the Purchasing page.",
  },
};

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const errText = (e: any) =>
  e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail
    ?? e?.message
    ?? "Request failed";

export default function PurchasingStagePage() {
  const { stage } = useParams<{ stage: string }>();
  const nav = useNavigate();
  const key = (stage ?? "") as StageKey;
  const meta = STAGES[key];

  if (!meta) {
    return (
      <div className="card p-10 text-center">
        <div className="mt-3 font-semibold">{T("Unknown procurement stage")}</div>
        <p className="text-sm muted mt-1">"{stage}{T("\" isn't a stage we know about.")}</p>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchasing")}>
          <ArrowLeft size={14} /> {T("Back to Purchasing")}</button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Link
        to="/purchasing"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> {T("Back to Purchasing")}</Link>

      <div className="card p-6 lg:p-8">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <meta.icon size={13} className="text-brand-600" /> {T("Procurement stage")}</div>
            <h1 className="text-2xl font-semibold tracking-tight mt-0.5">{T(meta.label)}</h1>
          </div>
          <span className={clsx("chip text-xs font-semibold", meta.tone)}>{T(meta.label)}</span>
        </div>
        <p className="text-sm muted mt-3 max-w-2xl">{T(meta.description)}</p>
      </div>

      {key === "pr" && <PRWorkspace />}
      {key === "rfq" && <RFQWorkspace />}
      {key === "gr" && <GRWorkspace />}
      {key === "qc" && <QCWorkspace />}
    </div>
  );
}

/* ─── Shared bits ──────────────────────────────────────────────────────────── */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{T(label)}</span>
      {children}
    </label>
  );
}

function Flash({ flash, onClose }: {
  flash: { kind: "ok" | "err"; text: string } | null;
  onClose: () => void;
}) {
  if (!flash) return null;
  return (
    <div className={clsx(
      "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
      flash.kind === "ok"
        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
        : "border-red-200 bg-red-50 text-red-800",
    )}>
      <span className="flex-1">{flash.text}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100"><X size={14} /></button>
    </div>
  );
}

function ModalShell({ title, subtitle, onClose, children }: {
  title: string; subtitle?: string; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-xl bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm muted mt-0.5">{subtitle}</p>}
        </header>
        {children}
      </div>
    </div>
  );
}

type Col = { key: string; label: string; type?: "text" | "number"; placeholder?: string };

/** Tiny repeatable line-item editor. Rows are plain objects keyed by `cols`. */
function ItemsEditor({ cols, rows, onChange }: {
  cols: Col[];
  rows: Record<string, any>[];
  onChange: (rows: Record<string, any>[]) => void;
}) {
  const blank = () => Object.fromEntries(cols.map((c) => [c.key, ""]));
  const update = (i: number, k: string, v: string) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-end gap-2">
          {cols.map((c) => (
            <label key={c.key} className="flex-1 block">
              {i === 0 && (
                <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{T(c.label)}</span>
              )}
              <input
                className="input"
                type={c.type === "number" ? "number" : "text"}
                placeholder={c.placeholder}
                value={r[c.key] ?? ""}
                onChange={(e) => update(i, c.key, e.target.value)}
              />
            </label>
          ))}
          <button
            type="button"
            className="btn-ghost text-red-600 shrink-0 mb-0.5"
            onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
            aria-label={T("Remove line")}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <button type="button" className="btn-ghost text-xs" onClick={() => onChange([...rows, blank()])}>
        <Plus size={13} /> {T("Add line")}</button>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  return <span className="chip bg-ink-100 text-ink-700 capitalize">{T(status?.replace(/_/g, " "))}</span>;
}

function TableShell({ headers, empty, loading, children }: {
  headers: string[]; empty: boolean; loading: boolean; children: React.ReactNode;
}) {
  if (loading) {
    return (
      <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
    );
  }
  if (empty) return <div className="px-5 py-12 text-center text-sm muted">{T("Nothing here yet.")}</div>;
  return (
    <table className="w-full text-sm">
      <thead className="bg-ink-50/60">
        <tr>{headers.map((h) => <th key={h} className={clsx("th", h === "" && "text-right")}>{h}</th>)}</tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

/* ─── PR ───────────────────────────────────────────────────────────────────── */

function PRWorkspace() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const list = useQuery({
    queryKey: ["pr-list"],
    queryFn: () => api.get("/purchasing/pr").then((r) => r.data as any[]),
    retry: false,
  });
  const close = useMutation({
    mutationFn: (id: string) => api.patch(`/purchasing/pr/${id}`, { status: "closed" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pr-list"] }); },
    onError: (e) => setFlash({ kind: "err", text: errText(e) }),
  });

  return (
    <div className="space-y-4">
      <Flash flash={flash} onClose={() => setFlash(null)} />
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setOpen(true)}><Plus size={15} /> {T("New PR")}</button>
      </div>
      <div className="card overflow-hidden">
        <TableShell
          headers={["Number", "Project", "Requested by", "Items", "Status", ""]}
          loading={list.isLoading}
          empty={!list.data?.length}
        >
          {(list.data ?? []).map((r) => (
            <tr key={r.id} className="border-t border-ink-100">
              <td className="td font-mono text-xs">{r.number}</td>
              <td className="td font-mono text-xs">{r.project_code ?? "—"}</td>
              <td className="td">{r.requested_by_name ?? "—"}</td>
              <td className="td muted">{(r.items ?? []).length} {T("line(s)")}</td>
              <td className="td"><StatusChip status={r.status} /></td>
              <td className="td text-right">
                {r.status === "open" && (
                  <button className="btn-ghost text-xs" disabled={close.isPending}
                    onClick={() => close.mutate(r.id)}>
                    <CheckCircle2 size={13} /> {T("Close")}</button>
                )}
              </td>
            </tr>
          ))}
        </TableShell>
      </div>
      {open && (
        <PRModal
          onClose={() => setOpen(false)}
          onDone={(num) => {
            qc.invalidateQueries({ queryKey: ["pr-list"] });
            setOpen(false);
            setFlash({ kind: "ok", text: `PR ${num} created.` });
          }}
          onError={(m) => setFlash({ kind: "err", text: m })}
        />
      )}
    </div>
  );
}

function PRModal({ onClose, onDone, onError }: {
  onClose: () => void; onDone: (num: string) => void; onError: (m: string) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<Record<string, any>[]>([{ description: "", qty: "", uom: "" }]);

  const projects = useQuery({
    queryKey: ["projects-min"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data as any[]),
    retry: false,
  });
  const create = useMutation({
    mutationFn: () => api.post("/purchasing/pr", {
      project_id: projectId || null,
      notes: notes.trim() || null,
      items: items
        .filter((i) => (i.description ?? "").trim())
        .map((i) => ({ description: i.description.trim(), qty: Number(i.qty) || 0, uom: i.uom || null })),
    }).then((r) => r.data),
    onSuccess: (r) => onDone(r.number),
    onError: (e) => onError(errText(e)),
  });

  return (
    <ModalShell title={T("New purchase request")} subtitle={T("Signal demand for materials on a project.")}
      onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
        className="flex-1 overflow-auto p-5 space-y-3">
        <Field label={T("Project (optional)")}>
          <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">{T("No project")}</option>
            {(projects.data ?? []).map((p: any) => (
              <option key={p.id} value={p.id}>{p.code}{p.status ? ` · ${p.status}` : ""}</option>
            ))}
          </select>
        </Field>
        <div>
          <span className="block text-xs font-medium text-ink-600 mb-1">{T("Items")}</span>
          <ItemsEditor
            cols={[
              { key: "description", label: "Description", placeholder: "Steel plate 10mm" },
              { key: "qty", label: "Qty", type: "number", placeholder: "0" },
              { key: "uom", label: "UoM", placeholder: "pcs" },
            ]}
            rows={items}
            onChange={setItems}
          />
        </div>
        <Field label={T("Notes (optional)")}>
          <textarea rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
          <button type="submit" className="btn-primary" disabled={create.isPending}>
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {T("Create PR")}</button>
        </div>
      </form>
    </ModalShell>
  );
}

/* ─── RFQ ──────────────────────────────────────────────────────────────────── */

function RFQWorkspace() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const list = useQuery({
    queryKey: ["rfq-list"],
    queryFn: () => api.get("/purchasing/rfq").then((r) => r.data as any[]),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <Flash flash={flash} onClose={() => setFlash(null)} />
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setOpen(true)}><Plus size={15} /> {T("New RFQ")}</button>
      </div>
      <div className="card overflow-hidden">
        <TableShell
          headers={["PR", "Supplier", "Lead time", "Quoted total", "Status"]}
          loading={list.isLoading}
          empty={!list.data?.length}
        >
          {(list.data ?? []).map((r) => (
            <tr key={r.id} className="border-t border-ink-100">
              <td className="td font-mono text-xs">{r.pr_number ?? "—"}</td>
              <td className="td">{r.supplier_name ?? "—"}</td>
              <td className="td tabular-nums">{r.quoted_lead_days != null ? `${r.quoted_lead_days} d` : "—"}</td>
              <td className="td tabular-nums">{idr(r.quoted_total)}</td>
              <td className="td"><StatusChip status={r.status} /></td>
            </tr>
          ))}
        </TableShell>
      </div>
      {open && (
        <RFQModal
          onClose={() => setOpen(false)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["rfq-list"] });
            setOpen(false);
            setFlash({ kind: "ok", text: "RFQ recorded." });
          }}
          onError={(m) => setFlash({ kind: "err", text: m })}
        />
      )}
    </div>
  );
}

function RFQModal({ onClose, onDone, onError }: {
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const [prId, setPrId] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [leadDays, setLeadDays] = useState("");
  const [lines, setLines] = useState<Record<string, any>[]>([{ description: "", amount: "" }]);

  const prs = useQuery({
    queryKey: ["pr-open"],
    queryFn: () => api.get("/purchasing/pr", { params: { status_filter: "open" } }).then((r) => r.data as any[]),
    retry: false,
  });
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as any[]),
    retry: false,
  });
  const create = useMutation({
    mutationFn: () => api.post(`/purchasing/pr/${prId}/rfq`, {
      supplier_id: supplierId,
      quoted_lead_days: leadDays ? Number(leadDays) : null,
      quoted_lines: lines
        .filter((l) => (l.description ?? "").trim())
        .map((l) => ({ description: l.description.trim(), amount: Number(l.amount) || 0 })),
    }),
    onSuccess: () => onDone(),
    onError: (e) => onError(errText(e)),
  });

  const ready = prId && supplierId;
  return (
    <ModalShell title={T("Record a supplier quote")} subtitle={T("One row per supplier quoting a PR.")}
      onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (ready) create.mutate(); }}
        className="flex-1 overflow-auto p-5 space-y-3">
        <Field label={T("Purchase request *")}>
          <select required className="input" value={prId} onChange={(e) => setPrId(e.target.value)}>
            <option value="">{T("Choose an open PR…")}</option>
            {(prs.data ?? []).map((p: any) => (
              <option key={p.id} value={p.id}>{p.number}{p.project_code ? ` · ${p.project_code}` : ""}</option>
            ))}
          </select>
        </Field>
        <Field label={T("Supplier *")}>
          <select required className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
            <option value="">{T("Choose a supplier…")}</option>
            {(suppliers.data ?? []).map((s: any) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </Field>
        <Field label={T("Quoted lead time (days)")}>
          <input type="number" min={0} className="input" value={leadDays}
            onChange={(e) => setLeadDays(e.target.value)} />
        </Field>
        <div>
          <span className="block text-xs font-medium text-ink-600 mb-1">{T("Quoted lines")}</span>
          <ItemsEditor
            cols={[
              { key: "description", label: "Description", placeholder: "Steel plate 10mm" },
              { key: "amount", label: "Amount (Rp)", type: "number", placeholder: "0" },
            ]}
            rows={lines}
            onChange={setLines}
          />
        </div>
        {!ready && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-800 flex items-start gap-2">
            <AlertCircle size={13} className="mt-0.5 shrink-0" /> {T("Pick a PR and a supplier first.")}</div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
          <button type="submit" className="btn-primary" disabled={create.isPending || !ready}>
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {T("Save quote")}</button>
        </div>
      </form>
    </ModalShell>
  );
}

/* ─── GR ───────────────────────────────────────────────────────────────────── */

function GRWorkspace() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const list = useQuery({
    queryKey: ["gr-list"],
    queryFn: () => api.get("/purchasing/gr").then((r) => r.data as any[]),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <Flash flash={flash} onClose={() => setFlash(null)} />
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setOpen(true)}><Plus size={15} /> {T("Receive goods")}</button>
      </div>
      <div className="card overflow-hidden">
        <TableShell
          headers={["PO", "Received", "Items", "Status"]}
          loading={list.isLoading}
          empty={!list.data?.length}
        >
          {(list.data ?? []).map((r) => (
            <tr key={r.id} className="border-t border-ink-100">
              <td className="td font-mono text-xs">{r.po_number ?? "—"}</td>
              <td className="td muted">{r.received_at ?? "—"}</td>
              <td className="td muted">{(r.items ?? []).length} {T("line(s)")}</td>
              <td className="td"><StatusChip status={r.status} /></td>
            </tr>
          ))}
        </TableShell>
      </div>
      {open && (
        <GRModal
          onClose={() => setOpen(false)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["gr-list"] });
            setOpen(false);
            setFlash({ kind: "ok", text: "Goods receipt recorded." });
          }}
          onError={(m) => setFlash({ kind: "err", text: m })}
        />
      )}
    </div>
  );
}

function GRModal({ onClose, onDone, onError }: {
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const [poId, setPoId] = useState("");
  const [receivedAt, setReceivedAt] = useState(new Date().toISOString().slice(0, 10));
  const [items, setItems] = useState<Record<string, any>[]>([{ description: "", qty: "" }]);

  const pos = useQuery({
    queryKey: ["po-min"],
    queryFn: () => api.get("/purchasing/po").then((r) => r.data as any[]),
    retry: false,
  });
  const create = useMutation({
    mutationFn: () => api.post(`/purchasing/po/${poId}/gr`, {
      received_at: receivedAt || null,
      items: items
        .filter((i) => (i.description ?? "").trim())
        .map((i) => ({ description: i.description.trim(), qty: Number(i.qty) || 0 })),
    }),
    onSuccess: () => onDone(),
    onError: (e) => onError(errText(e)),
  });

  return (
    <ModalShell title={T("Receive goods")} subtitle={T("Confirm what arrived against a supplier PO.")}
      onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (poId) create.mutate(); }}
        className="flex-1 overflow-auto p-5 space-y-3">
        <Field label={T("Supplier PO *")}>
          <select required className="input" value={poId} onChange={(e) => setPoId(e.target.value)}>
            <option value="">{T("Choose a PO…")}</option>
            {(pos.data ?? []).map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.number}{p.supplier_name ? ` · ${p.supplier_name}` : ""}{p.project_code ? ` · ${p.project_code}` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label={T("Received date")}>
          <input type="date" className="input" value={receivedAt}
            onChange={(e) => setReceivedAt(e.target.value)} />
        </Field>
        <div>
          <span className="block text-xs font-medium text-ink-600 mb-1">{T("Received items")}</span>
          <ItemsEditor
            cols={[
              { key: "description", label: "Description", placeholder: "Steel plate 10mm" },
              { key: "qty", label: "Qty received", type: "number", placeholder: "0" },
            ]}
            rows={items}
            onChange={setItems}
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
          <button type="submit" className="btn-primary" disabled={create.isPending || !poId}>
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {T("Record receipt")}</button>
        </div>
      </form>
    </ModalShell>
  );
}

/* ─── QC ───────────────────────────────────────────────────────────────────── */

function QCWorkspace() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const list = useQuery({
    queryKey: ["qc-list"],
    queryFn: () => api.get("/purchasing/qc").then((r) => r.data as any[]),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <Flash flash={flash} onClose={() => setFlash(null)} />
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setOpen(true)}><Plus size={15} /> {T("Log inspection")}</button>
      </div>
      <div className="card overflow-hidden">
        <TableShell
          headers={["PO", "Pass", "Fail", "Decision"]}
          loading={list.isLoading}
          empty={!list.data?.length}
        >
          {(list.data ?? []).map((r) => (
            <tr key={r.id} className="border-t border-ink-100">
              <td className="td font-mono text-xs">{r.po_number ?? "—"}</td>
              <td className="td tabular-nums text-emerald-700">{r.pass_qty}</td>
              <td className="td tabular-nums text-red-700">{r.fail_qty}</td>
              <td className="td">
                <span className={clsx("chip capitalize",
                  r.decision === "accepted" ? "bg-emerald-50 text-emerald-700"
                  : r.decision === "rejected" ? "bg-red-50 text-red-700"
                  : "bg-amber-50 text-amber-700")}>
                  {r.decision}
                </span>
              </td>
            </tr>
          ))}
        </TableShell>
      </div>
      {open && (
        <QCModal
          onClose={() => setOpen(false)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["qc-list"] });
            qc.invalidateQueries({ queryKey: ["suppliers"] });
            setOpen(false);
            setFlash({ kind: "ok", text: "Inspection logged; supplier QC rate updated." });
          }}
          onError={(m) => setFlash({ kind: "err", text: m })}
        />
      )}
    </div>
  );
}

function QCModal({ onClose, onDone, onError }: {
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const [poId, setPoId] = useState("");
  const [passQty, setPassQty] = useState("");
  const [failQty, setFailQty] = useState("");
  const [decision, setDecision] = useState("accepted");
  const [findings, setFindings] = useState("");

  const pos = useQuery({
    queryKey: ["po-min"],
    queryFn: () => api.get("/purchasing/po").then((r) => r.data as any[]),
    retry: false,
  });
  const create = useMutation({
    mutationFn: () => api.post(`/purchasing/po/${poId}/qc`, {
      pass_qty: Number(passQty) || 0,
      fail_qty: Number(failQty) || 0,
      decision,
      findings: findings.trim() || null,
    }),
    onSuccess: () => onDone(),
    onError: (e) => onError(errText(e)),
  });

  return (
    <ModalShell title={T("Log incoming QC")} subtitle={T("Pass / fail counts feed the supplier's QC fail rate.")}
      onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (poId) create.mutate(); }}
        className="flex-1 overflow-auto p-5 space-y-3">
        <Field label={T("Supplier PO *")}>
          <select required className="input" value={poId} onChange={(e) => setPoId(e.target.value)}>
            <option value="">{T("Choose a PO…")}</option>
            {(pos.data ?? []).map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.number}{p.supplier_name ? ` · ${p.supplier_name}` : ""}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={T("Pass qty")}>
            <input type="number" min={0} className="input" value={passQty}
              onChange={(e) => setPassQty(e.target.value)} />
          </Field>
          <Field label={T("Fail qty")}>
            <input type="number" min={0} className="input" value={failQty}
              onChange={(e) => setFailQty(e.target.value)} />
          </Field>
        </div>
        <Field label={T("Decision")}>
          <select className="input" value={decision} onChange={(e) => setDecision(e.target.value)}>
            <option value="accepted">{T("Accepted")}</option>
            <option value="conditional">{T("Conditional")}</option>
            <option value="rejected">{T("Rejected")}</option>
          </select>
        </Field>
        <Field label={T("Findings (optional)")}>
          <textarea rows={2} className="input" value={findings}
            onChange={(e) => setFindings(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
          <button type="submit" className="btn-primary" disabled={create.isPending || !poId}>
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {T("Log inspection")}</button>
        </div>
      </form>
    </ModalShell>
  );
}
