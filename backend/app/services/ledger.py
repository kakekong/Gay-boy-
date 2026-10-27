"""Post-to-ledger service for quotations and payments.

Keeps the Chart-of-Accounts balances in sync with what a won quotation
implies, and now mirrors every movement into the `ledger_entries`
transaction journal so finance can slice activity by period and by
salesperson. Pure single-entry-style balance updates here (we are not
building a full double-entry general ledger). Each quotation posting is
also recorded as a snapshot on the quotation so it can be reversed cleanly.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.finance import LedgerEntry
from app.models.quotation import Quotation


DEFAULTS = {
    "revenue":    "400001",   # Penjualan
    "receivable": "110301",   # Piutang Usaha IDR
    "discount":   "400004",   # Diskon Penjualan
    "tax":        "2102-01",  # PPN Keluaran
}

# Where a received customer payment lands by default, and which receivable
# it draws down. Cash up + receivable down is the standard collection entry.
PAYMENT_CASH_DEFAULT = "1101-01"   # Bank Bca
PAYMENT_RECEIVABLE = "110301"      # Piutang Usaha IDR


async def journal_post(
    db: AsyncSession,
    *,
    entry_date: date,
    account_no: str,
    account_type: str,
    account_name: str | None,
    amount: float,
    source_type: str,
    source_id: UUID | None = None,
    source_ref: str | None = None,
    memo: str | None = None,
    customer_id: UUID | None = None,
    sales_pic_id: UUID | None = None,
    created_by: UUID | None = None,
    cash_delta: float | None = None,
) -> LedgerEntry:
    """Append one line to the transaction journal.

    `cash_delta` defaults to `amount` for Cash & Bank lines and 0 otherwise,
    so money-in / money-out is always a plain SUM over cash_delta.
    """
    if cash_delta is None:
        cash_delta = amount if account_type == "Cash & Bank" else 0.0
    entry = LedgerEntry(
        entry_date=entry_date, account_no=account_no, account_type=account_type,
        account_name=account_name, amount=amount, cash_delta=cash_delta,
        source_type=source_type, source_id=source_id, source_ref=source_ref,
        memo=memo, customer_id=customer_id, sales_pic_id=sales_pic_id,
        created_by=created_by,
    )
    db.add(entry)
    return entry


def _ensure_defaults(q: Quotation) -> None:
    """Fall back to standard accounts if the user hasn't customised them."""
    if not q.account_revenue_no:    q.account_revenue_no    = DEFAULTS["revenue"]
    if not q.account_receivable_no: q.account_receivable_no = DEFAULTS["receivable"]
    if not q.account_discount_no:   q.account_discount_no   = DEFAULTS["discount"]
    if not q.account_tax_no:        q.account_tax_no        = DEFAULTS["tax"]


def compute_amounts(q: Quotation) -> dict:
    """Recompute the four ledger amounts from the quotation totals."""
    subtotal = float(q.subtotal or 0)
    discount_amount = float(q.discount_amount or 0)
    after_discount = subtotal - discount_amount
    total = float(q.total or 0)
    tax_amount = total - after_discount
    return {
        "receivable": total,
        "revenue":    after_discount,
        "discount":   discount_amount,
        "tax":        tax_amount,
    }


def posting_amounts(q: Quotation) -> dict:
    """What a won quotation does to each account, in the account's own sign.

    Penjualan is credited the full price before discount and Diskon Penjualan
    — a revenue account that is read as a reduction of it — is debited the
    discount, so the two net to what the customer was charged. It used to
    credit Penjualan the net figure *and* credit Diskon Penjualan the
    discount, which counted the discount as extra revenue and put the
    balance sheet out by every discount ever given.
    """
    a = compute_amounts(q)
    return {
        "receivable": a["receivable"],
        "revenue": round(a["revenue"] + a["discount"], 2),
        "discount": -a["discount"],
        "tax": a["tax"],
    }


