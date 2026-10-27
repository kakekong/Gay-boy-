"""Each item's accounts — Accurate's Akun-Akun tab.

Finance keeps the books the Accurate way: every barang carries the accounts
its movements post to. Seven of them:

  acc_inventory        Akun Persediaan            110401 Persediaan
  acc_sales            Akun Penjualan             400001 Penjualan
  acc_sales_return     Akun Ret. Penjualan        400003 Retur Penjualan
  acc_sales_discount   Akun Disk. Penjualan       400004 Diskon Penjualan
  acc_cogs             Akun HPP                   5101   Beban Pokok Penjualan
  acc_purchase_return  Akun Ret. Pembelian        110401 Persediaan
  acc_unbilled         Akun Belum Tertagih        2102-03 Hutang Pembelian Belum Ditagih

An item with an account left empty uses the company default, kept in
app_settings under `item_accounts` ("Set sbg Default" saves an item's
accounts as it). The returns accounts are kept for the day returns are
recorded here; nothing posts to them yet.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account

FIELDS: list[tuple[str, str, str]] = [
    ("acc_inventory", "Akun Persediaan", "110401"),
    ("acc_sales", "Akun Penjualan", "400001"),
    ("acc_sales_return", "Akun Ret. Penjualan", "400003"),
    ("acc_sales_discount", "Akun Disk. Penjualan", "400004"),
    ("acc_cogs", "Akun HPP", "5101"),
    ("acc_purchase_return", "Akun Ret. Pembelian", "110401"),
    ("acc_unbilled", "Akun Belum Tertagih", "2102-03"),
]
NAMES = [f for f, _, _ in FIELDS]

# The kinds of account each one can be, as Accurate offers them: stock on a
# stock account, sales on a revenue account, cost on a cost account, what is
# owed on a liability.
TYPES: dict[str, tuple[str, ...]] = {
    "acc_inventory": ("Inventory",),
    "acc_purchase_return": ("Inventory",),
    "acc_sales": ("Revenue", "Other Income"),
    "acc_sales_return": ("Revenue", "Other Income"),
    "acc_sales_discount": ("Revenue", "Other Income", "Expense"),
    "acc_cogs": ("Cost Of Good Sold", "Expense"),
    "acc_unbilled": ("Payable", "Other Current Liability"),
}
SETTING = "item_accounts"


async def defaults(db: AsyncSession) -> dict[str, str]:
    from app.models.app_setting import AppSetting
    row = await db.get(AppSetting, SETTING)
    saved = dict(row.value or {}) if row else {}
    return {f: (saved.get(f) or d) for f, _, d in FIELDS}


async def set_defaults(db: AsyncSession, values: dict[str, str]) -> dict[str, str]:
    from app.models.app_setting import AppSetting
    await validate(db, values)
    row = await db.get(AppSetting, SETTING)
    merged = {**(await defaults(db)), **{k: v for k, v in values.items() if k in NAMES and v}}
    if row is None:
        db.add(AppSetting(key=SETTING, value=merged))
    else:
        row.value = merged
    await db.flush()
    return merged


def resolved(item, dflt: dict[str, str]) -> dict[str, str]:
    """The item's accounts, its own where set and the default where not."""
    return {f: ((getattr(item, f, None) if item is not None else None) or dflt[f])
            for f in NAMES}


async def validate(db: AsyncSession, values: dict) -> None:
    """Every account named exists and takes postings."""
    from app.services.financials import EARNINGS_ACCOUNT
    nos = {v for k, v in values.items() if k in NAMES and v}
    if not nos:
        return
    found = {a.account_no: a for a in (await db.scalars(
        select(Account).where(Account.account_no.in_(nos)))).all()}
    for k, v in values.items():
        if k not in NAMES or not v:
            continue
        label = next(lbl for f, lbl, _ in FIELDS if f == k)
        a = found.get(v)
        if a is None:
            raise ValueError(f"{label}: there is no account {v}.")
        if a.is_parent:
            raise ValueError(f"{label}: {v} {a.name} is a heading — pick an account under it.")
        if v == EARNINGS_ACCOUNT:
            raise ValueError(f"{label}: {v} is the computed Laba/Rugi Tahun Berjalan.")
        if a.account_type not in TYPES[k]:
            raise ValueError(f"{label}: {v} {a.name} is {a.account_type} — it has to be "
                             f"{' or '.join(TYPES[k])}.")


async def item_for_line(db: AsyncSession, *, sku: str | None, name: str | None):
    """The stock item a document line stands for: by SKU, else by name."""
    from app.models.inventory import InventoryItem
    if sku:
        it = await db.scalar(select(InventoryItem).where(InventoryItem.sku == sku))
        if it is not None:
            return it
    key = " ".join((name or "").lower().split())
    if not key:
        return None
    from sqlalchemy import func
    return await db.scalar(select(InventoryItem).where(
        func.lower(func.trim(InventoryItem.name)) == key).limit(1))
