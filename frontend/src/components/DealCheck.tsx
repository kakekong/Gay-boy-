import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Check } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt } from "@/store/lang";

/**
 * The director's deal check: does the rest of this deal still say what this
 * document says?
 *
 * One deal is written down several times — price request, quotation,
 * customer PO, and on the buy side the supplier requests and POs. The server
 * (`services/order_consistency.py`) compares them. Each mismatch is shown as
 * the two documents **side by side**, each difference on the same row in
 * both columns, with "This one is right" under each. Picking one changes the
 * other to match, after a confirm that names exactly what will change.
 *
 * Director only — the server refuses everyone else, and the card is not
 * rendered for them. Ordinary edits still sync on their own.
 */

type Where = {
  price_request_id?: string; quotation_id?: string;
  customer_po_id?: string; project_id?: string;
};
interface DocRef { kind: string; id: string | null; number: string; docs?: DocRef[] }
interface Field { field: string; left: any; right: any }
interface Line { line_no: number | null; change: string; description: string | null; fields?: Field[] }
interface Action { id: "use_left" | "use_right"; allowed: boolean; reason: string | null; how: string }
interface Check { key: string; left: DocRef; right: DocRef; lines: Line[]; actions: Action[];
  info_only?: boolean; partial?: boolean }
interface Report { documents: Record<string, any>; checks: Check[]; issues: number }

const KIND: Record<string, [string, string]> = {
  price_request: ["Price request", "Permintaan harga"],
  quotation: ["Quotation", "Penawaran"],
  customer_po: ["Customer PO", "PO pelanggan"],
  supplier_price_request: ["Supplier request", "Permintaan ke supplier"],
  supplier_po: ["Supplier PO", "PO supplier"],
  supplier_pos: ["Ordered from supplier", "Dipesan ke supplier"],
};
const FIELD: Record<string, [string, string]> = {
  description: ["Wording", "Deskripsi"], qty: ["Quantity", "Jumlah"],
  uom: ["Unit", "Satuan"], price: ["Price", "Harga"],
};

function linkOf(d: DocRef): string | null {
  if (!d.id) return null;
  switch (d.kind) {
    case "price_request": return `/price-requests?open=${d.id}`;
    case "quotation": return `/quotations/${d.id}`;
    case "customer_po": return `/customer-pos/${d.id}`;
    case "supplier_price_request": return `/purchasing/price-requests/${d.id}`;
    case "supplier_po": return `/purchase-orders/${d.id}`;
    default: return null;
  }
}
const kindName = (k: string) => (KIND[k] ? tt(KIND[k][0], KIND[k][1]) : k);
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

function val(field: string, v: any): string {
  if (v == null || v === "") return "—";
  if (field === "price") return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(Number(v)));
  if (field === "qty") return new Intl.NumberFormat("id-ID").format(Number(v));
  return String(v);
}

/** One row of the comparison: the same difference, as each document has it. */
interface Row { item: string; label: string; left: string; right: string; missing?: "left" | "right" }

function rowsOf(c: Check): Row[] {
  const out: Row[] = [];
  for (const l of c.lines) {
    const item = l.description || tt(`Line ${l.line_no}`, `Baris ${l.line_no}`);
    if (l.change === "only_left" || l.change === "only_right") {
      const here = tt("On this one", "Ada di sini"), gone = tt("Not on this one", "Tidak ada");
      out.push({ item, label: tt("Line", "Baris"),
        left: l.change === "only_left" ? here : gone, right: l.change === "only_right" ? here : gone,
        missing: l.change === "only_left" ? "right" : "left" });
      continue;
    }
    for (const f of l.fields ?? []) {
      out.push({ item, label: FIELD[f.field] ? tt(FIELD[f.field][0], FIELD[f.field][1]) : f.field,
        left: val(f.field, f.left), right: val(f.field, f.right) });
    }
  }
  return out;
}

