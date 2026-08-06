"""Read an Accurate "Daftar Akun" export and map it onto our Account rows.

Most of this file is already in the app. The chart of accounts was seeded from
this same company's books (`app/scripts/coa_seed.py`), so a fresh export mostly
confirms what is there — which is the useful part. What matters is the residue:
the handful of accounts the seed never had, and the accounts whose name has
since drifted apart between the two systems.

Names that differ are **reported, never applied**. An account number is
referenced by posted ledger entries and by the account_*_no columns on
quotations and invoices; quietly renaming one because a spreadsheet spelled it
differently would rewrite the labels on financial statements that have already
been read and signed off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Accurate's four-letter type codes → the account-type strings the app's
# financial statements classify on (see `services/financials.py`). A code we
# have never seen is reported rather than guessed at, because the wrong one
# puts the account on the wrong side of the balance sheet.
TYPE_MAP = {
    "BANK": "Cash & Bank",
    "AREC": "Receivable",
    "INTR": "Inventory",
    "OCAS": "Other Current Asset",
    "FASS": "Fixed Asset",
    "DEPR": "Accumulated Depreciation",
    "APAY": "Payable",
    "OCLY": "Other Current Liability",
    "LTLY": "Long Term Liability",
    "EQTY": "Equity",
    "REVE": "Revenue",
    "OINC": "Other Income",
    "COGS": "Cost Of Good Sold",
    "EXPS": "Expense",
    "OEXP": "Other Expense",
}

COLUMNS = {
    "account_type": ["tipe akun", "account type"],
    "account_no": ["kode perkiraan", "kode akun", "account no"],
    "name": ["nama", "name"],
    "parent": ["akun induk", "parent account"],
    "currency": ["mata uang", "currency"],
    "opening_balance": ["saldo awal", "opening balance"],
    "notes": ["catatan", "notes"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _money(v: str | None) -> float:
    s = (_clean(v) or "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


@dataclass
class MappedAccount:
    row_no: int
    account_no: str
    name: str
    account_type: str
    parent_account_no: str | None = None
    is_parent: bool = False
    level: int = 0
    balance: float = 0.0
    is_tax: bool = False
    description: str | None = None
    warnings: list[str] = field(default_factory=list)


def _header_index(header: list[str]) -> dict[str, int]:
    norm = [_norm(h) for h in header]
    out: dict[str, int] = {}
    for field_name, candidates in COLUMNS.items():
        for cand in candidates:
            if cand in norm:
                out[field_name] = norm.index(cand)
                break
    return out


def map_accounts(header: list[str], rows: list[list[str]]) -> tuple[list[MappedAccount], list[str]]:
    from app.scripts.coa_seed import TAX_ACCOUNTS

    idx = _header_index(header)
    problems: list[str] = []
    for need, label in (("account_no", "Kode Perkiraan"), ("name", "Nama")):
        if need not in idx:
            problems.append(
                f"Could not find the '{label}' column. Is this the Daftar Akun export?")
    if problems:
        return [], problems
    if "account_type" not in idx:
        problems.append(
            "No 'Tipe Akun' column — without it an account cannot be placed on "
            "the balance sheet or the profit and loss, so nothing will import.")
        return [], problems

    def cell(row: list[str], key: str) -> str | None:
        i = idx.get(key)
        if i is None or i >= len(row):
            return None
        return _clean(row[i])

    # `is_parent` is a fact about the file, not about any one row: an account
    # is a parent because something else points at it.
    parents = {cell(r, "parent") for r in rows if cell(r, "parent")}

    out: list[MappedAccount] = []
    for n, row in enumerate(rows, start=2):
        no, name = cell(row, "account_no"), cell(row, "name")
        if not no or not name:
            continue
        warnings: list[str] = []

        raw_type = (cell(row, "account_type") or "").upper()
        acc_type = TYPE_MAP.get(raw_type)
        if not acc_type:
            warnings.append(
                f"unknown account type '{raw_type or '(blank)'}' — this account "
                f"would not appear on any financial statement, so it is skipped")
            continue

        cur = (cell(row, "currency") or "IDR").upper()
        if cur != "IDR":
            warnings.append(f"currency is {cur}; the app keeps accounts in IDR")

        parent = cell(row, "parent")
        out.append(MappedAccount(
            row_no=n,
            account_no=no,
            name=name,
            account_type=acc_type,
            parent_account_no=parent,
            is_parent=no in parents,
            level=0 if not parent else 1,
            balance=_money(cell(row, "opening_balance")),
            is_tax=no in TAX_ACCOUNTS,
            description=cell(row, "notes"),
            warnings=warnings,
        ))
    return out, problems
