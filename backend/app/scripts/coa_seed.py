"""Chart of Accounts — full seed data.

Each entry: (account_no, name, account_type, parent_account_no, is_parent, level)
Tax accounts are flagged via the TAX_ACCOUNTS set below.
"""

TAX_ACCOUNTS: set[str] = {
    # Asset-side tax credits
    "1105-04", "1105-05", "1105-08",
    # Liability-side tax payable
    "2102-01", "2102-04", "2102-05", "2102-06",
    # Expense-side
    "6000-17", "6000-20", "6000-25",
    # Other-expense
    "7200-03",
}


COA_SEED: list[tuple[str, str, str, str | None, bool, int]] = [
    # ─── ASSETS ──────────────────────────────────────────────────────────────
    # 1101 Bank
    ("1101",    "Bank",                              "Cash & Bank", None,   True,  0),
    ("1101-01", "Bank Bca Ac 5785523889",            "Cash & Bank", "1101", False, 1),
    ("1101-02", "Bank Bni",                          "Cash & Bank", "1101", False, 1),
    ("1101-03", "Bank Ocbc",                         "Cash & Bank", "1101", False, 1),
    ("1101-04", "Bank Panin",                        "Cash & Bank", "1101", False, 1),
    ("1101-05", "Bank KK Bca",                       "Cash & Bank", "1101", False, 1),

    # 1102 Kas
    ("1102",    "Kas",                               "Cash & Bank", None,   True,  0),
    ("1102-01", "Kas Kecil",                         "Cash & Bank", "1102", False, 1),
    ("1102-02", "Kas Besar",                         "Cash & Bank", "1102", False, 1),
    ("1102-03", "Kas Jaminan Penawaran",             "Cash & Bank", "1102", False, 1),
    ("1102-04", "Kas Jaminan Pelaksana",             "Cash & Bank", "1102", False, 1),

    # 1103 Piutang Usaha
    ("1103",    "Piutang Usaha",                     "Receivable",  None,   True,  0),
    ("110301",  "Piutang Usaha IDR",                 "Receivable",  "1103", False, 1),
    ("110302",  "Uang Muka Pembelian IDR",           "Receivable",  "1103", False, 1),

    # 1104 Persediaan
    ("1104",    "Persediaan",                        "Inventory",   None,   True,  0),
    ("110401",  "Persediaan",                        "Inventory",   "1104", False, 1),
    ("110402",  "Persediaan Terkirim",               "Inventory",   "1104", False, 1),

    # 1105 Aset Lancar Lainnya
    ("1105",    "Aset Lancar Lainnya",               "Other Current Asset", None,   True,  0),
    ("1105-01", "Perlengkapan Kantor",               "Other Current Asset", "1105", False, 1),
    ("1105-02", "Sewa Gedung Dibayar Dimuka",        "Other Current Asset", "1105", False, 1),
    ("1105-03", "Asuransi Dibayar Dimuka",           "Other Current Asset", "1105", False, 1),
    ("1105-04", "PPN Masukan",                       "Other Current Asset", "1105", False, 1),
    ("1105-05", "PPh 26 Penjualan",                  "Other Current Asset", "1105", False, 1),
    ("1105-06", "Pembelian Aset",                    "Other Current Asset", "1105", False, 1),
    ("1105-07", "Retensi",                           "Other Current Asset", "1105", False, 1),
    ("1105-08", "PPH 25-29 (411126) TRANSMISI SETIAP BULAN", "Other Current Asset", "1105", False, 1),

    # 1200 Aset Tetap
    ("1200",    "Aset Tetap",                        "Fixed Asset", None,   True,  0),
    ("1200-01", "Gedung",                            "Fixed Asset", "1200", False, 1),
    ("1200-02", "Kendaraan Hyundai Creta",           "Fixed Asset", "1200", False, 1),
    ("1200-03", "Kendaraan Aeon",                    "Fixed Asset", "1200", False, 1),
    ("1200-04", "Peralatan",                         "Fixed Asset", "1200", False, 1),
    ("1200-05", "Kendaraan Mobil Wrv Honda",         "Fixed Asset", "1200", False, 1),

    # 1201 Akumulasi Depresiasi
    ("1201",    "Akumulasi Depresiasi Aset Tetap",   "Accumulated Depreciation", None,   True,  0),
    ("1201-01", "Akumulasi Penyusutan Gedung",       "Accumulated Depreciation", "1201", False, 1),
    ("1201-02", "Akumulasi Penyusutan Kendaraan",    "Accumulated Depreciation", "1201", False, 1),
    ("1201-03", "Akumulasi Penyusutan Peralatan",    "Accumulated Depreciation", "1201", False, 1),
    ("1201-04", "Akumulasi Penyusutan Inventaris Kantor", "Accumulated Depreciation", "1201", False, 1),

    # ─── LIABILITIES ─────────────────────────────────────────────────────────
    # 2101 Utang Usaha
    ("2101",    "Utang Usaha",                       "Payable",     None,   True,  0),
    ("210101",  "Utang Usaha IDR",                   "Payable",     "2101", False, 1),
    ("210102",  "Uang Muka Penjualan IDR",           "Payable",     "2101", False, 1),

    # 2102 Kewajiban Jangka Pendek Lainnya
    ("2102",    "Kewajiban Jangka Pendek Lainnya",   "Other Current Liability", None,   True,  0),
    ("2102-01", "PPN Keluaran",                      "Other Current Liability", "2102", False, 1),
    ("2102-02", "Hutang Gaji Karyawan",              "Other Current Liability", "2102", False, 1),
    ("2102-03", "Hutang Pembelian Belum Ditagih",    "Other Current Liability", "2102", False, 1),
    ("2102-04", "Hutang Pph 21 Pt.Transmisi Enjinering", "Other Current Liability", "2102", False, 1),
    ("2102-05", "Hutang Pph 25-29 (411126) Pt.Transmisi Enjinering Per bulan",
                                                     "Other Current Liability", "2102", False, 1),
    ("2102-06", "Hutang Pph 25-29 (411126) Pt. Transmisi Enjinering Per Tahun",
                                                     "Other Current Liability", "2102", False, 1),

    # 2201 Hutang Jangka Panjang
    ("2201",    "Hutang Jangka Panjang",             "Long Term Liability", None, True, 0),

    # ─── EQUITY ──────────────────────────────────────────────────────────────
    ("3000",    "Modal",                             "Equity",      None,   True,  0),
    ("300001",  "Equitas Saldo Awal",                "Equity",      "3000", False, 1),
    ("300002",  "Laba Ditahan",                      "Equity",      "3000", False, 1),
    ("300003",  "Modal Saham",                       "Equity",      "3000", False, 1),

    # ─── REVENUE ─────────────────────────────────────────────────────────────
    ("4000",    "Pendapatan Operasional",            "Revenue",     None,   True,  0),
    ("400001",  "Penjualan",                         "Revenue",     "4000", False, 1),
    ("400003",  "Retur Penjualan",                   "Revenue",     "4000", False, 1),
    ("400004",  "Diskon Penjualan",                  "Revenue",     "4000", False, 1),

    ("4401",    "Diskon Penjualan Retensi",          "Revenue",     None,   True,  0),
    ("4401-01", "Diskon Penjualan Retensi",          "Revenue",     "4401", False, 1),

    # ─── COGS ────────────────────────────────────────────────────────────────
    ("5101",    "Beban Pokok Penjualan",             "Cost Of Good Sold", None, True, 0),

    # ─── EXPENSES ────────────────────────────────────────────────────────────
    ("6000",    "Beban Operasional",                 "Expense",     None,   True,  0),
    ("6000-01", "Beban IPL Ruko Osaka",              "Expense",     "6000", False, 1),
    ("6000-02", "Beban Komisi Penjualan Sales",      "Expense",     "6000", False, 1),
    ("6000-03", "Beban Bensin, Parkir, Tol Kendaraan", "Expense",   "6000", False, 1),
    ("6000-04", "Beban Gaji Karyawan",               "Expense",     "6000", False, 1),
    ("6000-05", "Beban Bonus, Pesangon & Kompensasi", "Expense",    "6000", False, 1),
    ("6000-06", "Beban Transportasi Karyawan",       "Expense",     "6000", False, 1),
    ("6000-07", "Beban Katering & Makan Karyawan",   "Expense",     "6000", False, 1),
    ("6000-08", "Beban Tunjangan Kesehatan",         "Expense",     "6000", False, 1),
    ("6000-09", "Beban Bpjs Karyawan",               "Expense",     "6000", False, 1),
    ("6000-10", "Beban THR",                         "Expense",     "6000", False, 1),
    ("6000-11", "Beban Listrik",                     "Expense",     "6000", False, 1),
    ("6000-12", "Beban Retensi 5%",                  "Expense",     "6000", False, 1),
    ("6000-13", "Beban Telekomunikasi",              "Expense",     "6000", False, 1),
    ("6000-14", "Beban Ekspedisi Customer Luar Kota", "Expense",    "6000", False, 1),
    ("6000-15", "Beban Perjalanan Dinas",            "Expense",     "6000", False, 1),
    ("6000-16", "Beban Perlengkapan Kantor",         "Expense",     "6000", False, 1),
    ("6000-17", "Beban Urus Laporan Pajak",          "Expense",     "6000", False, 1),
    ("6000-18", "Beban Ekspedisi Pembelian",         "Expense",     "6000", False, 1),
    ("6000-19", "Beban Sewa Virtual Office",         "Expense",     "6000", False, 1),
    ("6000-20", "Tunjangan Pajak Pph 21 Karyawan",   "Expense",     "6000", False, 1),
    ("6000-21", "Beban Penyusutan Gedung",           "Expense",     "6000", False, 1),
    ("6000-22", "Beban Penyusutan Kendaraan",        "Expense",     "6000", False, 1),
    ("6000-23", "Beban Penyusutan Peralatan",        "Expense",     "6000", False, 1),
    ("6000-24", "Beban Penyusutan Inventaris Kantor", "Expense",    "6000", False, 1),
    ("6000-25", "Beban Pajak SPT 1771 (411126 PPH 25/29 Badan)", "Expense", "6000", False, 1),
    ("6000-27", "Biaya Perawatan Mobil Hrv",         "Expense",     "6000", False, 1),
    ("6000-28", "Biaya Perawatan Mobil Vw",          "Expense",     "6000", False, 1),
    ("6000-29", "Biaya Entertainment",               "Expense",     "6000", False, 1),
    ("6000-30", "By Sewa Forklift",                  "Expense",     "6000", False, 1),
    ("6000-31", "By Lain Lain",                      "Expense",     "6000", False, 1),
    ("6000-32", "Biaya Asuransi Mobil",              "Expense",     "6000", False, 1),
    ("6000-33", "Biaya Stnk Kendaraan",              "Expense",     "6000", False, 1),
    ("6000-34", "Biaya Website Transmisi",           "Expense",     "6000", False, 1),

    # ─── OTHER INCOME ────────────────────────────────────────────────────────
    ("7100",    "Pendapatan Diluar Usaha",           "Other Income", None,   True,  0),
    ("7100-01", "Pendapatan Jasa Giro",              "Other Income", "7100", False, 1),
    ("7100-02", "Pendapatan Bunga Deposito",         "Other Income", "7100", False, 1),
    ("7100-03", "Penjualan Persediaan / Perlengkapan", "Other Income", "7100", False, 1),
    ("7100-04", "Laba/Rugi Revaluasi Aset",          "Other Income", "7100", False, 1),
    ("7100-05", "Pendapatan Diluar Usaha Lainnya",   "Other Income", "7100", False, 1),

    # ─── OTHER EXPENSE ───────────────────────────────────────────────────────
    ("7200",    "Beban Diluar Usaha",                "Other Expense", None,   True,  0),
    ("7200-01", "Beban Bunga Pinjaman",              "Other Expense", "7200", False, 1),
    ("7200-02", "Beban Adm. Bank & Buku Cek/Giro",   "Other Expense", "7200", False, 1),
    ("7200-03", "Pajak Jasa Giro",                   "Other Expense", "7200", False, 1),
    ("7200-04", "Laba/Rugi Terealisasi",             "Other Expense", "7200", False, 1),
    ("7200-05", "Laba/Rugi Belum Terealisasi",       "Other Expense", "7200", False, 1),
    ("7200-06", "Laba/Rugi Disposisi Aset",          "Other Expense", "7200", False, 1),
    ("7200-07", "Beban Diluar Usaha Lainnya",        "Other Expense", "7200", False, 1),

    ("7201",    "Laba/Rugi Terealisasi",             "Other Expense", None,   True,  0),
    ("720101",  "Laba/Rugi Terealisasi IDR",         "Other Expense", "7201", False, 1),

    ("7202",    "Laba/Rugi Belum Terealisasi",       "Other Expense", None,   True,  0),
    ("720201",  "Laba/Rugi Belum Terealisasi IDR",   "Other Expense", "7202", False, 1),
]


async def seed_coa(db) -> int:
    """Idempotent seed: only insert accounts that don't already exist."""
    from sqlalchemy import select
    from app.models.account import Account

    existing_nos = set((await db.scalars(select(Account.account_no))).all())
    created = 0
    for no, name, atype, parent, is_parent, level in COA_SEED:
        if no in existing_nos:
            continue
        db.add(Account(
            account_no=no,
            name=name,
            account_type=atype,
            parent_account_no=parent,
            is_parent=is_parent,
            level=level,
            is_tax=no in TAX_ACCOUNTS,
            balance=0,
            is_suspended=False,
        ))
        created += 1
    await db.flush()
    return created
