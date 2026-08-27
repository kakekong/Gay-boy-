"""Master data for the tax and payroll sides of the books.

Two lists a company sets up once and then uses everywhere.

**Pajak.** Indonesian tax on a sale or a purchase is not one rate — PPN,
PPnBM, and the withholding articles (PPh Ps.4(2), 15, 21, 22, 23) each land
in a different account and are reported on a different form. What makes this
master data rather than a number typed on an invoice is the pair of accounts:
the same tax has one account when we charge it (pajak keluaran) and another
when we are charged it (pajak masukan), and getting that pair wrong is a tax
return that does not reconcile.

**Gaji/Tunjangan.** A payroll line is not just an amount. The fourteen types
here are the ones the PPh 21 form distinguishes, and the distinction is the
whole point: a bonus is taxed differently from a salary, an employer-paid
pension contribution is income to the employee, a salary deduction may or
may not reduce taxable income depending on which kind it is. Each component
carries which type it is, and its type decides whether it is paid or
deducted and whether it moves the tax base — so payroll can compute rather
than being told.
"""

from uuid import UUID

from sqlalchemy import Boolean, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

# The tax types as the forms name them. The key is what we store; the label
# is what the dropdown shows, in the words the tax office uses.
TAX_KINDS: dict[str, str] = {
    "ppn":       "Pajak Pertambahan Nilai",
    "ppnbm":     "Pajak Pertambahan Barang Mewah",
    "pph_4_2":   "Pajak Penghasilan Ps.4(2)",
    "pph_15":    "Pajak Penghasilan Ps.15",
    "pph_21":    "Pajak Penghasilan Ps.21",
    "pph_22":    "Pajak Penghasilan Ps.22",
    "pph_23":    "Pajak Penghasilan Ps.23",
}


class TaxType(Base, UUIDPK, TimestampMixin):
    __tablename__ = "tax_types"

    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # "Keterangan" — what this one is for, in the company's own words:
    # "PPN Keluaran 11%", "PPh 23 jasa 2%".
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_pct: Mapped[float] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    # The pair that makes this master data. Sales tax is what we charge a
    # customer; purchase tax is what a supplier charges us. Same tax, two
    # accounts, and mixing them up is a return that will not reconcile.
    sales_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    purchase_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


# Every payroll component the PPh 21 form distinguishes, and what each one
# does. `pay` means it adds to what the employee receives; `deduct` takes
# away. `taxable` says whether it enters the PPh 21 base — which is the
# reason these are types rather than free text, because two deductions that
# look identical on a payslip can differ on exactly that.
PAY_KINDS: dict[str, dict] = {
    "gaji":            {"label": "Gaji/Pensiun atau THT/JHT",
                        "direction": "pay", "taxable": True, "regular": True},
    "tunjangan_pph":   {"label": "Tunjangan PPh",
                        "direction": "pay", "taxable": True, "regular": True},
    "subsidi_pph":     {"label": "Subsidi PPh",
                        "direction": "pay", "taxable": True, "regular": True},
    "tunjangan_lain":  {"label": "Tunjangan Lainnya, Uang lembur dan sebagainya",
                        "direction": "pay", "taxable": True, "regular": True},
    "tunjangan_jkk":   {"label": "Tunjangan Jaminan Kecelakaan Kerja, Jaminan Kematian",
                        "direction": "pay", "taxable": True, "regular": True},
    "honorarium":      {"label": "Honorarium dan Imbalan lain sejenisnya",
                        "direction": "pay", "taxable": True, "regular": True},
    "premi_pemberi":   {"label": "Premi asuransi kesehatan yang dibayarkan pemberi kerja",
                        "direction": "pay", "taxable": True, "regular": True},
    "natura":          {"label": "Penerimaan dalam bentuk natura dan kenikmatan lainnya",
                        "direction": "pay", "taxable": True, "regular": True},
    "tantiem":         {"label": "Tantiem, Bonus, Rapel, Gratifikasi, Jasa Produksi dan THR",
                        # Irregular income: taxed, but not part of the
                        # monthly run — which is why it is its own type.
                        "direction": "pay", "taxable": True, "regular": False},
    "iuran_pemberi":   {"label": "Tunjangan Iuran Pensiun/THT/JHT dibayarkan Pemberi Kerja",
                        "direction": "pay", "taxable": True, "regular": True},
    "potongan":        {"label": "Potongan Gaji (Tidak Mengurangi PPh)",
                        "direction": "deduct", "taxable": False, "regular": True},
    "pengurangan":     {"label": "Pengurangan Gaji (Mengurangi PPh)",
                        "direction": "deduct", "taxable": True, "regular": True},
    "premi_pekerja":   {"label": "Premi asuransi kesehatan dibayarkan pekerja",
                        "direction": "deduct", "taxable": False, "regular": True},
    "iuran_pekerja":   {"label": "Iuran Pensiun/THT/JHT dibayarkan Pekerja",
                        "direction": "deduct", "taxable": True, "regular": True},
}


class PayComponent(Base, UUIDPK, TimestampMixin):
    __tablename__ = "pay_components"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # Where it lands in the books. A salary is an expense; so is the
    # employer's half of a pension contribution. A deduction that is held
    # and paid on (tax withheld, the employee's BPJS share) is a liability
    # until it is handed over, which is why this is an account rather than
    # an assumption.
    account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    # A default, when a component is the same for everyone — the employee's
    # own figure still wins.
    default_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
