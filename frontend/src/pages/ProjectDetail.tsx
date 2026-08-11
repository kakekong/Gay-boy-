import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Briefcase, Building2, FileText, Calendar, Truck, Receipt,
  ShoppingCart, Wrench, Plus, CheckCircle, XCircle, ShieldCheck,
  Loader2, Hammer, User as UserIcon, Trash2, Tag, HelpCircle, ArrowRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, T, locale } from "@/store/lang";
import { UserLink } from "@/components/UserLink";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { ShippingTimeline } from "@/components/ShippingTimeline";
import { ShippingTimelineEditor } from "@/components/ShippingTimelineEditor";

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

// Mirrors backend PROJECT_STATUS_ORDER: purchasing files a supplier PO
// first, then supplier posts a drawing → director approves → ops runs
// production/QC/packaging → finance/admin close out → payment.
const PIPELINE_STAGES = [
  "new", "purchasing", "drawing", "drawing_approved",
  "production", "qc", "packaging", "invoiced", "delivered", "paid", "closed",
];

// What actually moves a project out of each stage. Every line mirrors the
// real trigger in the backend — the event that calls advance_project_status —
// not the idealised workflow, so nobody waits on a step the code never checks.
// `needs` is a hard gate the API enforces; `note` is context, not a blocker.
type StageGuide = {
  who: [string, string];
  action: [string, string];
  where: [string, string];
  needs?: [string, string];
  note?: [string, string];
};

const STAGE_GUIDE: Record<string, StageGuide> = {
  new: {
    who: ["Purchasing files it, the director approves",
          "Pembelian yang membuat, direktur menyetujui"],
    action: ["Raise the supplier PO for this project and get it approved.",
             "Buat PO supplier untuk proyek ini lalu mintakan persetujuan."],
    where: ["Purchasing → Purchase orders (the director decides in /approvals)",
            "Pembelian → Purchase order (direktur memutuskan di /approvals)"],
  },
  purchasing: {
    who: ["Supplier, purchasing, admin or the director",
          "Supplier, pembelian, admin atau direktur"],
    action: ["Upload the technical drawing. Any submitted drawing moves the project here.",
             "Unggah gambar teknis. Gambar apa pun yang diajukan memindahkan proyek ke tahap ini."],
    where: ["The Drawings card below — or the supplier uploads it from their portal",
            "Kartu Gambar di bawah — atau supplier mengunggah dari portalnya"],
  },
  drawing: {
    who: ["The director — or the customer on their portal",
          "Direktur — atau pelanggan lewat portalnya"],
    action: ["Approve the submitted drawing. A rejection sends it back for revision instead.",
             "Setujui gambar yang diajukan. Penolakan mengembalikannya untuk revisi."],
    where: ["The Drawings card below (Approve / Request revision)",
            "Kartu Gambar di bawah (Setujui / Minta revisi)"],
    needs: ["A drawing must be uploaded and awaiting a decision.",
            "Harus ada gambar yang sudah diunggah dan menunggu keputusan."],
  },
  drawing_approved: {
    who: ["Purchasing, a manager or the director",
          "Pembelian, manajer atau direktur"],
    action: ["Confirm the goods have shipped — that is what opens the ops board.",
             "Konfirmasi barang sudah dikirim — itulah yang membuka papan operasi."],
    where: ["The Logistics card below → Confirm delivery",
            "Kartu Logistik di bawah → Konfirmasi pengiriman"],
    needs: ["Every required import document must be director-approved first.",
            "Semua dokumen impor yang diwajibkan harus disetujui direktur lebih dulu."],
  },
  production: {
    who: ["Purchasing, admin or the director",
          "Pembelian, admin atau direktur"],
    action: ["Record the QC result as a pass, or file a QC work order on the ops board.",
             "Catat hasil QC sebagai lulus, atau buat work order QC di papan operasi."],
    where: ["The QC card below, or Work orders → new QC work order",
            "Kartu QC di bawah, atau Work order → work order QC baru"],
    note: ["A QC fail keeps the project here — and blocks the final invoice.",
           "QC gagal menahan proyek di sini — dan memblokir faktur final."],
  },
  qc: {
    who: ["Purchasing, admin or the director",
          "Pembelian, admin atau direktur"],
    action: ["File the packaging work order once the goods are ready to pack.",
             "Buat work order pengemasan begitu barang siap dikemas."],
    where: ["Work orders → new work order, stage 'packaging'",
            "Work order → work order baru, tahap 'pengemasan'"],
  },
  packaging: {
    who: ["Finance (the director is the backstop)",
          "Keuangan (direktur sebagai cadangan)"],
    action: ["Approve the invoice with its faktur pajak number — approval is the trigger, not issuing.",
             "Setujui faktur dengan nomor faktur pajaknya — persetujuan itu pemicunya, bukan penerbitan."],
    where: ["Finance → Pending invoices",
            "Keuangan → Faktur menunggu"],
    needs: ["The final invoice has to be issued first, and issuing it needs QC recorded as a pass.",
            "Faktur final harus diterbitkan dulu, dan penerbitannya butuh QC tercatat lulus."],
  },
  invoiced: {
    who: ["Admin", "Admin"],
    action: ["Confirm the customer received the goods. This also closes any open delivery orders.",
             "Konfirmasi pelanggan sudah menerima barang. Ini juga menutup semua surat jalan terbuka."],
    where: ["The Delivery card below → Customer received",
            "Kartu Pengiriman di bawah → Pelanggan menerima"],
    note: ["Upload the delivery proof and let the director verify it before confirming.",
           "Unggah bukti pengiriman dan minta direktur memverifikasinya sebelum konfirmasi."],
  },
  delivered: {
    who: ["Finance", "Keuangan"],
    action: ["Verify the customer's payment claim, or record the payment manually. Paying in full closes the project outright.",
             "Verifikasi klaim pembayaran pelanggan, atau catat pembayaran manual. Pelunasan penuh langsung menutup proyek."],
    where: ["Finance → Payment verification, or the invoice card → Enter payment manually",
            "Keuangan → Verifikasi pembayaran, atau kartu faktur → Catat pembayaran manual"],
    note: ["A part payment leaves the invoice 'partial' and the project here until the rest lands.",
           "Pembayaran sebagian membuat faktur 'sebagian' dan proyek tetap di sini sampai sisanya masuk."],
  },
  paid: {
    who: ["Nobody — it is automatic", "Tidak ada — otomatis"],
    action: ["The payment that settles the invoice closes the project in the same step.",
             "Pembayaran yang melunasi faktur menutup proyek pada langkah yang sama."],
    where: ["No action needed", "Tidak perlu tindakan"],
  },
};

const WO_STAGES = ["receiving", "warehousing", "qc", "packaging", "delivery"];

// Mirror of the backend's _WO_STAGE_MIN_PROJECT_STATUS. The WO board can't
// get ahead of the project: a 'packaging' WO can only be filed once the
// project itself has reached qc, etc. Keep this in lockstep with the
// server-side check in operation.py so the UI never offers a stage the
// backend will reject.
const WO_STAGE_MIN_PROJECT_STATUS: Record<string, string> = {
  receiving:   "production",
  warehousing: "production",
  qc:          "production",   // creating a QC WO bumps project 'production' → 'qc'
  packaging:   "qc",           // creating a packaging WO bumps 'qc' → 'packaging'
  delivery:    "packaging",    // delivery WO ships out after packaging
};
// Short suffixes used to auto-generate the WO code per stage, e.g.
// WO-PRJ-2026-0006-PKG for a packaging work order.
const WO_STAGE_SUFFIX: Record<string, string> = {
  receiving: "RCV", warehousing: "WRS", qc: "QC",
  packaging: "PKG", delivery: "DLY",
};

