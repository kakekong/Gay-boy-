import { useState, useEffect } from "react";
import {
  Map, ChevronRight, User, ShoppingCart, HardHat, UserCog, BarChart3, Crown,
  Building2, Factory, BookOpen, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/auth";
import { useT, T } from "@/store/lang";

type RoleKey =
  | "sales" | "purchasing" | "hr" | "finance" | "admin" | "manager" | "director"
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
        detail: "→ amber banner: sent for approval (a manager or the director can clear it). Once approved, send deck.",
        detail_id: "→ banner kuning: dikirim untuk persetujuan (manajer atau direktur bisa menyelesaikannya). Setelah disetujui, kirim deck." },
      { title: "File a Price request → quotation is generated from it", title_id: "Ajukan Permintaan Harga → penawaran dibuat darinya",
        detail: "You can't create a quotation from scratch anymore. File a Price request on the customer page; once it's priced + approved, generate the quotation from the approved PR — the numbers carry over.",
        detail_id: "Anda tidak bisa lagi membuat penawaran dari nol. Ajukan Permintaan Harga di halaman pelanggan; setelah dihargai + disetujui, buat penawaran dari PR yang disetujui — angkanya terbawa otomatis." },
      { title: "Submit quotation → director approves", title_id: "Kirim penawaran → direktur menyetujui",
        detail: "EVERY quotation needs director sign-off in /approvals before it can be sent. Submitted by accident? Click Unsubmit to pull it back to draft while it's still pending.",
        detail_id: "SETIAP penawaran wajib persetujuan direktur di /approvals sebelum bisa dikirim. Terkirim tak sengaja? Klik Batalkan-kirim untuk menariknya kembali ke draft selagi masih menunggu." },
      { title: "Mark deal Won → director approves", title_id: "Tandai deal Menang → direktur menyetujui",
        detail: "Sends a Won request to the director; the quote flips to Won once they approve. Still no project yet — that needs the customer PO.",
        detail_id: "Mengirim permintaan Menang ke direktur; penawaran jadi Menang setelah disetujui. Belum ada proyek — itu butuh PO pelanggan." },
      { title: "Customer sends their signed PO → Submit customer PO", title_id: "Pelanggan kirim PO tertanda → Kirim PO pelanggan",
        detail: "On the quote's 'Next step' card: attach the PO file, pick which line items they actually ordered, set the PO number, and tick 'This PO is a down payment' if it's a DP.",
        detail_id: "Di kartu 'Langkah berikutnya' pada penawaran: lampirkan file PO, pilih item yang benar-benar dipesan, isi nomor PO, dan centang 'PO ini adalah down payment' kalau DP." },
      { title: "Regular PO → Director approves → project is created", title_id: "PO reguler → Direktur menyetujui → proyek terbentuk",
        detail: "The project carries the PO number, date and value automatically.",
        detail_id: "Proyek otomatis mewarisi nomor PO, tanggal, dan nilai." },
      { title: "DP PO → Finance approves → you confirm deposit landed → project", title_id: "PO DP → Keuangan menyetujui → Anda konfirmasi DP masuk → proyek",
        detail: "DP PO routes to Finance first (they issue the DP invoice). Once the customer pays, Finance approves it — you get pinged to confirm the deposit cleared, and clicking 'Confirm deposit received' is what spawns the project.",
        detail_id: "PO DP masuk ke Keuangan dulu (mereka menerbitkan faktur DP). Setelah pelanggan bayar, Keuangan menyetujui — Anda dapat notifikasi untuk konfirmasi DP cair, dan klik 'Konfirmasi DP diterima' inilah yang membentuk proyek." },
    ],
    buttons: [
      { page: "Customers", page_id: "Pelanggan", button: "+ New customer", button_id: "+ Pelanggan baru",
        effect: "3-step wizard (basics / PICs / tax)", effect_id: "Wizard 3 langkah (data dasar / PIC / pajak)" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "+ Price request", button_id: "+ Permintaan harga",
        effect: "Ask purchasing/director to price the items — an approved PR is the only way to a quotation",
        effect_id: "Minta pembelian/direktur menghargai item — PR yang disetujui satu-satunya jalan ke penawaran" },
      { page: "Price request (approved)", page_id: "Permintaan harga (disetujui)", button: "Generate quotation", button_id: "Buat penawaran",
        effect: "Creates the quotation draft from the approved prices",
        effect_id: "Membuat draft penawaran dari harga yang disetujui" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Advance to …", button_id: "Lanjut ke …",
        effect: "Request a stage move (director approves)", effect_id: "Minta pindah tahap (direktur menyetujui)" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Log activity", button_id: "Catat aktivitas",
        effect: "Record a call/note; a follow-up is sent to the director for approval first", effect_id: "Catat telepon/catatan; tindak lanjut dikirim dulu ke direktur untuk persetujuan" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "AI suggest", button_id: "Saran AI",
        effect: "Generate a Bahasa Indonesia follow-up", effect_id: "Buat tindak lanjut dalam Bahasa Indonesia" },
      { page: "Customer page", page_id: "Halaman pelanggan", button: "Stage checklist circle", button_id: "Lingkaran checklist tahap",
        effect: "Tick required actions off", effect_id: "Centang aksi wajib" },
      { page: "Quotation page", page_id: "Halaman penawaran", button: "Submit", button_id: "Kirim",
        effect: "Send to director for approval (always)", effect_id: "Kirim ke direktur untuk persetujuan (selalu)" },
      { page: "Quotation page (pending)", page_id: "Halaman penawaran (menunggu)", button: "Unsubmit", button_id: "Batalkan kirim",
        effect: "Pull an accidentally-submitted quote back to draft (only while it's still pending)",
        effect_id: "Tarik penawaran yang terkirim tak sengaja kembali ke draft (hanya selagi masih menunggu)" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Upload drawing", button_id: "Unggah gambar",
        effect: "Upload the customer's drawing on your customers' projects",
        effect_id: "Unggah gambar dari pelanggan di proyek pelanggan Anda" },
      { page: "Quotation page", page_id: "Halaman penawaran", button: "Log follow-up", button_id: "Catat tindak lanjut",
        effect: "Sent to the director for approval before it's recorded", effect_id: "Dikirim ke direktur untuk persetujuan sebelum dicatat" },
      { page: "Quotation page (approved)", page_id: "Halaman penawaran (disetujui)", button: "Mark won", button_id: "Tandai menang",
        effect: "Sends a Won request to the director", effect_id: "Mengirim permintaan Menang ke direktur" },
      { page: "Quotation page (Won)", page_id: "Halaman penawaran (Menang)", button: "Submit customer PO", button_id: "Kirim PO pelanggan",
        effect: "File the customer's PO → director approval → project (regular) OR finance → your DP-received confirm → project (DP)",
        effect_id: "Daftarkan PO pelanggan → persetujuan direktur → proyek (reguler) ATAU keuangan → konfirmasi DP masuk → proyek (DP)" },
      { page: "Customer PO detail", page_id: "Detail PO pelanggan", button: "Confirm deposit received", button_id: "Konfirmasi DP diterima",
        effect: "Only shows on a DP PO once finance has approved — clicking it spawns the project",
        effect_id: "Hanya muncul di PO DP setelah keuangan menyetujui — klik untuk membentuk proyek" },
      { page: "Ops board", page_id: "Papan Operasi", button: "Stage cards / rows", button_id: "Kartu / baris tahap",
        effect: "Read-only view of where your customers' orders are in production (no WO codes, no notes, no action buttons)",
        effect_id: "Tampilan read-only lokasi pesanan pelanggan di produksi (tanpa kode WO, catatan, atau tombol aksi)" },
      { page: "Customer PO", page_id: "PO Pelanggan", button: "(sidebar, Workspace)", button_id: "(sidebar, Ruang kerja)",
        effect: "Track the POs you've filed and their status", effect_id: "Pantau PO yang Anda daftarkan dan statusnya" },
      { page: "Notifications bell", page_id: "Lonceng notifikasi", button: "Any item", button_id: "Item apa saja",
        effect: "Jump to whatever needs you", effect_id: "Lompat ke apa pun yang butuh Anda" },
    ],
    rules: [
      "You can only edit customers assigned to you (sales PIC).",
      "Quotations start from a Price request — direct '+ New quotation' is blocked for sales. File the PR, wait for pricing approval, then generate the quote from it.",
      "EVERY quotation needs director approval before it leaves draft — there's no more discount-based auto-approve. Submitted by accident? Unsubmit pulls it back while it's pending.",
      "Follow-ups you log — on a customer or a quotation — now go to the director for approval before they're recorded.",
      "Marking a quote Won sends a request to the director; it only flips to Won once they approve in /approvals.",
      "Marking a quote Won is what creates the project — the customer's PO is already on file by then, since Won can't be clicked without it. The director's approval of that PO still matters; it attaches to the project rather than creating it.",
      "Two PO paths: a regular PO goes to the director for approval; a DP PO (tick the 'This PO is a down payment' toggle) goes to finance first, then you get pinged to confirm the deposit landed — your 'Confirm deposit received' click spawns the project.",
      "When the customer only orders some of the quoted items, untick the rest in the Submit-customer-PO modal and edit prices if they negotiated.",
      "Manual stage moves need a manager's or director's approval — but the pipeline now advances AUTOMATICALLY with the deal documents: quotation approved → stage 'quotation'; Mark-Won approved → stage 'negotiation'; customer PO approved → stage 'po'. You no longer file separate stage-move requests along the quote path, and Mark-Won is no longer blocked by the stage.",
      "Ops board is read-only for you — you can see which of your customers' orders are moving through production, but the WO codes, notes and action buttons are hidden. That's production's territory.",
      "The customer page reads top-to-bottom as a deal funnel: name → contacts → quotations → customer POs → projects. Rejected POs show the director's / finance's reason inline on the quotation page.",
      "You can upload the customer's drawing on your own customers' projects — the rest of the project page (work orders, invoices, margins) stays internal and hidden from you.",
      "Overdue stage tasks light up the bell and the calendar in red — and you only get YOUR tasks now (deal chores for your customers), not purchasing's or finance's.",
    ],
    rules_id: [
      "Anda hanya bisa mengedit pelanggan yang ditugaskan kepada Anda (sales PIC).",
      "Penawaran dimulai dari Permintaan Harga — '+ Penawaran baru' langsung diblokir untuk sales. Ajukan PR, tunggu persetujuan harga, lalu buat penawaran darinya.",
      "SETIAP penawaran wajib persetujuan direktur sebelum keluar dari draft — tidak ada lagi auto-approve berdasarkan diskon. Terkirim tak sengaja? Batalkan-kirim menariknya kembali selagi menunggu.",
      "Tindak lanjut yang Anda catat — di pelanggan atau penawaran — sekarang masuk ke direktur untuk persetujuan sebelum tercatat.",
      "Menandai penawaran Menang mengirim permintaan ke direktur; baru jadi Menang setelah disetujui di /approvals.",
      "Proyek TIDAK terbentuk saat Anda menandai penawaran Menang. Anda mendaftarkan PO pelanggan — dan persetujuan atas PO itulah yang membentuk proyek.",
      "Dua jalur PO: PO reguler masuk ke direktur untuk disetujui; PO DP (centang toggle 'PO ini adalah down payment') masuk ke keuangan dulu, lalu Anda dapat notifikasi untuk konfirmasi DP masuk — klik 'Konfirmasi DP diterima' Anda yang membentuk proyek.",
      "Kalau pelanggan hanya pesan sebagian item dari penawaran, hilangkan centang yang tidak dipesan di modal Kirim-PO-pelanggan, dan edit harga kalau ada negosiasi.",
      "Pindah tahap manual butuh persetujuan manajer atau direktur — tapi pipeline sekarang maju OTOMATIS mengikuti dokumen deal: penawaran disetujui → tahap 'quotation'; Mark-Won disetujui → 'negotiation'; PO pelanggan disetujui → 'po'. Anda tidak lagi mengajukan pindah-tahap terpisah di sepanjang jalur penawaran.",
      "Papan Operasi read-only untuk Anda — Anda bisa lihat pesanan pelanggan Anda bergerak di produksi, tapi kode WO, catatan, dan tombol aksi disembunyikan. Itu wilayah produksi.",
      "Halaman pelanggan mengalir atas-ke-bawah sebagai funnel deal: nama → kontak → penawaran → PO pelanggan → proyek. PO yang ditolak menampilkan alasan direktur / keuangan langsung di halaman penawaran.",
      "Anda bisa mengunggah gambar dari pelanggan di proyek pelanggan Anda sendiri — sisa halaman proyek (work order, faktur, margin) tetap internal dan tersembunyi dari Anda.",
      "Tugas tahap yang telat menyala merah di lonceng dan kalender — dan sekarang hanya tugas ANDA (urusan deal pelanggan Anda), bukan tugas pembelian atau keuangan.",
    ],
  },
  {
    key: "purchasing",
    label: "Purchasing",
    label_id: "Pembelian",
    emoji: "📦",
    Icon: ShoppingCart,
    blurb:
      "You price the deals and book the goods in. Price requests, the vendor " +
      "list, supplier POs, and the origin leg of every shipment run through you — " +
      "without ever seeing which customer an order belongs to.",
    blurb_id:
      "Anda menghargai deal dan mendatangkan barang. Permintaan harga, daftar vendor, " +
      "PO supplier, dan leg asal setiap pengiriman lewat Anda — " +
      "tanpa pernah melihat pesanan itu milik pelanggan yang mana.",
    daily:
      "Morning: clear the Price requests costing queue (your bell pings you on new ones). " +
      "Keep supplier ratings and lead times accurate, book origin shipments on active " +
      "projects, and keep import documents complete before goods land.",
    daily_id:
      "Pagi: bereskan antrean Permintaan Harga (lonceng Anda berbunyi kalau ada yang baru). " +
      "Jaga rating dan lead time supplier tetap akurat, jadwalkan pengiriman dari asal di " +
      "proyek aktif, dan lengkapi dokumen impor sebelum barang tiba.",
    flow: [
      { title: "Sales files a Price request → your costing queue", title_id: "Sales mengajukan Permintaan Harga → antrean penetapan harga Anda",
        detail: "Open Price requests, fill in cost + recommended sell price per item. The customer's identity stays hidden — you price the items, not the relationship.",
        detail_id: "Buka Permintaan Harga, isi biaya + harga jual rekomendasi per item. Identitas pelanggan tetap tersembunyi — Anda menghargai item, bukan relasinya." },
      { title: "Director approves the PR → sales generates the quotation", title_id: "Direktur menyetujui PR → sales membuat penawaran",
        detail: "Your prices carry into the quote automatically.",
        detail_id: "Harga Anda otomatis terbawa ke penawaran." },
      { title: "Project spawns → raise the supplier PO", title_id: "Proyek terbentuk → ajukan PO supplier",
        detail: "You can file a supplier PO request; it waits for the director's approval (they own the supplier ↔ customer mapping).",
        detail_id: "Anda bisa mengajukan permintaan PO supplier; menunggu persetujuan direktur (mereka yang memegang pemetaan supplier ↔ pelanggan)." },
      { title: "File work orders as goods move", title_id: "Buat work order saat barang bergerak",
        detail: "Receiving / warehousing / QC work orders — only for stages the project has actually reached.",
        detail_id: "Work order penerimaan / penyimpanan / QC — hanya untuk tahap yang sudah dicapai proyek." },
      { title: "Book the origin shipment on the project", title_id: "Jadwalkan pengiriman asal di proyek",
        detail: "Edit shipping timeline → Est. + Actual shipped-from-origin, the import checkbox and origin location. Date changes go to the director for approval before the customer sees them.",
        detail_id: "Edit linimasa pengiriman → Perkiraan + Aktual kirim-dari-asal, centang impor, dan lokasi asal. Perubahan tanggal disetujui direktur dulu sebelum terlihat pelanggan." },
      { title: "Import order? Collect the import documents", title_id: "Pesanan impor? Lengkapi dokumen impor",
        detail: "Invoice, packing list, B/L, PIB etc. on the project's logistics card — complete them before the goods land.",
        detail_id: "Invoice, packing list, B/L, PIB dll. di kartu logistik proyek — lengkapi sebelum barang tiba." },
    ],
    buttons: [
      { page: "Price requests", page_id: "Permintaan Harga", button: "(row → cost fields)", button_id: "(baris → kolom biaya)",
        effect: "Price a request: cost + recommended sell per item, then submit for director approval",
        effect_id: "Hargai permintaan: biaya + rekomendasi jual per item, lalu ajukan persetujuan direktur" },
      { page: "Purchasing", page_id: "Pembelian", button: "+ New supplier", button_id: "+ Supplier baru",
        effect: "Add a vendor", effect_id: "Tambah vendor" },
      { page: "Purchasing (supplier row)", page_id: "Pembelian (baris supplier)", button: "Click row", button_id: "Klik baris",
        effect: "Open the supplier detail page + PO history", effect_id: "Buka halaman detail supplier + riwayat PO" },
      { page: "Purchasing PO", page_id: "PO Pembelian", button: "+ New PO", button_id: "+ PO baru",
        effect: "Request a supplier PO — waits for director approval",
        effect_id: "Ajukan PO supplier — menunggu persetujuan direktur" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Edit shipping timeline", button_id: "Edit linimasa pengiriman",
        effect: "Your lane: Est./Actual shipped-from-origin + import flag + origin location (director approves date changes)",
        effect_id: "Jalur Anda: Perkiraan/Aktual kirim-dari-asal + tanda impor + lokasi asal (perubahan tanggal disetujui direktur)" },
      { page: "Project detail", page_id: "Detail Proyek", button: "+ Work order", button_id: "+ Work order",
        effect: "File receiving / warehousing / QC WOs once the project reaches production",
        effect_id: "Buat WO penerimaan / penyimpanan / QC setelah proyek mencapai produksi" },
    ],
    rules: [
      "You never see customer names — projects show as 'Order PRJ-…' and price requests hide the requester's customer. That's deliberate.",
      "You can request a supplier PO but only the director can approve it — they own which supplier serves which project.",
      "On the shipping timeline you edit ONLY the origin leg (Est. + Actual shipped-from-origin) plus the import flag and origin location. Arrival dates are admin's lane.",
      "Shipping-date changes you save don't apply immediately — they go to the director for approval first (customers see these dates).",
      "Your bell and calendar only show purchasing work now: new price requests, your stage tasks (raise PR, select supplier), and your own reminders.",
      "Keep rating + lead-time fresh; the AI vendor-picker uses both.",
    ],
    rules_id: [
      "Anda tidak pernah melihat nama pelanggan — proyek tampil sebagai 'Order PRJ-…' dan permintaan harga menyembunyikan pelanggannya. Itu disengaja.",
      "Anda bisa mengajukan PO supplier tapi hanya direktur yang menyetujuinya — mereka yang menentukan supplier mana melayani proyek mana.",
      "Di linimasa pengiriman Anda HANYA mengedit leg asal (Perkiraan + Aktual kirim-dari-asal) plus tanda impor dan lokasi asal. Tanggal kedatangan jalurnya admin.",
      "Perubahan tanggal pengiriman yang Anda simpan tidak langsung berlaku — masuk dulu ke direktur untuk persetujuan (pelanggan melihat tanggal ini).",
      "Lonceng dan kalender Anda sekarang hanya menampilkan pekerjaan pembelian: permintaan harga baru, tugas tahap Anda (ajukan PR, pilih supplier), dan pengingat Anda sendiri.",
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
      "Whenever a new hire lands, file their KTP / contract / NPWP / BPJS on their employee profile. " +
      "On the 1st of the month, sweep for anyone with a red missed-days chip.",
    daily_id:
      "Setiap hari lihat halaman Absensi untuk perbaiki tanda alpa yang salah. " +
      "Setiap ada karyawan baru, arsipkan KTP / kontrak / NPWP / BPJS di profil karyawannya. " +
      "Tanggal 1 tiap bulan, sapu siapa saja yang punya chip merah hari-bolos.",
    flow: [
      { title: "Day 1 of the month", title_id: "Tanggal 1 setiap bulan",
        detail: "Open Employees", detail_id: "Buka Karyawan" },
      { title: "Anyone joined? → put them on the register yourself", title_id: "Ada yang masuk? → daftarkan sendiri orangnya",
        detail: "Employees → + New employee. Name, position, start date. Their login is created against this record afterwards — the director does that half in Admin → Users.",
        detail_id: "Karyawan → + Karyawan baru. Nama, jabatan, tanggal mulai. Akun masuknya dibuat dari data ini setelahnya — bagian itu dikerjakan direktur di Admin → Pengguna." },
      { title: "Open the new employee's profile → Employee documents", title_id: "Buka profil karyawan baru → Dokumen karyawan",
        detail: "Upload KTP, signed employment contract, NPWP (tax ID) and BPJS (social security) into the four labelled slots.",
        detail_id: "Unggah KTP, kontrak kerja tertanda, NPWP, dan BPJS ke empat slot bertanda tersebut." },
      { title: "Anyone left? → deactivate their account", title_id: "Ada yang keluar? → nonaktifkan akunnya" },
      { title: "Daily: Attendance → spot wrong Absent marks → fix", title_id: "Harian: Absensi → temukan tanda Alpa salah → perbaiki" },
      { title: "End of month: scan missed-days chips", title_id: "Akhir bulan: pindai chip hari-bolos" },
      { title: "Tell the director who to deduct", title_id: "Beri tahu direktur siapa yang dipotong" },
    ],
    buttons: [
      { page: "Employees", page_id: "Karyawan", button: "+ New employee", button_id: "+ Karyawan baru",
        effect: "Put a person on the register — before, and independently of, any login",
        effect_id: "Daftarkan orangnya — sebelum dan terpisah dari akun masuk mana pun" },
      { page: "Employees", page_id: "Karyawan", button: "+ Manage tags", button_id: "+ Kelola tag",
        effect: "Create / rename labels", effect_id: "Buat / ganti nama label" },
      { page: "Employee profile", page_id: "Profil karyawan", button: "Employee documents → Upload", button_id: "Dokumen karyawan → Unggah",
        effect: "File KTP / contract / NPWP / BPJS per employee (visible to HR + finance + management)",
        effect_id: "Arsipkan KTP / kontrak / NPWP / BPJS per karyawan (terlihat HR + keuangan + manajemen)" },
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
      "Every employee should have all four docs on file: KTP, contract, NPWP, BPJS. Missing ones show as empty slots on the Employee documents card so they're easy to spot.",
      "Employee documents are visible to HR, finance and management — sales / admin / purchasing don't see them.",
    ],
    rules_id: [
      "Chip kuning = 1–2 hari bolos; chip merah = 3+. Merah biasanya berarti perlu bicara payroll.",
      "Tag seperti 'Top performer' atau 'Spesialis tambang' bikin penyaringan lebih cepat.",
      "Setiap karyawan harus punya keempat dokumen terarsip: KTP, kontrak, NPWP, BPJS. Yang belum ada tampil sebagai slot kosong di kartu Dokumen karyawan supaya mudah terlihat.",
      "Dokumen karyawan hanya bisa dilihat HR, keuangan, dan manajemen — sales / admin / pembelian tidak melihatnya.",
    ],
  },
  {
    key: "admin",
    label: "Admin",
    label_id: "Admin",
    emoji: "🧑‍💼",
    Icon: UserCog,
    blurb:
      "Operations glue. You run projects, purchasing follow-through, inventory, " +
      "and the ops board — CRM and pricing aren't your desk.",
    blurb_id:
      "Perekat operasi. Anda mengurus proyek, tindak lanjut pembelian, inventaris, " +
      "dan papan operasi — CRM dan pricing bukan meja Anda.",
    daily:
      "Drive projects forward on the Operation board, keep Inventory counts honest, " +
      "stamp arrival dates as goods land, upload delivery proofs. Money pages " +
      "(invoices, payments, accounts) are finance's desk now, not yours.",
    daily_id:
      "Dorong proyek maju di Papan Operasi, jaga stok Inventaris tetap benar, " +
      "isi tanggal kedatangan saat barang tiba, unggah bukti kirim. Halaman uang " +
      "(faktur, pembayaran, akun) sekarang mejanya keuangan, bukan Anda.",
    flow: [
      { title: "Open Projects → work the active ones", title_id: "Buka Proyek → kerjakan yang aktif",
        detail: "Projects move ONE stage at a time, forward only: new → purchasing → drawing → drawing approved → production → QC → packaging → invoiced → delivered → paid → closed.",
        detail_id: "Proyek bergerak SATU tahap sekali jalan, hanya maju: baru → pembelian → gambar → gambar disetujui → produksi → QC → pengemasan → difakturkan → terkirim → lunas → tutup." },
      { title: "Operation board → advance work orders through the stages", title_id: "Papan Operasi → jalankan work order melalui tiap tahap",
        detail: "Receiving → Warehousing → QC → Packaging → Delivery. You can only file a WO for a stage the project has actually reached.",
        detail_id: "Penerimaan → Penyimpanan → QC → Pengemasan → Pengiriman. WO hanya bisa dibuat untuk tahap yang sudah dicapai proyek." },
      { title: "Inventory → Adjust stock if a count is off", title_id: "Inventaris → Sesuaikan stok kalau hitungan salah" },
      { title: "Goods land → stamp the arrival dates", title_id: "Barang tiba → isi tanggal kedatangan",
        detail: "Edit shipping timeline: your lane is the arrival legs — Est. + Actual at our warehouse and at the customer's site. Date changes go to the director for approval.",
        detail_id: "Edit linimasa pengiriman: jalur Anda adalah leg kedatangan — Perkiraan + Aktual di gudang kami dan di lokasi pelanggan. Perubahan tanggal disetujui direktur dulu." },
      { title: "After QC passes → Finance issues the final invoice + DO", title_id: "Setelah QC lulus → Keuangan menerbitkan faktur akhir + DO",
        detail: "You upload the delivery proof (POD) and confirm 'customer received' once the goods land — that's the delivered gate.",
        detail_id: "Anda unggah bukti kirim (POD) dan konfirmasi 'pelanggan menerima' setelah barang tiba — itu gerbang delivered." },
    ],
    buttons: [
      { page: "Projects", page_id: "Proyek", button: "(row / detail)", button_id: "(baris / detail)",
        effect: "Drive a project through drawings, deliveries, QC, close-out",
        effect_id: "Jalankan proyek melewati gambar, pengiriman, QC, dan penutupan" },
      { page: "Operation board", page_id: "Papan Operasi", button: "Stage card", button_id: "Kartu tahap",
        effect: "Open a stage's work-order list; mark Done / Advance them",
        effect_id: "Buka daftar work order di tahap itu; tandai Selesai / Lanjutkan" },
      { page: "Inventory", page_id: "Inventaris", button: "Adjust", button_id: "Sesuaikan",
        effect: "Correct stock counts", effect_id: "Koreksi jumlah stok" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Edit shipping timeline", button_id: "Edit linimasa pengiriman",
        effect: "Your lane: Est. + Actual arrival at our warehouse / at the customer (director approves date changes)",
        effect_id: "Jalur Anda: Perkiraan + Aktual tiba di gudang kami / di pelanggan (perubahan tanggal disetujui direktur)" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Upload delivery proof", button_id: "Unggah bukti kirim",
        effect: "POD / courier slip — the director verifies it before delivery can be confirmed",
        effect_id: "POD / resi kurir — direktur memverifikasinya sebelum pengiriman bisa dikonfirmasi" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Confirm customer received", button_id: "Konfirmasi pelanggan menerima",
        effect: "Marks deliveries delivered + moves the project to 'delivered'",
        effect_id: "Menandai pengiriman terkirim + memindahkan proyek ke 'delivered'" },
    ],
    rules: [
      "Your sidebar is ops-only: Projects, Operation board, Inventory, Attendance, Chat, Role guide. CRM, price requests, finance pages, payment verification and user admin are all out of scope.",
      "Finance uploads the invoice file (down-payment or final) and verifies payments — you don't. You confirm the customer received the goods, not the money.",
      "Projects advance ONE stage at a time and never backwards; work orders are gated to stages the project has reached (packaging needs QC passed, delivery needs packaging).",
      "On the shipping timeline you own the arrival legs (est. + actual at our warehouse / at the customer). Origin-shipment dates are purchasing's lane. Your date edits wait for the director's approval.",
      "Adjusting stock writes an audit trail — corrections are visible to the director.",
    ],
    rules_id: [
      "Sidebar Anda hanya operasi: Proyek, Papan Operasi, Inventaris, Absensi, Chat, Panduan peran. CRM, permintaan harga, halaman keuangan, verifikasi pembayaran, dan admin pengguna semua di luar wilayah.",
      "Keuangan yang mengunggah file faktur (DP atau final) dan memverifikasi pembayaran — bukan Anda. Anda konfirmasi barang diterima pelanggan, bukan uangnya.",
      "Proyek maju SATU tahap sekali jalan dan tidak pernah mundur; work order dibatasi ke tahap yang sudah dicapai proyek (pengemasan butuh QC lulus, pengiriman butuh pengemasan).",
      "Di linimasa pengiriman Anda memegang leg kedatangan (perkiraan + aktual di gudang kami / di pelanggan). Tanggal kirim-dari-asal jalurnya pembelian. Perubahan tanggal Anda menunggu persetujuan direktur.",
      "Penyesuaian stok mencatat jejak audit — koreksinya bisa dilihat direktur.",
    ],
  },
  {
    key: "finance",
    label: "Finance",
    label_id: "Keuangan",
    emoji: "💰",
    Icon: BarChart3,
    blurb:
      "The money desk. You issue invoices (DP and final), approve them into the tax record, " +
      "gate down-payment POs, and watch AR / financial reports.",
    blurb_id:
      "Meja keuangan. Anda menerbitkan faktur (DP dan final), menyetujuinya ke catatan pajak, " +
      "mengunci gerbang PO DP, dan memantau piutang / laporan keuangan.",
    daily:
      "Morning: the bell shows DP POs waiting for you; Payment verification for new proofs. " +
      "Whenever a project passes QC, upload its final invoice + DO. Approve invoices with the Faktur Pajak number, " +
      "and record bank-transfer payments manually for customers who skip the portal.",
    daily_id:
      "Pagi: lonceng menampilkan PO DP yang menunggu Anda; Verifikasi Pembayaran untuk bukti baru. " +
      "Setiap proyek lulus QC, unggah faktur akhir + DO. Setujui faktur dengan nomor Faktur Pajak, " +
      "dan catat pembayaran transfer secara manual untuk pelanggan yang tidak pakai portal.",
    flow: [
      { title: "Sales files a DP customer PO → your bell pings", title_id: "Sales mendaftarkan PO DP pelanggan → lonceng Anda berbunyi",
        detail: "Open the customer PO (sidebar → Customer PO), review the deal + attached PO file, click 'Finance approve DP' — or reject with a reason sales will see.",
        detail_id: "Buka PO pelanggan (sidebar → PO Pelanggan), tinjau deal + file PO terlampir, klik 'Setujui DP' — atau tolak dengan alasan yang akan dilihat sales." },
      { title: "Issue the DP invoice from the customer PO page", title_id: "Terbitkan faktur DP dari halaman PO pelanggan",
        detail: "The project doesn't exist yet — the DP invoice attaches to the PO itself. Once sales confirms the deposit, it's re-linked to the spawned project automatically.",
        detail_id: "Proyek belum ada — faktur DP menempel di PO-nya. Setelah sales konfirmasi DP, otomatis tertaut ke proyek yang terbentuk." },
      { title: "Customer pays → sales confirms → project spawns", title_id: "Pelanggan bayar → sales konfirmasi → proyek terbentuk",
        detail: "Sales clicks 'Confirm deposit received' once it lands.",
        detail_id: "Sales klik 'Konfirmasi DP diterima' setelah masuk." },
      { title: "After QC passes → issue the final invoice + DO", title_id: "Setelah QC lulus → terbitkan faktur akhir + DO",
        detail: "Project detail → Issue invoice → 'Final invoice (after delivery)' → upload both files.",
        detail_id: "Detail proyek → Terbitkan faktur → 'Faktur akhir (setelah kirim)' → unggah kedua file." },
      { title: "Approve invoices with the Faktur Pajak number", title_id: "Setujui faktur dengan nomor Faktur Pajak",
        detail: "Finance → Pending invoices → enter FP number + upload FP file → Approve.",
        detail_id: "Keuangan → Faktur menunggu → isi nomor FP + unggah file FP → Setujui." },
      { title: "Money lands → verify the claim OR record it manually", title_id: "Uang masuk → verifikasi klaim ATAU catat manual",
        detail: "Portal customers file claims you verify on Payment verification. Customers who pay by transfer without the portal: open the project → invoice card → 'Enter payment manually' — recorded + verified in one stroke. Full payment auto-closes the project.",
        detail_id: "Pelanggan portal mengirim klaim yang Anda verifikasi di Verifikasi Pembayaran. Pelanggan yang transfer tanpa portal: buka proyek → kartu faktur → 'Masukkan pembayaran manual' — tercatat + terverifikasi sekaligus. Pembayaran penuh otomatis menutup proyek." },
      { title: "Watch AR + financial reports", title_id: "Pantau piutang + laporan keuangan" },
    ],
    buttons: [
      { page: "Customer PO detail (DP)", page_id: "Detail PO Pelanggan (DP)", button: "Finance approve DP", button_id: "Setujui DP",
        effect: "Approves a DP PO; sales gets pinged to confirm the deposit once it lands",
        effect_id: "Menyetujui PO DP; sales akan dinotifikasi untuk konfirmasi DP setelah masuk" },
      { page: "Customer PO detail (DP)", page_id: "Detail PO Pelanggan (DP)", button: "Issue DP invoice", button_id: "Terbitkan faktur DP",
        effect: "Upload the down-payment invoice against the PO (no project exists yet; it re-links to the project after sales confirms)",
        effect_id: "Unggah faktur DP terhadap PO (proyek belum ada; otomatis tertaut ke proyek setelah sales konfirmasi)" },
      { page: "Project detail", page_id: "Detail Proyek", button: "Issue invoice + DO", button_id: "Terbitkan faktur + DO",
        effect: "Upload the final post-QC invoice + delivery-order",
        effect_id: "Unggah faktur akhir pasca-QC + delivery-order" },
      { page: "Finance → Pending invoices", page_id: "Keuangan → Faktur menunggu", button: "Approve (with FP no.)", button_id: "Setujui (dengan No. FP)",
        effect: "Enter faktur pajak + upload the FP file; invoice moves to approved",
        effect_id: "Isi faktur pajak + unggah file FP; faktur pindah ke approved" },
      { page: "Payment verification", page_id: "Verifikasi pembayaran", button: "Verify / Reject", button_id: "Verifikasi / Tolak",
        effect: "Settle or bounce a customer payment", effect_id: "Selesaikan atau tolak pembayaran pelanggan" },
      { page: "Project detail (invoice card)", page_id: "Detail Proyek (kartu faktur)", button: "Enter payment manually", button_id: "Masukkan pembayaran manual",
        effect: "For customers who paid by transfer without the portal — amount prefills to the outstanding balance; recorded + verified in one stroke",
        effect_id: "Untuk pelanggan yang transfer tanpa portal — jumlah terisi otomatis sebesar sisa tagihan; tercatat + terverifikasi sekaligus" },
      { page: "Project detail (invoice card)", page_id: "Detail Proyek (kartu faktur)", button: "Delete invoice", button_id: "Hapus faktur",
        effect: "Remove a duplicate/mistaken invoice + its faktur pajak record — blocked once a payment is verified",
        effect_id: "Hapus faktur duplikat/salah + catatan faktur pajaknya — terkunci setelah ada pembayaran terverifikasi" },
      { page: "Finance", page_id: "Keuangan", button: "(read)", button_id: "(lihat)",
        effect: "See invoices, payments, outstanding AR", effect_id: "Lihat faktur, pembayaran, piutang" },
      { page: "Financial reports", page_id: "Laporan keuangan", button: "Any tab", button_id: "Tab apa saja",
        effect: "P&L, cash flow, revenue by sales rep — sliced by month / quarter / year",
        effect_id: "Laba/rugi, arus kas, pendapatan per sales — per bulan / kuartal / tahun" },
    ],
    rules: [
      "You now own invoice issuing — both flavours. DP invoices are issued from the CUSTOMER PO page (before any project exists); final invoices from the project page after QC passes, with the delivery order.",
      "The Faktur Pajak number is entered by you at the approve step, not at issue — that way a mistyped FP can't corrupt the tax record before finance double-checks.",
      "DP customer POs come straight to you (bell + Customer PO page), not the director. Approving one moves it to sales' 'confirm deposit received' step — you don't spawn the project yourself.",
      "Two ways money gets recorded: portal customers file a claim you Verify on Payment verification; everyone else you enter yourself on the project's invoice card ('Enter payment manually') — one stroke, already verified. Fully paying an invoice auto-advances its project to paid → closed.",
      "You can delete a duplicate/mistaken invoice and its faktur pajak record — but not once a payment has been verified against it.",
      "Your sidebar: Customer PO, Projects, Finance, Financial reports, Payment verification, Chart of Accounts, Recent ledgers, Attendance, Chat.",
      "Reject a payment proof or a DP PO with a clear reason — sales and the customer see it.",
    ],
    rules_id: [
      "Anda sekarang yang menerbitkan faktur — kedua jenisnya. Faktur DP diterbitkan dari halaman PO PELANGGAN (sebelum proyek ada); faktur akhir dari halaman proyek setelah QC lulus, dengan DO.",
      "Nomor Faktur Pajak Anda isi di langkah setujui, bukan saat terbit — jadi salah ketik FP tidak bisa mencemari catatan pajak sebelum keuangan cek ulang.",
      "PO pelanggan DP langsung ke Anda (lonceng + halaman PO Pelanggan), bukan direktur. Setuju memindahkannya ke langkah 'konfirmasi DP diterima' milik sales — Anda tidak membentuk proyek sendiri.",
      "Dua cara uang tercatat: pelanggan portal mengirim klaim yang Anda Verifikasi di Verifikasi Pembayaran; selain itu Anda masukkan sendiri di kartu faktur proyek ('Masukkan pembayaran manual') — sekali jalan, langsung terverifikasi. Faktur lunas otomatis memajukan proyeknya ke lunas → tutup.",
      "Anda bisa menghapus faktur duplikat/salah beserta catatan faktur pajaknya — tapi tidak setelah ada pembayaran terverifikasi di dalamnya.",
      "Sidebar Anda: PO Pelanggan, Proyek, Keuangan, Laporan keuangan, Verifikasi Pembayaran, Bagan Akun, Ledger Terbaru, Absensi, Chat.",
      "Tolak bukti bayar atau PO DP dengan alasan jelas — sales dan pelanggan melihatnya.",
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
      "You CAN clear manual customer stage-move requests and manager-tier data changes — they accept a manager or director decision.",
      "Deal documents are director-only: quotations, customer POs, supplier POs, sales follow-ups, Mark-won, price-request pricing, and shipping-date changes all wait for the director, not you.",
      "You see every role's notifications and stage tasks for oversight — sales', purchasing's, finance's and admin's queues all reach your bell.",
      "On the shipping timeline you can edit any field, but like everyone below director your date changes wait for the director's approval before the customer sees them.",
    ],
    rules_id: [
      "Anda BISA menyelesaikan permintaan pindah-tahap manual pelanggan dan perubahan data tingkat manajer — keduanya menerima keputusan manajer atau direktur.",
      "Dokumen deal hanya direktur: penawaran, PO pelanggan, PO supplier, tindak lanjut sales, Mark-won, penetapan harga PR, dan perubahan tanggal kirim semuanya menunggu direktur, bukan Anda.",
      "Anda melihat notifikasi dan tugas tahap semua peran untuk pengawasan — antrean sales, pembelian, keuangan, dan admin semuanya masuk lonceng Anda.",
      "Di linimasa pengiriman Anda bisa mengedit semua kolom, tapi seperti semua di bawah direktur, perubahan tanggal Anda menunggu persetujuan direktur sebelum terlihat pelanggan.",
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
        detail: "Quotations, customer POs, stage moves, sales follow-ups, and Mark-won requests — green-light or reject. Approving a follow-up records it; approving Mark-won flips the quote to Won and posts the ledger.",
        detail_id: "Penawaran, PO pelanggan, pindah tahap, tindak lanjut sales, dan permintaan Mark-won — setujui atau tolak. Menyetujui tindak lanjut mencatatnya; menyetujui Mark-won mengubah penawaran jadi Menang dan posting ke ledger." },
      { title: "Approve a regular customer PO → project is created", title_id: "Setujui PO pelanggan reguler → proyek terbentuk",
        detail: "The project carries the customer's PO number, date and ordered items. DP POs take a different path — see next step.",
        detail_id: "Proyek mewarisi nomor PO pelanggan, tanggal, dan item yang dipesan. PO DP jalur berbeda — lihat langkah berikutnya." },
      { title: "Down-payment POs route through Finance instead", title_id: "PO DP lewat Keuangan, bukan Anda",
        detail: "Finance approves the DP PO + issues the DP invoice, sales confirms the deposit landed, and the project spawns then. You still see the PO in the approvals feed for visibility but don't gate it.",
        detail_id: "Keuangan menyetujui PO DP + menerbitkan faktur DP, sales konfirmasi DP masuk, dan proyek terbentuk saat itu. Anda tetap melihat PO di feed persetujuan untuk visibilitas tapi tidak menjadi gerbang." },
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
        effect: "Sign off on every quotation, customer PO, supplier PO, stage move, sales follow-up, Mark-won + data change",
        effect_id: "Tanda tangan tiap penawaran, PO pelanggan, PO supplier, pindah tahap, tindak lanjut sales, Mark-won + perubahan data" },
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
        effect: "Create the login for somebody already on the employee register — or a customer / supplier portal account, who need no record",
        effect_id: "Buat akun masuk untuk orang yang sudah ada di daftar karyawan — atau akun portal pelanggan / pemasok, yang tidak perlu data itu" },
      { page: "Admin → Users", page_id: "Admin → Pengguna", button: "Custom roles", button_id: "Peran khusus",
        effect: "Build your own role: name + base tier + which pages it sees",
        effect_id: "Buat peran sendiri: nama + tingkat dasar + halaman yang bisa dilihat" },
    ],
    rules: [
      "A staff login is created against an employee record, so HR puts the person on the register (Employees → + New employee) before you can give them a way to sign in. Customer and supplier portal accounts are the exception — they are not employees.",
      "Build custom roles (Admin → Users → Custom roles) when the fixed roles don't fit — pick a name, a base access tier, and tick the pages it can open.",
      "EVERY quotation needs your approval before sales can send it — no auto-approve on small discounts anymore.",
      "Sales follow-ups and Mark-won both queue in Approvals and only take effect once you approve — a follow-up isn't recorded, and a deal isn't Won, until then.",
      "Two customer-PO gates: regular POs go to YOU (approve → project spawns). Down-payment POs go to Finance first (finance approves → sales confirms deposit → project spawns). You still see DP POs in the approvals feed for visibility.",
      "Every rejected PO stores the rejection reason. It shows up inline on the source quotation's PO list and on the customer page, so sales sees why without asking.",
      "Only YOU can issue a supplier PO and decide which supplier serves which project — keeps the customer ↔ supplier mapping private. Non-directors can request one, but it waits for your approval.",
      "Manual CRM stage moves clear through a manager or you — but approving a deal document moves the stage automatically: quotation approval → 'quotation', Mark-Won approval → 'negotiation', customer PO approval → 'po'. One decision drives both records.",
      "PO Recap is director-only — the company-wide view of customer + supplier POs.",
      "The Approvals page also queues DOCUMENTS waiting on you: submitted drawings, import-doc scans, delivery proofs, and price requests pending your pricing sign-off — with deep links to each.",
      "Shipping/delivery date changes from purchasing, admin or the manager land in your Approvals — the customer-visible timeline only moves after you approve. Your own edits apply instantly.",
      "Only YOU can delete a project (soft-delete; the PO/quotation/invoice history stays). Use it for test data or pre-reorder leftovers.",
      "Traceability chain: project detail links back to the customer PO that spawned it, which links back to the quotation. All three docs travel together forwards and backwards.",
      "Mark-paid + post-to-ledger feel irreversible — reverse uses a matching reversal entry, not a hard delete.",
    ],
    rules_id: [
      "Akun masuk karyawan dibuat dari data di daftar karyawan, jadi HR mendaftarkan orangnya dulu (Karyawan → + Karyawan baru) sebelum Anda bisa memberi akun. Akun portal pelanggan dan pemasok pengecualian — mereka bukan karyawan.",
      "Buat peran khusus (Admin → Pengguna → Peran khusus) kalau peran bawaan tidak cocok — pilih nama, tingkat akses dasar, dan centang halaman yang bisa dibuka.",
      "SETIAP penawaran butuh persetujuan Anda sebelum sales bisa mengirimnya — tidak ada lagi auto-approve untuk diskon kecil.",
      "Tindak lanjut sales dan Mark-won sama-sama masuk antrean Persetujuan dan baru berlaku setelah Anda setujui — tindak lanjut belum tercatat, dan deal belum Menang, sampai saat itu.",
      "Dua gerbang PO pelanggan: PO reguler ke ANDA (setujui → proyek terbentuk). PO DP ke Keuangan dulu (keuangan setuju → sales konfirmasi DP → proyek terbentuk). Anda tetap melihat PO DP di feed persetujuan untuk visibilitas.",
      "Setiap PO yang ditolak menyimpan alasan penolakan. Muncul langsung di daftar PO pada penawaran sumber dan di halaman pelanggan, jadi sales tahu alasan tanpa bertanya.",
      "Hanya ANDA yang bisa menerbitkan PO supplier dan menentukan supplier mana melayani proyek mana — menjaga pemetaan pelanggan ↔ supplier tetap rahasia. Non-direktur bisa meminta, tapi menunggu persetujuan Anda.",
      "Pindah tahap CRM manual bisa diselesaikan manajer atau Anda — tapi menyetujui dokumen deal memindahkan tahapnya otomatis: persetujuan penawaran → 'quotation', persetujuan Mark-Won → 'negotiation', persetujuan PO pelanggan → 'po'. Satu keputusan menggerakkan kedua catatan.",
      "Rekap PO hanya untuk direktur — tampilan PO pelanggan + supplier seluruh perusahaan.",
      "Halaman Persetujuan juga mengantrekan DOKUMEN yang menunggu Anda: gambar yang diajukan, pindaian dokumen impor, bukti kirim, dan permintaan harga menunggu persetujuan harga — dengan tautan langsung ke masing-masing.",
      "Perubahan tanggal kirim dari pembelian, admin, atau manajer masuk ke Persetujuan Anda — linimasa yang dilihat pelanggan baru bergerak setelah Anda setujui. Edit Anda sendiri langsung berlaku.",
      "Hanya ANDA yang bisa menghapus proyek (soft-delete; riwayat PO/penawaran/faktur tetap ada). Pakai untuk data uji atau sisa sebelum penataan ulang.",
      "Rantai jejak: detail proyek balik ke PO pelanggan yang membentuknya, dan itu balik ke penawaran. Ketiganya bergerak bersama, maju dan mundur.",
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
    problem: "Clicked Mark won / logged a follow-up but nothing changed",
    problem_id: "Klik Mark won / catat tindak lanjut tapi tidak berubah",
    answer: "Both now need Director approval — they're waiting in /approvals. The quote flips to Won (and the follow-up is recorded) once the Director approves.",
    answer_id: "Keduanya sekarang butuh persetujuan Direktur — sedang menunggu di /approvals. Penawaran jadi Menang (dan tindak lanjut tercatat) setelah Direktur menyetujui.",
  },
  {
    problem: "Marked Won but no project appeared",
    problem_id: "Sudah Menang tapi proyek belum muncul",
    answer: "That's intentional. Sales files the customer's PO (with the PO file + ordered items). Regular PO → Director approves → project spawns. DP PO → Finance approves → Sales confirms 'deposit received' → project spawns. Both paths end in a project, but the trigger differs.",
    answer_id: "Itu memang disengaja. Sales mendaftarkan PO pelanggan (dengan file PO + item yang dipesan). PO reguler → Direktur menyetujui → proyek terbentuk. PO DP → Keuangan menyetujui → Sales konfirmasi 'DP diterima' → proyek terbentuk. Kedua jalur berujung ke proyek, tapi pemicunya beda.",
  },
  {
    problem: "DP PO stuck on 'pending finance' or 'pending sales confirm'",
    problem_id: "PO DP macet di 'menunggu keuangan' atau 'menunggu sales konfirmasi'",
    answer: "Both steps are Finance's. 'pending_finance' → Finance opens the customer PO and clicks 'Finance approve DP', then issues the DP invoice. 'pending_payment_confirm' → once the money is in the bank Finance clicks 'Yes — deposit received' and the project spawns; if it never came they click 'No — never arrived' with a reason, which sales sees.",
    answer_id: "Kedua langkah milik Keuangan. 'pending_finance' → Keuangan membuka PO pelanggan dan klik 'Setujui DP', lalu menerbitkan faktur DP. 'pending_payment_confirm' → setelah uang masuk rekening Keuangan klik 'Ya — DP sudah diterima' dan proyek terbentuk; jika tidak pernah masuk mereka klik 'Tidak — DP tidak masuk' dengan alasan, yang bisa dilihat sales.",
  },
  {
    problem: "PO was rejected — why?",
    problem_id: "PO ditolak — kenapa?",
    answer: "Open the source quotation: the PO row shows the rejection reason in a red inline note, with the decided date. Or open the PO detail itself — same reason appears in the 'Director/Finance decision' card.",
    answer_id: "Buka penawaran sumber: baris PO menampilkan alasan penolakan dalam catatan merah inline, dengan tanggal keputusan. Atau buka detail PO — alasan yang sama muncul di kartu 'Keputusan Direktur/Keuangan'.",
  },
  {
    problem: "Employee missing KTP / NPWP / BPJS / contract",
    problem_id: "Karyawan belum punya KTP / NPWP / BPJS / kontrak",
    answer: "HR: open the employee profile → Employee documents card → the empty slot for the missing doc → Upload. Files are visible to HR, finance and management.",
    answer_id: "HR: buka profil karyawan → kartu Dokumen karyawan → slot kosong untuk dokumen yang hilang → Unggah. File terlihat oleh HR, keuangan, dan manajemen.",
  },
  {
    problem: "Admin can't see CRM / Finance anymore",
    problem_id: "Admin tidak lihat CRM / Keuangan lagi",
    answer: "That's the current scope. Admin's sidebar is ops-only: Projects, Operation board, Inventory, Attendance, Chat. Money pages live with Finance; customer-facing sales lives with Sales / Manager / Director.",
    answer_id: "Itu batas wilayah sekarang. Sidebar admin hanya operasi: Proyek, Papan Operasi, Inventaris, Absensi, Chat. Halaman uang ada di Keuangan; sisi pelanggan ada di Sales / Manajer / Direktur.",
  },
  {
    problem: "Sales can't create a quotation",
    problem_id: "Sales tidak bisa membuat penawaran",
    answer: "By design — quotations start from a Price request. File the PR on the customer page, purchasing/director price and approve it, then 'Generate quotation' from the approved PR.",
    answer_id: "Memang begitu — penawaran dimulai dari Permintaan Harga. Ajukan PR di halaman pelanggan, pembelian/direktur menghargai dan menyetujuinya, lalu 'Buat penawaran' dari PR yang disetujui.",
  },
  {
    problem: "Saved shipping dates but the timeline didn't change",
    problem_id: "Sudah simpan tanggal kirim tapi linimasa tidak berubah",
    answer: "Non-director date edits go to the director for approval first (customers see these dates). Check Approvals — the timeline updates the moment the director approves. Director edits apply instantly.",
    answer_id: "Perubahan tanggal oleh non-direktur masuk dulu ke direktur untuk persetujuan (pelanggan melihat tanggal ini). Cek Persetujuan — linimasa berubah begitu direktur menyetujui. Edit direktur langsung berlaku.",
  },
  {
    problem: "Sales can see the ops board but no action buttons",
    problem_id: "Sales melihat papan operasi tapi tanpa tombol aksi",
    answer: "Correct — sales gets a read-only view (customer / project / target-delivery / created). WO codes, notes and Advance/Done buttons are hidden. Advancing WOs is production's job.",
    answer_id: "Benar — sales dapat tampilan read-only (pelanggan / proyek / target kirim / tanggal dibuat). Kode WO, catatan, dan tombol Lanjutkan/Selesai disembunyikan. Menjalankan WO adalah tugas produksi.",
  },
  {
    problem: "Stage move stuck on amber 'awaiting approval'",
    problem_id: "Pindah tahap macet di kuning 'menunggu persetujuan'",
    answer: "Ping a Manager or the Director — manual stage moves need one of them to sign off in Approvals. (Deal documents advance the stage automatically when approved.)",
    answer_id: "Hubungi Manajer atau Direktur — pindah tahap manual butuh tanda tangan salah satunya di Persetujuan. (Dokumen deal memajukan tahap otomatis saat disetujui.)",
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
    answer: "Finance (or Director) → Payment verification. If the customer paid by transfer without the portal, finance skips the claim entirely: project → invoice card → 'Enter payment manually'.",
    answer_id: "Keuangan (atau Direktur) → Verifikasi pembayaran. Kalau pelanggan transfer tanpa portal, keuangan lewati klaim: proyek → kartu faktur → 'Masukkan pembayaran manual'.",
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

  // Non-directors are pinned to their own role guide — the director is
  // the only role that can browse every playbook via the tab strip.
  const isDirector = me?.role === "director";
  const effectiveKey: RoleKey = isDirector
    ? active
    : ((ROLES.find((r) => r.key === me?.role)?.key ?? active) as RoleKey);
  const section = ROLES.find((r) => r.key === effectiveKey) ?? ROLES[0];

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Map size={22} className="text-brand-600" /> {t("Role guide", "Panduan peran")}
          </h1>
          <p className="text-sm muted">
            {isDirector
              ? t(
                  "Pick any role to read its daily workflow, the buttons they'll touch, and the rules.",
                  "Pilih peran mana saja untuk membaca alur kerja harian, tombol yang dipakai, dan aturannya.",
                )
              : t(
                  "Your daily workflow, the buttons you'll touch, and the rules for your role.",
                  "Alur kerja harian Anda, tombol yang Anda pakai, dan aturan untuk peran Anda.",
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

      {/* Role tabs — each user only sees their own role guide. The
          director oversees the whole company, so they keep the full
          tab strip to read every role's playbook. */}
      {me?.role === "director" ? (
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
      ) : null}

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
      <div className="font-semibold mt-1 text-sm">{T(label)}</div>
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
      {lane("👤", "Sales", ["adds customer", "files price request → quote", "files customer PO (regular OR DP)", "confirms DP received"], "border-brand-200")}
      {arrow}
      {lane("📦", "Purchasing", ["prices the request", "raises supplier PO", "books origin shipment"], "border-orange-200")}
      {arrow}
      {lane("💰", "Finance", ["approves DP POs", "issues DP + final invoices", "verifies / records payments"], "border-amber-200")}
      {arrow}
      {lane("👑", "Director", ["approves quotes + regular POs", "regular PO → creates project", "approves supplier POs + date changes"], "border-red-200")}
      {arrow}
      {lane("🧑‍💼", "Admin", ["runs ops board", "drives projects", "stamps arrivals + delivery proof"], "border-violet-200")}
      {arrow}
      {lane("🏭", "Supplier", ["uploads drawing", "sets warehouse ETA"], "border-teal-200")}
      {arrow}
      {lane("🛠", "HR", ["employee docs (KTP/NPWP/BPJS)", "attendance", "payroll feed"], "border-emerald-200")}
    </div>
  );
}
