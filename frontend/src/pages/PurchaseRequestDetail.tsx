import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, Loader2, Lock, Package, Plus, RotateCcw, Save, ShoppingCart, Trash2, X,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { UnitSelect } from "@/components/UnitSelect";
import { PR_STATUS } from "@/components/PurchaseRequestsPanel";
import { CURRENCIES, money } from "@/lib/currency";
import { useAuthStore } from "@/store/auth";
import { t } from "@/store/lang";

/**
 * One purchase request — its own page, the way a price request has one.
 *
 * What is asked for, how many, at what price and in which currency, and from
 * which supplier. Purchasing (and the manager and director) correct any of it
 * until the request is closed; while it still waits for the director, the
 * card in their Approvals follows the edit. The director decides it here too.
 */

interface Line {
  name: string; qty: string; uom: string; price: string;
  sku?: string | null; from_inventory_id?: string | null;
}
interface PR {
  id: string; number: string; status: string;
  project_id: string | null; project_code: string | null;
  requested_by_name: string | null; created_at: string; updated_at: string;
  notes: string | null; items: any[];
  supplier_id: string | null; supplier_name: string | null;
  currency: string; totals: Record<string, number>;
  from_inventory: boolean; editable: boolean;
  approval: { id: string; status: string; reason: string; decision_notes: string | null; decided_at: string | null } | null;
}

const errText = (e: any, fb: string) =>
  e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? fb;

const toLines = (items: any[]): Line[] => items.map((it) => ({
  name: it.name ?? it.description ?? "", qty: String(it.qty ?? ""), uom: it.uom ?? "pcs",
  price: it.unit_price != null ? String(it.unit_price) : "",
  sku: it.sku ?? null, from_inventory_id: it.from_inventory_id ?? null,
}));