// Indonesian display labels for backend status/stage keys. Display only —
// the keys themselves are still what the code compares and sends.
const STATUS_LABEL_ID: Record<string, string> = {
  new: "baru", purchasing: "pembelian", drawing: "gambar",
  drawing_approved: "gambar disetujui", production: "produksi", qc: "QC",
  packaging: "pengemasan", invoiced: "difakturkan", delivered: "terkirim",
  paid: "lunas", closed: "tutup",
};
// "qc" humanises to "Qc" under the CSS capitalize the stage chips use, which
// reads wrong for an initialism. Only the English side needs the override.
const STATUS_LABEL_EN: Record<string, string> = { qc: "QC" };
const WO_STAGE_LABEL_ID: Record<string, string> = {
  receiving: "penerimaan", warehousing: "pergudangan", qc: "QC",
  packaging: "pengemasan", delivery: "pengiriman",
};
const DRAWING_STATUS_LABEL_ID: Record<string, string> = {
  approved: "disetujui", submitted: "diajukan",
  revision_requested: "revisi diminta", rejected: "ditolak",
};
const DOC_STATUS_LABEL_ID: Record<string, string> = {
  approved: "disetujui", rejected: "ditolak", pending: "menunggu",
};
const INVOICE_STATUS_LABEL_ID: Record<string, string> = {
  approved: "disetujui", pending_finance: "menunggu keuangan",
  rejected: "ditolak", issued: "terbit", partial: "sebagian",
  overdue: "jatuh tempo", paid: "lunas",
};
const CLAIM_STATUS_LABEL_ID: Record<string, string> = {
  verified: "terverifikasi", rejected: "ditolak", pending: "menunggu",
};
const SUPPLIER_PO_STATUS_LABEL_ID: Record<string, string> = {
  open: "terbuka", received: "diterima",
  pending_approval: "menunggu persetujuan", cancelled: "dibatalkan",
};
const DELIVERY_MODE_LABEL_ID: Record<string, string> = {
  local: "lokal", direct_import: "impor langsung", agent: "lewat agen",
};

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  // Display label for a backend status key: humanised English key, or the
  // Indonesian label from the given map when the app is in Indonesian.
  const sl = (key: string, map: Record<string, string>) => {
    const en = (key ?? "").replace(/_/g, " ");
    return t(en, map[key] ?? en);
  };
  // Project stage label — same as sl() but honours the English overrides.
  const stageLabel = (key: string) =>
    t(STATUS_LABEL_EN[key] ?? (key ?? "").replace(/_/g, " "), STATUS_LABEL_ID[key] ?? key);
  // Purchasing sees the project's procurement detail (items, work orders,
  // drawings, deliveries) but not its deal economics — PO value, margins,
  // or invoice amounts. The backend nulls these for purchasing too.
  const showMoney = useAuthStore((s) => s.user?.role) !== "purchasing";
  // Drawing files are viewable by the director only (internal app).
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const userId = useAuthStore((s) => s.user?.id) ?? "";
  const canLogistics = ["purchasing", "director", "manager", "admin"].includes(role);
  const isOps = ["manager", "director", "admin"].includes(role);
  const isAdmin = ["admin", "director"].includes(role);
  // "Money viewer" — who may see amounts/totals. NOT who may act on finance forms.
  const isFinance = ["finance", "admin", "manager", "director"].includes(role);
  // Strict finance approval role — only finance (plus director as backstop)
  // gets the "Approve invoice + enter faktur pajak" form on the project page.
  const canFinanceApprove = role === "finance" || role === "director";
  // Internal staff upload the drawing (on behalf of the supplier); the director
  // signs it off. The drawing file is viewable by either of those.
  const canUploadDrawing = ["purchasing", "sales", "manager", "director", "admin"].includes(role);
  const canApproveDrawing = ["director", "manager", "admin"].includes(role);
  const canViewDrawing = canUploadDrawing || canApproveDrawing;
  // Only purchasing / admin / director may file or move work orders — the
  // backend enforces the same set. Sales/finance/hr never touch WOs.
  const canManageWO = ["purchasing", "admin", "director"].includes(role);
  // Sales sees only the customer-facing shell of a project (header,
  // pipeline, sales rep, shipping timeline view). Every internal card —
  // work orders, drawings, deliveries, invoices, supplier POs, logistics,
  // QC, margins — stays hidden so the sales role never leaks internal
  // ops or money detail. The customer's project timeline lives on the
  // portal; this is the internal page.
  const isSales = role === "sales";
  const canSeeOpsDetails = !isSales;

  const data = useQuery({
    queryKey: ["project-full", id],
    queryFn: () => api.get(`/operation/projects/${id}/full`).then((r) => r.data),
    enabled: !!id,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["project-full", id] });

  const [newWoCode, setNewWoCode] = useState("");
  const [newWoStage, setNewWoStage] = useState("receiving");
  const [flashErr, setFlashErr] = useState<string | null>(null);
  // Which stage's "how do I move on" guide is open. Null = follow the project's
  // own stage, so the card is always answering the question you actually have;
  // clicking another chip lets you read ahead without changing anything.
  const [guideStage, setGuideStage] = useState<string | null>(null);

  // Auto-fill the WO code field as WO-{project}-{stage-suffix} so ops doesn't
  // have to type it. Re-syncs whenever stage changes or the project data
  // arrives; user can still type over it for a custom code.
  const projectCode: string | undefined = data.data?.project?.code;
  const defaultWoCode = projectCode
    ? `WO-${projectCode}-${WO_STAGE_SUFFIX[newWoStage] ?? newWoStage.toUpperCase()}`
    : "";
  useEffect(() => {
    if (defaultWoCode) setNewWoCode(defaultWoCode);
  }, [defaultWoCode]);
  const [drawingFile, setDrawingFile] = useState<File | null>(null);
  const [drawingNotes, setDrawingNotes] = useState("");
  const [revFiles, setRevFiles] = useState<Record<string, File | null>>({});
  // Per-DO proof upload form (file + optional courier/tracking).
  const [doProof, setDoProof] = useState<Record<string, {
    file?: File | null; courier?: string; tracking?: string;
  }>>({});

  const onErr = (e: any) => alert(
    e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? e?.message
      ?? tt("Operation failed", "Operasi gagal")
  );

  // Drawing files live behind the authenticated API. A plain <a href> opens a
  // new tab with no auth token (and, in prod, hits the frontend origin instead
  // of the API), which bounces to login. Fetch it through the API client (token
  // + correct base URL) and open the blob instead.
  const viewFile = async (fileUrl: string) => {
    try {
      const path = fileUrl.replace(/^\/api\/v1/, "");
      const resp = await api.get(path, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data as Blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      onErr(e);
    }
  };
  const addWO = useMutation({
    mutationFn: (vars: { stage: string }) =>
      api.post(`/operation/projects/${id}/work-orders`, {
        code: newWoCode, stage: vars.stage,
      }),
    // Don't blank the code after submit — leave the auto-default visible
    // so the user can switch stage and submit again without re-typing.
    onSuccess: () => { refresh(); },
    onError: onErr,
  });
  const completeWO = useMutation({
    mutationFn: (woId: string) =>
      api.patch(`/operation/work-orders/${woId}`, null, { params: { completed: true } }),
    onSuccess: refresh,
    onError: onErr,
  });
  const uploadDeliveryProof = useMutation({
    mutationFn: (body: { doId: string; file: File; courier?: string; tracking?: string }) => {
      const fd = new FormData();
      fd.append("file", body.file);
      if (body.courier != null) fd.append("courier", body.courier);
      if (body.tracking != null) fd.append("tracking_no", body.tracking);
      return api.post(`/operation/deliveries/${body.doId}/proof`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const verifyDelivery = useMutation({
    mutationFn: (doId: string) => api.post(`/operation/deliveries/${doId}/verify`),
    onSuccess: refresh, onError: onErr,
  });
  const markDelivered = useMutation({
    mutationFn: (doId: string) => api.patch(`/operation/deliveries/${doId}/delivered`),
    onSuccess: refresh,
    onError: onErr,
  });

  // Drawings: internal upload + director sign-off.
  const uploadDrawing = useMutation({
    mutationFn: (body: { file: File; notes: string }) => {
      const fd = new FormData();
      fd.append("file", body.file);
      if (body.notes) fd.append("notes", body.notes);
      return api.post(`/operation/projects/${id}/drawings`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const decideDrawing = useMutation({
    mutationFn: (body: { drawingId: string; decision: string; notes?: string }) =>
      api.post(`/operation/drawings/${body.drawingId}/decide`, {
        decision: body.decision, notes: body.notes,
      }),
    onSuccess: refresh, onError: onErr,
  });
  const reuploadDrawing = useMutation({
    mutationFn: (body: { drawingId: string; file: File }) => {
      const fd = new FormData();
      fd.append("file", body.file);
      return api.post(`/operation/drawings/${body.drawingId}/reupload`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const deleteDrawing = useMutation({
    mutationFn: (drawingId: string) => api.delete(`/operation/drawings/${drawingId}`),
    onSuccess: refresh, onError: onErr,
  });

  // Post-drawing logistics (purchasing)
  const setLogistics = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/operation/projects/${id}/logistics`, body),
    onSuccess: refresh, onError: onErr,
  });
  const uploadDoc = useMutation({
    mutationFn: (body: { key: string; file: File }) => {
      const fd = new FormData();
      fd.append("file", body.file);
      return api.post(`/operation/projects/${id}/import-docs/${body.key}/upload`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const decideDoc = useMutation({
    mutationFn: (body: { key: string; decision: string; note?: string }) =>
      api.post(`/operation/projects/${id}/import-docs/${body.key}/decide`, {
        decision: body.decision, note: body.note,
      }),
    onSuccess: refresh, onError: onErr,
  });
  const confirmDelivery = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/confirm-delivery`),
    onSuccess: refresh, onError: onErr,
  });

  // Operations QC + admin/finance close-out
  const recordQC = useMutation({
    mutationFn: (body: { decision: string; findings?: string }) =>
      api.post(`/operation/projects/${id}/qc`, body),
    onSuccess: refresh, onError: onErr,
  });
  const issueInvoice = useMutation({
    mutationFn: (body: {
      amount?: number; invoiceFile?: File | null; doFile?: File | null;
      invoiceType?: "dp" | "final" | "single";
    }) => {
      const fd = new FormData();
      if (body.amount != null) fd.append("amount", String(body.amount));
      if (body.invoiceFile) fd.append("invoice_file", body.invoiceFile);
      if (body.doFile) fd.append("delivery_order_file", body.doFile);
      fd.append("invoice_type", body.invoiceType ?? "final");
      // A DP invoice is billed BEFORE delivery so no DO is filed with it —
      // the backend also skips DO creation when type == 'dp'.
      if ((body.invoiceType ?? "final") === "dp") {
        fd.append("create_delivery_order", "false");
      }
      return api.post(`/operation/projects/${id}/issue-invoice`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const approveInvoice = useMutation({
    mutationFn: (body: { invoiceId: string; fpNo: string; fpFile?: File | null }) => {
      const fd = new FormData();
      fd.append("faktur_pajak_no", body.fpNo);
      if (body.fpFile) fd.append("faktur_pajak_file", body.fpFile);
      return api.post(`/finance/invoices/${body.invoiceId}/approve`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const deleteInvoice = useMutation({
    // Finance-only escape hatch — used for duplicates and re-tests. The
    // backend refuses if the invoice has any verified payments (would
    // orphan a ledger entry). Pending claims + file rows are cleaned up
    // alongside the invoice.
    mutationFn: (invoiceId: string) =>
      api.delete(`/finance/invoices/${invoiceId}`),
    onSuccess: refresh, onError: onErr,
  });
  const customerReceived = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/customer-received`),
    onSuccess: refresh, onError: onErr,
  });
  // Director-only escape hatch for stale/test projects. Soft-deletes on
  // the backend so the audit/history chain isn't orphaned. Navigates back
  // to the Projects list on success so the deleted row disappears from
  // view immediately.
  const deleteProject = useMutation({
    mutationFn: () => api.delete(`/operation/projects/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav("/projects");
    },
    onError: onErr,
  });
  // Finance records the payment manually and it's verified in one stroke
  // (same endpoint as the Payment-verification page) — no separate
  // claim-then-verify round trip when finance is the one typing it in.
  // Fully paying the invoice auto-advances the project to paid → closed.
  const recordManualPayment = useMutation({
    mutationFn: async (body: {
      invoiceId: string; amount: number; paidAt?: string;
      method?: string; reference?: string; notes?: string; file?: File | null;
    }) => {
      let attachmentId: string | null = null;
      if (body.file) {
        const fd = new FormData();
        fd.append("owner_type", "invoice");
        fd.append("owner_id", body.invoiceId);
        fd.append("description", "payment_proof");
        fd.append("file", body.file);
        const up = await api.post("/attachments", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        attachmentId = up.data?.id ?? null;
      }
      return api.post("/payments/manual", {
        invoice_id: body.invoiceId,
        amount: body.amount,
        paid_at: body.paidAt || null,
        method: body.method || null,
        reference: body.reference || null,
        notes: body.notes || null,
        attachment_id: attachmentId,
      });
    },
    onSuccess: () => {
      refresh();
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["open-invoices"] });
      qc.invalidateQueries({ queryKey: ["ar-aging"] });
    },
    onError: onErr,
  });
  // Per-invoice manual-payment form state.
  const [payForm, setPayForm] = useState<Record<string, {
    amount?: string; paidAt?: string; method?: string; reference?: string;
    notes?: string; file?: File | null;
  }>>({});
  const [qcFindings, setQcFindings] = useState("");
  const [invAmount, setInvAmount] = useState("");
  const [invFile, setInvFile] = useState<File | null>(null);
  const [doFile, setDoFile] = useState<File | null>(null);
  const [invType, setInvType] = useState<"dp" | "final">("final");
  // Per-invoice finance-approval form state (FP number + FP file).
  const [fpForm, setFpForm] = useState<Record<string, { no: string; file?: File | null }>>({});

  // Inline edit for target / actual delivery dates.
  const patchProject = useMutation({
    mutationFn: (body: Record<string, string | null>) =>
      api.patch(`/operation/projects/${id}`, body).then((r) => r.data),
    onSuccess: (data: any) => {
      refresh();
      if (data?.pending_approval) {
        alert(tt(
          "Shipping/delivery date change submitted to the director for approval.",
          "Perubahan tanggal kirim/pengiriman dikirim ke direktur untuk persetujuan.",
        ));
      }
    },
    onError: onErr,
  });

  if (data.isLoading) return <div className="muted text-sm">{t("Loading…", "Memuat…")}</div>;
  if (data.isError) {
    const e: any = data.error;
    const httpStatus = e?.response?.status;
    const msg = e?.response?.data?.errors?.[0]?.message ?? e?.message
      ?? t("Failed to load project", "Gagal memuat proyek");
    return (
      <div className="space-y-4">
        <div className="card p-6 text-sm">
          <div className="font-semibold text-red-700">{t("Could not load project", "Gagal memuat proyek")}</div>
          <div className="muted mt-1">{msg}</div>
          {httpStatus && (
            <div className="text-xs muted mt-2">{T("HTTP")}{" "}{httpStatus} {T("· GET /operation/projects/")}{id}{T("/full")}</div>
          )}
          <div className="text-xs muted mt-3">
            {t(
              "If you just upgraded, the api container may still be running the old code. Try a hard refresh, or restart the api container.",
              "Jika baru saja meng-upgrade, kontainer api mungkin masih menjalankan kode lama. Coba hard refresh, atau restart kontainer api.",
            )}
          </div>
        </div>
      </div>
    );
  }
  if (!data.data)     return <div className="muted text-sm">{t("Project not found.", "Proyek tidak ditemukan.")}</div>;

  const p   = data.data.project;
  const cu  = data.data.customer;
  const qt  = data.data.quotation;
  const cpo = data.data.customer_po;
  const salesPicId   = data.data.sales_pic_id;
  const salesPicName = data.data.sales_pic_name;
  const wos = data.data.work_orders ?? [];
  const dr  = data.data.drawings ?? [];
  const dos = data.data.deliveries ?? [];
  const inv = data.data.invoices ?? [];
  const prs = data.data.purchase_requests ?? [];
  const supplierPOs: any[] = data.data.supplier_pos ?? [];
  const priceReq = data.data.price_request ?? null;
  const logistics = data.data.logistics ?? null;

  const marginDelta = (p.margin_actual || 0) - (p.margin_estimate || 0);
  const stageIdx = PIPELINE_STAGES.indexOf(p.status);
  const shownStage = guideStage ?? p.status;
  const guide = STAGE_GUIDE[shownStage];
  const nextStage = PIPELINE_STAGES[PIPELINE_STAGES.indexOf(shownStage) + 1] ?? null;

  return (
    <div className="space-y-6">
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
                  {stageLabel(p.status)}
                </span>
                {role === "director" && (
                  <button
                    type="button"
                    className="btn-ghost text-red-600 text-xs px-2 py-0.5"
                    title={t(
                      "Delete this project (director only). Soft-delete so history isn't orphaned; the linked customer PO gets unlinked.",
                      "Hapus proyek ini (hanya direktur). Soft-delete agar riwayat tidak yatim; PO pelanggan yang tertaut dilepas.",
                    )}
                    disabled={deleteProject.isPending}
                    onClick={() => {
                      if (window.confirm(tt(
                        `Delete ${p.code}? The project is soft-deleted and disappears from the Projects list. The linked customer PO is unlinked so it can be re-approved later. Purchase orders, drawings and invoices remain in the DB.`,
                        `Hapus ${p.code}? Proyek di-soft-delete dan hilang dari daftar Proyek. PO pelanggan yang tertaut dilepas agar bisa disetujui ulang nanti. Purchase order, gambar, dan faktur tetap ada di DB.`,
                      ))) {
                        deleteProject.mutate();
                      }
                    }}
                  >
                    <Trash2 size={12} /> {t("Delete project", "Hapus proyek")}
                  </button>
                )}
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
                {cpo && (
                  <Link to={`/customer-pos/${cpo.id}`}
                    className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700"
                    title={t("Customer PO that spawned this project", "PO pelanggan asal proyek ini")}>
                    <FileText size={13} /> {T("PO")}{" "}{cpo.number}
                  </Link>
                )}
                {priceReq && (
                  ["sales", "purchasing", "manager", "director"].includes(role) ? (
                    <Link to={`/price-requests?open=${priceReq.id}`}
                      className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700"
                      title={t("The approved price request this project fulfils", "Permintaan harga yang dipenuhi proyek ini")}>
                      <Tag size={13} /> {T("PR")}{" "}{priceReq.number}
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-ink-600">
                      <Tag size={13} /> {T("PR")}{" "}{priceReq.number}
                    </span>
                  )
                )}
                {salesPicName && (
                  <span className="inline-flex items-center gap-1.5 text-ink-600">
                    <UserIcon size={13} /> <UserLink id={salesPicId} name={salesPicName} />
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Stage pipeline — each chip opens that stage's "how to move on" guide */}
        <div className="mt-6 flex flex-wrap items-center gap-1.5">
          {PIPELINE_STAGES.map((s, i) => (
            <button key={s} type="button"
              onClick={() => setGuideStage(s === shownStage ? null : s)}
              title={t("What moves this stage forward?", "Apa yang memajukan tahap ini?")}
              className={clsx(
                "chip capitalize transition-shadow",
                i < stageIdx        ? "bg-emerald-100 text-emerald-700"
                : i === stageIdx    ? STATUS_CHIP[s] ?? "bg-ink-100 text-ink-700"
                                    : "bg-ink-100/60 text-ink-400",
                s === shownStage && "ring-2 ring-brand-300"
              )}
            >
              {i < stageIdx && <CheckCircle size={10} />}
              {stageLabel(s)}
            </button>
          ))}
        </div>

        {/* How to move to the next stage */}
        {guide && (
          <div className="mt-3 card p-4 bg-brand-50/40 border-brand-200">
            <div className="flex items-start gap-2">
              <HelpCircle size={15} className="text-brand-700 mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                  <span className="capitalize">{stageLabel(shownStage)}</span>
                  <ArrowRight size={13} className="muted" />
                  <span className="capitalize">
                    {nextStage ? stageLabel(nextStage) : t("done", "selesai")}
                  </span>
                  {shownStage !== p.status && (
                    <span className="chip bg-ink-100 text-ink-600">
                      {stageIdx > PIPELINE_STAGES.indexOf(shownStage)
                        ? t("already passed", "sudah dilewati")
                        : t("coming up", "berikutnya")}
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-sm">{t(guide.action[0], guide.action[1])}</p>
                <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2 text-xs">
                  <div className="flex gap-1.5">
                    <dt className="muted shrink-0">{t("Who", "Siapa")}:</dt>
                    <dd>{t(guide.who[0], guide.who[1])}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="muted shrink-0">{t("Where", "Di mana")}:</dt>
                    <dd>{t(guide.where[0], guide.where[1])}</dd>
                  </div>
                </dl>
                {guide.needs && (
                  <p className="mt-2 text-xs text-amber-700 flex gap-1.5">
                    <ShieldCheck size={13} className="mt-px shrink-0" />
                    <span>
                      <b>{t("Required first", "Wajib lebih dulu")}:</b>{" "}
                      {t(guide.needs[0], guide.needs[1])}
                    </span>
                  </p>
                )}
                {guide.note && (
                  <p className="mt-1 text-xs muted">{t(guide.note[0], guide.note[1])}</p>
                )}
              </div>
              {shownStage !== p.status && (
                <button type="button" className="btn-ghost text-xs shrink-0"
                  onClick={() => setGuideStage(null)}>
                  {t("Current stage", "Tahap saat ini")}
                </button>
              )}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 text-sm">
          <EditableTextField
            label={t("PO Number", "Nomor PO")}
            icon={<FileText size={13} />}
            value={p.po_number ?? ""}
            disabled={patchProject.isPending}
            placeholder="—"
            onCommit={(v) => {
              const next = v.trim();
              if (next !== (p.po_number ?? "")) {
                patchProject.mutate({ po_number: next || null });
              }
            }}
          />
          <EditableDateField
            label={t("PO Date", "Tanggal PO")}
            icon={<Calendar size={13} />}
            value={p.po_date ?? ""}
            disabled={patchProject.isPending}
            onChange={(v) => patchProject.mutate({ po_date: v || null })}
          />
          {/* Delivery dates are read-only for sales. They are promises about
              physical goods somebody else is moving — purchasing books the
              origin leg, admin the arrival legs, the director owns what the
              customer is told. A rep who could type here was really filing an
              approval request against a shipment they cannot see. */}
          <EditableDateField
            label={t("Target delivery", "Target pengiriman")}
            icon={<Truck size={13} />}
            value={p.target_delivery ?? ""}
            disabled={patchProject.isPending}
            readOnly={isSales}
            readOnlyHint={t("Set by the director", "Ditetapkan oleh direktur")}
            onChange={(v) => patchProject.mutate({ target_delivery: v || null })}
          />
          <EditableDateField
            label={t("Actual delivery", "Pengiriman aktual")}
            icon={<Truck size={13} />}
            value={p.actual_delivery ?? ""}
            disabled={patchProject.isPending}
            readOnly={isSales}
            readOnlyHint={t("Set when delivery is confirmed", "Diisi saat pengiriman dikonfirmasi")}
            onChange={(v) => patchProject.mutate({ actual_delivery: v || null })}
          />
        </div>

        {/* Delivery-date guide: what each date means and when to set it.
            Hidden from sales — it is a set of instructions for a field they
            do not fill in, and telling somebody to "click the date field
            above" when the field is read-only for them is just confusing. */}
        {isSales ? (
          <div className="mt-4 rounded-xl border border-ink-100 bg-ink-50/60 p-3 text-xs muted flex gap-2">
            <Truck size={13} className="mt-px shrink-0" />
            <span>
              {t("Delivery dates are set by the people moving the goods — purchasing for the origin leg, admin on arrival, the director for what the customer is promised. Ask them if a date needs to change.",
                 "Tanggal pengiriman diisi oleh pihak yang menangani barang — pembelian untuk tahap asal, admin saat kedatangan, direktur untuk yang dijanjikan ke pelanggan. Hubungi mereka jika tanggal perlu diubah.")}
            </span>
          </div>
        ) : (
        <div className="mt-4 rounded-xl border border-brand-100 bg-brand-50/40 p-4 text-sm">
          <div className="font-semibold text-ink-800 flex items-center gap-2">
            <Truck size={14} className="text-brand-600" /> {t("How to set the delivery dates", "Cara mengisi tanggal pengiriman")}
          </div>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3 text-ink-700">
            <div>
              <div className="font-medium">{t("Target delivery", "Target pengiriman")}</div>
              <p className="text-xs text-ink-600 leading-relaxed mt-0.5">
                {t("The date you ", "Tanggal yang ")}
                <span className="font-medium">{t("promised the customer", "Anda janjikan ke pelanggan")}</span>
                {t(
                  ". Set it as soon as the PO is signed. Click the date field above and pick a date. Once set, leave it alone — change it only after a written customer reschedule.",
                  ". Isi segera setelah PO ditandatangani. Klik kolom tanggal di atas lalu pilih tanggal. Setelah diisi, biarkan — ubah hanya jika ada penjadwalan ulang tertulis dari pelanggan.",
                )}
              </p>
            </div>
            <div>
              <div className="font-medium">{t("Actual delivery", "Pengiriman aktual")}</div>
              <p className="text-xs text-ink-600 leading-relaxed mt-0.5">
                {t("The date the goods ", "Tanggal barang ")}
                <span className="font-medium">{t("actually arrived at the customer", "benar-benar tiba di pelanggan")}</span>
                {t(
                  ". Set it the day delivery is confirmed (proof of delivery, courier sign-off, or customer acknowledgement). The system uses the gap between Target and Actual to track on-time performance.",
                  ". Isi pada hari pengiriman dikonfirmasi (bukti pengiriman, tanda terima kurir, atau konfirmasi pelanggan). Sistem memakai selisih antara Target dan Aktual untuk memantau ketepatan waktu.",
                )}
              </p>
            </div>
          </div>
          <p className="text-[11px] text-ink-500 mt-3">
            {t(
              "For multi-leg shipments (origin → warehouse → customer), use the Shipping timeline editor below for each leg's ETA, and keep this Actual delivery as the final arrival at the customer.",
              "Untuk pengiriman multi-tahap (asal → gudang → pelanggan), gunakan editor linimasa pengiriman di bawah untuk ETA tiap tahap, dan isi Pengiriman aktual ini sebagai kedatangan akhir di pelanggan.",
            )}
          </p>
        </div>
        )}
      </div>

      {/* Profit / Margin — hidden from purchasing and sales */}
      {showMoney && canSeeOpsDetails && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Stat label={t("PO value", "Nilai PO")}      value={idr(p.po_value)}              tone="brand"   />
          <Stat label={t("Margin (est)", "Margin (estimasi)")}  value={pct(p.margin_estimate)}       tone="amber"   />
          <Stat
            label={t("Margin (actual)", "Margin (aktual)")}
            value={pct(p.margin_actual)}
            tone={marginDelta < -0.05 ? "red"
                  : marginDelta < 0    ? "amber" : "emerald"}
          />
          <Stat
            label={t("Delta vs estimate", "Selisih vs estimasi")}
            value={`${marginDelta >= 0 ? "+" : ""}${(marginDelta * 100).toFixed(1)} pp`}
            tone={marginDelta < -0.05 ? "red" : marginDelta < 0 ? "amber" : "emerald"}
          />
        </div>
      )}

      {/* Shipping timeline — sales gets the read-only viewer so they can
          answer 'when's it arriving?' from the customer, but not the
          editor (dates flow from purchasing/ops). */}
      <ShippingTimeline projectId={p.id} />
      {canSeeOpsDetails && <ShippingTimelineEditor projectId={p.id} />}

      {/* Price request (the approved order behind this project) */}
      {priceReq && canSeeOpsDetails && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <FileText size={15} className="text-brand-600" /> {t("Order", "Pesanan")} — {priceReq.number}
            </div>
            <div className="text-xs muted">{t("The approved price request this project fulfils.", "Permintaan harga yang disetujui dan dipenuhi proyek ini.")}</div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">{t("Description", "Deskripsi")}</th>
                <th className="th text-right">{t("Qty", "Jml")}</th>
                <th className="th">{t("UoM", "Satuan")}</th>
                <th className="th">{t("Spec", "Spek")}</th>
                <th className="th text-right">{t("Cost", "Biaya")}</th>
                {priceReq.items?.[0] && "sell_price" in priceReq.items[0] && (
                  <th className="th text-right">{t("Sell", "Jual")}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {(priceReq.items ?? []).map((it: any) => (
                <tr key={it.line_no} className="border-t border-ink-100">
                  <td className="td muted">{it.line_no}</td>
                  <td className="td">{it.description}</td>
                  <td className="td text-right tabular-nums">{it.qty}</td>
                  <td className="td muted">{it.uom || "—"}</td>
                  <td className="td muted text-xs">{it.spec || "—"}</td>
                  <td className="td text-right tabular-nums">{it.cost_price != null ? idr(it.cost_price) : "—"}</td>
                  {"sell_price" in it && (
                    <td className="td text-right tabular-nums">{it.sell_price != null ? idr(it.sell_price) : "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Work orders — ops-internal, hidden from sales */}
      {canSeeOpsDetails && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="font-semibold flex items-center gap-2">
              <Wrench size={15} className="text-brand-600" /> {t("Work orders", "Work order")}
            </div>
            <div className="text-xs muted mt-0.5 max-w-xl leading-relaxed">
              {t(
                "A work order is a single internal step on this project — receiving, warehousing, QC, packaging, or delivery. Each one is a checkable card the shop floor ticks off. Add one per stage you need to track, then mark it complete as the work happens.",
                "Work order adalah satu langkah internal pada proyek ini — penerimaan, pergudangan, QC, pengemasan, atau pengiriman. Masing-masing berupa kartu yang dicentang tim lapangan. Tambahkan satu per tahap yang perlu dilacak, lalu tandai selesai saat pekerjaannya berjalan.",
              )}
            </div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted shrink-0">
            {wos.length} {t(wos.length === 1 ? "step" : "steps", "langkah")}
          </div>
        </div>
        {(() => {
          // Only stages the project has legitimately reached can be filed.
          // Mirrors the backend guard exactly so the UI never offers a stage
          // the server will 409 on.
          const curIdx = PIPELINE_STAGES.indexOf(p.status);
          const allowedStages = WO_STAGES.filter((s) => {
            const min = WO_STAGE_MIN_PROJECT_STATUS[s];
            return curIdx >= PIPELINE_STAGES.indexOf(min);
          });
          const canFileAny = canManageWO && allowedStages.length > 0;
          // If the currently-selected stage isn't allowed anymore, snap
          // back to the first allowed one so the button submits a valid
          // value rather than a stale one.
          const effectiveStage = allowedStages.includes(newWoStage)
            ? newWoStage
            : (allowedStages[0] ?? newWoStage);
          const blockedReason = !canManageWO
            ? t(
                "Only purchasing, admin or director can file work orders.",
                "Hanya pembelian, admin, atau direktur yang dapat membuat work order.",
              )
            : allowedStages.length === 0
              ? t(
                  `The project is still at '${p.status.replace(/_/g, " ")}'. Work orders will unlock once it reaches production — advance the earlier stages (purchasing → drawing → drawing_approved → production) first.`,
                  `Proyek masih di tahap '${STATUS_LABEL_ID[p.status] ?? p.status.replace(/_/g, " ")}'. Work order terbuka setelah proyek mencapai produksi — selesaikan dulu tahap sebelumnya (pembelian → gambar → gambar disetujui → produksi).`,
                )
              : null;
          return (
            <div className="p-3 space-y-2 border-b border-ink-100 bg-ink-50/40">
              {blockedReason && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {blockedReason}
                </div>
              )}
              <div className={clsx(
                "flex flex-wrap items-end gap-2",
                !canFileAny && "opacity-60 pointer-events-none",
              )}>
                <div className="flex-1 min-w-[180px]">
                  <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{t("Code *", "Kode *")}</span>
                  <input className="input" value={newWoCode}
                    disabled={!canFileAny}
                    onChange={(e) => setNewWoCode(e.target.value)}
                    placeholder={t("e.g. WO-PRJ-2026-0042-02", "cth. WO-PRJ-2026-0042-02")} />
                </div>
                <div>
                  <span className="block text-[10px] uppercase text-ink-500 mb-0.5">{t("Stage", "Tahap")}</span>
                  <select
                    className="input"
                    value={effectiveStage}
                    disabled={!canFileAny}
                    onChange={(e) => setNewWoStage(e.target.value)}
                  >
                    {allowedStages.length === 0
                      ? <option value="">{t("— locked —", "— terkunci —")}</option>
                      : allowedStages.map((s) => <option key={s} value={s}>{t(s, WO_STAGE_LABEL_ID[s] ?? s)}</option>)}
                  </select>
                </div>
                <button className="btn-primary"
                  disabled={addWO.isPending || !canFileAny}
                  onClick={() => {
                    if (!newWoCode.trim()) {
                      setFlashErr(tt(
                        "Work-order code is required (the default is auto-generated from project + stage).",
                        "Kode work order wajib diisi (default dibuat otomatis dari proyek + tahap).",
                      ));
                      return;
                    }
                    setFlashErr(null);
                    if (newWoStage !== effectiveStage) setNewWoStage(effectiveStage);
                    addWO.mutate({ stage: effectiveStage });
                  }}>
                  {addWO.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  {t("Add work order", "Tambah work order")}
                </button>
              </div>
            </div>
          );
        })()}
        {flashErr && (
          <div className="mx-3 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {flashErr}
          </div>
        )}
        {wos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">{t("No work orders yet.", "Belum ada work order.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Code", "Kode")}</th>
                <th className="th">{t("Stage", "Tahap")}</th>
                <th className="th">{t("Started", "Mulai")}</th>
                <th className="th">{t("Completed", "Selesai")}</th>
                <th className="th text-right">{t("Actions", "Aksi")}</th>
              </tr>
            </thead>
            <tbody>
              {wos.map((w: any) => (
                <tr key={w.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{w.code}</td>
                  <td className="td">
                    <span className="chip bg-ink-100 text-ink-700 capitalize">{t(w.stage, WO_STAGE_LABEL_ID[w.stage] ?? w.stage)}</span>
                  </td>
                  <td className="td muted">{w.started_at ? new Date(w.started_at).toLocaleDateString(locale()) : "—"}</td>
                  <td className="td muted">
                    {w.completed_at
                      ? <span className="text-emerald-700">{new Date(w.completed_at).toLocaleDateString(locale())}</span>
                      : "—"}
                  </td>
                  <td className="td text-right">
                    {!w.completed_at && (
                      isAdmin ? (
                        <button className="btn-ghost text-emerald-700"
                          onClick={() => completeWO.mutate(w.id)}>
                          <CheckCircle size={13} /> {t("Complete", "Selesaikan")}
                        </button>
                      ) : (
                        <span className="muted text-xs" title={t("Only admin or director can confirm a work order", "Hanya admin atau direktur yang dapat mengonfirmasi work order")}>
                          {t("admin/director only", "hanya admin/direktur")}
                        </span>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Drawings — visible to sales too: they're often the ones holding the
          customer's drawing and need to file it. Sales gets upload + the
          revision list only; approve/reject stays with director/manager/
          admin (canApproveDrawing). All other ops cards remain hidden from
          sales via canSeeOpsDetails. */}
      {(canSeeOpsDetails || canUploadDrawing) && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Hammer size={15} className="text-brand-600" /> {t("Drawings", "Gambar")}
          </div>
          <div className="text-xs muted">{dr.length} {t("revision(s)", "revisi")}</div>
          <div className="text-[11px] text-ink-500 mt-1 max-w-2xl leading-relaxed">
            {t(
              "Upload the customer's or supplier's drawing here — sales files the customer's version, purchasing the supplier's. The director reviews and approves (or requests a revision). An approval advances the project to \"drawing approved\" automatically so logistics can begin.",
              "Unggah gambar dari pelanggan atau supplier di sini — sales mengunggah versi pelanggan, pembelian versi supplier. Direktur meninjau dan menyetujui (atau meminta revisi). Persetujuan otomatis memajukan proyek ke \"gambar disetujui\" sehingga logistik bisa dimulai.",
            )}
          </div>
        </div>

        {canUploadDrawing && (
          <div className="px-5 py-3 border-b border-ink-100 bg-ink-50/40 flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[180px]">
              <label className="block text-[11px] uppercase muted mb-1">{t("Drawing file", "File gambar")}</label>
              <input type="file"
                className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white file:text-xs hover:file:bg-brand-700"
                onChange={(e) => setDrawingFile(e.target.files?.[0] ?? null)} />
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="block text-[11px] uppercase muted mb-1">{t("Notes (optional)", "Catatan (opsional)")}</label>
              <input className="input" value={drawingNotes}
                onChange={(e) => setDrawingNotes(e.target.value)} placeholder={t("e.g. rev from supplier", "cth. revisi dari supplier")} />
            </div>
            <button className="btn-primary"
              disabled={!drawingFile || uploadDrawing.isPending}
              onClick={() => drawingFile && uploadDrawing.mutate(
                { file: drawingFile, notes: drawingNotes },
                { onSuccess: () => { setDrawingFile(null); setDrawingNotes(""); } },
              )}>
              {uploadDrawing.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              {t("Upload drawing", "Unggah gambar")}
            </button>
          </div>
        )}

        {dr.length === 0 ? (
          <div className="p-8 text-center muted text-sm">{t("No drawings uploaded.", "Belum ada gambar diunggah.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Rev", "Rev")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th">{t("Decision", "Keputusan")}</th>
                <th className="th">{T("File")}</th>
                <th className="th">{t("Notes", "Catatan")}</th>
                {canApproveDrawing && <th className="th text-right">{t("Sign-off", "Persetujuan")}</th>}
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
                      {sl(d.status, DRAWING_STATUS_LABEL_ID)}
                    </span>
                    {/* After a revision is requested, only the account that
                        uploaded the drawing can post a corrected file. */}
                    {d.status === "revision_requested"
                      && d.uploaded_by != null && d.uploaded_by === userId && (
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <input type="file"
                          className="block text-[11px] file:mr-1.5 file:rounded file:border-0 file:bg-ink-100 file:px-1.5 file:py-0.5 file:text-[11px]"
                          onChange={(e) => setRevFiles((f) => ({ ...f, [d.id]: e.target.files?.[0] ?? null }))} />
                        <button className="btn-primary py-0.5 px-2 text-[11px] whitespace-nowrap"
                          disabled={!revFiles[d.id] || reuploadDrawing.isPending}
                          onClick={() => {
                            const f = revFiles[d.id];
                            if (f) reuploadDrawing.mutate(
                              { drawingId: d.id, file: f },
                              { onSuccess: () => setRevFiles((m) => ({ ...m, [d.id]: null })) },
                            );
                          }}>
                          {t("Re-upload", "Unggah ulang")}
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="td muted">
                    {(d.decided_at || d.customer_decision_at) ? (
                      <span>
                        {new Date(d.decided_at ?? d.customer_decision_at).toLocaleDateString(locale())}
                        {d.decided_by_name && <span className="block text-[11px]">{t("by", "oleh")} {d.decided_by_name}</span>}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="td">
                    {!d.file_url ? "—"
                      : canViewDrawing ? (
                        <button type="button" onClick={() => viewFile(d.file_url)}
                           className="text-brand-700 hover:underline">{t("View", "Lihat")}</button>
                      ) : (
                        <span className="muted text-xs">{t("internal only", "hanya internal")}</span>
                      )}
                  </td>
                  <td className="td muted">
                    <div className="flex items-center justify-between gap-2">
                      <span>{d.notes ?? "—"}</span>
                      {((d.uploaded_by != null && d.uploaded_by === userId) || canApproveDrawing) && (
                        <button className="btn-ghost p-1 text-red-600 shrink-0"
                          title={t("Delete this revision", "Hapus revisi ini")}
                          disabled={deleteDrawing.isPending}
                          onClick={() => {
                            if (window.confirm(tt(
                              `Delete revision v${d.revision}? This can't be undone.`,
                              `Hapus revisi v${d.revision}? Tindakan ini tidak bisa dibatalkan.`,
                            )))
                              deleteDrawing.mutate(d.id);
                          }}>
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                  {canApproveDrawing && (
                    <td className="td text-right">
                      {d.status === "approved" ? (
                        <span className="text-emerald-700 text-xs inline-flex items-center gap-1">
                          <CheckCircle size={13} /> {t("Approved", "Disetujui")}
                        </span>
                      ) : (
                        <div className="inline-flex gap-1.5">
                          <button className="btn-primary py-1 px-2 text-xs"
                            disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ drawingId: d.id, decision: "approve" })}>
                            <CheckCircle size={13} /> {t("Approve", "Setujui")}
                          </button>
                          <button className="btn-ghost py-1 px-2 text-xs text-red-600"
                            disabled={decideDrawing.isPending}
                            onClick={() => {
                              const notes = window.prompt(tt("What needs revising? (optional)", "Apa yang perlu direvisi? (opsional)")) ?? undefined;
                              decideDrawing.mutate({ drawingId: d.id, decision: "request_revision", notes });
                            }}>
                            <XCircle size={13} /> {t("Revise", "Revisi")}
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Logistics & import documents — only meaningful once the drawing
          has been approved. Hidden before that so the project page stays
          focused on what's actually happening at the current stage.
          Also hidden from sales — this is purchasing's card. */}
      {canSeeOpsDetails && logistics && PIPELINE_STAGES.indexOf(p.status) >= PIPELINE_STAGES.indexOf("drawing_approved") && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-semibold flex items-center gap-2">
                <Truck size={15} className="text-brand-600" /> {t("Logistics & import documents", "Logistik & dokumen impor")}
              </div>
              <div className="text-xs muted">
                {t(
                  "Set after the drawing is approved. Documents are due two weeks before delivery.",
                  "Diisi setelah gambar disetujui. Dokumen jatuh tempo dua minggu sebelum pengiriman.",
                )}
              </div>
            </div>
            {logistics.docs_due && (
              <span className="chip bg-red-50 text-red-700">{t("Documents due", "Dokumen jatuh tempo")}</span>
            )}
          </div>
          <div className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">{t("Delivery mode", "Mode pengiriman")}</div>
                {canLogistics ? (
                  <select className="input" value={logistics.delivery_mode}
                    onChange={(e) => setLogistics.mutate({ delivery_mode: e.target.value })}>
                    <option value="local">{t("Local", "Lokal")}</option>
                    <option value="direct_import">{t("Direct import", "Impor langsung")}</option>
                    <option value="agent">{t("Via agent", "Lewat agen")}</option>
                  </select>
                ) : <div className="capitalize">{sl(logistics.delivery_mode, DELIVERY_MODE_LABEL_ID)}</div>}
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">{t("Estimated delivery", "Estimasi pengiriman")}</div>
                {canLogistics ? (
                  <input type="date" className="input"
                    defaultValue={logistics.est_delivery_date ?? ""}
                    onChange={(e) => e.target.value && setLogistics.mutate({ est_delivery_date: e.target.value })} />
                ) : <div>{logistics.est_delivery_date ?? "—"}</div>}
                {logistics.days_to_delivery != null && (
                  <div className="text-[11px] muted mt-0.5">{logistics.days_to_delivery} {t("day(s) to go", "hari lagi")}</div>
                )}
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">{t("Delivery date", "Tanggal pengiriman")}</div>
                {logistics.delivery_confirmed_at ? (
                  <div className="text-emerald-700 text-sm">
                    {t("Confirmed", "Dikonfirmasi")} {new Date(logistics.delivery_confirmed_at).toLocaleDateString(locale())}
                  </div>
                ) : canLogistics ? (
                  <>
                    <button className="btn-primary"
                      disabled={!logistics.est_delivery_date || !logistics.docs_approved || confirmDelivery.isPending}
                      onClick={() => confirmDelivery.mutate()}>
                      <CheckCircle size={14} /> {t("Confirm → receiving WO", "Konfirmasi → WO penerimaan")}
                    </button>
                    {!logistics.docs_approved && (
                      <div className="text-[11px] text-amber-700 mt-1">
                        {t("All documents must be director-approved first.", "Semua dokumen harus disetujui direktur dahulu.")}
                      </div>
                    )}
                  </>
                ) : <div className="muted">{t("Not confirmed", "Belum dikonfirmasi")}</div>}
              </div>
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wider muted mb-2">
                {t("Required documents", "Dokumen wajib")} ({sl(logistics.delivery_mode, DELIVERY_MODE_LABEL_ID)})
              </div>
              <div className="space-y-2">
                {(logistics.required_docs ?? []).map((d: any) => (
                  <div key={d.key} className="flex items-center gap-3 flex-wrap text-sm border-b border-ink-50 pb-2">
                    <span className="w-32 shrink-0 font-medium">{T(d.label)}</span>

                    {/* Status chip */}
                    <span className={clsx("chip text-xs",
                      d.status === "approved" ? "bg-emerald-50 text-emerald-700"
                      : d.status === "rejected" ? "bg-red-50 text-red-700"
                      : d.status === "pending" ? "bg-amber-50 text-amber-700"
                      : "bg-ink-100 text-ink-500")}>
                      {d.status ? sl(d.status, DOC_STATUS_LABEL_ID) : t("missing", "belum ada")}
                    </span>

                    {/* File: view if uploaded */}
                    {d.attachment_id && (
                      <button type="button"
                        className="text-brand-700 hover:underline text-xs"
                        onClick={() => viewFile(`/api/v1/attachments/${d.attachment_id}/download`)}>
                        {d.filename ? `${t("View", "Lihat")} (${d.filename})` : t("View", "Lihat")}
                      </button>
                    )}

                    {/* Upload / replace (purchasing/management) */}
                    {canLogistics && (
                      <label className="text-xs text-brand-700 hover:underline cursor-pointer">
                        {d.attachment_id ? t("Replace file", "Ganti file") : t("Upload file", "Unggah file")}
                        <input type="file" className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) uploadDoc.mutate({ key: d.key, file: f });
                            e.target.value = "";
                          }} />
                      </label>
                    )}

                    {/* Director approve / reject */}
                    {canApproveDrawing && d.status === "pending" && (
                      <span className="inline-flex gap-1.5 ml-auto">
                        <button className="btn-primary py-0.5 px-2 text-xs"
                          disabled={decideDoc.isPending}
                          onClick={() => decideDoc.mutate({ key: d.key, decision: "approve" })}>
                          <CheckCircle size={12} /> {t("Approve", "Setujui")}
                        </button>
                        <button className="btn-ghost py-0.5 px-2 text-xs text-red-600"
                          disabled={decideDoc.isPending}
                          onClick={() => decideDoc.mutate({ key: d.key, decision: "reject" })}>
                          <XCircle size={12} /> {t("Reject", "Tolak")}
                        </button>
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {!logistics.docs_approved && (
                <div className="text-[11px] text-amber-700 mt-2">
                  {logistics.required_docs.filter((d: any) => d.status !== "approved").length} {t("document(s) not yet approved.", "dokumen belum disetujui.")}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Operations QC — only shown once the project has reached the QC
          stage (i.e. production is done and it's time to inspect). Kept
          visible afterwards so historical qc_decision/qc_passed_at stays
          on the page. Also hidden from sales (internal ops signal). */}
      {canSeeOpsDetails && (PIPELINE_STAGES.indexOf(p.status) >= PIPELINE_STAGES.indexOf("qc") || p.qc_decision || p.qc_passed_at) && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
          <div className="font-semibold flex items-center gap-2">
            <ShieldCheck size={15} className="text-brand-600" /> {t("Quality control", "Kontrol kualitas")}
          </div>
          {p.qc_decision && (
            <span className={clsx("chip", p.qc_decision === "pass"
              ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")}>
              {p.qc_decision === "pass" ? t("QC passed", "QC lulus") : t("QC failed", "QC gagal")}
            </span>
          )}
        </div>
        <div className="p-5 space-y-3">
          {p.qc_passed_at ? (
            <div className="text-sm text-emerald-700">
              {t("Passed", "Lulus")} {new Date(p.qc_passed_at).toLocaleString(locale())}{t(
                " — finance can now issue the final invoice + delivery order.",
                " — keuangan kini dapat menerbitkan faktur final + surat jalan.",
              )}
            </div>
          ) : (
            <div className="text-sm muted">
              {t(
                "Operations checks the goods. Passing QC unlocks the final invoice + delivery order (issued by finance).",
                "Operasional memeriksa barang. Lulus QC membuka faktur final + surat jalan (diterbitkan keuangan).",
              )}
            </div>
          )}
          {p.qc_findings && (
            <div className="text-xs text-amber-700">{t("Findings:", "Temuan:")} {p.qc_findings}</div>
          )}
          {isOps && !p.qc_passed_at && (
            <div className="space-y-2">
              <textarea className="input" rows={2} placeholder={t("Findings (optional)", "Temuan (opsional)")}
                value={qcFindings} onChange={(e) => setQcFindings(e.target.value)} />
              <div className="flex gap-2">
                <button className="btn-primary" disabled={recordQC.isPending}
                  onClick={() => recordQC.mutate({ decision: "pass", findings: qcFindings || undefined })}>
                  <CheckCircle size={14} /> {t("Pass QC", "Luluskan QC")}
                </button>
                <button className="btn-ghost text-red-600" disabled={recordQC.isPending}
                  onClick={() => recordQC.mutate({ decision: "fail", findings: qcFindings || undefined })}>
                  <XCircle size={14} /> {t("Fail", "Gagalkan")}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      )}

      {/* Finance close-out: invoice + faktur pajak. Sales doesn't see
          money detail so this whole card is hidden from them. */}
      {canSeeOpsDetails && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> {t("Invoice & faktur pajak", "Faktur & faktur pajak")}
          </div>
          {p.customer_received_at && (
            <span className="chip bg-emerald-50 text-emerald-700">
              {t("Customer received", "Diterima pelanggan")} {new Date(p.customer_received_at).toLocaleDateString(locale())}
            </span>
          )}
        </div>
        <div className="p-5 space-y-4">
          {inv.length === 0 && <div className="text-sm muted">{t("No invoice issued yet.", "Belum ada faktur diterbitkan.")}</div>}
          {inv.map((iv: any) => {
            const fp = fpForm[iv.id] ?? { no: "", file: null };
            return (
              <div key={iv.id} className="border-b border-ink-50 pb-3 space-y-2">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="text-sm">
                    <span className="font-medium">{iv.number}</span>
                    {showMoney && iv.total != null && (
                      <span className="muted"> · {iv.total.toLocaleString(locale())}</span>
                    )}
                    <div className="text-[11px] muted">
                      {T("FP:")}{" "}{iv.faktur_pajak_no || "—"} ({iv.faktur_pajak_status})
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={clsx("chip text-[11px]",
                      iv.status === "approved" ? "bg-emerald-50 text-emerald-700"
                      : iv.status === "pending_finance" ? "bg-amber-50 text-amber-700"
                      : iv.status === "rejected" ? "bg-red-50 text-red-700"
                      : "bg-ink-50 text-ink-600")}>{sl(iv.status, INVOICE_STATUS_LABEL_ID)}</span>
                    {canFinanceApprove && (iv.paid_amount ?? 0) === 0 && (
                      <button
                        type="button"
                        className="btn-ghost text-red-600 text-[11px] px-2 py-0.5"
                        title={t(
                          "Delete this invoice + its faktur pajak record. Blocked if a payment has been verified.",
                          "Hapus faktur ini + catatan faktur pajaknya. Diblokir jika ada pembayaran yang sudah diverifikasi.",
                        )}
                        disabled={deleteInvoice.isPending}
                        onClick={() => {
                          const label = iv.faktur_pajak_no
                            ? `${iv.number} (FP ${iv.faktur_pajak_no})`
                            : iv.number;
                          if (window.confirm(tt(
                            `Delete ${label}? This also drops any pending payment claims and file rows tied to it. Verified payments block deletion. This can't be undone.`,
                            `Hapus ${label}? Ini juga menghapus klaim pembayaran yang menunggu dan baris file yang terkait. Pembayaran terverifikasi memblokir penghapusan. Tindakan ini tidak bisa dibatalkan.`,
                          ))) {
                            deleteInvoice.mutate(iv.id);
                          }
                        }}
                      >
                        <Trash2 size={12} /> {t("Delete", "Hapus")}
                      </button>
                    )}
                  </div>
                </div>
                {iv.status === "rejected" && iv.notes && (
                  <div className="rounded-lg border border-red-200 bg-red-50/70 px-3 py-2 text-[11px] text-red-800 whitespace-pre-wrap">
                    {iv.notes}
                  </div>
                )}
                {(iv.files ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-2 text-xs">
                    {iv.files.map((f: any) => (
                      <button key={f.id} type="button"
                        className="text-brand-700 hover:underline inline-flex items-center gap-1"
                        onClick={() => viewFile(f.download_url)}>
                        <FileText size={11} />
                        {f.kind ? `${f.kind}: ` : ""}{f.filename}
                      </button>
                    ))}
                  </div>
                )}
                {canFinanceApprove && iv.status === "pending_finance" && (
                  <div className="rounded-lg bg-ink-50/60 p-3 space-y-2">
                    <div className="text-[11px] uppercase tracking-wider muted">
                      {t(
                        "Finance approval — enter the faktur pajak yourself (admin doesn't set it)",
                        "Persetujuan keuangan — masukkan faktur pajak sendiri (admin tidak mengisinya)",
                      )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <input className="input" placeholder={t("Faktur pajak no. *", "No. faktur pajak *")}
                        value={fp.no}
                        onChange={(e) => setFpForm((m) => ({
                          ...m, [iv.id]: { ...fp, no: e.target.value },
                        }))} />
                      <input type="file"
                        className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white file:text-xs hover:file:bg-brand-700"
                        onChange={(e) => setFpForm((m) => ({
                          ...m, [iv.id]: { ...fp, file: e.target.files?.[0] ?? null },
                        }))} />
                    </div>
                    <button className="btn-primary"
                      disabled={!fp.no.trim() || approveInvoice.isPending}
                      onClick={() => approveInvoice.mutate({
                        invoiceId: iv.id, fpNo: fp.no.trim(), fpFile: fp.file,
                      })}>
                      <CheckCircle size={14} /> {t("Approve (finance)", "Setujui (keuangan)")}
                    </button>
                  </div>
                )}

                {/* Payments — record what the customer paid and see how much
                    is left. When cumulative verified ≥ invoice total, finance
                    verify auto-advances the project delivered → paid → closed.
                    Stays visible on 'partial'/'overdue' so finance can enter
                    the remaining tranches from this same card. */}
                {["approved", "issued", "partial", "overdue"].includes(iv.status) && canFinanceApprove && (
                  <div className="rounded-lg bg-ink-50/60 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="text-[11px] uppercase tracking-wider muted">
                        {t("Payments", "Pembayaran")} · {iv.claims?.length ?? 0} {t("claim(s)", "klaim")}
                      </div>
                      {showMoney && iv.total != null && (
                        <div className="text-[11px] muted tabular-nums">
                          {t("Paid", "Dibayar")} {T("Rp")}{" "}{new Intl.NumberFormat("id-ID").format(Math.round(iv.paid_amount ?? 0))}
                          {" / "}
                          <span className={clsx(
                            (iv.outstanding ?? 0) === 0 ? "text-emerald-700 font-medium" : ""
                          )}>
                            {(iv.outstanding ?? 0) === 0
                              ? t("fully paid", "lunas penuh")
                              : t(
                                  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(iv.outstanding ?? 0)) + " left",
                                  "sisa Rp " + new Intl.NumberFormat("id-ID").format(Math.round(iv.outstanding ?? 0)),
                                )}
                          </span>
                        </div>
                      )}
                    </div>
                    {(iv.claims ?? []).length > 0 && (
                      <ul className="text-[11px] space-y-1">
                        {iv.claims.map((c: any) => (
                          <li key={c.id} className="flex items-center gap-2 flex-wrap">
                            <span className={clsx("chip text-[10px]",
                              c.status === "verified" ? "bg-emerald-50 text-emerald-700"
                              : c.status === "rejected" ? "bg-red-50 text-red-700"
                              : "bg-amber-50 text-amber-700")}>{sl(c.status, CLAIM_STATUS_LABEL_ID)}</span>
                            <span className="tabular-nums font-medium">
                              {T("Rp")}{" "}{new Intl.NumberFormat("id-ID").format(Math.round(c.amount || 0))}
                            </span>
                            {c.method && <span className="muted">· {c.method}</span>}
                            {c.reference && <span className="muted">{T("· ref")}{" "}{c.reference}</span>}
                            {c.paid_at && <span className="muted">· {new Date(c.paid_at).toLocaleDateString(locale())}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                    {/* Manual entry — finance types in what landed on the bank
                        statement (for customers who pay outside the portal)
                        and it's recorded + verified in one stroke. Full
                        payment auto-advances the project to paid → closed. */}
                    {(iv.outstanding ?? 0) > 0 && (
                      <details>
                        <summary className="cursor-pointer text-brand-700 hover:underline text-[11px]">
                          {t("Enter payment manually (record & verify)", "Masukkan pembayaran manual (catat & verifikasi)")}
                        </summary>
                        {(() => {
                          const pf = payForm[iv.id] ?? {};
                          const today = new Date().toISOString().slice(0, 10);
                          return (
                            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                              <input className="input" type="number"
                                placeholder={t(
                                  `Amount (outstanding: Rp ${new Intl.NumberFormat("id-ID").format(Math.round(iv.outstanding ?? 0))})`,
                                  `Jumlah (sisa: Rp ${new Intl.NumberFormat("id-ID").format(Math.round(iv.outstanding ?? 0))})`,
                                )}
                                value={pf.amount ?? ""}
                                onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, amount: e.target.value } }))} />
                              <input className="input" type="date"
                                value={pf.paidAt ?? today}
                                onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, paidAt: e.target.value } }))} />
                              <select className="input" value={pf.method ?? "bank_transfer"}
                                onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, method: e.target.value } }))}>
                                <option value="bank_transfer">{t("Bank transfer", "Transfer bank")}</option>
                                <option value="cash">{t("Cash", "Tunai")}</option>
                                <option value="cheque">{t("Cheque", "Cek")}</option>
                                <option value="other">{t("Other", "Lainnya")}</option>
                              </select>
                              <input className="input"
                                placeholder={t("Reference (transfer no., cheque no., etc.)", "Referensi (no. transfer, no. cek, dll.)")}
                                value={pf.reference ?? ""}
                                onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, reference: e.target.value } }))} />
                              <input className="input sm:col-span-2"
                                placeholder={t("Notes (optional)", "Catatan (opsional)")}
                                value={pf.notes ?? ""}
                                onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, notes: e.target.value } }))} />
                              <label className="sm:col-span-2 text-[11px] text-ink-600 flex items-center gap-2">
                                {t("Proof of payment (optional):", "Bukti pembayaran (opsional):")}
                                <input type="file"
                                  onChange={(e) => setPayForm((m) => ({ ...m, [iv.id]: { ...pf, file: e.target.files?.[0] ?? null } }))} />
                              </label>
                              <button className="btn-primary sm:col-span-2"
                                disabled={!pf.amount || Number(pf.amount) <= 0 || recordManualPayment.isPending}
                                onClick={() => recordManualPayment.mutate(
                                  {
                                    invoiceId: iv.id,
                                    amount: Number(pf.amount),
                                    paidAt: pf.paidAt || today,
                                    method: pf.method || "bank_transfer",
                                    reference: pf.reference,
                                    notes: pf.notes,
                                    file: pf.file,
                                  },
                                  { onSuccess: () => setPayForm((m) => ({ ...m, [iv.id]: {} })) },
                                )}>
                                {t("Record & verify payment", "Catat & verifikasi pembayaran")}
                              </button>
                              {Number(pf.amount) > 0 && Number(pf.amount) < (iv.outstanding ?? 0) && (
                                <div className="sm:col-span-2 text-[11px] text-amber-700">
                                  {t(
                                    "Partial payment — the invoice stays open with Rp ",
                                    "Pembayaran sebagian — faktur tetap terbuka dengan sisa Rp ",
                                  )}
                                  {new Intl.NumberFormat("id-ID").format(Math.round((iv.outstanding ?? 0) - Number(pf.amount)))}{t(" remaining.", ".")}
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </details>
                    )}
                  </div>
                )}

                {/* Per-invoice discussion. Finance queries usually concern one
                    invoice, not the whole project, and @mention can pull in
                    whoever raised it. */}
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-brand-700 select-none">
                    {t("Discussion", "Diskusi")}
                  </summary>
                  <div className="mt-2">
                    <CommentThread
                      ownerType="invoice"
                      ownerId={iv.id}
                      title={`${t("Invoice", "Faktur")} ${iv.number ?? ""}`.trim()}
                    />
                  </div>
                </details>
              </div>
            );
          })}

          {canFinanceApprove && (
            <div className="rounded-lg bg-ink-50/60 p-3 space-y-2">
              <div className="text-[11px] uppercase tracking-wider muted">
                {t("Issue invoice", "Terbitkan faktur")} {invType === "final" ? t("+ delivery order", "+ surat jalan") : t("(down-payment)", "(down payment/DP)")}
              </div>
              <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
                {([
                  ["dp", t("Down payment (before delivery)", "Down payment (sebelum pengiriman)")],
                  ["final", t("Final invoice (after delivery)", "Faktur final (setelah pengiriman)")],
                ] as ["dp" | "final", string][]).map(([k, label]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setInvType(k)}
                    className={clsx(
                      "px-3 py-1 rounded-md text-xs font-medium",
                      invType === k ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
                    )}
                  >
                    {T(label)}
                  </button>
                ))}
              </div>
              {invType === "final" && !p.qc_passed_at && (
                <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  {t(
                    "Final invoice can only be issued after QC has passed. Use \"Down payment\" to bill before delivery, or wait for QC.",
                    "Faktur final hanya bisa diterbitkan setelah QC lulus. Gunakan \"Down payment\" untuk menagih sebelum pengiriman, atau tunggu QC.",
                  )}
                </div>
              )}
              <div className={clsx(
                "grid grid-cols-1 gap-2",
                invType === "final" ? "sm:grid-cols-3" : "sm:grid-cols-2",
              )}>
                <input className="input" placeholder={t("Amount (blank = quotation total)", "Jumlah (kosong = total penawaran)")}
                  value={invAmount} onChange={(e) => setInvAmount(e.target.value)} />
                <label className="block">
                  <span className="block text-[10px] muted mb-1">{t("Invoice file", "File faktur")}</span>
                  <input type="file"
                    className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-ink-700 file:text-xs hover:file:bg-ink-200"
                    onChange={(e) => setInvFile(e.target.files?.[0] ?? null)} />
                </label>
                {invType === "final" && (
                  <label className="block">
                    <span className="block text-[10px] muted mb-1">{t("Delivery-order file", "File surat jalan")}</span>
                    <input type="file"
                      className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-ink-700 file:text-xs hover:file:bg-ink-200"
                      onChange={(e) => setDoFile(e.target.files?.[0] ?? null)} />
                  </label>
                )}
              </div>
              <p className="text-[11px] muted">
                {t(
                  "Finance uploads the invoice here. Faktur pajak number is entered by finance again during the approval step, not on upload.",
                  "Keuangan mengunggah faktur di sini. Nomor faktur pajak diisi keuangan lagi pada langkah persetujuan, bukan saat unggah.",
                )}
              </p>
              <button className="btn-primary"
                disabled={
                  issueInvoice.isPending
                  || (invType === "final" && !p.qc_passed_at)
                }
                onClick={() => issueInvoice.mutate(
                  {
                    amount: invAmount ? Number(invAmount) : undefined,
                    invoiceFile: invFile,
                    doFile: invType === "final" ? doFile : null,
                    invoiceType: invType,
                  },
                  { onSuccess: () => { setInvAmount(""); setInvFile(null); setDoFile(null); } },
                )}>
                <FileText size={14} />
                {invType === "dp" ? t("Issue DP invoice", "Terbitkan faktur DP") : t("Issue invoice + DO", "Terbitkan faktur + DO")}
              </button>
            </div>
          )}

          {isAdmin && !p.customer_received_at && inv.some((iv: any) => iv.status === "approved") && (
            <button className="btn-ghost" disabled={customerReceived.isPending}
              onClick={() => customerReceived.mutate()}>
              <CheckCircle size={14} /> {t("Confirm customer received", "Konfirmasi pelanggan menerima")}
            </button>
          )}
        </div>
      </div>
      )}

      {/* Deliveries — ops-internal, hidden from sales */}
      {canSeeOpsDetails && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Truck size={15} className="text-brand-600" /> {t("Deliveries", "Pengiriman")}
          </div>
          <div className="text-xs muted">{dos.length} {t("shipment(s)", "kiriman")}</div>
        </div>
        {dos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">{t("No deliveries yet.", "Belum ada pengiriman.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("DO")}</th>
                <th className="th">{t("Split", "Bagian")}</th>
                <th className="th">{t("Courier", "Kurir")}</th>
                <th className="th">{t("Tracking", "Resi")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{t("Actions", "Aksi")}</th>
              </tr>
            </thead>
            <tbody>
              {dos.map((d: any) => {
                const proof = doProof[d.id] ?? {};
                const isDirector = role === "director";
                const isVerified = !!d.verified_at;
                const isDelivered = d.status === "delivered";
                return (
                  <tr key={d.id} className="border-t border-ink-100 align-top">
                    <td className="td font-mono text-xs">{d.number}</td>
                    <td className="td muted">#{d.split_index}</td>
                    <td className="td">{d.courier ?? "—"}</td>
                    <td className="td font-mono text-xs">{d.tracking_no ?? "—"}</td>
                    <td className="td space-y-1">
                      <span className={clsx("chip capitalize",
                        isDelivered ? "bg-emerald-50 text-emerald-700"
                        : isVerified ? "bg-cyan-50 text-cyan-700"
                        : (d.files ?? []).length > 0 ? "bg-amber-50 text-amber-700"
                        : "bg-ink-100 text-ink-700"
                      )}>
                        {isDelivered ? t("delivered", "terkirim")
                          : isVerified ? t("verified", "terverifikasi")
                          : (d.files ?? []).length > 0 ? t("awaiting verify", "menunggu verifikasi")
                          : t("pending", "menunggu")}
                      </span>
                      {isVerified && (
                        <div className="text-[10px] muted">
                          {t("verified", "diverifikasi")} {new Date(d.verified_at).toLocaleDateString(locale())}
                          {d.verified_by_name && <> {t("by", "oleh")} {d.verified_by_name}</>}
                        </div>
                      )}
                      {(d.files ?? []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5 text-[11px]">
                          {d.files.map((f: any) => (
                            <button key={f.id} type="button"
                              className="text-brand-700 hover:underline inline-flex items-center gap-0.5"
                              onClick={() => viewFile(f.download_url)}>
                              <FileText size={10} /> {f.filename}
                            </button>
                          ))}
                        </div>
                      )}
                      {isAdmin && !isDelivered && (
                        <details className="text-[11px]">
                          <summary className="cursor-pointer text-brand-700 hover:underline">
                            {(d.files ?? []).length > 0 ? t("Replace proof", "Ganti bukti") : t("Upload proof", "Unggah bukti")}
                          </summary>
                          <div className="mt-1.5 space-y-1.5 bg-ink-50/60 p-2 rounded">
                            <input type="file"
                              className="block w-full text-[11px] file:mr-1.5 file:rounded file:border-0 file:bg-ink-100 file:px-1.5 file:py-0.5 file:text-[11px]"
                              onChange={(e) => setDoProof((m) => ({
                                ...m, [d.id]: { ...proof, file: e.target.files?.[0] ?? null },
                              }))} />
                            <input className="input text-[11px] py-1"
                              placeholder={t("Courier (optional)", "Kurir (opsional)")}
                              defaultValue={d.courier ?? ""}
                              onChange={(e) => setDoProof((m) => ({
                                ...m, [d.id]: { ...proof, courier: e.target.value },
                              }))} />
                            <input className="input text-[11px] py-1"
                              placeholder={t("Tracking no. (optional)", "No. resi (opsional)")}
                              defaultValue={d.tracking_no ?? ""}
                              onChange={(e) => setDoProof((m) => ({
                                ...m, [d.id]: { ...proof, tracking: e.target.value },
                              }))} />
                            <button className="btn-primary py-0.5 px-2 text-[11px]"
                              disabled={!proof.file || uploadDeliveryProof.isPending}
                              onClick={() => proof.file && uploadDeliveryProof.mutate(
                                { doId: d.id, file: proof.file,
                                  courier: proof.courier, tracking: proof.tracking },
                                { onSuccess: () => setDoProof((m) => ({ ...m, [d.id]: {} })) },
                              )}>
                              {t("Upload — director will verify", "Unggah — direktur akan verifikasi")}
                            </button>
                          </div>
                        </details>
                      )}
                    </td>
                    <td className="td text-right">
                      {isDelivered ? null
                        : isDirector ? (
                          // Director can both verify and mark delivered. Their
                          // single click does both when no verification exists yet.
                          <button className="btn-primary py-1 px-2 text-xs"
                            disabled={markDelivered.isPending || verifyDelivery.isPending}
                            onClick={() => markDelivered.mutate(d.id)}>
                            <CheckCircle size={13} />
                            {isVerified ? t("Mark delivered", "Tandai terkirim") : t("Verify & mark delivered", "Verifikasi & tandai terkirim")}
                          </button>
                        ) : isVerified ? (
                          <button className="btn-ghost text-emerald-700"
                            disabled={markDelivered.isPending}
                            onClick={() => markDelivered.mutate(d.id)}>
                            <CheckCircle size={13} /> {t("Mark delivered", "Tandai terkirim")}
                          </button>
                        ) : (d.files ?? []).length === 0 ? (
                          // No proof uploaded yet — admin's next step is upload.
                          <span className="muted text-xs">{t("Upload proof to proceed", "Unggah bukti untuk lanjut")}</span>
                        ) : (
                          // Proof is in; just waiting on director to verify.
                          <span className="chip bg-amber-50 text-amber-700 text-[11px]">
                            {t("Awaiting director verification", "Menunggu verifikasi direktur")}
                          </span>
                        )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Invoices list — same audience as the finance close-out card,
          hidden from sales. */}
      {canSeeOpsDetails && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> {t("Invoices", "Faktur")}
          </div>
          <div className="text-xs muted">{inv.length} {t("invoice(s)", "faktur")}</div>
        </div>
        {inv.length === 0 ? (
          <div className="p-8 text-center muted text-sm">{t("No invoices yet.", "Belum ada faktur.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{t("Type", "Tipe")}</th>
                <th className="th">{t("Due", "Jatuh tempo")}</th>
                <th className="th">{T("Status")}</th>
                {showMoney && <th className="th text-right">{T("Total")}</th>}
              </tr>
            </thead>
            <tbody>
              {inv.map((i: any) => (
                <tr key={i.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{i.number}</td>
                  <td className="td capitalize">{i.type}{i.termin_index ? ` #${i.termin_index}` : ""}</td>
                  <td className="td muted">{i.due_date ?? "—"}</td>
                  <td className="td"><span className="chip bg-ink-100 text-ink-700">{sl(i.status, INVOICE_STATUS_LABEL_ID)}</span></td>
                  {showMoney && (
                    <td className="td text-right font-medium tabular-nums">{idr(i.total)}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Supplier POs — customer/supplier mapping is kept private from sales. */}
      {canSeeOpsDetails && (
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-end justify-between gap-3 flex-wrap">
          <div>
            <div className="font-semibold flex items-center gap-2">
              <Truck size={15} className="text-brand-600" /> {t("Supplier purchase orders", "Purchase order ke supplier")}
            </div>
            <div className="text-xs muted">{supplierPOs.length} {t("PO(s) for this project", "PO untuk proyek ini")}</div>
          </div>
          <Link to="/purchase-orders" className="text-xs text-brand-700 hover:underline">
            {t("Open Purchasing PO →", "Buka PO Pembelian →")}
          </Link>
        </div>
        {supplierPOs.length === 0 ? (
          <div className="p-8 text-center muted text-sm">{t("No supplier POs yet for this project.", "Belum ada PO supplier untuk proyek ini.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{T("Supplier")}</th>
                <th className="th">{t("PO date", "Tanggal PO")}</th>
                <th className="th">{t("Lead", "Lead")}</th>
                <th className="th">{T("Status")}</th>
                {showMoney && <th className="th text-right">{T("Total")}</th>}
              </tr>
            </thead>
            <tbody>
              {supplierPOs.map((po: any) => (
                <tr key={po.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">
                    <Link to={`/purchase-orders/${po.id}`} className="text-brand-700 hover:underline">
                      {po.number}
                    </Link>
                  </td>
                  <td className="td">{po.supplier_name ?? "—"}</td>
                  <td className="td muted">{po.po_date ? new Date(po.po_date).toLocaleDateString(locale()) : "—"}</td>
                  <td className="td muted">{po.quoted_lead_days != null ? `${po.quoted_lead_days}d` : "—"}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      po.status === "open" ? "bg-emerald-50 text-emerald-700"
                      : po.status === "received" ? "bg-cyan-50 text-cyan-700"
                      : po.status === "pending_approval" ? "bg-amber-50 text-amber-700"
                      : po.status === "cancelled" ? "bg-red-50 text-red-700"
                      : "bg-ink-100 text-ink-700")}>
                      {sl(po.status ?? "", SUPPLIER_PO_STATUS_LABEL_ID)}
                    </span>
                  </td>
                  {showMoney && (
                    <td className="td text-right tabular-nums">
                      {po.total != null ? "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(po.total)) : "—"}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Legacy purchase requests (only when present — inventory-side flow).
          Hidden from sales alongside the other purchasing internals. */}
      {canSeeOpsDetails && prs.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <ShoppingCart size={15} className="text-brand-600" /> {t("Purchase requests", "Permintaan pembelian")}
            </div>
            <div className="text-xs muted">{prs.length} {t("PR(s) (legacy / inventory-raised)", "PR (lama / dari inventori)")}</div>
          </div>
          <ul className="divide-y divide-ink-100">
            {prs.map((pr: any) => (
              <li key={pr.id} className="p-3 flex items-center gap-3">
                <span className="font-mono text-xs">{pr.number}</span>
                <span className="chip bg-ink-100 text-ink-700">{pr.status}</span>
                <span className="text-xs muted">{(pr.items ?? []).length} {t("item(s)", "item")}</span>
                <span className="ml-auto text-[11px] text-ink-400">
                  {new Date(pr.created_at).toLocaleDateString(locale())}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Attachments */}
      <AttachmentsSection ownerType="project" ownerId={p.id} />

      {/* Discussion — @mention pulls in anyone, including staff who can't
          open this project. */}
      <CommentThread
        ownerType="project"
        ownerId={p.id}
        title={t("Discussion", "Diskusi")}
      />
    </div>
  );
}

function Field({ icon, label, children }: {
  icon?: React.ReactNode; label: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {T(label)}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}

function EditableTextField({
  label, icon, value, disabled, placeholder, onCommit,
}: {
  label: string;
  icon?: React.ReactNode;
  value: string;
  disabled?: boolean;
  placeholder?: string;
  onCommit: (v: string) => void;
}) {
  // Local draft so typing doesn't fire a PATCH per keystroke. Commits on
  // blur (the natural "I'm done editing" moment) and on Enter; Escape
  // reverts to whatever the parent last passed in. The useEffect keeps
  // the draft in sync if the server-side value changes from outside
  // (refetch after a PATCH, or another user's edit).
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {T(label)}
      </div>
      <input
        type="text"
        value={draft}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onCommit(draft)}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
          if (e.key === "Escape") {
            setDraft(value);
            (e.currentTarget as HTMLInputElement).blur();
          }
        }}
        className="mt-1 w-full bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm py-0.5 px-0 disabled:opacity-50"
      />
    </div>
  );
}

function EditableDateField({
  label, icon, value, disabled, onChange, readOnly, readOnlyHint,
}: {
  label: string;
  icon?: React.ReactNode;
  value: string;
  disabled?: boolean;
  onChange: (v: string) => void;
  /** Show the date, don't offer to change it. Used where the role may see a
   *  date but is not the one who sets it — the backend refuses those writes,
   *  and an input that 403s reads as a broken page rather than a rule. */
  readOnly?: boolean;
  readOnlyHint?: string;
}) {
  // The PATCH endpoint refuses to wipe a date when null is sent — once a
  // date is set, the user can change it but not clear it from this field.
  // Editing fires onChange only on a real value to keep semantics matching
  // the backend's "protected date fields" rule.
  if (readOnly) {
    return (
      <div>
        <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
          {icon} {T(label)}
        </div>
        <div className="mt-1 text-sm text-ink-900 py-0.5">{value || "—"}</div>
        {readOnlyHint && (
          <div className="text-[10px] muted mt-0.5">{readOnlyHint}</div>
        )}
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {T(label)}
      </div>
      <input
        type="date"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm py-0.5 px-0 cursor-pointer disabled:opacity-50"
      />
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
        {T(label)}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
