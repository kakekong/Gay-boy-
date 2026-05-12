import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Package, Plus, Search, AlertTriangle, CheckCircle2, ShoppingCart, Loader2,
  Pencil, ArrowDownUp, Boxes, Wrench,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { InventoryItemForm } from "@/components/forms/InventoryItemForm";
import { AdjustStockForm } from "@/components/forms/AdjustStockForm";
import { useAuthStore } from "@/store/auth";

interface Item {
  id: string;
  sku: string;
  name: string;
  category: string | null;
  uom: string;
  unit_cost: number;
  current_stock: number;
  reorder_point: number;
  reorder_qty: number;
  location: string | null;
  supplier_hint: string | null;
  is_active: boolean;
  stock_status: "ok" | "low" | "out";
}

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

  const [q, setQ] = useState("");
  const [onlyLow, setOnlyLow] = useState(false);
  const [openNew, setOpenNew] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);
  const [adjusting, setAdjusting] = useState<Item | null>(null);

  const items = useQuery({
    queryKey: ["inventory", q, onlyLow],
    queryFn: () => api.get("/inventory", {
      params: { q: q || undefined, only_low: onlyLow || undefined },
    }).then((r) => r.data as Item[]),
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

  const lowCount = (items.data ?? []).filter((i) => i.stock_status !== "ok").length;
  const totalValue = (items.data ?? []).reduce(
    (acc, i) => acc + (i.current_stock || 0) * (i.unit_cost || 0), 0
  );

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Package size={22} className="text-brand-600" /> Inventory
          </h1>
          <p className="text-sm muted">
            Check what's in stock before promising delivery. Need more? Click "Request order"
            and a Purchase Request is sent to purchasing.
          </p>
        </div>
        {canEdit && (
          <button className="btn-primary" onClick={() => { setEditing(null); setOpenNew(true); }}>
            <Plus size={14} /> New item
          </button>
        )}
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Card label="Items tracked" value={String((items.data ?? []).length)} Icon={Boxes} tone="brand" />
        <Card label="Low / out of stock" value={String(lowCount)} Icon={AlertTriangle}
              tone={lowCount > 0 ? "amber" : "emerald"} />
        <Card label="Total stock value" value={`Rp ${idr(totalValue)}`} Icon={Wrench} tone="violet" />
      </div>

      {/* Toolbar */}
      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search by SKU or name…" className="input pl-9" />
        </div>
        <label className="flex items-center gap-2 text-sm select-none cursor-pointer">
          <input type="checkbox" checked={onlyLow} onChange={(e) => setOnlyLow(e.target.checked)} />
          Show only low / out of stock
        </label>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">SKU</th>
                <th className="th">Name</th>
                <th className="th">Category</th>
                <th className="th text-right">Stock</th>
                <th className="th text-right">Reorder at</th>
                <th className="th text-right">Unit cost</th>
                <th className="th">Status</th>
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(items.data ?? []).map((i) => {
                const M = STATUS_META[i.stock_status];
                return (
                  <tr key={i.id} className="tr-hover border-t border-ink-100">
                    <td className="td font-mono text-xs">{i.sku}</td>
                    <td className="td">
                      <div className="font-medium">{i.name}</div>
                      {i.location && <div className="text-[11px] muted">📍 {i.location}</div>}
                    </td>
                    <td className="td muted">{i.category ?? "—"}</td>
                    <td className="td text-right tabular-nums font-semibold">
                      {i.current_stock} <span className="muted text-xs">{i.uom}</span>
                    </td>
                    <td className="td text-right tabular-nums muted">
                      {i.reorder_point} {i.uom}
                    </td>
                    <td className="td text-right tabular-nums">Rp {idr(i.unit_cost)}</td>
                    <td className="td">
                      <span className={clsx("chip ring-1", M.tone)}>
                        <M.Icon size={11} /> {M.label}
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
                            Request order
                          </button>
                        ) : (
                          <button
                            className="btn-ghost"
                            onClick={() => order.mutate({ id: i.id })}
                            title="Reorder even though stock is OK"
                          >
                            <ShoppingCart size={13} /> Order
                          </button>
                        )}
                        {canEdit && (
                          <>
                            <button className="btn-ghost"
                              onClick={() => setAdjusting(i)}
                              title="Adjust stock">
                              <ArrowDownUp size={13} />
                            </button>
                            <button className="btn-ghost"
                              onClick={() => { setEditing(i); setOpenNew(true); }}
                              title="Edit item">
                              <Pencil size={13} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!items.data?.length && (
                <tr>
                  <td colSpan={8} className="td text-center muted py-12">
                    {items.isLoading
                      ? "Loading…"
                      : "No inventory items yet."}
                    {canEdit && !items.isLoading && (
                      <> Click <b>+ New item</b> to add one.</>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
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
        title="Adjust stock"
        subtitle="Record stock in / out with a reason."
        size="md"
      >
        {adjusting && <AdjustStockForm item={adjusting} onClose={() => setAdjusting(null)} />}
      </Modal>
    </div>
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
        <div className="text-[11px] uppercase tracking-wider muted">{label}</div>
        <div className={`h-7 w-7 rounded ${cls} grid place-items-center`}>
          <Icon size={13} />
        </div>
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