async def fix_posted_discounts(db: AsyncSession) -> dict:
    """Quotations posted the old way: credit Penjualan the discount and take
    twice it off Diskon Penjualan, so each reads as posting_amounts says —
    and rewrite the posting's record, so reversing it later undoes the
    right figures. Run once."""
    rows = (await db.scalars(select(Quotation).where(Quotation.is_posted.is_(True)))).all()
    fixed = 0
    for q in rows:
        snap = dict(q.posted_snapshot or {})
        moves = [dict(m) for m in snap.get("movements", [])]
        disc = next((m for m in moves if m.get("role") == "discount"), None)
        rev = next((m for m in moves if m.get("role") == "revenue"), None)
        if not disc or float(disc.get("delta") or 0) <= 0.005:
            continue                     # no discount, or already a reduction
        d = float(disc["delta"])
        for m, delta, what in ((rev, d, "revenue"), (disc, -2 * d, "discount")):
            if m is None:
                continue
            b = await _bump(db, m.get("account_no"), delta)
            if b:
                await journal_post(
                    db, entry_date=datetime.now(UTC).date(), account_no=b["account_no"],
                    account_type=b["account_type"], account_name=b["name"],
                    amount=delta, source_type="quotation", source_id=q.id,
                    source_ref=q.number,
                    memo=f"Quotation {q.number}: discount booked as a reduction ({what})",
                    customer_id=q.customer_id, sales_pic_id=q.sales_pic_id)
                m["delta"] = float(m["delta"]) + delta
        snap["movements"] = moves
        q.posted_snapshot = snap
        fixed += 1
    await db.flush()
    return {"quotations": fixed}


async def _bump(db: AsyncSession, account_no: str | None, delta: float) -> dict | None:
    from app.services.financials import EARNINGS_ACCOUNT
    if not account_no or account_no == EARNINGS_ACCOUNT:
        # The profit line is computed, never posted to.
        return None
    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        return None
    new_balance = float(acc.balance or 0) + delta
    acc.balance = new_balance
    return {
        "account_no": account_no,
        "name": acc.name,
        "account_type": acc.account_type,
        "delta": delta,
        "new_balance": new_balance,
    }


async def post_quotation(db: AsyncSession, q: Quotation) -> dict:
    """Add the implied amounts to the linked accounts. Idempotent."""
    if q.is_posted:
        return {"already_posted": True, "snapshot": q.posted_snapshot}

    _ensure_defaults(q)
    amounts = posting_amounts(q)
    entry_date = datetime.now(UTC).date()

    movements = []
    legs: list[tuple[str, str | None, float]] = []
    split = await _by_item_accounts(db, q, amounts)
    for key in ("receivable", "revenue", "discount", "tax"):
        if key in split:
            legs += [(key, no, amt) for no, amt in split[key]]
        else:
            legs.append((key, getattr(q, f"account_{key}_no"), amounts[key]))
    for key, acc_no, amount in legs:
        # Nothing to write for a figure that is nothing: a quotation with no
        # discount used to put a Rp 0 "posted (discount)" line on Diskon
        # Penjualan for every deal won — hundreds of rows saying nothing.
        if abs(float(amount or 0)) < 0.005:
            continue
        m = await _bump(db, acc_no, amount)
        if m:
            movements.append({**m, "role": key})
            await journal_post(
                db, entry_date=entry_date, account_no=m["account_no"],
                account_type=m["account_type"], account_name=m["name"],
                amount=m["delta"], source_type="quotation", source_id=q.id,
                source_ref=q.number, memo=f"Quotation {q.number} posted ({key})",
                customer_id=q.customer_id, sales_pic_id=q.sales_pic_id,
            )

    q.is_posted = True
    q.posted_at = datetime.now(UTC)
    q.posted_snapshot = {
        "amounts": amounts,
        "movements": movements,
        "posted_at": q.posted_at.isoformat(),
    }
    await db.flush()
    return q.posted_snapshot