function DocHead({ d }: { d: DocRef }) {
  const href = d.docs ? null : linkOf(d);
  return (
    <div className="pb-2 mb-1 border-b border-ink-100">
      <div className="text-[11px] uppercase tracking-wider muted">{kindName(d.kind)}</div>
      {d.docs ? (
        <div className="flex flex-wrap gap-x-2 text-sm font-mono">
          {d.docs.map((x) => (
            <Link key={x.id} to={linkOf(x) ?? "#"} className="text-brand-700 hover:underline inline-flex items-center gap-0.5">
              {x.number}<ExternalLink size={10} />
            </Link>
          ))}
        </div>
      ) : href ? (
        <Link to={href} className="text-sm font-mono font-semibold text-brand-700 hover:underline inline-flex items-center gap-1">
          {d.number}<ExternalLink size={11} />
        </Link>
      ) : <div className="text-sm font-mono font-semibold">{d.number}</div>}
    </div>
  );
}

function Mismatch({ c, onFix, busy }: {
  c: Check; onFix: (check: string, action: string) => void; busy: boolean;
}) {
  const t = useT();
  const [picked, setPicked] = useState<Action | null>(null);
  const rows = rowsOf(c);
  const act = (side: "left" | "right") => c.actions.find((a) => a.id === (side === "left" ? "use_left" : "use_right"));
  const changes = (a: Action) => (a.id === "use_left" ? c.right : c.left);
  const keeps = (a: Action) => (a.id === "use_left" ? c.left : c.right);

  // Two cards side by side, built as one grid so each row lines up across
  // both: the header, one row per difference, then the button.
  const col = (side: "left" | "right", first: boolean, last: boolean) => clsx(
    "px-3 bg-white dark:bg-ink-50/5 border-x border-ink-200",
    first && "border-t rounded-t-lg pt-3",
    last && "border-b rounded-b-lg pb-3",
    picked && keeps(picked) === (side === "left" ? c.left : c.right) && "border-brand-500 bg-brand-50/40",
  );

  const title = c.info_only
    ? t("Supplier order quantity differs from what the job needs", "Jumlah pesanan ke supplier beda dengan kebutuhan")
    : c.key.startsWith("supplier_request")
    ? t("The supplier was asked for an older version of this order", "Supplier diminta versi lama pesanan ini")
    : t(`${kindName(c.left.kind)} and ${lower(kindName(c.right.kind))} don't match`,
        `${kindName(c.left.kind)} dan ${lower(kindName(c.right.kind))} tidak sama`);

  const button = (side: "left" | "right") => {
    if (c.info_only) return null;
    const a = act(side);
    if (!a) return <div className="h-9" />;
    const label = c.key.startsWith("supplier_request")
      ? t("Update the supplier request to this", "Samakan permintaan supplier dengan ini")
      : t("This one is right", "Ini yang benar");
    return (
      <div className="pt-2">
        <button className={clsx("w-full", picked?.id === a.id ? "btn-primary" : "btn-ghost border border-ink-300 hover:border-brand-500 hover:text-brand-700")}
          disabled={!a.allowed || busy} title={a.reason ?? undefined} onClick={() => setPicked(a)}>
          {picked?.id === a.id && <Check size={14} />} {label}
        </button>
        {!a.allowed && a.reason && <div className="text-[11px] muted mt-1">{a.reason}</div>}
      </div>
    );
  };

  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold">{title}</div>
      <div className="grid grid-cols-2 gap-x-3">
        <div className={col("left", true, false)}><DocHead d={c.left} /></div>
        <div className={col("right", true, false)}><DocHead d={c.right} /></div>
        {rows.slice(0, 10).map((r, i) => (
          [("left" as const), ("right" as const)].map((side) => {
            const v = side === "left" ? r.left : r.right;
            const absent = r.missing === side;
            return (
              <div key={`${i}-${side}`} className={clsx(col(side, false, false), "py-1.5")}>
                <div className="text-[11px] muted break-words" title={r.item}>{r.item} · {r.label}</div>
                <div className={clsx("text-sm font-semibold break-words",
                  absent ? "muted font-normal italic" : "text-amber-800 dark:text-amber-300")}>{v}</div>
              </div>
            );
          })
        ))}
        {rows.length > 10 && (
          <>
            <div className={clsx(col("left", false, false), "py-1 text-[11px] muted")}>+{rows.length - 10} {t("more", "lagi")}</div>
            <div className={clsx(col("right", false, false), "py-1")} />
          </>
        )}
        <div className={col("left", false, true)}>{button("left")}</div>
        <div className={col("right", false, true)}>{button("right")}</div>
      </div>

      {c.info_only && (
        <div className="text-xs muted">
          {t("A placed order is changed with the supplier — open the supplier PO to adjust it.",
             "Pesanan yang sudah dikirim diubah bersama supplier — buka PO supplier untuk menyesuaikan.")}
        </div>
      )}
      {c.partial && (
        <div className="text-[11px] muted">
          {t("The customer ordered in parts, so quantities aren't compared.",
             "Pelanggan memesan bertahap, jadi jumlah tidak dibandingkan.")}
        </div>
      )}
      {picked && (
        <div className="rounded-lg border border-brand-200 bg-brand-50/50 p-3 text-sm flex items-center gap-3 flex-wrap">
          <span className="flex-1 min-w-[240px]">
            {t(`${kindName(changes(picked).kind)} ${changes(picked).number} will be changed to match ${lower(kindName(keeps(picked).kind))} ${keeps(picked).number}.`,
               `${kindName(changes(picked).kind)} ${changes(picked).number} akan diubah mengikuti ${lower(kindName(keeps(picked).kind))} ${keeps(picked).number}.`)}
          </span>
          <button className="btn-primary" disabled={busy}
            onClick={() => { onFix(c.key, picked.id); setPicked(null); }}>
            {t("Yes, change it", "Ya, ubah")}
          </button>
          <button className="btn-ghost" onClick={() => setPicked(null)}>{t("Cancel", "Batal")}</button>
        </div>
      )}
    </div>
  );
}