export default function PurchaseRequestDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const isDirector = role === "director";
  const mayEdit = ["purchasing", "manager", "director"].includes(role);
  const supplierRequired = role === "purchasing";

  const pr = useQuery({
    queryKey: ["purchase-request", id],
    queryFn: () => api.get(`/purchasing/pr/${id}`).then((r) => r.data as PR),
  });
  const suppliers = useQuery({
    queryKey: ["suppliers-min"],
    queryFn: () => api.get("/purchasing/suppliers").then((r) => r.data as { id: string; name: string }[]),
    staleTime: 5 * 60_000,
  });
  const projects = useQuery({
    queryKey: ["projects-min"],
    queryFn: () => api.get("/operation/projects").then((r) => r.data as any[]),
    retry: false,
  });

  // The form, loaded from the request and reset whenever it reloads.
  const [lines, setLines] = useState<Line[]>([]);
  const [currency, setCurrency] = useState("IDR");
  const [supplierId, setSupplierId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const load = (d: PR) => {
    setLines(toLines(d.items)); setCurrency(d.currency || "IDR");
    setSupplierId(d.supplier_id ?? ""); setProjectId(d.project_id ?? ""); setNotes(d.notes ?? "");
  };
  useEffect(() => { if (pr.data) load(pr.data); }, [pr.data]);

  const d = pr.data;
  const editing = !!d && d.editable && mayEdit;
  const dirty = useMemo(() => {
    if (!d) return false;
    return JSON.stringify([toLines(d.items), d.currency, d.supplier_id ?? "", d.project_id ?? "", d.notes ?? ""])
      !== JSON.stringify([lines, currency, supplierId, projectId, notes]);
  }, [d, lines, currency, supplierId, projectId, notes]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["purchase-request", id] });
    qc.invalidateQueries({ queryKey: ["pr-list"] });
  };
  const save = useMutation({
    mutationFn: () => api.put(`/purchasing/pr/${id}`, {
      currency, supplier_id: supplierId || null, project_id: projectId || null,
      notes: notes.trim() || null,
      items: lines.filter((l) => l.name.trim()).map((l) => ({
        name: l.name.trim(), qty: Number(l.qty), uom: l.uom || "pcs",
        unit_price: l.price.trim() !== "" ? Number(l.price) : null,
        sku: l.sku || null, from_inventory_id: l.from_inventory_id || null,
      })),
    }).then((r) => r.data as PR),
    onSuccess: (data) => {
      qc.setQueryData(["purchase-request", id], data);
      qc.invalidateQueries({ queryKey: ["pr-list"] });
      setMsg({ kind: "ok", text: data.status === "pending_approval"
        ? t("Saved. The director's approval card shows the new figures.", "Tersimpan. Kartu persetujuan direktur menampilkan angka baru.")
        : t("Saved.", "Tersimpan.") });
    },
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't save it.", "Gagal menyimpan.")) }),
  });
  const setStatus = useMutation({
    mutationFn: (status: "open" | "closed") => api.patch(`/purchasing/pr/${id}`, { status }),
    onSuccess: () => { setMsg(null); refresh(); },
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't change it.", "Gagal mengubah.")) }),
  });
  const decide = useMutation({
    mutationFn: (v: { approve: boolean; notes?: string }) =>
      api.post(`/approvals/${d!.approval!.id}/${v.approve ? "approve" : "reject"}`, null,
               { params: v.notes ? { notes: v.notes } : undefined }),
    onSuccess: (_r, v) => {
      setMsg({ kind: "ok", text: v.approve ? t("Approved — it's open to order.", "Disetujui — siap dipesan.")
                                           : t("Rejected.", "Ditolak.") });
      refresh(); qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e) => setMsg({ kind: "err", text: errText(e, t("Couldn't decide it.", "Gagal memutuskan.")) }),
  });

  const lineTotal = (l: Line) => (Number(l.qty) || 0) * (Number(l.price) || 0);
  const grand = lines.reduce((s, l) => s + lineTotal(l), 0);
  const update = (i: number, k: keyof Line, v: string) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));

  function attempt() {
    setMsg(null);
    const kept = lines.filter((l) => l.name.trim());
    if (!kept.length) return setMsg({ kind: "err", text: t("Keep at least one item.", "Sisakan minimal satu barang.") });
    if (kept.some((l) => !(Number(l.qty) > 0)))
      return setMsg({ kind: "err", text: t("Every item needs a quantity above zero.", "Setiap barang perlu jumlah lebih dari nol.") });
    if (supplierRequired && !supplierId)
      return setMsg({ kind: "err", text: t("Pick the supplier to order from.", "Pilih pemasoknya.") });
    save.mutate();
  }

  if (pr.isLoading) return <div className="p-8 muted text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}</div>;
  if (pr.isError || !d) return (
    <div className="p-8 space-y-3">
      <div className="text-sm">{t("This purchase request couldn't be opened.", "Permintaan pembelian ini tidak dapat dibuka.")}</div>
      <Link to="/purchasing?tab=requests" className="btn-ghost inline-flex"><ArrowLeft size={14} /> {t("Back to purchase requests", "Kembali ke permintaan pembelian")}</Link>
    </div>
  );

  const st = PR_STATUS[d.status] ?? { en: d.status, id: d.status, tone: "bg-ink-100 text-ink-600" };
  const pending = d.status === "pending_approval" && d.approval?.status === "pending";

  return (
    <div className="space-y-5 max-w-5xl">
      <Link to="/purchasing?tab=requests" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> {t("Purchase requests", "Permintaan pembelian")}
      </Link>

      <div className="card p-5 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <ShoppingCart size={20} className="text-brand-600" />
            <h1 className="font-mono text-xl font-semibold">{d.number}</h1>
            <span className={clsx("chip text-[11px]", st.tone)}>{t(st.en, st.id)}</span>
            {d.from_inventory && (
              <span className="chip text-[11px] bg-ink-50 text-ink-600 inline-flex items-center gap-1">
                <Package size={11} /> {t("from Inventory", "dari Inventaris")}</span>)}
          </div>
          <div className="text-sm muted mt-1">
            {t("Requested by", "Diminta oleh")} <span className="text-ink-800">{d.requested_by_name ?? "—"}</span>
            {" · "}{new Date(d.created_at).toLocaleDateString("id-ID")}
            {d.project_code && <> · {t("Project", "Proyek")} <span className="font-mono text-ink-800">{d.project_code}</span></>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {mayEdit && d.status === "open" && (
            <button className="btn-ghost" disabled={setStatus.isPending || dirty}
              title={dirty ? t("Save or undo your changes first", "Simpan atau batalkan perubahan dulu") : undefined}
              onClick={() => window.confirm(t(`Close ${d.number}? Do this once it's ordered or no longer needed.`,
                                              `Tutup ${d.number}? Lakukan setelah dipesan atau tidak diperlukan lagi.`))
                             && setStatus.mutate("closed")}>
              <Lock size={14} /> {t("Close", "Tutup")}</button>)}
          {mayEdit && d.status === "closed" && (
            <button className="btn-ghost" disabled={setStatus.isPending} onClick={() => setStatus.mutate("open")}>
              <RotateCcw size={14} /> {t("Reopen", "Buka kembali")}</button>)}
        </div>
      </div>

      {/* The director's decision. */}
      {pending && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div className="text-sm text-amber-900">
            <div className="font-medium">{t("Waiting for the director's approval", "Menunggu persetujuan direktur")}</div>
            <div className="text-xs opacity-80">{d.approval!.reason}</div>
          </div>
          {isDirector && (
            <div className="flex gap-2">
              <button className="btn-primary" disabled={decide.isPending || dirty}
                title={dirty ? t("Save your changes first", "Simpan perubahan dulu") : undefined}
                onClick={() => decide.mutate({ approve: true })}>
                <Check size={14} /> {t("Approve", "Setujui")}</button>
              <button className="btn-ghost text-red-600" disabled={decide.isPending}
                onClick={() => {
                  const why = window.prompt(t("Why is it rejected? The requester sees this.", "Mengapa ditolak? Peminta akan melihat ini."));
                  if (why && why.trim()) decide.mutate({ approve: false, notes: why.trim() });
                }}>
                <X size={14} /> {t("Reject", "Tolak")}</button>
            </div>)}
        </div>
      )}
      {d.status === "cancelled" && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {t("The director rejected this request.", "Direktur menolak permintaan ini.")}
          {d.approval?.decision_notes && <> “{d.approval.decision_notes}”</>}
        </div>
      )}

      {msg && (
        <div className={clsx("rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
          msg.kind === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800")}>
          <span className="flex-1">{msg.text}</span>
          <button onClick={() => setMsg(null)} aria-label={t("Dismiss", "Tutup")}><X size={14} /></button>
        </div>
      )}

      <form className="card overflow-hidden" onSubmit={(e) => { e.preventDefault(); attempt(); }}>
        <div className="p-5 grid grid-cols-1 md:grid-cols-3 gap-4 border-b border-ink-100">
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">
              {t("Supplier", "Pemasok")}{supplierRequired && editing && <span className="text-red-600"> *</span>}</span>
            {editing ? (
              <select className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}
                aria-label={t("Supplier", "Pemasok")}>
                <option value="">{supplierRequired ? t("Pick the supplier…", "Pilih pemasok…") : t("Not picked yet", "Belum dipilih")}</option>
                {(suppliers.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            ) : <div className="text-sm py-2">{d.supplier_name ?? <span className="muted">{t("Not picked", "Belum dipilih")}</span>}</div>}
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{t("Project", "Proyek")}</span>
            {editing ? (
              <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}
                aria-label={t("Project", "Proyek")}>
                <option value="">{t("No project (stock)", "Tanpa proyek (stok)")}</option>
                {(projects.data ?? []).map((p: any) => <option key={p.id} value={p.id}>{p.code}</option>)}
              </select>
            ) : <div className="text-sm py-2 font-mono">{d.project_code ?? <span className="muted font-sans">{t("No project (stock)", "Tanpa proyek (stok)")}</span>}</div>}
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{t("Prices in", "Harga dalam")}</span>
            {editing ? (
              <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}
                aria-label={t("Currency", "Mata uang")}>
                {CURRENCIES.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
              </select>
            ) : <div className="text-sm py-2">{d.currency}</div>}
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th w-8">#</th>
                <th className="th">{t("Item", "Barang")}</th>
                <th className="th text-right w-24">{t("Qty", "Jml")}</th>
                <th className="th w-32">{t("Unit", "Satuan")}</th>
                <th className="th text-right w-36">{t("Unit price", "Harga satuan")} ({editing ? currency : d.currency})</th>
                <th className="th text-right w-36">{t("Line total", "Total baris")}</th>
                {editing && <th className="th w-10" />}
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i} className="border-t border-ink-100 align-top">
                  <td className="td muted tabular-nums pt-4">{i + 1}</td>
                  <td className="td">
                    {l.sku && <div className="font-mono text-[10px] text-ink-500 mb-0.5">{l.sku}</div>}
                    {editing ? (
                      <input className="input" value={l.name} aria-label={`${t("Item", "Barang")} ${i + 1}`}
                        onChange={(e) => update(i, "name", e.target.value)} />
                    ) : <div className="py-1">{l.name}</div>}
                  </td>
                  <td className="td text-right">
                    {editing ? (
                      <input className="input text-right tabular-nums" type="number" min={0} step="any" value={l.qty}
                        aria-label={`${t("Qty", "Jml")} ${i + 1}`} onChange={(e) => update(i, "qty", e.target.value)} />
                    ) : <div className="py-1 tabular-nums">{l.qty}</div>}
                  </td>
                  <td className="td">
                    {editing ? (
                      <UnitSelect label={`${t("Unit", "Satuan")} ${i + 1}`} value={l.uom} allowBlank={false}
                        onChange={(v) => update(i, "uom", v)} />
                    ) : <div className="py-1">{l.uom}</div>}
                  </td>
                  <td className="td text-right">
                    {editing ? (
                      <input className="input text-right tabular-nums" type="number" min={0} step="any" value={l.price}
                        placeholder={t("Optional", "Opsional")} aria-label={`${t("Unit price", "Harga satuan")} ${i + 1}`}
                        onChange={(e) => update(i, "price", e.target.value)} />
                    ) : <div className="py-1 tabular-nums">{l.price !== "" ? money(Number(l.price), d.currency) : "—"}</div>}
                  </td>
                  <td className="td text-right tabular-nums pt-4">
                    {l.price !== "" ? money(lineTotal(l), editing ? currency : d.currency) : <span className="muted">—</span>}
                  </td>
                  {editing && (
                    <td className="td pt-3">
                      <button type="button" className="btn-ghost text-red-600 px-1.5" disabled={lines.length === 1}
                        aria-label={t("Remove line", "Hapus baris")}
                        onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
                    </td>)}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink-200">
                <td className="td" colSpan={2}>
                  {editing && (
                    <button type="button" className="btn-ghost text-xs"
                      onClick={() => setLines((ls) => [...ls, { name: "", qty: "", uom: "pcs", price: "" }])}>
                      <Plus size={13} /> {t("Add line", "Tambah baris")}</button>)}
                </td>
                <td className="td text-right font-medium" colSpan={3}>{t("Total", "Total")}</td>
                <td className="td text-right font-semibold tabular-nums">
                  {grand ? money(grand, editing ? currency : d.currency) : "—"}</td>
                {editing && <td />}
              </tr>
            </tfoot>
          </table>
        </div>

        <div className="p-5 border-t border-ink-100 space-y-4">
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">{t("Notes", "Catatan")}</span>
            {editing ? (
              <textarea rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
            ) : <div className="text-sm">{d.notes || <span className="muted">—</span>}</div>}
          </label>
          {editing ? (
            <div className="flex items-center justify-end gap-2">
              {dirty && <span className="text-xs text-amber-700 mr-auto">{t("Unsaved changes", "Ada perubahan belum disimpan")}</span>}
              <button type="button" className="btn-ghost" disabled={!dirty} onClick={() => { load(d); setMsg(null); }}>
                {t("Undo changes", "Batalkan perubahan")}</button>
              <button type="submit" className="btn-primary" disabled={!dirty || save.isPending}>
                {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {t("Save", "Simpan")}</button>
            </div>
          ) : (
            <div className="text-xs muted">
              {d.status === "closed" ? t("Closed — reopen it to make changes.", "Ditutup — buka kembali untuk mengubah.")
                : d.status === "cancelled" ? t("Rejected requests can't be changed.", "Permintaan yang ditolak tidak dapat diubah.")
                : t("Read-only.", "Hanya baca.")}
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