async def _by_item_accounts(db: AsyncSession, q: Quotation, amounts: dict) -> dict:
    """Penjualan and Diskon Penjualan split by each line's item's own
    accounts (Akun Penjualan, Akun Disk. Penjualan) — where the quotation
    posts to the standard accounts; one set on the quotation by hand wins.
    The discount is shared out by line value. Returns {role: [(account,
    amount)]} for the roles it splits; amounts add up to the whole exactly."""
    from app.models.quotation import QuotationItem
    from app.services import item_accounts as ia

    roles = [r for r, f in (("revenue", "acc_sales"), ("discount", "acc_sales_discount"))
             if getattr(q, f"account_{r}_no") in (None, DEFAULTS[r])
             and abs(float(amounts.get(r) or 0)) >= 0.005]
    if not roles:
        return {}
    lines = (await db.scalars(select(QuotationItem).where(
        QuotationItem.quotation_id == q.id))).all()
    values = [(it, float(it.qty or 0) * float(it.unit_price or 0)) for it in lines]
    whole = sum(v for _, v in values)
    if whole <= 0:
        return {}
    dflt = await ia.defaults(db)
    weights: dict[str, dict[str, float]] = {r: {} for r in roles}
    for it, v in values:
        acc = ia.resolved(await ia.item_for_line(db, sku=it.sku, name=it.description), dflt)
        for r in roles:
            no = acc["acc_sales" if r == "revenue" else "acc_sales_discount"]
            no = await _usable(db, no, DEFAULTS[r])
            weights[r][no] = weights[r].get(no, 0.0) + v
    out = {}
    for r in roles:
        total = round(float(amounts[r]), 2)
        parts = sorted(weights[r].items(), key=lambda kv: -kv[1])
        shares = [(no, round(total * w / whole, 2)) for no, w in parts]
        # Rounding goes to the biggest share, so the parts are the whole.
        drift = round(total - sum(a for _, a in shares), 2)
        shares[0] = (shares[0][0], round(shares[0][1] + drift, 2))
        out[r] = shares
    return out


async def reverse_quotation(db: AsyncSession, q: Quotation) -> dict:
    """Subtract previously-posted amounts from the linked accounts."""
    if not q.is_posted:
        return {"not_posted": True}

    movements = []
    snapshot = q.posted_snapshot or {}
    entry_date = datetime.now(UTC).date()
    for m in snapshot.get("movements", []):
        if abs(float(m.get("delta") or 0)) < 0.005:
            continue            # a zero line has nothing to take back
        rev = await _bump(db, m.get("account_no"), -float(m.get("delta") or 0))
        if rev:
            movements.append({**rev, "role": m.get("role"), "reversed": True})
            await journal_post(
                db, entry_date=entry_date, account_no=rev["account_no"],
                account_type=rev["account_type"], account_name=rev["name"],
                amount=rev["delta"], source_type="quotation", source_id=q.id,
                source_ref=q.number,
                memo=f"Quotation {q.number} reversed ({m.get('role')})",
                customer_id=q.customer_id, sales_pic_id=q.sales_pic_id,
            )

    q.is_posted = False
    q.posted_at = None
    q.posted_snapshot = {
        "reversed_at": datetime.now(UTC).isoformat(),
        "previous": snapshot,
        "movements": movements,
    }
    await db.flush()
    return q.posted_snapshot


async def post_payment(
    db: AsyncSession,
    *,
    amount: float,
    entry_date: date,
    invoice_number: str | None = None,
    customer_id: UUID | None = None,
    sales_pic_id: UUID | None = None,
    payment_id: UUID | None = None,
    created_by: UUID | None = None,
    cash_account_no: str = PAYMENT_CASH_DEFAULT,
) -> list[dict]:
    """Record a received customer payment in the ledger: cash up, receivable
    down. Bumps the Chart-of-Accounts balances (so cash-held and AR stay
    accurate) and writes the matching journal lines. Returns the movements.
    """
    if amount <= 0:
        return []
    moves: list[dict] = []
    cash = await _bump(db, cash_account_no, amount)
    recv = await _bump(db, PAYMENT_RECEIVABLE, -amount)
    for m, role in ((cash, "cash"), (recv, "receivable")):
        if not m:
            continue
        await journal_post(
            db, entry_date=entry_date, account_no=m["account_no"],
            account_type=m["account_type"], account_name=m["name"],
            amount=m["delta"], source_type="payment", source_id=payment_id,
            source_ref=invoice_number,
            memo=f"Payment received for {invoice_number or 'invoice'} ({role})",
            customer_id=customer_id, sales_pic_id=sales_pic_id,
            created_by=created_by,
        )
        moves.append({**m, "role": role})
    return moves