export function DealCheck({ where }: { where: Where }) {
  const t = useT();
  const qc = useQueryClient();
  const isDirector = useAuthStore((s) => s.user?.role) === "director";
  const [open, setOpen] = useState(true);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const rep = useQuery({
    queryKey: ["consistency", where],
    queryFn: () => api.get("/consistency", { params: where }).then((r) => r.data as Report),
    enabled: isDirector,
    retry: false,
  });
  const fix = useMutation({
    mutationFn: (b: { check: string; action: string }) =>
      api.post("/consistency/fix", { ...where, ...b }).then((r) => r.data),
    onSuccess: (data) => {
      setMsg({ ok: true, text: data.message });
      // A fix moves other documents than this one; refresh whatever is open.
      qc.invalidateQueries();
    },
    onError: (e: any) => setMsg({ ok: false, text: e?.response?.data?.detail ?? tt("Couldn't change it.", "Gagal diubah.") }),
  });

  const r = rep.data;
  if (!isDirector || !r) return null;
  const problems = r.checks.filter((c) => c.lines.length > 0);
  const docs = r.documents ?? {};
  const count = [docs.price_request, docs.quotation, ...(docs.customer_pos ?? [])].filter(Boolean).length;

  if (!problems.length) {
    if (count < 2 && !msg) return null;
    return (
      <div className="flex items-center gap-1.5 text-xs text-emerald-700">
        <CheckCircle2 size={13} className="shrink-0" />
        {msg?.ok ? msg.text + " " : ""}
        {t("Price request, quotation and customer PO all match.",
           "Permintaan harga, penawaran dan PO pelanggan sudah sama.")}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50/60 dark:bg-amber-500/5">
      <button className="w-full px-4 py-3 flex items-center gap-2 text-left" onClick={() => setOpen((o) => !o)}>
        <AlertTriangle size={16} className="text-amber-600 shrink-0" />
        <span className="font-semibold text-amber-900 dark:text-amber-300">
          {problems.length === 1
            ? t("1 thing on this deal doesn't match", "1 hal pada kesepakatan ini tidak sama")
            : t(`${problems.length} things on this deal don't match`, `${problems.length} hal pada kesepakatan ini tidak sama`)}
        </span>
        <ChevronDown size={16} className={clsx("ml-auto text-amber-700 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-5">
          {msg && (
            <div className={clsx("text-sm rounded-md px-3 py-2",
              msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800")}>
              {msg.text}
            </div>
          )}
          {problems.map((c) => (
            <Mismatch key={c.key} c={c} busy={fix.isPending}
              onFix={(check, action) => { setMsg(null); fix.mutate({ check, action }); }} />
          ))}
        </div>
      )}
    </div>
  );
}
