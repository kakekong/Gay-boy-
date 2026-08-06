"""Read an Accurate "Barang & Jasa" export and map it onto InventoryItem rows.

Worth knowing before anyone gets their hopes up: this export is a **catalogue,
not a stocktake**. Its 80 columns include buying price, selling price, minimum
stock and opening quantity, and in this company's file every one of them is
zero or blank. What it does carry is the part number, the name, the category
and the unit — which is the hard part to retype for 700-odd items, and the part
the rest of the app can use immediately.

So the mapping deliberately does not invent what is not there. Prices stay at
zero and the preview says so, rather than importing 731 items that all look
like they cost nothing because someone assumed the column was meaningful.

Opening stock, if a future export does carry it, is written as an inventory
*movement* rather than by setting the number directly — every other change to
stock in this app leaves that trail, and an import is no reason to start the
history with a quantity nobody can account for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COLUMNS = {
    "sku": ["kode barang", "item code"],
    "name": ["nama barang", "item name"],
    "category": ["kategori barang", "item category"],
    "kind": ["jenis barang", "item type"],
    "uom": ["satuan", "unit"],
    "unit_cost": ["harga beli", "purchase price"],
    "sell_price": ["def. hrg. jual satuan #1", "default selling price unit #1"],
    "reorder_point": ["batas minimum stok", "minimum stock"],
    "opening_qty": ["kuantitas saldo awal", "opening quantity"],
    "warehouse": ["gudang saldo awal", "opening warehouse"],
    "supplier": ["pemasok utama", "main supplier"],
    "brand": ["merek barang", "brand"],
    "notes": ["catatan", "notes"],
    "inactive": ["non aktif", "inactive"],
}

# `Jenis Barang`: INV is a stocked item, NON is a service. Only the first is
# something the inventory screen can count.
STOCKED = {"INV", "INVENTORY", ""}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _num(v: str | None) -> float:
    s = (_clean(v) or "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


@dataclass
class MappedItem:
    row_no: int
    sku: str
    name: str
    category: str | None = None
    uom: str = "pcs"
    unit_cost: float = 0.0
    sell_price: float = 0.0
    reorder_point: float = 0.0
    opening_qty: float = 0.0
    location: str | None = None
    supplier_hint: str | None = None
    notes: str | None = None
    is_active: bool = True
    warnings: list[str] = field(default_factory=list)


def _header_index(header: list[str]) -> dict[str, int]:
    # Accurate ships at least one header with a trailing tab ("Panjang (cm)\t"),
    # so compare on the normalised form rather than the literal cell.
    norm = [_norm(h) for h in header]
    out: dict[str, int] = {}
    for field_name, candidates in COLUMNS.items():
        for cand in candidates:
            if cand in norm:
                out[field_name] = norm.index(cand)
                break
    return out


def map_items(header: list[str], rows: list[list[str]]) -> tuple[list[MappedItem], list[str]]:
    idx = _header_index(header)
    problems: list[str] = []
    for need, label in (("sku", "Kode Barang"), ("name", "Nama Barang")):
        if need not in idx:
            problems.append(
                f"Could not find the '{label}' column. Is this the Barang & Jasa export?")
    if problems:
        return [], problems

    def cell(row: list[str], key: str) -> str | None:
        i = idx.get(key)
        if i is None or i >= len(row):
            return None
        return _clean(row[i])

    priced = 0
    out: list[MappedItem] = []
    for n, row in enumerate(rows, start=2):
        sku, name = cell(row, "sku"), cell(row, "name")
        if not sku or not name:
            continue
        warnings: list[str] = []

        kind = (cell(row, "kind") or "").upper()
        if kind not in STOCKED:
            warnings.append(f"'{kind}' is a service, not a stocked item — "
                            f"it imports with no stock to count")

        cost, sell = _num(cell(row, "unit_cost")), _num(cell(row, "sell_price"))
        if cost or sell:
            priced += 1

        qty = _num(cell(row, "opening_qty"))
        if qty:
            warnings.append(f"opening stock of {qty:g} will be recorded as a "
                            f"stock adjustment, not set silently")

        out.append(MappedItem(
            row_no=n,
            sku=sku,
            name=name,
            category=cell(row, "category"),
            # The unit is displayed everywhere alongside quantities, and the
            # app's own default is lowercase "pcs"; the export shouts "PCS".
            uom=(cell(row, "uom") or "pcs").lower(),
            unit_cost=cost,
            sell_price=sell,
            reorder_point=_num(cell(row, "reorder_point")),
            opening_qty=qty,
            location=cell(row, "warehouse"),
            supplier_hint=cell(row, "supplier") or cell(row, "brand"),
            notes=cell(row, "notes"),
            is_active=(cell(row, "inactive") or "TIDAK").upper() not in ("YA", "YES", "TRUE"),
            warnings=warnings,
        ))

    if out and not priced:
        problems.append(
            f"None of the {len(out)} items carry a price in this export — the "
            f"Harga Beli and Harga Jual columns are all zero. They will import "
            f"as a parts catalogue with no cost, which is what the file says.")
    return out, problems