async def reverse_payment(
    db: AsyncSession,
    *,
    payment_id: UUID,
    amount: float,
    entry_date: date,
    invoice_number: str | None = None,
    customer_id: UUID | None = None,
    sales_pic_id: UUID | None = None,
    reversal_payment_id: UUID | None = None,
    created_by: UUID | None = None,
    memo_suffix: str | None = None,
) -> list[dict]:
    """Take a received payment back off the books: cash down, receivable up.

    It reverses *what was actually posted* rather than what the defaults say
    should have been — the original journal lines are read back by
    `source_id`, and each one is undone against its own account. That matters
    for a receipt booked into a different bank account, and for the old
    "ghost" payments recorded before this service existed, which have no
    journal lines at all: those fall back to the standard cash/receivable
    pair so the balances still move.

    Nothing is deleted. The original lines stay exactly where they are and
    the reversal is written beside them, which is what makes the journal
    readable a year later: the money arrived, and then it didn't.
    """
    if amount <= 0:
        return []
    originals = (await db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.source_type == "payment",
            LedgerEntry.source_id == payment_id,
        )
    )).all()
    pairs: list[tuple[str, float, str]] = []
    if originals:
        for e in originals:
            pairs.append((e.account_no, -float(e.amount or 0),
                          "cash" if float(e.amount or 0) > 0 else "receivable"))
    else:
        pairs = [(PAYMENT_CASH_DEFAULT, -amount, "cash"),
                 (PAYMENT_RECEIVABLE, amount, "receivable")]

    tail = f" — {memo_suffix}" if memo_suffix else ""
    moves: list[dict] = []
    for account_no, delta, role in pairs:
        m = await _bump(db, account_no, delta)
        if not m:
            continue
        await journal_post(
            db, entry_date=entry_date, account_no=m["account_no"],
            account_type=m["account_type"], account_name=m["name"],
            amount=m["delta"], source_type="payment",
            source_id=reversal_payment_id or payment_id,
            source_ref=invoice_number,
            memo=(f"Payment reversed for {invoice_number or 'invoice'} "
                  f"({role}){tail}"),
            customer_id=customer_id, sales_pic_id=sales_pic_id,
            created_by=created_by,
        )
        moves.append({**m, "role": role, "reversed": True})
    return moves


# ─── Utang usaha: suppliers ───────────────────────────────────────────────────
#
# Goods received on a purchase order are owed for from the moment they are in
# the building: inventory up, utang usaha up, for the value of what arrived.
# Paying the supplier is the other half: utang usaha down, the bank down.
INVENTORY_ACCOUNT = "110401"     # Persediaan
PAYABLE_ACCOUNT = "210101"       # Utang Usaha IDR


UNBILLED_ACCOUNT = "2102-03"      # Hutang Pembelian Belum Ditagih


async def post_goods_receipt(
    db: AsyncSession, *, value: float, entry_date: date, po_number: str,
    supplier_name: str | None = None, receipt_id: UUID | None = None,
    created_by: UUID | None = None, inventory_account: str = INVENTORY_ACCOUNT,
    credits: list[tuple[str, float, str]] | None = None,
) -> list[dict]:
    """Goods received: the stock account up by `value` (rupiah), and the
    other side on `credits` — [(account, amount, role)], by default all of it
    on Utang Usaha. A negative value (a receipt corrected downward) reverses.
    """
    if abs(value) < 0.005:
        return []
    legs = [(inventory_account, value, "inventory")] + (
        credits if credits is not None else [(PAYABLE_ACCOUNT, value, "payable")])
    moves: list[dict] = []
    who = f" — {supplier_name}" if supplier_name else ""
    for acc_no, amount, role in legs:
        if abs(amount) < 0.005:
            continue
        m = await _bump(db, acc_no, amount)
        if not m:
            continue
        await journal_post(
            db, entry_date=entry_date, account_no=m["account_no"],
            account_type=m["account_type"], account_name=m["name"],
            amount=m["delta"], source_type="goods_receipt", source_id=receipt_id,
            source_ref=po_number,
            memo=f"Goods received on {po_number}{who} ({role})",
            created_by=created_by,
        )
        moves.append({**m, "role": role})
    return moves


