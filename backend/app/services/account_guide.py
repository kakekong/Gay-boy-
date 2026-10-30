"""How an account works — what it is, and exactly what moves it.

Every account's ledger page carries this guide. It is built from what the app
really does, not written once per account: the roles an account plays are
read live — the receivable a won quotation posts to, the stock account items
receive into, the bank customer payments land in, the accounts a salary or an
asset category names — so the guide follows when an account is reassigned.

Three parts:
- what the account is, by its type;
- what moves it up and down: the app's own postings for each role it plays
  (marked automatic, with where in the app it happens), then what can be done
  by hand;
- what a healthy balance looks like, and a warning when this one isn't.

Each text is in English and Indonesian; the page shows the user's language.
"""
from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.journal import CREDIT_NORMAL


def L(en: str, id_: str, *, auto: bool = False, where: tuple[str, str] | None = None) -> dict:
    out = {"en": en, "id": id_, "auto": auto}
    if where:
        out["where_en"], out["where_id"] = where
    return out


# ── What each type of account is, and what a healthy balance looks like ─────
TYPES: dict[str, dict] = {
    "Cash & Bank": {
        "what": L("Money the company holds: a bank account or a cash box. The balance should be what the bank statement or the cash count says.",
                  "Uang yang dimiliki perusahaan: rekening bank atau kas. Saldonya harus sama dengan rekening koran atau hitungan kas."),
        "healthy": L("Zero or above, and equal to the bank statement (Cash & bank › Rekening Koran).",
                     "Nol atau lebih, dan sama dengan rekening koran (Kas & bank › Rekening Koran)."),
        "min_zero": True,
    },
    "Receivable": {
        "what": L("Money owed to the company that hasn't been received yet. It is an asset: it is the company's money, just not in the bank.",
                  "Uang yang menjadi hak perusahaan tetapi belum diterima. Termasuk aset: uangnya milik perusahaan, hanya belum masuk bank."),
        "healthy": L("Zero or above. It should match what is still unpaid on invoices (Rekap Piutang).",
                     "Nol atau lebih. Harus sama dengan sisa tagihan yang belum dibayar (Rekap Piutang)."),
        "min_zero": True,
    },
    "Inventory": {
        "what": L("Goods the company owns and hasn't sold yet, at what they cost.",
                  "Barang milik perusahaan yang belum terjual, dinilai sebesar harga belinya."),
        "healthy": L("Zero or above — a warehouse can't hold less than nothing.",
                     "Nol atau lebih — gudang tidak bisa berisi kurang dari nol."),
        "min_zero": True,
    },
    "Other Current Asset": {
        "what": L("Other things of value the company will use or get back within a year: prepaid rent or insurance, office supplies, tax paid in advance (PPN Masukan, PPh), retention held by customers.",
                  "Aset lain yang akan dipakai atau kembali dalam setahun: sewa/asuransi dibayar dimuka, perlengkapan kantor, pajak dibayar dimuka (PPN Masukan, PPh), retensi."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": True,
    },
    "Fixed Asset": {
        "what": L("Things the company owns and uses for years — buildings, vehicles, equipment — at what they cost.",
                  "Barang milik perusahaan yang dipakai bertahun-tahun — gedung, kendaraan, peralatan — sebesar harga perolehannya."),
        "healthy": L("Zero or above: the cost of the assets still owned.",
                     "Nol atau lebih: harga perolehan aset yang masih dimiliki."),
        "min_zero": True,
    },
    "Accumulated Depreciation": {
        "what": L("How much of the fixed assets' cost has been used up so far. It reduces the assets on the balance sheet (cost − accumulated depreciation = book value).",
                  "Bagian harga aset tetap yang sudah terpakai sejauh ini. Mengurangi nilai aset di neraca (harga perolehan − akumulasi penyusutan = nilai buku)."),
        "healthy": L("Zero or above, and never more than the cost of the assets it belongs to.",
                     "Nol atau lebih, dan tidak pernah lebih besar dari harga perolehan asetnya."),
        "min_zero": True,
    },
    "Payable": {
        "what": L("Money the company owes and hasn't paid yet. It is a liability.",
                  "Uang yang menjadi kewajiban perusahaan dan belum dibayar. Termasuk kewajiban (utang)."),
        "healthy": L("Zero or above: what is still owed. Below zero means something was paid ahead — before it was owed.",
                     "Nol atau lebih: yang masih terutang. Di bawah nol artinya ada yang dibayar di muka — sebelum terutang."),
        "min_zero": True,
    },
    "Other Current Liability": {
        "what": L("Other amounts the company owes within a year: taxes collected or withheld and not yet paid over, salaries not yet paid, goods received and not yet invoiced.",
                  "Kewajiban lain yang jatuh tempo dalam setahun: pajak yang dipungut/dipotong dan belum disetor, gaji yang belum dibayar, barang diterima yang belum ditagih."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": True,
    },
    "Long Term Liability": {
        "what": L("Money the company owes over more than a year, such as a loan.",
                  "Utang perusahaan yang jatuh tempo lebih dari setahun, misalnya pinjaman."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": True,
    },
    "Equity": {
        "what": L("The owners' stake in the company: what was put in, plus the profit kept. Assets − liabilities = equity.",
                  "Bagian pemilik dalam perusahaan: modal yang disetor ditambah laba yang ditahan. Aset − kewajiban = ekuitas."),
        "healthy": L("Usually above zero.", "Biasanya di atas nol."),
        "min_zero": False,
    },
    "Revenue": {
        "what": L("What the company earned from selling — its sales. It belongs to the profit & loss: it adds to profit.",
                  "Pendapatan dari penjualan. Masuk laporan laba rugi: menambah laba."),
        "healthy": L("Above zero. A discount or returns account sits below zero — it reduces sales.",
                     "Di atas nol. Akun diskon atau retur bernilai di bawah nol — mengurangi penjualan."),
        "min_zero": False,
    },
    "Cost Of Good Sold": {
        "what": L("What the goods that were sold cost the company (HPP). It belongs to the profit & loss: sales − HPP = gross profit.",
                  "Harga pokok barang yang terjual (HPP). Masuk laporan laba rugi: penjualan − HPP = laba kotor."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": True,
    },
    "Expense": {
        "what": L("A cost of running the company — salaries, electricity, fuel, rent, depreciation. It belongs to the profit & loss: it reduces profit.",
                  "Biaya menjalankan perusahaan — gaji, listrik, bensin, sewa, penyusutan. Masuk laporan laba rugi: mengurangi laba."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": True,
    },
    "Other Income": {
        "what": L("Income from outside the main business — bank interest, selling old supplies, gains on assets.",
                  "Pendapatan di luar usaha utama — bunga bank, penjualan perlengkapan bekas, laba aset."),
        "healthy": L("Zero or above.", "Nol atau lebih."),
        "min_zero": False,
    },
    "Other Expense": {
        "what": L("Costs from outside the main business — bank charges, loan interest, exchange-rate losses.",
                  "Biaya di luar usaha utama — biaya administrasi bank, bunga pinjaman, rugi selisih kurs."),
        "healthy": L("Usually above zero; a gain shows as below zero.",
                     "Biasanya di atas nol; keuntungan tampil di bawah nol."),
        "min_zero": False,
    },
}

# ── What the app itself posts, per role an account plays ─────────────────────
QUOTE = ("Quotations › mark Won", "Penawaran › tandai Menang")
RATE = ("Purchasing PO › exchange rate", "PO pembelian › kurs")
QUOTE_EDIT = ("Quotations › edit a won quotation", "Penawaran › ubah penawaran Menang")
PAYMENTS = ("Finance › record payment / Payment verification",
            "Keuangan › catat pembayaran / Verifikasi pembayaran")
REVERSE = ("Invoice › reverse payment (director)", "Faktur › batalkan pembayaran (direktur)")
RECEIVE = ("Purchasing PO › receive goods", "PO pembelian › terima barang")
SUP_INV = ("Finance › Utang usaha › Supplier invoiced", "Keuangan › Utang usaha › Faktur pemasok")
SUP_PAY = ("Finance › Utang usaha › Pay", "Keuangan › Utang usaha › Bayar")
PAYROLL = ("Payroll › post / pay salary", "Penggajian › posting / bayar gaji")
ASSETS = ("Fixed assets › monthly depreciation run", "Aset tetap › proses penyusutan bulanan")

ROLES: dict[str, dict[str, list]] = {
    "receivable": {
        "up": [L("A quotation is marked Won: its whole total, including PPN.",
                 "Penawaran ditandai Menang: seluruh totalnya, termasuk PPN.", auto=True, where=QUOTE),
               L("A customer payment is reversed: the amount goes back to being owed.",
                 "Pembayaran pelanggan dibatalkan: jumlahnya kembali menjadi piutang.", auto=True, where=REVERSE)],
        "down": [L("A customer payment is recorded or verified: by the amount paid.",
                   "Pembayaran pelanggan dicatat atau diverifikasi: sebesar yang dibayar.", auto=True, where=PAYMENTS),
                 L("A won quotation is edited to a lower total: the difference is taken back.",
                   "Penawaran yang sudah Menang diubah menjadi lebih kecil: selisihnya dikurangi.", auto=True, where=QUOTE_EDIT)],
    },
    "sales": {
        "up": [L("A quotation is marked Won: the price before discount, on each item's Akun Penjualan.",
                 "Penawaran ditandai Menang: harga sebelum diskon, ke Akun Penjualan tiap barang.", auto=True, where=QUOTE)],
        "down": [L("A won quotation is edited to a lower total, or taken off the books.",
                   "Penawaran yang sudah Menang diubah menjadi lebih kecil, atau dibatalkan dari pembukuan.", auto=True, where=QUOTE_EDIT)],
    },
    "discount": {
        "up": [L("A won quotation's discount is taken off sales here — shown below zero, reducing Penjualan.",
                 "Diskon penawaran yang Menang dicatat di sini — bernilai minus, mengurangi Penjualan.", auto=True, where=QUOTE)],
        "down": [],
    },
    "ppn_out": {
        "up": [L("A quotation is marked Won: its PPN (the tax collected from the customer, owed to the state).",
                 "Penawaran ditandai Menang: PPN-nya (pajak yang dipungut dari pelanggan, terutang ke negara).", auto=True, where=QUOTE)],
        "down": [L("Paying the PPN to the tax office — by hand, as a Kas & Bank payment or a journal entry.",
                   "Menyetor PPN ke kantor pajak — manual, lewat Pembayaran Kas & Bank atau jurnal.")],
    },
    "inventory": {
        "up": [L("Goods are received on a purchasing PO: the value received (qty × price × the PO's rate), on each item's Akun Persediaan.",
                 "Barang diterima dari PO pembelian: nilai yang diterima (qty × harga × kurs PO), ke Akun Persediaan tiap barang.", auto=True, where=RECEIVE),
               L("A foreign PO's rate is set or raised: what was received is re-valued at it (nothing is booked before a foreign PO has a rate).",
                 "Kurs PO valas diisi atau dinaikkan: barang yang sudah diterima dinilai ulang dengan kurs itu (tidak ada yang dibukukan sebelum PO valas punya kurs).", auto=True, where=RATE),
               L("A paid job's payment is reversed: its cost comes back from HPP.",
                 "Pembayaran job yang lunas dibatalkan: biayanya kembali dari HPP.", auto=True, where=REVERSE)],
        "down": [L("Every invoice on the job is paid: the cost of what was received on its POs moves to HPP.",
                   "Semua faktur pada job lunas: biaya barang yang diterima dari PO-nya pindah ke HPP.", auto=True, where=PAYMENTS),
                 L("A receipt is corrected downward.", "Penerimaan barang dikoreksi turun.", auto=True, where=RECEIVE)],
    },
    "unbilled": {
        "up": [L("Goods are received on a purchasing PO and the supplier hasn't invoiced yet: owed, but not yet billed.",
                 "Barang diterima dari PO pembelian dan pemasok belum menagih: terutang, tetapi belum ditagih.", auto=True, where=RECEIVE),
               L("A foreign PO's rate is set or raised before the supplier invoices: re-valued at it.",
                 "Kurs PO valas diisi atau dinaikkan sebelum pemasok menagih: dinilai ulang dengan kurs itu.", auto=True, where=RATE)],
        "down": [L("Finance records the supplier's invoice: the amount moves to Utang Usaha.",
                   "Keuangan mencatat faktur pemasok: jumlahnya pindah ke Utang Usaha.", auto=True, where=SUP_INV),
                 L("A foreign PO's rate is lowered before the supplier invoices.",
                   "Kurs PO valas diturunkan sebelum pemasok menagih.", auto=True, where=RATE)],
    },
    "payable": {
        "up": [L("Finance records the supplier's invoice: what was received moves here from Hutang Pembelian Belum Ditagih.",
                 "Keuangan mencatat faktur pemasok: barang yang diterima pindah ke sini dari Hutang Pembelian Belum Ditagih.", auto=True, where=SUP_INV),
               L("Goods received before 27 Oct 2026 came straight here.",
                 "Barang yang diterima sebelum 27 Okt 2026 langsung masuk ke sini."),
               L("A foreign PO's rate is raised after the supplier invoiced: the unpaid part is re-valued (what's paid stays at its rate).",
                 "Kurs PO valas dinaikkan sesudah pemasok menagih: bagian yang belum dibayar dinilai ulang (yang sudah dibayar tetap dengan kursnya).", auto=True, where=RATE)],
        "down": [L("Finance pays the supplier: by the debt it settles (at the PO's rate on a foreign order).",
                   "Keuangan membayar pemasok: sebesar utang yang dilunasi (dengan kurs PO untuk order valas).", auto=True, where=SUP_PAY)],
    },
    "cogs": {
        "up": [L("Every invoice on the job is paid: the cost of what was received on its purchasing POs moves here from Persediaan. Goods received after that come straight here.",
                 "Semua faktur pada job lunas: biaya barang yang diterima dari PO pembelian pindah ke sini dari Persediaan. Barang yang diterima sesudahnya langsung ke sini.", auto=True, where=PAYMENTS)],
        "down": [L("A payment on the job is reversed (no longer fully paid), or the PO is cancelled: the cost goes back to Persediaan.",
                   "Pembayaran job dibatalkan (tidak lagi lunas), atau PO dibatalkan: biayanya kembali ke Persediaan.", auto=True, where=REVERSE)],
    },
    "customer_bank": {
        "up": [L("A customer payment is recorded or verified — customer payments land in this account.",
                 "Pembayaran pelanggan dicatat atau diverifikasi — pembayaran pelanggan masuk ke rekening ini.", auto=True, where=PAYMENTS)],
        "down": [L("A customer payment is reversed.", "Pembayaran pelanggan dibatalkan.", auto=True, where=REVERSE)],
    },
    "bank": {
        "up": [L("Money received at the Kas & Bank desk (Penerimaan), or a transfer in from another of our accounts.",
                 "Uang diterima lewat Kas & Bank (Penerimaan), atau transfer masuk dari rekening kita yang lain.", where=("Cash & bank", "Kas & bank"))],
        "down": [L("A supplier is paid from this account.", "Pemasok dibayar dari rekening ini.", auto=True, where=SUP_PAY),
                 L("A payment at the Kas & Bank desk (Pembayaran), or a transfer out.",
                   "Pembayaran lewat Kas & Bank (Pembayaran), atau transfer keluar.", where=("Cash & bank", "Kas & bank"))],
    },
    "fx": {
        "up": [L("A foreign supplier is paid at a worse rate than the PO was booked at — an exchange loss.",
                 "Pemasok valas dibayar dengan kurs lebih buruk dari kurs PO — rugi selisih kurs.", auto=True, where=SUP_PAY)],
        "down": [L("…or at a better rate — an exchange gain.",
                   "…atau dengan kurs lebih baik — laba selisih kurs.", auto=True, where=SUP_PAY)],
    },
    "opening_equity": {
        "up": [L("Opening balances are written down: the difference that makes the opening entry balance lands here.",
                 "Saldo awal dicatat: selisih yang menyeimbangkan jurnal saldo awal masuk ke sini.", auto=True,
                 where=("Journals › Opening balances", "Jurnal › Saldo awal"))],
        "down": [],
    },
    "payroll_expense": {
        "up": [L("A salary is posted: the gross salary.", "Gaji diposting: gaji bruto.", auto=True, where=PAYROLL)],
        "down": [L("A posted salary is reversed.", "Posting gaji dibatalkan.", auto=True, where=PAYROLL)],
    },
    "payroll_liability": {
        "up": [L("A salary is posted: the net pay the employee is owed.",
                 "Gaji diposting: gaji bersih yang terutang ke karyawan.", auto=True, where=PAYROLL)],
        "down": [L("The salary is paid out of the bank.", "Gaji dibayarkan dari bank.", auto=True, where=PAYROLL)],
    },
    "payroll_tax": {
        "up": [L("A salary is posted: the PPh 21 withheld from it.", "Gaji diposting: PPh 21 yang dipotong.", auto=True, where=PAYROLL)],
        "down": [L("Paying the PPh 21 to the tax office — by hand, as a Kas & Bank payment or a journal entry.",
                   "Menyetor PPh 21 ke kantor pajak — manual, lewat Pembayaran Kas & Bank atau jurnal.")],
    },
    "payroll_bank": {
        "up": [],
        "down": [L("Salaries are paid out of this account.", "Gaji dibayarkan dari rekening ini.", auto=True, where=PAYROLL)],
    },
    "dep_expense": {
        "up": [L("The monthly depreciation run: each asset's share of its cost for the month.",
                 "Proses penyusutan bulanan: bagian biaya aset untuk bulan itu.", auto=True, where=ASSETS)],
        "down": [],
    },
    "dep_accum": {
        "up": [L("The monthly depreciation run adds the month's depreciation.",
                 "Proses penyusutan bulanan menambah penyusutan bulan itu.", auto=True, where=ASSETS)],
        "down": [L("An asset is disposed of: what had built up on it comes off.",
                   "Aset dilepas: akumulasi penyusutannya dikeluarkan.", auto=True,
                   where=("Fixed assets › dispose", "Aset tetap › lepas aset"))],
    },
    "fixed_asset": {
        "up": [L("An asset is registered in this category: its cost.",
                 "Aset dicatat dalam kategori ini: harga perolehannya.", auto=True,
                 where=("Fixed assets › add asset", "Aset tetap › tambah aset"))],
        "down": [L("An asset is disposed of: its cost comes off.",
                   "Aset dilepas: harga perolehannya dikeluarkan.", auto=True,
                   where=("Fixed assets › dispose", "Aset tetap › lepas aset"))],
    },
}

BY_HAND_ALL = L(
    "By hand: a general journal entry (Jurnal Umum), or the director setting the balance on the Chart of Accounts (shown on the ledger as “Set by hand”).",
    "Manual: jurnal umum, atau direktur mengubah saldo di Akun Perkiraan (tampil di buku besar sebagai “Diisi manual”).")
BY_HAND_DESK = {
    "Expense": L("Paying this cost at the Kas & Bank desk (Pembayaran).",
                 "Membayar biaya ini lewat Kas & Bank (Pembayaran).", where=("Cash & bank", "Kas & bank")),
    "Other Expense": L("Paying this cost at the Kas & Bank desk (Pembayaran).",
                       "Membayar biaya ini lewat Kas & Bank (Pembayaran).", where=("Cash & bank", "Kas & bank")),
    "Other Income": L("Receiving this income at the Kas & Bank desk (Penerimaan).",
                      "Menerima pendapatan ini lewat Kas & Bank (Penerimaan).", where=("Cash & bank", "Kas & bank")),
}


async def _roles(db: AsyncSession, acc: Account) -> list[str]:
    """Which of the app's own postings reach this account, read live."""
    from app.services import ledger
    from app.services import item_accounts as ia
    from app.services.financials import EARNINGS_ACCOUNT
    no = acc.account_no
    roles: list[str] = []

    def has(*nos):
        return no in {n for n in nos if n}

    # Won quotations — their own account choices as well as the defaults.
    from app.models.quotation import Quotation
    q = {k: set((await db.scalars(select(distinct(getattr(Quotation, f"account_{k}_no"))))).all())
         | {ledger.DEFAULTS[k]} for k in ("receivable", "revenue", "discount", "tax")}
    # Items' own accounts, and the defaults items take.
    dflt = await ia.defaults(db)
    from app.models.inventory import InventoryItem
    items = {f: set((await db.scalars(select(distinct(getattr(InventoryItem, f))))).all()) | {dflt[f]}
             for f in ("acc_inventory", "acc_sales", "acc_sales_discount", "acc_cogs", "acc_unbilled")}

    if no in q["receivable"] or has(ledger.PAYMENT_RECEIVABLE):
        roles.append("receivable")
    if no in q["revenue"] or no in items["acc_sales"]:
        roles.append("sales")
    if no in q["discount"] or no in items["acc_sales_discount"]:
        roles.append("discount")
    if no in q["tax"]:
        roles.append("ppn_out")
    if no in items["acc_inventory"] or has(ledger.INVENTORY_ACCOUNT):
        roles.append("inventory")
    if no in items["acc_unbilled"] or has(ledger.UNBILLED_ACCOUNT):
        roles.append("unbilled")
    if has(ledger.PAYABLE_ACCOUNT):
        roles.append("payable")
    if no in items["acc_cogs"] or has(ledger.COGS_ACCOUNT, await ledger._cogs_account(db)):
        roles.append("cogs")
    if has(ledger.FX_REALISED_ACCOUNT):
        roles.append("fx")
    if acc.account_type == "Cash & Bank":
        if has(ledger.PAYMENT_CASH_DEFAULT):
            roles.append("customer_bank")
        roles.append("bank")
    from app.services.journal import OPENING_EQUITY
    if has(OPENING_EQUITY):
        roles.append("opening_equity")

    # Payroll: the accounts salaries name, and the defaults.
    from app.api.v1.endpoints.salaries import DEFAULTS as PAY
    from app.models.salary import Salary
    for field, key, role in (("account_expense_no", "expense", "payroll_expense"),
                             ("account_liability_no", "liability", "payroll_liability"),
                             ("account_tax_no", "tax", "payroll_tax"),
                             ("account_bank_no", "bank", "payroll_bank")):
        used = set((await db.scalars(select(distinct(getattr(Salary, field))))).all()) | {PAY[key]}
        if no in used:
            roles.append(role)

    # Fixed assets: the accounts each category names.
    from app.models.asset import AssetCategory
    for field, role in (("asset_account_no", "fixed_asset"), ("accum_account_no", "dep_accum"),
                        ("expense_account_no", "dep_expense")):
        if await db.scalar(select(func.count()).select_from(AssetCategory)
                           .where(getattr(AssetCategory, field) == no)):
            roles.append(role)

    if no == EARNINGS_ACCOUNT:
        roles = ["earnings"]
    return roles


async def _receivable_check(db: AsyncSession, balance: float) -> dict:
    """Piutang against what is really still unpaid on invoices."""
    from app.models.finance import OUTSTANDING_INVOICE_STATUSES, Invoice, Payment
    billed = float(await db.scalar(select(func.coalesce(func.sum(Invoice.total), 0))
                                   .where(Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES))) or 0)
    paid = float(await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES))) or 0)
    unpaid = round(billed - paid, 2)
    return {"unpaid_invoices": unpaid, "balance": round(balance, 2),
            "difference": round(balance - unpaid, 2)}


async def guide_for(db: AsyncSession, acc: Account, balance: float) -> dict:
    t = TYPES.get(acc.account_type, {
        "what": L("An account in the chart.", "Akun di bagan akun."),
        "healthy": L("—", "—"), "min_zero": False})
    roles = await _roles(db, acc)
    up_side = "credit" if acc.account_type in CREDIT_NORMAL else "debit"

    if roles == ["earnings"]:
        return {
            "what": L("Laba/Rugi Tahun Berjalan: all revenue less all costs and expenses, worked out from the balances each time it is read.",
                      "Laba/Rugi Tahun Berjalan: semua pendapatan dikurangi semua HPP dan beban, dihitung dari saldo setiap kali dibuka."),
            "up_side": up_side, "roles": roles,
            "up": [L("Any sale, or other income, adds to it — through the revenue accounts.",
                     "Setiap penjualan atau pendapatan lain menambahnya — lewat akun pendapatan.", auto=True)],
            "down": [L("Any cost or expense reduces it — through the HPP and expense accounts.",
                       "Setiap HPP atau beban menguranginya — lewat akun HPP dan beban.", auto=True)],
            "by_hand": [L("Nothing is ever posted to it — not by the app, not by a journal, not by hand.",
                          "Tidak pernah ada yang diposting ke akun ini — tidak oleh aplikasi, jurnal, maupun manual.")],
            "healthy": L("Above zero is a profit, below zero a loss.", "Di atas nol laba, di bawah nol rugi."),
            "warning": None, "check": None,
        }

    up, down = [], []
    for r in roles:
        up += ROLES[r]["up"]
        down += ROLES[r]["down"]
    by_hand = [BY_HAND_ALL] + ([BY_HAND_DESK[acc.account_type]] if acc.account_type in BY_HAND_DESK else [])
    if not up and not down:
        by_hand.insert(0, L("The app never posts to this account by itself — only what is done by hand moves it.",
                            "Aplikasi tidak pernah memposting ke akun ini sendiri — hanya transaksi manual yang menggerakkannya."))

    warning = None
    check = None
    if "receivable" in roles:
        check = await _receivable_check(db, balance)
    if t["min_zero"] and balance < -0.5 and not ("discount" in roles):
        if "receivable" in roles:
            warning = L(
                "Below zero: more was received than was ever booked as owed. Usual causes: payments left behind by deleted test invoices (Chart of Accounts › Left behind), invoices billed for more than the won quotation, or invoices on deals with no won quotation.",
                "Di bawah nol: yang diterima lebih besar dari yang pernah dicatat sebagai piutang. Penyebab umum: pembayaran sisa faktur uji yang dihapus (Akun Perkiraan › Sisa terhapus), faktur lebih besar dari penawaran yang Menang, atau faktur tanpa penawaran Menang.")
        elif acc.account_type == "Payable":
            warning = L("Below zero: more was paid than is owed — a payment ahead of the goods, or a supplier invoice not yet recorded.",
                        "Di bawah nol: dibayar lebih dari yang terutang — pembayaran di muka, atau faktur pemasok belum dicatat.")
        else:
            warning = L("Below zero, which this kind of account shouldn't be. Open the lines below to find what took it there.",
                        "Di bawah nol, padahal akun jenis ini seharusnya tidak. Periksa baris di bawah untuk menemukan penyebabnya.")
    return {"what": t["what"], "up_side": up_side, "roles": roles,
            "up": up, "down": down, "by_hand": by_hand,
            "healthy": t["healthy"], "warning": warning, "check": check}
