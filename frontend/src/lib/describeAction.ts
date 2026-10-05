import { t as tt } from "@/store/lang";

/**
 * "POST /api/v1/quotations/<id>/submit" → { verb: "Submit", what: "Quotation",
 * link: "/quotations/<id>" } — the system log's way of saying what somebody
 * did without showing the director a URL.
 */

// Longest prefix wins; [English, Indonesian, page for one record].
const ENTITIES: [string, string, string, string | null][] = [
  ["purchasing/price-requests", "Supplier price request", "Permintaan harga supplier", "/purchasing/price-requests/:id"],
  ["purchasing/po", "Purchasing PO", "PO pembelian", "/purchase-orders/:id"],
  ["purchasing/suppliers", "Supplier", "Supplier", "/suppliers/:id"],
  ["operation/projects", "Project", "Proyek", "/projects/:id"],
  ["operation/deliveries", "Delivery order", "Surat jalan", "/deliveries/:id"],
  ["operation/work-orders", "Work order", "Work order", null],
  ["customers", "Customer", "Pelanggan", "/customers/:id"],
  ["customer-pos", "Customer PO", "PO pelanggan", "/customer-pos/:id"],
  ["price-requests", "Price request", "Permintaan harga", null],
  ["quotations", "Quotation", "Penawaran", "/quotations/:id"],
  ["inventory", "Inventory", "Inventori", "/inventory/:id"],
  ["finance/invoices", "Invoice", "Faktur", "/invoices/:id"],
  ["employees", "Employee", "Karyawan", "/employees/:id"],
  ["users", "User", "Pengguna", null],
  ["attachments", "File", "Berkas", null],
  ["attendance", "Attendance", "Absensi", null],
  ["salaries", "Salary", "Gaji", null],
  ["approvals", "Approval", "Persetujuan", null],
  ["comments", "Comment", "Komentar", null],
  ["chat", "Chat", "Chat", null],
  ["notifications", "Notification", "Notifikasi", null],
  ["calendar", "Calendar", "Kalender", null],
  ["assets", "Fixed asset", "Aset tetap", "/assets/:id"],
  ["journals", "Journal", "Jurnal", null],
  ["cash", "Cash & bank", "Kas & bank", null],
  ["budgets", "Budget", "Anggaran", null],
  ["payments", "Payment", "Pembayaran", null],
  ["finance", "Finance", "Keuangan", null],
  ["purchasing", "Purchasing", "Pembelian", null],
  ["operation", "Operation", "Operasi", null],
];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function describeAction(method: string, path: string): {
  verb: string; what: string; link: string | null;
} {
  const segs = path.replace(/^\/api\/v1\//, "").split("/").filter(Boolean);
  const words = segs.filter((s) => !UUID_RE.test(s));
  const firstId = segs.find((s) => UUID_RE.test(s)) ?? null;
  const joined = words.join("/");
  const ent = ENTITIES.find(([p]) => joined === p || joined.startsWith(p + "/"));
  const what = ent ? tt(ent[1], ent[2]) : cap((words[0] ?? "").replace(/-/g, " "));
  const rest = ent ? joined.slice(ent[0].length).replace(/^\//, "") : words.slice(1).join("/");
  const verb = rest
    ? cap(rest.replace(/[/_-]+/g, " "))
    : method === "POST" ? tt("Created", "Membuat")
    : method === "DELETE" ? tt("Deleted", "Menghapus")
    : tt("Edited", "Mengubah");
  // Only a record that still exists has a page; a deleted one links nowhere.
  const link = ent?.[3] && firstId && method !== "DELETE" ? ent[3].replace(":id", firstId) : null;
  return { verb, what, link };
}