async def _usable(db: AsyncSession, no: str | None, fallback: str | None) -> str | None:
    """`no` if it is an account that takes postings, else `fallback`."""
    if no:
        acc = await db.scalar(select(Account).where(Account.account_no == no))
        if acc is not None and not acc.is_parent:
            return no
        if acc is not None and no == COGS_ACCOUNT:
            return await _cogs_account(db)
    return fallback


async def post_receipt_by_item(db: AsyncSession, po, moved: list[dict], *,
                               entry_date: date, receipt_id: UUID | None,
                               supplier_name: str | None, created_by: UUID | None) -> float:
    """A receipt on the books the Accurate way: each line's value to its
    item's Persediaan, against its item's Belum Tertagih (Hutang Pembelian
    Belum Ditagih) until the supplier's invoice is recorded
    (`record_supplier_invoice`). Keeps on the order what sits unbilled per
    account, and what was received per stock/HPP account for the HPP later.
    A downward correction takes back from what is still unbilled first, and
    the rest off Utang Usaha. Returns the receipt's value in rupiah."""
    from app.services import item_accounts as ia

    rate = 1.0
    if (po.currency or "IDR").upper() != "IDR":
        rate = float(po.fx_rate or 0) or 1.0
    lines = list(po.items or [])
    dflt = await ia.defaults(db)
    parts: dict[tuple[str, str, str], float] = {}
    for m in moved:
        idx = int(m.get("line_no") or 0) - 1
        if not (0 <= idx < len(lines)):
            continue
        unit = float(lines[idx].get("unit_price") or lines[idx].get("unit_cost") or 0)
        value = float(m.get("delta") or 0) * unit * rate
        if abs(value) < 1e-9:
            continue
        item = await ia.item_for_line(db, sku=m.get("sku"), name=m.get("name"))
        acc = ia.resolved(item, dflt)
        key = (acc["acc_inventory"], acc["acc_unbilled"], acc["acc_cogs"])
        parts[key] = parts.get(key, 0.0) + value

    unbilled = {k: float(v) for k, v in (po.unbilled or {}).items()}
    received_by = {k: float(v) for k, v in (po.received_by or {}).items()}
    total = 0.0
    for (inv, unb, cogs), value in parts.items():
        value = round(value, 2)
        if abs(value) < 0.005:
            continue
        inv = await _usable(db, inv, INVENTORY_ACCOUNT)
        unb = await _usable(db, unb, PAYABLE_ACCOUNT)
        cogs = await _usable(db, cogs, None) or await _cogs_account(db) or COGS_ACCOUNT
        if value > 0 or unb == PAYABLE_ACCOUNT:
            credits = [(unb, value, "not yet invoiced" if unb != PAYABLE_ACCOUNT else "payable")]
            if unb != PAYABLE_ACCOUNT:
                unbilled[unb] = round(unbilled.get(unb, 0.0) + value, 2)
        else:
            back = min(-value, max(unbilled.get(unb, 0.0), 0.0))
            credits = [(unb, -back, "not yet invoiced"), (PAYABLE_ACCOUNT, value + back, "payable")]
            unbilled[unb] = round(unbilled.get(unb, 0.0) - back, 2)
        await post_goods_receipt(
            db, value=value, entry_date=entry_date, po_number=po.number,
            supplier_name=supplier_name, receipt_id=receipt_id, created_by=created_by,
            inventory_account=inv, credits=credits)
        k = f"{inv}|{cogs}"
        received_by[k] = round(received_by.get(k, 0.0) + value, 2)
        total += value
    po.unbilled = {k: v for k, v in unbilled.items() if abs(v) >= 0.005}
    po.received_by = {k: v for k, v in received_by.items() if abs(v) >= 0.005}
    return round(total, 2)


