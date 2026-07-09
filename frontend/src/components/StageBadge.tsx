import clsx from "clsx";
import { useT } from "@/store/lang";

const STYLES: Record<string, { bg: string; dot: string; label?: string }> = {
  lead:          { bg: "bg-ink-100 text-ink-700",            dot: "bg-ink-400",     label: "Lead" },
  presentation:  { bg: "bg-blue-50 text-blue-700",           dot: "bg-blue-500",    label: "Presentation" },
  engineering:   { bg: "bg-indigo-50 text-indigo-700",       dot: "bg-indigo-500",  label: "Engineering" },
  quotation:     { bg: "bg-violet-50 text-violet-700",       dot: "bg-violet-500",  label: "Quotation" },
  negotiation:   { bg: "bg-amber-50 text-amber-700",         dot: "bg-amber-500",   label: "Negotiation" },
  po:            { bg: "bg-emerald-50 text-emerald-700",     dot: "bg-emerald-500", label: "PO" },
  drawing:       { bg: "bg-cyan-50 text-cyan-700",           dot: "bg-cyan-500",    label: "Drawing" },
  purchasing:    { bg: "bg-teal-50 text-teal-700",           dot: "bg-teal-500",    label: "Purchasing" },
  delivery:      { bg: "bg-lime-50 text-lime-700",           dot: "bg-lime-500",    label: "Delivery" },
  invoicing:     { bg: "bg-yellow-50 text-yellow-700",       dot: "bg-yellow-500",  label: "Invoicing" },
  payment:       { bg: "bg-orange-50 text-orange-700",       dot: "bg-orange-500",  label: "Payment" },
  closed_won:    { bg: "bg-emerald-100 text-emerald-800",    dot: "bg-emerald-600", label: "Won" },
  closed_lost:   { bg: "bg-red-100 text-red-800",            dot: "bg-red-600",     label: "Lost" },
};

// Indonesian display labels for the backend stage keys. Display only — the
// keys themselves are still what the code compares and sends.
const LABEL_ID: Record<string, string> = {
  lead:         "Prospek",
  presentation: "Presentasi",
  engineering:  "Engineering",
  quotation:    "Penawaran",
  negotiation:  "Negosiasi",
  po:           "PO",
  drawing:      "Gambar",
  purchasing:   "Pembelian",
  delivery:     "Pengiriman",
  invoicing:    "Penagihan",
  payment:      "Pembayaran",
  closed_won:   "Menang",
  closed_lost:  "Kalah",
};

export function StageBadge({ stage }: { stage: string }) {
  const t = useT();
  const s = STYLES[stage] ?? { bg: "bg-ink-100 text-ink-600", dot: "bg-ink-400" };
  const en = s.label ?? stage;
  return (
    <span className={clsx("chip", s.bg)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {t(en, LABEL_ID[stage] ?? en)}
    </span>
  );
}
