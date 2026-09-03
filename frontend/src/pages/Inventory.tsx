import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Package, Plus, Search, AlertTriangle, CheckCircle2, ShoppingCart, Loader2,
  Pencil, ArrowDownUp, Boxes, Wrench, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { UnitSelect } from "@/components/UnitSelect";
import { Modal } from "@/components/Modal";
import { InventoryItemForm } from "@/components/forms/InventoryItemForm";
import { AdjustStockForm } from "@/components/forms/AdjustStockForm";
import { useAuthStore } from "@/store/auth";
import { T } from "@/store/lang";

interface Item {
  id: string;
  sku: string;
  name: string;
  category: string | null;
  uom: string;
  unit_cost: number | null;
  current_stock: number;
  reorder_point: number;
  reorder_qty: number;
  location: string | null;
  supplier_hint: string | null;
  link: string | null;
  is_active: boolean;
  stock_status: "ok" | "low" | "out";
}

// How many rows to fetch at a time. Comfortably more than this company's
// catalogue today, so nobody meets the pager until it earns its keep.
const PAGE = 200;

const idr = (n: number) => new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_META: Record<Item["stock_status"], { label: string; tone: string; Icon: any }> = {
  ok:  { label: "In stock",  tone: "bg-emerald-50 text-emerald-700 ring-emerald-200", Icon: CheckCircle2 },
  low: { label: "Low",       tone: "bg-amber-50 text-amber-700 ring-amber-200",       Icon: AlertTriangle },
  out: { label: "Out",       tone: "bg-red-50 text-red-700 ring-red-200",             Icon: AlertTriangle },
};