async def record_supplier_invoice(db: AsyncSession, po, *, number: str, on: date,
                                  user=None, note: str | None = None) -> dict:
    """The supplier's invoice (Faktur Pembelian) has come: what was received
    and sat on Hutang Pembelian Belum Ditagih moves to Utang Usaha, where the
    payment then takes it off."""
    moved = 0.0
    moves: list[dict] = []
    for acc_no, amount in (po.unbilled or {}).items():
        amount = round(float(amount or 0), 2)
        if abs(amount) < 0.005:
            continue
        for no, delta, role in ((acc_no, -amount, "not yet invoiced"),
                                (PAYABLE_ACCOUNT, amount, "payable")):
            m = await _bump(db, no, delta)
            if not m:
                continue
            await journal_post(
                db, entry_date=on, account_no=m["account_no"],
                account_type=m["account_type"], account_name=m["name"],
                amount=m["delta"], source_type="supplier_invoice", source_id=po.id,
                source_ref=po.number,
                memo=f"Supplier invoice {number} on {po.number} ({role})",
                created_by=getattr(user, "id", None))
            moves.append({**m, "role": role})
        moved += amount
    po.unbilled = {}
    invoices = list(po.supplier_invoices or [])
    same = next((i for i in invoices if i.get("number") == number), None)
    if same is not None:
        same = dict(same)
        same["amount"] = round(float(same.get("amount") or 0) + moved, 2)
        invoices = [same if i.get("number") == number else i for i in invoices]
    else:
        invoices.append({"number": number, "date": on.isoformat(), "amount": round(moved, 2),
                         "note": note, "by": getattr(user, "full_name", None),
                         "at": datetime.now(UTC).isoformat()})
    po.supplier_invoices = invoices
    return {"moved": round(moved, 2), "moves": moves}


# ─── Beban Pokok Penjualan: booked when the customer has paid ───────────────
#
# The cost of the goods is booked when the job they were bought for has been
# invoiced and paid in full — not when the PO is approved. Until then the
# goods sit in Persediaan, where receiving put them (Persediaan up, Utang
# Usaha up). When every invoice on the project is paid, what was received on
# each of its purchasing POs moves from Persediaan to 5101: HPP up,
# Persediaan down, by the received value in rupiah.
#
# The amount booked is kept on the order (`cogs_posted`) and kept equal to
# what the rule says now: a receipt after payment books the difference; a
# payment reversed (the job no longer fully paid) or the order cancelled takes
# it back. A PO serving several jobs is booked once all of them are paid.
COGS_ACCOUNT = "5101"            # Beban Pokok Penjualan
_PO_NOT_LIVE = ("pending_approval", "cancelled", "rejected")
# Invoices that are issued — the ones a customer is asked to pay.
_BILLED = ("approved", "issued", "partial", "overdue", "paid")


async def project_fully_paid(db: AsyncSession, project_id) -> bool:
    """Every invoice issued on the job is paid (and there is at least one)."""
    from app.models.finance import Invoice
    statuses = (await db.scalars(select(Invoice.status).where(
        Invoice.project_id == project_id, Invoice.status.in_(_BILLED)))).all()
    return bool(statuses) and all(st == "paid" for st in statuses)


def _po_project_ids(po) -> set:
    ids = {str(po.project_id)} if po.project_id else set()
    ids.update(str(x) for x in (po.project_ids or []) if x)
    return ids


async def _cogs_account(db: AsyncSession) -> str | None:
    """5101 itself — or, if a chart keeps it as a header with accounts under
    it, the first of those. Reports skip headers, so cost booked on one would
    show nowhere."""
    acc = await db.scalar(select(Account).where(Account.account_no == COGS_ACCOUNT))
    if acc is None:
        return None
    if not acc.is_parent:
        return acc.account_no
    return await db.scalar(
        select(Account.account_no).where(Account.parent_account_no == COGS_ACCOUNT,
                                         Account.is_parent.is_(False))
        .order_by(Account.account_no).limit(1))


def po_value_idr(po) -> float | None:
    """The order's total in rupiah, or None when its rate isn't known yet."""
    cur = (po.currency or "IDR").upper()
    rate = 1.0 if cur == "IDR" else (None if po.fx_rate is None else float(po.fx_rate))
    if rate is None:
        return None
    return round(float(po.total or 0) * rate, 2)


