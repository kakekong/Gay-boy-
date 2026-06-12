import { useState, useEffect } from "react";
import {
  Map, ChevronRight, User, ShoppingCart, HardHat, UserCog, BarChart3, Crown,
  Building2, Factory, BookOpen, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/auth";
import { useT } from "@/store/lang";

type RoleKey =
  | "sales" | "purchasing" | "hr" | "admin" | "manager" | "director"
  | "customer" | "supplier";

interface Step {
  title: string;
  title_id: string;
  detail?: string;
  detail_id?: string;
}
interface ButtonRef {
  page: string;
  page_id: string;
  button: string;
  button_id: string;
  effect: string;
  effect_id: string;
}
interface RoleSection {
  key: RoleKey;
  label: string;
  label_id: string;
  emoji: string;
  Icon: any;
  blurb: string;
  blurb_id: string;
  daily: string;
  daily_id: string;
  flow: Step[];
  buttons: ButtonRef[];
  rules: string[];
  rules_id: string[];
}

const ROLES: RoleSection[] = [
  {
    key: "sales",
    label: "Sales",
    label_id: "Sales",
    emoji: "👤",
    Icon: User,
    blurb: "You own customer relationships from first hello to deal won.",
    blurb_id: "Anda yang memegang hubungan pelanggan dari sapaan pertama sampai deal menang.",
    daily:
      "Every morning: clear the notifications bell, glance at the pipeline, " +
      "tick any overdue stage-checklist items. That's your 5-minute warm-up.",
    daily_id:
      "Setiap pagi: bersihkan lonceng notifikasi, lihat pipeline sekilas, " +
      "centang tugas tahap yang telat. Pemanasan 5 menit Anda.",
    flow: [
      { title: "New inquiry comes in", title_id: "Pertanyaan baru masuk",
        detail: "WhatsApp, email, or referral", detail_id: "WhatsApp, email, atau referensi" },
      { title: "+ New customer", title_id: "+ Pelanggan baru",
        detail: "3-step wizard: basics → PICs (WhatsApp/email/details) → tax info (NPWP/PKP)",
        detail_id: "Wizard 3 langkah: data dasar → PIC (WhatsApp/email/detail) → data pajak (NPWP/PKP)" },
      { title: "Tick first-contact + qualify-need", title_id: "Centang kontak pertama + kualifikasi kebutuhan",
        detail: "Stage checklist on the customer page", detail_id: "Checklist tahap di halaman pelanggan" },
      { title: "Click 'Advance to Presentation'", title_id: "Klik 'Lanjut ke Presentasi'",
        detail: "→ amber banner: sent to director for approval. Once approved, send deck.",
        detail_id: "→ banner kuning: dikirim ke direktur untuk persetujuan. Setelah disetujui, kirim deck." },
      { title: "Click 'Advance to Quotation' (director approves)", title_id: "Klik 'Lanjut ke Penawaran' (direktur menyetujui)",
        detail: "Then open the customer → + New quotation. Pick the PIC it's addressed to.",
        detail_id: "Buka pelanggan → + Penawaran baru. Pilih PIC yang dituju." },
      { title: "Submit quotation → director approves", title_id: "Kirim penawaran → direktur menyetujui",
        detail: "EVERY quotation now needs director sign-off in /approvals before it can be sent.",
        detail_id: "SETIAP penawaran sekarang wajib persetujuan direktur di /approvals sebelum bisa dikirim." },
      { title: "Mark deal Won", title_id: "Tandai deal Menang",
        detail: "No project yet — the quote just flips to Won.",
        detail_id: "Belum ada proyek — penawaran hanya berubah jadi Menang." },
      { title: "Customer sends their signed PO → Submit customer PO", title_id: "Pelanggan kirim PO tertanda → Kirim PO pelanggan",
        detail: "On the quote's 'Next step' card: attach the PO file, pick which line items they actually ordered, set the PO number.",
        detail_id: "Di kartu 'Langkah berikutnya' pada penawaran: lampirkan file PO, pilih item yang benar-benar dipesan, isi nomor PO." },
      { title: "Director approves the customer PO → project is created", title_id: "Direktur menyetujui PO pelanggan → proyek terbentuk",
        detail: "The project carries the PO number, date and value automatically.",
        detail_id: "Proyek otomatis mewarisi nomor PO, tanggal, dan nilai." },
    ],
    buttons: [
      { page: "Customers", page_id: "Pelanggan", button: "+ New customer", button_id: "+ Pelanggan baru",
        effect: "3-step wizard (basics / PICs / tax)", effect_id: "Wizard 3 langkah (data dasar / PIC / pajak)" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Advance to …", button_id: "Lanjut ke …",
        effect: "Request a stage move (director approves)", effect_id: "Minta pindah tahap (direktur menyetujui)" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Log activity", button_id: "Catat aktivitas",
        effect: "Record a call or WhatsApp", effect_id: "Catat telepon atau WhatsApp" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "AI suggest", button_id: "Saran AI",
        effect: "Generate a Bahasa Indonesia follow-up", effect_id: "Buat tindak lanjut dalam Bahasa Indonesia" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Stage checklist circle", button_id: "Lingkaran checklist tahap",
        effect: "Tick required actions off", effect_id: "Centang aksi wajib" },
      { page: "Quotation page", page_id: "Halaman penawaran", button: "Submit", button_id: "Kirim",
        effect: "Send to director for approval (always)", effect_id: "Kirim ke direktur untuk persetujuan (selalu)" },
      { page: "Quotation page (Won)", page_id: "Halaman penawaran (Menang)", button: "Submit customer PO", button_id: "Kirim PO pelanggan",
        effect: "File the customer's PO → director approval → project", effect_id: "Daftarkan PO pelanggan → persetujuan direktur → proyek" },
      { page: "Customer PO", page_id: "PO Pelanggan", button: "(sidebar, Workspace)", button_id: "(sidebar, Ruang kerja)",
        effect: "Track the POs you've filed and their status", effect_id: "Pantau PO yang Anda daftarkan dan statusnya" },
      { page: "Notifications bell", page_id: "Lonceng notifikasi", button: "Any item", button_id: "Item apa saja",
        effect: "Jump to whatever needs you", effect_id: "Lompat ke apa pun yang butuh Anda" },
    ],
    rules: [
      "You can only edit customers assigned to you (sales PIC).",
      "EVERY quotation needs director approval before it leaves draft — there's no more discount-based auto-approve.",
      "A project is NOT created when you mark a quote Won. You file the customer's PO (with the PO file + ordered items), and the director's approval of that PO is what spawns the project.",
      "When the customer only orders some of the quoted items, untick the rest in the Submit-customer-PO modal and edit prices if they negotiated.",
      "Every stage move needs the director's approval — the customer stays on the old stage until they click Approve in /approvals.",
      "Overdue stage tasks light up the bell and the calendar in red.",
    ],
    rules_id: [
      "Anda hanya bisa mengedit pelanggan yang ditugaskan kepada Anda (sales PIC).",
      "SETIAP penawaran wajib persetujuan direktur sebelum keluar dari draft — tidak ada lagi auto-approve berdasarkan diskon.",
      "Proyek TIDAK terbentuk saat Anda menandai penawaran Menang. Anda mendaftarkan PO pelanggan (dengan file PO + item yang dipesan), dan persetujuan direktur atas PO itulah yang membentuk proyek.",
      "Kalau pelanggan hanya pesan sebagian item dari penawaran, hilangkan centang yang tidak dipesan di modal Kirim-PO-pelanggan, dan edit harga kalau ada negosiasi.",
      "Setiap pindah tahap butuh persetujuan direktur — pelanggan tetap di tahap lama sampai direktur klik Setujui di /approvals.",
      "Tugas tahap yang telat akan menyala merah di lonceng dan kalender.",
    ],
  },
  {
    key: "purchasing",
    label: "Purchasing",
    label_id: "Pembelian",
    emoji: "📦",
    Icon: ShoppingCart,
    blurb:
      "You curate the vendor list. You don't create POs — that's the " +
      "director (keeps supplier ↔ customer mappings private).",
    blurb_id:
      "Anda mengurus daftar vendor. Anda tidak membuat PO — itu tugas direktur " +
      "(menjaga pemetaan supplier ↔ pelanggan tetap rahasia).",
    daily:
      "When the director asks for a new supplier, add them. Keep ratings " +
      "and lead times accurate so the AI can recommend the best vendor.",
    daily_id:
      "Kalau direktur minta supplier baru, tambahkan. Jaga rating dan lead " +
      "time tetap akurat supaya AI bisa merekomendasikan vendor terbaik.",
    flow: [
      { title: "Director needs a vendor", title_id: "Direktur butuh vendor",
        detail: "Asks you to add them", detail_id: "Minta Anda menambahkannya" },
      { title: "Open Purchasing page", title_id: "Buka halaman Pembelian" },
      { title: "+ New supplier", title_id: "+ Supplier baru",
        detail: "Name, category, initial rating, contact PIC",
        detail_id: "Nama, kategori, rating awal, PIC kontak" },
      { title: "Click a supplier row → supplier detail", title_id: "Klik baris supplier → detail supplier",
        detail: "See rating, lead time, QC fail %, and every PO issued to them",
        detail_id: "Lihat rating, lead time, % gagal QC, dan setiap PO yang diterbitkan ke mereka" },
      { title: "Director issues the supplier PO", title_id: "Direktur menerbitkan PO supplier",
        detail: "(out of your hands — director links supplier + project)",
        detail_id: "(di luar tangan Anda — direktur yang menghubungkan supplier + proyek)" },
      { title: "Supplier portal lights up", title_id: "Portal supplier menyala",
        detail: "Supplier uploads drawing, sets ETA", detail_id: "Supplier unggah gambar, isi ETA" },
      { title: "Customer sees forecast instantly", title_id: "Pelanggan langsung lihat perkiraan" },
    ],
    buttons: [
      { page: "Purchasing", page_id: "Pembelian", button: "+ New supplier", button_id: "+ Supplier baru",
        effect: "Add a vendor", effect_id: "Tambah vendor" },
      { page: "Purchasing (supplier row)", page_id: "Pembelian (baris supplier)", button: "Click row", button_id: "Klik baris",
        effect: "Open the supplier detail page + PO history", effect_id: "Buka halaman detail supplier + riwayat PO" },
      { page: "Purchasing board", page_id: "Papan Pembelian", button: "Stage cards", button_id: "Kartu tahap",
        effect: "PR / RFQ / GR / QC explain each procurement step; Supplier PO opens the PO list",
        effect_id: "PR / RFQ / GR / QC menjelaskan tiap langkah pembelian; PO Supplier membuka daftar PO" },
    ],
    rules: [
      "You can see the supplier directory and each supplier's PO history, but only the director can issue a supplier PO.",
      "Keep rating + lead-time fresh; the AI vendor-picker uses both.",
    ],
    rules_id: [
      "Anda bisa lihat direktori supplier dan riwayat PO tiap supplier, tapi hanya direktur yang bisa menerbitkan PO supplier.",
      "Jaga rating + lead time tetap segar; pemilih vendor AI memakai keduanya.",
    ],
  },
  {
    key: "hr",
    label: "HR",
    label_id: "HR",
    emoji: "🛠",
    Icon: HardHat,
    blurb: "Employee directory, tags, attendance, and feeding payroll.",
    blurb_id: "Direktori karyawan, tag, absensi, dan menyuplai data ke payroll.",
    daily:
      "Every day glance at the Attendance page to fix wrongly-marked absences. " +
      "On the 1st of the month, sweep for anyone with a red missed-days chip.",
    daily_id:
      "Setiap hari lihat halaman Absensi untuk perbaiki tanda alpa yang salah. " +
      "Tanggal 1 tiap bulan, sapu siapa saja yang punya chip merah hari-bolos.",
    flow: [
      { title: "Day 1 of the month", title_id: "Tanggal 1 setiap bulan",
        detail: "Open Employees", detail_id: "Buka Karyawan" },
      { title: "Anyone joined? → Admin → Users → New user", title_id: "Ada yang masuk? → Admin → Pengguna → Pengguna baru" },
      { title: "Anyone left? → deactivate their account", title_id: "Ada yang keluar? → nonaktifkan akunnya" },
      { title: "Daily: Attendance → spot wrong Absent marks → fix", title_id: "Harian: Absensi → temukan tanda Alpa salah → perbaiki" },
      { title: "End of month: scan missed-days chips", title_id: "Akhir bulan: pindai chip hari-bolos" },
      { title: "Tell the director who to deduct", title_id: "Beri tahu direktur siapa yang dipotong" },
    ],
    buttons: [
      { page: "Employees", page_id: "Karyawan", button: "+ Manage tags", button_id: "+ Kelola tag",
        effect: "Create / rename labels", effect_id: "Buat / ganti nama label" },
      { page: "Employee card", page_id: "Kartu karyawan", button: "(missed-days chip)", button_id: "(chip hari-bolos)",
        effect: "Quick attendance read", effect_id: "Baca absensi cepat" },
      { page: "Employee profile", page_id: "Profil karyawan", button: "Attendance card → month picker", button_id: "Kartu Absensi → pemilih bulan",
        effect: "Pull any month", effect_id: "Tarik bulan apa saja" },
      { page: "Attendance", page_id: "Absensi", button: "+ Manual entry", button_id: "+ Entri manual",
        effect: "Fix wrong clock-in / add leave", effect_id: "Perbaiki clock-in salah / tambah cuti" },
    ],
    rules: [
      "Yellow chip = 1–2 missed days; red chip = 3+. Red usually means a payroll conversation.",
      "Tags like 'Top performer' or 'Mining specialist' make filtering faster.",
    ],
    rules_id: [
      "Chip kuning = 1–2 hari bolos; chip merah = 3+. Merah biasanya berarti perlu bicara payroll.",
      "Tag seperti 'Top performer' atau 'Spesialis tambang' bikin penyaringan lebih cepat.",
    ],
  },
  {
    key: "admin",
    label: "Admin",
    label_id: "Admin",
    emoji: "🧑‍💼",
    Icon: UserCog,
    blurb:
      "Data hygiene. You can edit any customer, but big changes route " +
      "through the manager for approval.",
    blurb_id:
      "Kebersihan data. Anda bisa mengedit pelanggan mana saja, tapi perubahan " +
      "besar diteruskan ke manajer untuk persetujuan.",
    daily: "Maintain inventory counts and chart-of-accounts. Verify payment claims when they come in.",
    daily_id: "Jaga stok inventaris dan bagan akun. Verifikasi klaim pembayaran saat masuk.",
    flow: [
      { title: "Open Customers → spot stale data", title_id: "Buka Pelanggan → temukan data basi" },
      { title: "Small fix?", title_id: "Perbaikan kecil?",
        detail: "Edit → auto-saves", detail_id: "Edit → tersimpan otomatis" },
      { title: "Big change?", title_id: "Perubahan besar?",
        detail: "Name, terms, owner → goes to Manager for approval",
        detail_id: "Nama, syarat, pemilik → masuk ke Manajer untuk disetujui" },
      { title: "Inventory → Adjust stock if needed", title_id: "Inventaris → Sesuaikan stok kalau perlu" },
      { title: "Chart of Accounts → add new accounts as the business grows", title_id: "Bagan Akun → tambah akun baru seiring bisnis berkembang" },
      { title: "Payment verification → match received money to invoices", title_id: "Verifikasi Pembayaran → cocokkan uang masuk dengan faktur" },
    ],
    buttons: [
      { page: "Customers", page_id: "Pelanggan", button: "(any field)", button_id: "(field apa saja)",
        effect: "Small fixes save instantly, big ones request approval",
        effect_id: "Perbaikan kecil langsung simpan, yang besar minta persetujuan" },
      { page: "Inventory", page_id: "Inventaris", button: "Adjust", button_id: "Sesuaikan",
        effect: "Correct stock counts", effect_id: "Koreksi jumlah stok" },
      { page: "Chart of Accounts", page_id: "Bagan Akun", button: "+ Add account", button_id: "+ Tambah akun",
        effect: "New ledger account", effect_id: "Akun ledger baru" },
      { page: "Payment verification", page_id: "Verifikasi Pembayaran", button: "Verify / Reject", button_id: "Verifikasi / Tolak",
        effect: "Settle a customer payment", effect_id: "Selesaikan pembayaran pelanggan" },
    ],
    rules: [
      "You see all customers, but mutating 'important' fields creates an Approval Request.",
      "Adjusting stock writes an audit trail — corrections are visible to the director.",
    ],
    rules_id: [
      "Anda lihat semua pelanggan, tapi mengubah field 'penting' akan membuat Permintaan Persetujuan.",
      "Penyesuaian stok mencatat jejak audit — koreksinya bisa dilihat direktur.",
    ],
  },
  {
    key: "manager",
    label: "Manager",
    label_id: "Manajer",
    emoji: "📊",
    Icon: BarChart3,
    blurb: "Unblock sales by reviewing approvals; watch team performance.",
    blurb_id: "Lancarkan sales dengan meninjau persetujuan; pantau performa tim.",
    daily:
      "Open Approvals first thing in the morning. Then Executive Dashboard — " +
      "ping anyone whose deal looks stuck.",
    daily_id:
      "Pagi-pagi buka Persetujuan. Lalu Dasbor Eksekutif — " +
      "hubungi siapa pun yang deal-nya terlihat macet.",
    flow: [
      { title: "Open Approvals page", title_id: "Buka halaman Persetujuan" },
      { title: "Any pending? Read each request", title_id: "Ada yang menunggu? Baca tiap permintaan" },
      { title: "Looks right → Approve", title_id: "Terlihat benar → Setujui",
        detail: "Looks off → Reject with reason", detail_id: "Terlihat janggal → Tolak dengan alasan" },
      { title: "Open Executive Dashboard", title_id: "Buka Dasbor Eksekutif" },
      { title: "At-Risk Deals → ping the sales person", title_id: "Deal Berisiko → hubungi sales-nya" },
      { title: "Top Priority Actions → assign", title_id: "Aksi Prioritas Utama → tugaskan" },
    ],
    buttons: [
      { page: "Approvals", page_id: "Persetujuan", button: "Approve / Reject", button_id: "Setujui / Tolak",
        effect: "Unblock or reject a sales request", effect_id: "Lancarkan atau tolak permintaan sales" },
      { page: "Executive Dashboard", page_id: "Dasbor Eksekutif", button: "(at-risk row)", button_id: "(baris berisiko)",
        effect: "Jump to the slipping deal", effect_id: "Lompat ke deal yang melorot" },
      { page: "Sales Targets", page_id: "Target Penjualan", button: "+ New target", button_id: "+ Target baru",
        effect: "Set monthly quotas", effect_id: "Tetapkan kuota bulanan" },
      { page: "Employees", page_id: "Karyawan", button: "(sales person)", button_id: "(sales)",
        effect: "See KPIs and won revenue", effect_id: "Lihat KPI dan pendapatan menang" },
    ],
    rules: [
      "You approve 'data change' requests from admins. Quotations now route to the director, not you.",
      "Stage transitions (lead → presentation → … → won), quotations, and customer POs all go to the director, not you — your own stage moves on customers also go through the director.",
      "Anything bigger waits for the director.",
    ],
    rules_id: [
      "Anda menyetujui permintaan 'perubahan data' dari admin. Penawaran sekarang masuk ke direktur, bukan ke Anda.",
      "Pindah tahap (lead → presentasi → … → menang), penawaran, dan PO pelanggan semuanya ke direktur — pindah tahap Anda sendiri di pelanggan juga lewat direktur.",
      "Yang lebih besar menunggu direktur.",
    ],
  },
  {
    key: "director",
    label: "Director",
    label_id: "Direktur",
    emoji: "👑",
    Icon: Crown,
    blurb:
      "The biggest hat. You see everything, sign off on financial moves, " +
      "and own the supplier ⇄ customer link.",
    blurb_id:
      "Topi paling besar. Anda lihat semuanya, tanda tangan langkah finansial, " +
      "dan memegang hubungan supplier ⇄ pelanggan.",
    daily: "Morning: Approvals (quotations + customer POs + stage moves). Monday: Executive Dashboard + AI Recommendations. End of month: Salary.",
    daily_id: "Pagi: Persetujuan (penawaran + PO pelanggan + pindah tahap). Senin: Dasbor Eksekutif + Rekomendasi AI. Akhir bulan: Gaji.",
    flow: [
      { title: "Open Approvals first", title_id: "Buka Persetujuan dulu",
        detail: "Quotations, customer POs, stage-move requests — green-light or reject. Approving a quotation lets sales send it.",
        detail_id: "Penawaran, PO pelanggan, permintaan pindah tahap — setujui atau tolak. Menyetujui penawaran memberi sales lampu hijau untuk mengirim." },
      { title: "Approve a customer PO → project is created", title_id: "Setujui PO pelanggan → proyek terbentuk",
        detail: "The project carries the customer's PO number, date and ordered items. This is the ONLY way projects are made now.",
        detail_id: "Proyek mewarisi nomor PO pelanggan, tanggal, dan item yang dipesan. Ini SATU-SATUNYA cara proyek dibuat sekarang." },
      { title: "Executive Dashboard", title_id: "Dasbor Eksekutif",
        detail: "Read the AI recommendations", detail_id: "Baca rekomendasi AI" },
      { title: "Project needs material → Purchasing → + New PO", title_id: "Proyek butuh material → Pembelian → + PO baru",
        detail: "Link a supplier + project. Non-directors who file a supplier PO need your approval too.",
        detail_id: "Hubungkan supplier + proyek. Non-direktur yang mendaftarkan PO supplier juga butuh persetujuan Anda." },
      { title: "Track everything on PO Recap", title_id: "Pantau semua di Rekap PO",
        detail: "Customer POs + supplier POs in one view, with who's in charge of each.",
        detail_id: "PO pelanggan + PO supplier dalam satu tampilan, dengan penanggung jawabnya." },
      { title: "Supplier portal lights up automatically", title_id: "Portal supplier menyala otomatis",
        detail: "Supplier uploads drawing + sets warehouse ETA",
        detail_id: "Supplier unggah gambar + isi ETA gudang" },
      { title: "Drive work on the Operation board", title_id: "Jalankan kerja di Papan Operasi",
        detail: "Each stage (Receiving → … → Delivery) is its own screen; mark work orders Done / Advance them.",
        detail_id: "Tiap tahap (Penerimaan → … → Pengiriman) punya layar sendiri; tandai work order Selesai / Lanjutkan." },
      { title: "End of month: Salary → generate → post → mark paid", title_id: "Akhir bulan: Gaji → buat → posting → tandai dibayar" },
    ],
    buttons: [
      { page: "Approvals", page_id: "Persetujuan", button: "Approve / Reject", button_id: "Setujui / Tolak",
        effect: "Sign off on every quotation, customer PO, supplier PO, stage move + data change",
        effect_id: "Tanda tangan tiap penawaran, PO pelanggan, PO supplier, pindah tahap + perubahan data" },
      { page: "Customer PO (Workspace)", page_id: "PO Pelanggan (Ruang kerja)", button: "Row / detail", button_id: "Baris / detail",
        effect: "See every incoming customer PO + the project it spawned",
        effect_id: "Lihat tiap PO pelanggan masuk + proyek yang terbentuk darinya" },
      { page: "Purchasing PO (Workspace)", page_id: "PO Pembelian (Ruang kerja)", button: "+ New PO", button_id: "+ PO baru",
        effect: "Issue a supplier PO (link supplier + project)",
        effect_id: "Terbitkan PO supplier (hubungkan supplier + proyek)" },
      { page: "PO Recap (Workspace)", page_id: "Rekap PO (Ruang kerja)", button: "Tabs + search", button_id: "Tab + pencarian",
        effect: "All POs in one place, with the person in charge",
        effect_id: "Semua PO dalam satu tempat, dengan penanggung jawabnya" },
      { page: "Operation board", page_id: "Papan Operasi", button: "Stage card", button_id: "Kartu tahap",
        effect: "Open a stage's work-order list; mark Done / Advance",
        effect_id: "Buka daftar work order di tahap itu; tandai Selesai / Lanjutkan" },
      { page: "Purchasing (supplier row)", page_id: "Pembelian (baris supplier)", button: "Click row", button_id: "Klik baris",
        effect: "Supplier detail + full PO history", effect_id: "Detail supplier + riwayat PO lengkap" },
      { page: "All files", page_id: "Semua file", button: "Search / filter / download", button_id: "Cari / filter / unduh",
        effect: "Audit every upload in the system", effect_id: "Audit setiap unggahan di sistem" },
      { page: "Salary", page_id: "Gaji", button: "Post to ledger / Mark paid", button_id: "Posting ke ledger / Tandai dibayar",
        effect: "Finalize payroll", effect_id: "Finalisasi payroll" },
      { page: "Admin → Users", page_id: "Admin → Pengguna", button: "+ New user", button_id: "+ Pengguna baru",
        effect: "Create any account, any role", effect_id: "Buat akun apa saja, peran apa saja" },
    ],
    rules: [
      "EVERY quotation needs your approval before sales can send it — no auto-approve on small discounts anymore.",
      "A customer PO is the gate to project creation: approving it is what spawns the project (carrying the PO number / date / value).",
      "Only YOU can issue a supplier PO and decide which supplier serves which project — keeps the customer ↔ supplier mapping private. Non-directors can request one, but it waits for your approval.",
      "Only YOU can approve a CRM stage transition. Every 'Advance to …' from sales/manager/admin queues up in Approvals.",
      "PO Recap is director-only — the company-wide view of customer + supplier POs.",
      "Mark-paid + post-to-ledger feel irreversible — reverse uses a matching reversal entry, not a hard delete.",
    ],
    rules_id: [
      "SETIAP penawaran butuh persetujuan Anda sebelum sales bisa mengirimnya — tidak ada lagi auto-approve untuk diskon kecil.",
      "PO pelanggan adalah gerbang pembuatan proyek: menyetujuinya yang membentuk proyek (membawa nomor PO / tanggal / nilai).",
      "Hanya ANDA yang bisa menerbitkan PO supplier dan menentukan supplier mana melayani proyek mana — menjaga pemetaan pelanggan ↔ supplier tetap rahasia. Non-direktur bisa meminta, tapi menunggu persetujuan Anda.",
      "Hanya ANDA yang bisa menyetujui pindah tahap CRM. Setiap 'Lanjut ke …' dari sales/manajer/admin masuk antrean Persetujuan.",
      "Rekap PO hanya untuk direktur — tampilan PO pelanggan + supplier seluruh perusahaan.",
      "Tandai-dibayar + posting-ke-ledger terasa tak terbalik — pembalikan pakai entri jurnal balik, bukan hapus paksa.",
    ],
  },
  {
    key: "customer",
    label: "Customer (portal)",
    label_id: "Pelanggan (portal)",
    emoji: "🏢",
    Icon: Building2,
    blurb:
      "What your CUSTOMER sees when they log in. Stripped down — no sidebar, " +
      "no internal data, only their own deals.",
    blurb_id:
      "Apa yang dilihat PELANGGAN Anda saat masuk. Sangat sederhana — tanpa sidebar, " +
      "tanpa data internal, hanya deal mereka sendiri.",
    daily: "Log in, see status of their order, approve drawings, claim payments.",
    daily_id: "Masuk, lihat status pesanan, setujui gambar, klaim pembayaran.",
    flow: [
      { title: "Log in at /portal", title_id: "Masuk di /portal" },
      { title: "See own quotations + projects + invoices", title_id: "Lihat penawaran + proyek + faktur sendiri" },
      { title: "Drawing waiting? → Approve or Reject", title_id: "Ada gambar menunggu? → Setujui atau Tolak" },
      { title: "Shipping timeline shows Origin → Our warehouse → Their site", title_id: "Linimasa pengiriman: Asal → Gudang kami → Lokasi mereka",
        detail: "Forecast dates show amber, actuals green", detail_id: "Tanggal perkiraan kuning, aktual hijau" },
      { title: "Already paid? → 'I paid this' modal → upload proof", title_id: "Sudah bayar? → modal 'Saya sudah bayar' → unggah bukti" },
      { title: "Finance verifies → invoice marked paid", title_id: "Keuangan verifikasi → faktur ditandai lunas" },
    ],
    buttons: [
      { page: "Customer portal", page_id: "Portal pelanggan", button: "Approve / Reject drawing", button_id: "Setujui / Tolak gambar",
        effect: "Sign off on supplier drawings", effect_id: "Tanda tangan gambar supplier" },
      { page: "Customer portal", page_id: "Portal pelanggan", button: "I paid this", button_id: "Saya sudah bayar",
        effect: "Submit a payment claim with proof", effect_id: "Kirim klaim pembayaran dengan bukti" },
    ],
    rules: [
      "They never see your suppliers, costs, other customers, employees, chat, or AI.",
      "Only their own deals.",
    ],
    rules_id: [
      "Mereka tidak pernah melihat supplier Anda, biaya, pelanggan lain, karyawan, chat, atau AI.",
      "Hanya deal mereka sendiri.",
    ],
  },
  {
    key: "supplier",
    label: "Supplier (portal)",
    label_id: "Supplier (portal)",
    emoji: "🏭",
    Icon: Factory,
    blurb:
      "What a VENDOR sees when they log in. Equally stripped — only POs " +
      "assigned to them.",
    blurb_id:
      "Apa yang dilihat VENDOR saat masuk. Sama sederhananya — hanya PO " +
      "yang ditugaskan kepada mereka.",
    daily: "Open the portal, fill in the warehouse ETA, upload the drawing PDF.",
    daily_id: "Buka portal, isi ETA gudang, unggah PDF gambar.",
    flow: [
      { title: "Open the portal → see PO assigned to me", title_id: "Buka portal → lihat PO yang ditugaskan ke saya" },
      { title: "Upload drawing PDF → customer sees it for approval", title_id: "Unggah PDF gambar → pelanggan lihat untuk persetujuan" },
      { title: "Type estimated arrival at our warehouse → Save dates", title_id: "Isi perkiraan tiba di gudang kami → Simpan tanggal" },
      { title: "Customer's timeline updates instantly", title_id: "Linimasa pelanggan langsung ter-update",
        detail: "No internal step needed", detail_id: "Tidak perlu langkah internal" },
      { title: "Update actual ship date as goods leave", title_id: "Update tanggal kirim aktual saat barang berangkat" },
      { title: "Update actual arrival date as goods arrive", title_id: "Update tanggal tiba aktual saat barang sampai" },
    ],
    buttons: [
      { page: "Supplier portal", page_id: "Portal supplier", button: "Upload (Drawing)", button_id: "Unggah (Gambar)",
        effect: "Mirror to project drawings for customer approval",
        effect_id: "Disalin ke gambar proyek untuk persetujuan pelanggan" },
      { page: "Supplier portal", page_id: "Portal supplier", button: "Save dates", button_id: "Simpan tanggal",
        effect: "Warehouse ETA + ship dates flow to customer",
        effect_id: "ETA gudang + tanggal kirim mengalir ke pelanggan" },
    ],
    rules: [
      "Just the estimate is enough — don't wait for actual arrival to communicate the forecast.",
      "They never see other suppliers, your pricing, your other vendors, or your employees.",
    ],
    rules_id: [
      "Cukup perkiraan saja — jangan tunggu kedatangan aktual untuk menyampaikan forecast.",
      "Mereka tidak pernah melihat supplier lain, harga Anda, vendor lain, atau karyawan Anda.",
    ],
  },
];

const TROUBLES: { problem: string; problem_id: string; answer: string; answer_id: string }[] = [
  {
    problem: "Can't log in",
    problem_id: "Tidak bisa masuk",
    answer: "The Director can reset any password (Admin → Users).",
    answer_id: "Direktur bisa mereset kata sandi siapa pun (Admin → Pengguna).",
  },
  {
    problem: "Quotation stuck on 'pending approval'",
    problem_id: "Penawaran macet di 'menunggu persetujuan'",
    answer: "Every quotation now needs Director sign-off in /approvals — ask the Director to open Approvals.",
    answer_id: "Setiap penawaran sekarang butuh tanda tangan Direktur di /approvals — minta Direktur membuka Persetujuan.",
  },
  {
    problem: "Marked Won but no project appeared",
    problem_id: "Sudah Menang tapi proyek belum muncul",
    answer: "That's intentional. Sales has to submit the customer's PO (with the PO file + ordered items) and the Director has to approve it — approval creates the project.",
    answer_id: "Itu memang disengaja. Sales harus mengirim PO pelanggan (dengan file PO + item yang dipesan) dan Direktur harus menyetujuinya — persetujuan membuat proyek.",
  },
  {
    problem: "Stage move stuck on amber 'awaiting approval'",
    problem_id: "Pindah tahap macet di kuning 'menunggu persetujuan'",
    answer: "Ping the Director — every stage transition needs their sign-off in Approvals.",
    answer_id: "Hubungi Direktur — setiap pindah tahap butuh tanda tangannya di Persetujuan.",
  },
  {
    problem: "Where is the file I uploaded?",
    problem_id: "Di mana file yang saya unggah?",
    answer: "Director: open 'All files' in the sidebar, search by filename or filter by owner type.",
    answer_id: "Direktur: buka 'Semua file' di sidebar, cari berdasarkan nama atau filter berdasarkan tipe.",
  },
  {
    problem: "Customer asking when goods arrive",
    problem_id: "Pelanggan menanyakan kapan barang tiba",
    answer: "The supplier's ETA in the shipping timeline answers this; if it's stale, ping the supplier.",
    answer_id: "ETA supplier di linimasa pengiriman menjawab ini; kalau sudah basi, hubungi supplier.",
  },
  {
    problem: "Payment claim stuck",
    problem_id: "Klaim pembayaran macet",
    answer: "Admin or Director → Finance → Payment verification.",
    answer_id: "Admin atau Direktur → Keuangan → Verifikasi pembayaran.",
  },
  {
    problem: "Attendance wrong",
    problem_id: "Absensi salah",
    answer: "HR → Attendance → Manual entry — they can fix any record.",
    answer_id: "HR → Absensi → Entri manual — mereka bisa memperbaiki catatan apa pun.",
  },
  {
    problem: "Don't know which button to press",
    problem_id: "Tidak tahu tombol mana yang ditekan",
    answer: "Open Help in the sidebar — full page-by-page walkthrough.",
    answer_id: "Buka Bantuan di sidebar — panduan lengkap halaman per halaman.",
  },
];

export default function RoleGuidePage() {
  const me = useAuthStore((s) => s.user);
  const t = useT();
  // Default to the logged-in user's role if it's in our list, else director
  const initial = (ROLES.find((r) => r.key === me?.role)?.key ?? "director") as RoleKey;
  const [active, setActive] = useState<RoleKey>(initial);

  useEffect(() => {
    const r = ROLES.find((r) => r.key === me?.role);
    if (r) setActive(r.key);
  }, [me?.role]);

  const section = ROLES.find((r) => r.key === active) ?? ROLES[0];

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Map size={22} className="text-brand-600" /> {t("Role guide", "Panduan peran")}
          </h1>
          <p className="text-sm muted">
            {t(
              "Pick your role. Get your daily workflow, the buttons you'll touch, and the rules.",
              "Pilih peran Anda. Lihat alur kerja harian, tombol yang akan Anda pakai, dan aturannya.",
            )}{" "}
            {me?.role && (
              <span>
                {t("You're logged in as", "Anda masuk sebagai")}{" "}
                <b className="text-ink-900 capitalize">{me.role}</b>.
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Role tabs */}
      <div className="card p-1 flex flex-wrap gap-1">
        {ROLES.map((r) => {
          const Icon = r.Icon;
          const isMe = me?.role === r.key;
          return (
            <button
              key={r.key}
              onClick={() => setActive(r.key)}
              className={clsx(
                "px-3 py-1.5 rounded-md text-sm font-medium inline-flex items-center gap-1.5",
                active === r.key
                  ? "bg-brand-600 text-white shadow-sm"
                  : "text-ink-600 hover:bg-ink-100",
              )}
            >
              <Icon size={14} />
              <span>{t(r.label, r.label_id)}</span>
              {isMe && (
                <span className={clsx(
                  "text-[9px] uppercase font-bold tracking-widest px-1.5 py-0.5 rounded",
                  active === r.key ? "bg-white/20" : "bg-brand-50 text-brand-700",
                )}>{t("You", "Anda")}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Header card */}
      <div className="card p-5 lg:p-6 bg-gradient-to-br from-brand-600 to-brand-700 text-white">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-white/15 backdrop-blur grid place-items-center text-2xl shrink-0">
            {section.emoji}
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-widest text-white/70">
              {t("Role", "Peran")}
            </div>
            <h2 className="text-2xl font-semibold mt-0.5">{t(section.label, section.label_id)}</h2>
            <p className="text-white/90 mt-2 text-sm">{t(section.blurb, section.blurb_id)}</p>
          </div>
        </div>
      </div>

      {/* Daily snapshot */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-1">
          🌞 {t("Your daily rhythm", "Ritme harian Anda")}
        </div>
        <p className="text-sm text-ink-700">{t(section.daily, section.daily_id)}</p>
      </div>

      {/* Flow */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-3">
          <ChevronRight size={15} className="text-brand-600" /> {t("Your workflow, step by step", "Alur kerja Anda, langkah demi langkah")}
        </div>
        <ol className="space-y-2">
          {section.flow.map((s, i) => (
            <li key={i} className="flex items-start gap-3 rounded-lg border border-ink-200 bg-white p-3">
              <div className="h-7 w-7 rounded-full bg-brand-100 text-brand-700 font-semibold text-sm grid place-items-center shrink-0">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{t(s.title, s.title_id)}</div>
                {s.detail && (
                  <div className="text-xs muted mt-0.5">{t(s.detail, s.detail_id ?? s.detail)}</div>
                )}
              </div>
              {i < section.flow.length - 1 && (
                <ChevronRight size={14} className="text-ink-300 self-center hidden sm:block" />
              )}
            </li>
          ))}
        </ol>
      </div>

      {/* Buttons reference */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <BookOpen size={15} className="text-brand-600" /> {t("Buttons you'll touch", "Tombol yang Anda pakai")}
          </div>
          <div className="text-xs muted">
            {t("Quick reference card — print this if you like.", "Kartu referensi cepat — cetak kalau perlu.")}
          </div>
        </header>
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Page", "Halaman")}</th>
              <th className="th">{t("Button", "Tombol")}</th>
              <th className="th">{t("What it does", "Fungsinya")}</th>
            </tr>
          </thead>
          <tbody>
            {section.buttons.map((b, i) => (
              <tr key={i} className="border-t border-ink-100">
                <td className="td muted">{t(b.page, b.page_id)}</td>
                <td className="td font-medium">{t(b.button, b.button_id)}</td>
                <td className="td">{t(b.effect, b.effect_id)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Rules */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-2">
          <AlertCircle size={15} className="text-amber-600" /> {t("Rules to remember", "Aturan yang harus diingat")}
        </div>
        <ul className="space-y-1.5 text-sm">
          {(t("en", "id") === "id" ? section.rules_id : section.rules).map((r, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="text-ink-400 mt-1">•</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* How it all fits together (always visible) */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-3">
          🔄 {t("How everyone's work connects", "Bagaimana pekerjaan semua orang terhubung")}
        </div>
        <SystemFlow />
      </div>

      {/* Troubleshooting */}
      <div className="card p-5">
        <div className="font-semibold flex items-center gap-2 mb-2">
          🆘 {t("When something goes wrong", "Kalau ada yang salah")}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {TROUBLES.map((row, i) => (
            <div key={i} className="rounded-lg border border-ink-200 p-3 bg-white">
              <div className="text-xs uppercase tracking-wider muted">{t(row.problem, row.problem_id)}</div>
              <div className="text-sm mt-0.5">{t(row.answer, row.answer_id)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SystemFlow() {
  // Pure CSS / flexbox depiction of the cross-role flow
  const lane = (emoji: string, label: string, items: string[], colour: string) => (
    <div className={clsx(
      "flex-1 min-w-[140px] rounded-xl border p-3 bg-white",
      colour,
    )}>
      <div className="text-2xl">{emoji}</div>
      <div className="font-semibold mt-1 text-sm">{label}</div>
      <ul className="mt-2 space-y-1 text-xs text-ink-600">
        {items.map((it, i) => <li key={i}>· {it}</li>)}
      </ul>
    </div>
  );

  const arrow = (
    <div className="self-center text-ink-300 hidden lg:block">
      <ChevronRight size={18} />
    </div>
  );

  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
      {lane("🏢", "Customer", ["sends inquiry", "approves drawings", "pays invoices"], "border-cyan-200")}
      {arrow}
      {lane("👤", "Sales", ["adds customer", "builds quote", "files customer PO"], "border-brand-200")}
      {arrow}
      {lane("📊", "Manager", ["reviews data changes", "watches at-risk deals"], "border-emerald-200")}
      {arrow}
      {lane("👑", "Director", ["approves quotes + customer POs", "customer PO → creates project", "issues supplier PO"], "border-red-200")}
      {arrow}
      {lane("🏭", "Supplier", ["uploads drawing", "sets warehouse ETA"], "border-teal-200")}
      {arrow}
      {lane("🛠", "HR / Finance", ["attendance", "payroll", "verify payments"], "border-amber-200")}
    </div>
  );
}