export default function InventoryPage() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const canEdit = user && (user.role === "admin" || user.role === "director");
  const canAdd = user && ["purchasing", "admin", "manager", "director"].includes(user.role);
  const isDirector = user?.role === "director";
  // What stock cost us is procurement's figure. Admin run the customer side
  // and sales quote the sell price — neither is shown the buy price
  // anywhere else in the app, and the server sends them null for it, so the
  // column comes out rather than rendering "Rp 0" over a hidden number.
  const showCost = !!user && !["admin", "sales"].includes(user.role);

  const [q, setQ] = useState("");
  const [onlyLow, setOnlyLow] = useState(false);
  const [openNew, setOpenNew] = useState(false);
  const [openBulk, setOpenBulk] = useState(false);
  const [openRequest, setOpenRequest] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);
  const [adjusting, setAdjusting] = useState<Item | null>(null);

  // A page at a time. The catalogue gains a SKU for every purchase-order
  // line, so "load them all and filter in the browser" stops being free.
  const [shown, setShown] = useState(PAGE);
  useEffect(() => { setShown(PAGE); }, [q, onlyLow]);
  const items = useQuery({
    queryKey: ["inventory", q, onlyLow, shown],
    queryFn: () => api.get("/inventory", {
      params: { q: q || undefined, only_low: onlyLow || undefined, limit: shown },
    }).then((r) => r.data as { items: Item[]; total: number }),
  });
  const rows = items.data?.items ?? [];
  const total = items.data?.total ?? 0;

  // The three figures at the top describe the whole catalogue, so they come
  // from the database rather than from whatever is on screen.
  const stats = useQuery({
    queryKey: ["inventory-summary"],
    queryFn: () => api.get("/inventory/summary").then((r) => r.data as {
      tracked: number; low: number; out: number;
      needs_attention: number; stock_value: number | null;
    }),
  });

  const order = useMutation({
    mutationFn: ({ id, qty }: { id: string; qty?: number }) =>
      api.post(`/inventory/${id}/request-order`, { qty: qty ?? null })
        .then((r) => r.data),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      alert(`Purchase Request created: ${data.number}`);
    },
    onError: (e: any) => {
      alert(e?.response?.data?.errors?.[0]?.message ?? "Could not create order");
    },
  });

  const lowCount = stats.data?.needs_attention ?? 0;
  const totalValue = stats.data?.stock_value ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Package size={22} className="text-brand-600" /> {T("Inventory")}</h1>
          <p className="text-sm muted">
            {T("Check what's in stock before promising delivery. Need more? Click \"Request order\" to raise a purchase request.")}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-primary" onClick={() => setOpenRequest(true)}>
            <ShoppingCart size={14} /> {T("Request order")}</button>
          {canAdd && (
            <button className="btn-ghost" onClick={() => setOpenBulk(true)}>
              <Plus size={14} /> {T("New item")}</button>
          )}
        </div>
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Card label={T("Items tracked")} value={String(stats.data?.tracked ?? 0)} Icon={Boxes} tone="brand" />
        <Card label={T("Low / out of stock")} value={String(lowCount)} Icon={AlertTriangle}
              tone={lowCount > 0 ? "amber" : "emerald"} />
        {showCost && (
          <Card label={T("Total stock value")} value={`Rp ${idr(totalValue)}`} Icon={Wrench} tone="violet" />
        )}
      </div>

      {/* Toolbar */}
      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={T("Search by SKU or name…")} className="input pl-9" />
        </div>
        <label className="flex items-center gap-2 text-sm select-none cursor-pointer">
          <input type="checkbox" checked={onlyLow} onChange={(e) => setOnlyLow(e.target.checked)} />
          {T("Show only low / out of stock")}</label>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("SKU")}</th>
                <th className="th">{T("Name")}</th>
                <th className="th">{T("Category")}</th>
                <th className="th text-right">{T("Stock")}</th>
                <th className="th text-right">{T("Reorder at")}</th>
                {showCost && <th className="th text-right">{T("Unit cost")}</th>}
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => {
                const M = STATUS_META[i.stock_status];
                return (
                  <tr key={i.id} className="tr-hover border-t border-ink-100">
                    <td className="td font-mono text-xs">{i.sku}</td>
                    <td className="td">
                      <div className="font-medium">
                        {i.name}
                        {i.link && (
                          <a href={i.link} target="_blank" rel="noreferrer noopener"
                            className="ml-1.5 text-brand-700 hover:underline text-xs font-normal">
                            {T("link")}
                          </a>
                        )}
                      </div>
                      {i.location && <div className="text-[11px] muted">📍 {i.location}</div>}
                    </td>
                    <td className="td muted">{i.category ?? "—"}</td>
                    <td className="td text-right tabular-nums font-semibold">
                      {i.current_stock} <span className="muted text-xs">{i.uom}</span>
                    </td>
                    <td className="td text-right tabular-nums muted">
                      {i.reorder_point} {i.uom}
                    </td>
                    {showCost && (
                      <td className="td text-right tabular-nums">{T("Rp")}{" "}{idr(i.unit_cost ?? 0)}</td>
                    )}
                    <td className="td">
                      <span className={clsx("chip ring-1", M.tone)}>
                        <M.Icon size={11} /> {T(M.label)}
                      </span>
                    </td>
                    <td className="td text-right">
                      <div className="inline-flex gap-1 flex-wrap justify-end">
                        {i.stock_status !== "ok" ? (
                          <button
                            className="btn-primary"
                            disabled={order.isPending}
                            onClick={() => order.mutate({ id: i.id })}
                            title={`Create PR for ${i.reorder_qty || "?"} ${i.uom}`}
                          >
                            {order.isPending ? <Loader2 size={13} className="animate-spin" /> : <ShoppingCart size={13} />}
                            {T("Request order")}</button>
                        ) : (
                          <button
                            className="btn-ghost"
                            onClick={() => order.mutate({ id: i.id })}
                            title={T("Reorder even though stock is OK")}
                          >
                            <ShoppingCart size={13} /> {T("Order")}</button>
                        )}
                        {canEdit && (
                          <>
                            <button className="btn-ghost"
                              onClick={() => setAdjusting(i)}
                              title={T("Adjust stock")}>
                              <ArrowDownUp size={13} />
                            </button>
                            <button className="btn-ghost"
                              onClick={() => { setEditing(i); setOpenNew(true); }}
                              title={T("Edit item")}>
                              <Pencil size={13} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td colSpan={8} className="td text-center muted py-12">
                    {items.isLoading
                      ? T("Loading…")
                      : T("No inventory items yet.")}
                    {canEdit && !items.isLoading && (
                      <> {T("Click")}{" "}<b>{T("+ New item")}</b> {T("to add one.")}</>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {total > rows.length && (
          <div className="px-5 py-3 border-t border-ink-100 flex items-center justify-between gap-3 flex-wrap">
            <span className="text-xs muted">
              {T("Showing")} {rows.length} {T("of")} {total}
            </span>
            <button className="btn-ghost" disabled={items.isFetching}
              onClick={() => setShown((n) => n + PAGE)}>
              {items.isFetching ? T("Loading…") : T("Load more")}
            </button>
          </div>
        )}
      </div>

      <Modal
        open={openNew}
        onClose={() => setOpenNew(false)}
        title={editing ? "Edit item" : "New inventory item"}
        subtitle={editing ? `${editing.sku} · ${editing.name}` : "Add a stockable part, consumable, or material."}
        size="lg"
      >
        <InventoryItemForm initial={editing} onClose={() => setOpenNew(false)} />
      </Modal>

      <Modal
        open={!!adjusting}
        onClose={() => setAdjusting(null)}
        title={T("Adjust stock")}
        subtitle={T("Record stock in / out with a reason.")}
        size="md"
      >
        {adjusting && <AdjustStockForm item={adjusting} onClose={() => setAdjusting(null)} />}
      </Modal>

      <Modal
        open={openBulk}
        onClose={() => setOpenBulk(false)}
        title={T("Add inventory items")}
        subtitle={isDirector
          ? "Add one or more items. They're created immediately."
          : "Add one or more items. Each batch is sent to the director for approval before it becomes stock."}
        size="lg"
      >
        <BulkAddForm isDirector={!!isDirector} onClose={() => setOpenBulk(false)} />
      </Modal>

      <Modal
        open={openRequest}
        onClose={() => setOpenRequest(false)}
        title={T("Request order")}
        subtitle={T("Raise a purchase request for materials — even ones not stocked yet. Purchasing picks it up.")}
        size="lg"
      >
        <RequestOrderForm onClose={() => setOpenRequest(false)} />
      </Modal>
    </div>
  );
}

function BulkAddForm({ isDirector, onClose }: { isDirector: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  type Row = {
    sku: string; name: string; category: string; uom: string;
    unit_cost: string; current_stock: string; reorder_point: string; reorder_qty: string;
  };
  const blank = (): Row => ({
    sku: "", name: "", category: "", uom: "pcs",
    unit_cost: "", current_stock: "", reorder_point: "", reorder_qty: "",
  });
  const [rows, setRows] = useState<Row[]>([blank()]);
  const [err, setErr] = useState<string | null>(null);
  const [importWarn, setImportWarn] = useState<string[]>([]);

  const update = (i: number, k: keyof Row, v: string) =>
    setRows(rows.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));

  const importFile = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api.post("/inventory/parse-file", fd).then((r) => r.data);
    },
    onSuccess: (data: any) => {
      const parsed: Row[] = (data.items ?? []).map((it: any) => ({
        sku: "", name: it.name ?? "", category: it.category ?? "", uom: it.uom ?? "pcs",
        unit_cost: String(it.unit_cost ?? ""), current_stock: String(it.current_stock ?? ""),
        reorder_point: "", reorder_qty: "",
      }));
      setImportWarn(data.warnings ?? []);
      // Replace empty starter rows; otherwise append the imported lines.
      const hasContent = rows.some((r) => r.sku.trim() || r.name.trim());
      setRows(parsed.length ? (hasContent ? [...rows, ...parsed] : parsed) : rows);
      if (!parsed.length) setErr("No rows could be read from that file — add them manually.");
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail ?? "Could not read that file."),
  });

  const save = useMutation({
    mutationFn: () => api.post("/inventory/bulk", {
      items: rows
        .filter((r) => r.sku.trim() && r.name.trim())
        .map((r) => ({
          sku: r.sku.trim(), name: r.name.trim(),
          category: r.category.trim() || null, uom: r.uom.trim() || "pcs",
          unit_cost: parseFloat(r.unit_cost || "0"),
          current_stock: parseFloat(r.current_stock || "0"),
          reorder_point: parseFloat(r.reorder_point || "0"),
          reorder_qty: parseFloat(r.reorder_qty || "0"),
        })),
    }).then((r) => r.data),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      onClose();
      if (data.pending_approval) {
        alert(`Submitted ${data.count} item(s) for director approval.`);
      } else {
        const made = data.created_skus?.length ?? 0;
        const skip = data.skipped_skus?.length ?? 0;
        alert(`Added ${made} item(s).` + (skip ? ` Skipped ${skip} duplicate SKU(s).` : ""));
      }
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail ?? "Could not save items."),
  });

  function attempt() {
    setErr(null);
    if (!rows.some((r) => r.sku.trim() && r.name.trim())) {
      setErr("Add at least one item with a SKU and a name.");
      return;
    }
    save.mutate();
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); attempt(); }} className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[680px]">
          <thead>
            <tr className="text-[10px] uppercase text-ink-500 text-left">
              <th className="pb-1 pr-2">{T("SKU *")}</th>
              <th className="pb-1 pr-2">{T("Name *")}</th>
              <th className="pb-1 pr-2">{T("Category")}</th>
              <th className="pb-1 pr-2">{T("UoM")}</th>
              <th className="pb-1 pr-2">{T("Unit cost")}</th>
              <th className="pb-1 pr-2">{T("Stock")}</th>
              <th className="pb-1 pr-2">{T("Reorder pt")}</th>
              <th className="pb-1 pr-2">{T("Reorder qty")}</th>
              <th className="pb-1"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="pr-2 pb-1.5"><input className="input" value={r.sku} onChange={(e) => update(i, "sku", e.target.value)} /></td>
                <td className="pr-2 pb-1.5"><input className="input" value={r.name} onChange={(e) => update(i, "name", e.target.value)} /></td>
                <td className="pr-2 pb-1.5"><input className="input" value={r.category} onChange={(e) => update(i, "category", e.target.value)} /></td>
                <td className="pr-2 pb-1.5">
                  <UnitSelect className="input w-24" label={`Unit, row ${i + 1}`}
                    value={r.uom} onChange={(v) => update(i, "uom", v)}
                    allowBlank={false} />
                </td>
                <td className="pr-2 pb-1.5"><input className="input w-24" type="number" min={0} value={r.unit_cost} onChange={(e) => update(i, "unit_cost", e.target.value)} /></td>
                <td className="pr-2 pb-1.5"><input className="input w-20" type="number" min={0} value={r.current_stock} onChange={(e) => update(i, "current_stock", e.target.value)} /></td>
                <td className="pr-2 pb-1.5"><input className="input w-20" type="number" min={0} value={r.reorder_point} onChange={(e) => update(i, "reorder_point", e.target.value)} /></td>
                <td className="pr-2 pb-1.5"><input className="input w-20" type="number" min={0} value={r.reorder_qty} onChange={(e) => update(i, "reorder_qty", e.target.value)} /></td>
                <td className="pb-1.5">
                  <button type="button" className="btn-ghost text-red-600"
                    onClick={() => setRows(rows.filter((_, idx) => idx !== i))}
                    disabled={rows.length === 1} aria-label={T("Remove row")}>
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <button type="button" className="btn-ghost text-xs" onClick={() => setRows([...rows, blank()])}>
          <Plus size={13} /> {T("Add row")}</button>
        <label className="btn-ghost text-xs cursor-pointer">
          {importFile.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          {T("Import from file")}<input
            type="file"
            className="hidden"
            accept=".xlsx,.csv,.pdf,.doc,.docx,application/pdf,text/csv"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) { setErr(null); importFile.mutate(f); }
              e.target.value = "";
            }}
          />
        </label>
        <span className="text-[11px] muted">{T("Excel, CSV, PDF or Word — review before submitting.")}</span>
      </div>

      {importWarn.length > 0 && (
        <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-xs text-amber-800 space-y-0.5">
          {importWarn.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">{err}</div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          {isDirector ? T("Add items") : T("Submit for approval")}
        </button>
      </div>
    </form>
  );
}

function RequestOrderForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<{ name: string; qty: string; uom: string }[]>([
    { name: "", qty: "", uom: "pcs" },
  ]);
  const [err, setErr] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["projects-min"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data as any[]),
    retry: false,
  });

  const submit = useMutation({
    mutationFn: () => api.post("/inventory/request-order", {
      project_id: projectId || null,
      notes: notes.trim() || null,
      items: lines
        .filter((l) => l.name.trim() && Number(l.qty) > 0)
        .map((l) => ({ name: l.name.trim(), qty: Number(l.qty), uom: l.uom || "pcs" })),
    }).then((r) => r.data),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["pr-list"] });
      onClose();
      alert(`Purchase Request created: ${data.number}`);
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? "Could not create the request."),
  });

  const update = (i: number, k: "name" | "qty" | "uom", v: string) =>
    setLines(lines.map((l, idx) => (idx === i ? { ...l, [k]: v } : l)));

  function attempt() {
    setErr(null);
    if (!lines.some((l) => l.name.trim() && Number(l.qty) > 0)) {
      setErr("Add at least one item with a name and a quantity.");
      return;
    }
    submit.mutate();
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); attempt(); }} className="space-y-4">
      <label className="block">
        <span className="block text-xs font-medium text-ink-600 mb-1">{T("Project (optional)")}</span>
        <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">{T("No project")}</option>
          {(projects.data ?? []).map((p: any) => (
            <option key={p.id} value={p.id}>{p.code}{p.status ? ` · ${p.status}` : ""}</option>
          ))}
        </select>
      </label>

      <div>
        <span className="block text-xs font-medium text-ink-600 mb-1">{T("Items")}</span>
        <div className="space-y-2">
          {lines.map((l, i) => (
            <div key={i} className="flex items-end gap-2">
              <label className="flex-[3] block">
                {i === 0 && <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{T("Item")}</span>}
                <input className="input" placeholder={T("Steel plate 10mm")}
                  value={l.name} onChange={(e) => update(i, "name", e.target.value)} />
              </label>
              <label className="flex-1 block">
                {i === 0 && <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{T("Qty")}</span>}
                <input className="input" type="number" min={0} placeholder="0"
                  value={l.qty} onChange={(e) => update(i, "qty", e.target.value)} />
              </label>
              <label className="flex-1 block">
                {i === 0 && <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{T("UoM")}</span>}
                <UnitSelect label={`Unit, line ${i + 1}`} value={l.uom}
                  onChange={(v) => update(i, "uom", v)} allowBlank={false} />
              </label>
              <button type="button" className="btn-ghost text-red-600 shrink-0 mb-0.5"
                onClick={() => setLines(lines.filter((_, idx) => idx !== i))}
                aria-label={T("Remove line")} disabled={lines.length === 1}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <button type="button" className="btn-ghost text-xs"
            onClick={() => setLines([...lines, { name: "", qty: "", uom: "pcs" }])}>
            <Plus size={13} /> {T("Add line")}</button>
        </div>
      </div>

      <label className="block">
        <span className="block text-xs font-medium text-ink-600 mb-1">{T("Notes (optional)")}</span>
        <textarea rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {err && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button type="submit" className="btn-primary" disabled={submit.isPending}>
          {submit.isPending ? <Loader2 size={14} className="animate-spin" /> : <ShoppingCart size={14} />}
          {T("Send request")}</button>
      </div>
    </form>
  );
}

function Card({ label, value, Icon, tone }: {
  label: string; value: string; Icon: any;
  tone: "brand" | "amber" | "emerald" | "violet";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    amber:   "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
    violet:  "bg-violet-50 text-violet-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div className="text-[11px] uppercase tracking-wider muted">{T(label)}</div>
        <div className={`h-7 w-7 rounded ${cls} grid place-items-center`}>
          <Icon size={13} />
        </div>
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