async def sync_po_cogs(
    db: AsyncSession, po, *, created_by: UUID | None = None, **_ignored,
) -> list[dict]:
    """Bring the HPP booked for `po` in line with the rule: what was received
    on it, once every job it serves is fully paid; nothing otherwise.

    Kept per stock/HPP account pair (`received_by`), so each item's cost
    leaves its own Persediaan for its own HPP account. What was received
    before the order kept that record counts on the default pair."""
    from uuid import UUID as _U
    default_key = f"{INVENTORY_ACCOUNT}|{await _cogs_account(db) or COGS_ACCOUNT}"
    received = {k: float(v) for k, v in (po.received_by or {}).items()}
    older = round(float(po.payable_amount or 0) - sum(received.values()), 2)
    if abs(older) >= 0.005:
        received[default_key] = round(received.get(default_key, 0.0) + older, 2)
    paid = False
    projects = _po_project_ids(po)
    if po.status not in _PO_NOT_LIVE and projects:
        paid = True
        for pid in projects:
            if not await project_fully_paid(db, _U(pid)):
                paid = False
                break
    target = received if paid else {}
    booked = ({k: float(v) for k, v in po.cogs_by.items()} if po.cogs_by is not None
              else ({default_key: float(po.cogs_posted)} if po.cogs_posted else {}))
    from zoneinfo import ZoneInfo

    from app.core.config import settings
    today = datetime.now(ZoneInfo(settings.TIMEZONE or "Asia/Jakarta")).date()
    moves: list[dict] = []
    for key in sorted(set(target) | set(booked)):
        delta = round(target.get(key, 0.0) - booked.get(key, 0.0), 2)
        if abs(delta) < 0.005:
            continue
        inv_no, _, cogs_no = key.partition("|")
        # Both sides or neither: a chart missing either account must not
        # leave half an entry on the books.
        inv_no = await _usable(db, inv_no, None)
        cogs_no = await _usable(db, cogs_no, None)
        if not inv_no or not cogs_no:
            target[key] = booked.get(key, 0.0)
            continue
        why = ("job paid" if booked.get(key, 0.0) == 0 and delta > 0
               else "taken back — the job is no longer fully paid" if not paid
               else "received value changed")
        for acc_no, sign, role in ((cogs_no, 1, "cogs"), (inv_no, -1, "inventory")):
            m = await _bump(db, acc_no, sign * delta)
            if not m:
                continue
            await journal_post(
                db, entry_date=today, account_no=m["account_no"],
                account_type=m["account_type"], account_name=m["name"],
                amount=m["delta"], source_type="supplier_po_cogs", source_id=po.id,
                source_ref=po.number,
                memo=f"Cost of goods on {po.number} — {why} ({role})",
                created_by=created_by,
            )
            moves.append({**m, "role": role})
    po.cogs_by = {k: round(v, 2) for k, v in target.items() if abs(v) >= 0.005}
    po.cogs_posted = round(sum(po.cogs_by.values()), 2)
    return moves


async def sync_project_cogs(db: AsyncSession, project_id, *,
                            created_by: UUID | None = None) -> int:
    """Re-check HPP for every purchasing PO serving this job — after a
    payment lands or is reversed. Returns how many orders moved."""
    from sqlalchemy import or_

    from app.models.purchasing import SupplierPO
    if not project_id:
        return 0
    pos = (await db.scalars(select(SupplierPO).where(or_(
        SupplierPO.project_id == project_id,
        SupplierPO.project_ids.contains([str(project_id)]))))).all()
    n = 0
    for po in pos:
        n += bool(await sync_po_cogs(db, po, created_by=created_by))
    return n


async def resync_all_cogs(db: AsyncSession) -> dict:
    """Every PO to the rule — run once when the rule changed."""
    from app.models.purchasing import SupplierPO
    moved = 0
    for po in (await db.scalars(select(SupplierPO))).all():
        moved += bool(await sync_po_cogs(db, po))
    await db.flush()
    return {"orders_moved": moved}


# Where the gap between a foreign order's booked rate and the rate the bank
# really paid at goes: Laba/Rugi Terealisasi (under Beban Diluar Usaha). A
# loss raises it, a gain lowers it. It used to be 720101, which is now the
# computed Laba/Rugi Tahun Berjalan.
FX_REALISED_ACCOUNT = "7200-04"


async def post_supplier_payment(
    db: AsyncSession, *, amount: float, entry_date: date, po_number: str,
    supplier_name: str | None = None, payment_id: UUID | None = None,
    created_by: UUID | None = None, cash_account_no: str | None = None,
    cash_amount: float | None = None,
) -> list[dict]:
    """Paying a supplier: Utang Usaha down by what the payment settles, the
    bank down by what actually left it, and — on a foreign order paid at a
    different rate than it was booked at — the difference to Laba/Rugi
    Terealisasi, so the entry still balances."""
    if amount <= 0:
        return []
    cash_amount = amount if cash_amount is None else cash_amount
    moves: list[dict] = []
    who = f" — {supplier_name}" if supplier_name else ""
    legs = [(PAYABLE_ACCOUNT, "payable", -amount),
            (cash_account_no or PAYMENT_CASH_DEFAULT, "cash", -cash_amount)]
    diff = round(cash_amount - amount, 2)
    if abs(diff) >= 0.01:
        legs.append((FX_REALISED_ACCOUNT, "exchange loss" if diff > 0 else "exchange gain", diff))
    for acc_no, role, delta in legs:
        m = await _bump(db, acc_no, delta)
        if not m:
            continue
        await journal_post(
            db, entry_date=entry_date, account_no=m["account_no"],
            account_type=m["account_type"], account_name=m["name"],
            amount=m["delta"], source_type="supplier_payment", source_id=payment_id,
            source_ref=po_number,
            memo=f"Paid supplier for {po_number}{who} ({role})",
            created_by=created_by,
        )
        moves.append({**m, "role": role})
    return moves


async def free_earnings_account(db: AsyncSession) -> dict:
    """720101 became the computed Laba/Rugi Tahun Berjalan. What was posted
    to it — exchange differences on supplier payments — moves, lines and
    balance, to FX_REALISED_ACCOUNT, where those go from now on; 720101 is
    left at 0 as an equity line. Run once."""
    from sqlalchemy import update

    from app.models.journal import JournalLine
    from app.services.financials import EARNINGS_ACCOUNT, EARNINGS_TITLE

    fx = await db.scalar(select(Account).where(Account.account_no == FX_REALISED_ACCOUNT))
    if fx is None:
        head = await db.scalar(select(Account).where(Account.account_no == "7200"))
        fx = Account(account_no=FX_REALISED_ACCOUNT, name="Laba/Rugi Terealisasi",
                     account_type="Other Expense",
                     parent_account_no=head.account_no if head else None,
                     level=1 if head else 0, balance=0)
        db.add(fx)
        await db.flush()
    earn = await db.scalar(select(Account).where(Account.account_no == EARNINGS_ACCOUNT))
    moved = 0.0
    lines = 0
    if earn is not None:
        moved = float(earn.balance or 0)
        res = await db.execute(update(LedgerEntry)
                               .where(LedgerEntry.account_no == EARNINGS_ACCOUNT)
                               .values(account_no=fx.account_no, account_name=fx.name,
                                       account_type=fx.account_type))
        lines = res.rowcount or 0
        await db.execute(update(JournalLine)
                         .where(JournalLine.account_no == EARNINGS_ACCOUNT)
                         .values(account_no=fx.account_no, account_name=fx.name,
                                 account_type=fx.account_type))
        fx.balance = round(float(fx.balance or 0) + moved, 2)
        earn.balance = 0
        earn.account_type = "Equity"
        earn.is_parent = False
    else:
        head = await db.scalar(select(Account).where(Account.account_no == "7201"))
        db.add(Account(account_no=EARNINGS_ACCOUNT, name=EARNINGS_TITLE, account_type="Equity",
                       parent_account_no=head.account_no if head else None,
                       level=1 if head else 0, balance=0))
    await db.flush()
    return {"moved_balance": moved, "moved_lines": lines, "to": fx.account_no}
