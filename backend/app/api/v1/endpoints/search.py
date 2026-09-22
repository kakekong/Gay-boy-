"""Global search — the ⌘K command palette.

Two things this has to get right, and used not to.

**A document number is whatever somebody remembers of it.** People type
`PR-2026-0012`, `pr 2026 0012`, `PR20260012`, or just `0012` off a WhatsApp
message, and all four mean the same request. So every number is matched twice:
once as typed, and once with the separators stripped from both sides, which
makes the spacing and the dashes stop mattering.

**A product name should find every document it appears on.** Searching
"chain shackle" used to find an inventory row and nothing else, because only
headers were searched — the numbers and the notes. But the thing a person is
actually holding is a *line*: the item is on a price request, then a
quotation, then a customer PO, then a supplier PO. Those live in two shapes
— a JSONB `items` array on most documents, a real `quotation_items` table on
quotations — so both are searched, and the matching line is put in the
result's subtitle. A result you can't explain is a result you don't trust.

Scoping is per group and follows the page each result links to: there is no
point offering a sales rep a supplier PO they cannot open.
"""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.account import Account
from app.models.crm import Customer
from app.models.customer_po import CustomerPO
from app.models.finance import Invoice
from app.models.inventory import InventoryItem
from app.models.operation import Project
from app.models.price_request import PriceRequest
from app.models.purchasing import Supplier, SupplierPO, SupplierPriceRequest
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

# Everything people put between the parts of a document number, on a keyboard
# or on a phone. Stripping these from both the query and the stored number is
# what makes "pr 2026 0012" and "PR-2026-0012" the same search.
_SEPARATORS = re.compile(r"[\s\-_/.,#]+")


def _squash(s: str) -> str:
    return _SEPARATORS.sub("", s or "").upper()


def _number_match(column, q: str):
    """Match a document number as typed, and with separators ignored.

    The second half is done in SQL rather than in Python because the numbers
    live in the database — `REPLACE` nested over the separator characters is
    ugly but it is one indexable-enough pass, and it means a query of `20260012`
    still finds `PR-2026-0012`.
    """
    like = f"%{q.strip()}%"
    squashed = _squash(q)
    clauses = [column.ilike(like)]
    if squashed:
        stripped = column
        for ch in ("-", "_", " ", "/", ".", ",", "#"):
            stripped = _replace(stripped, ch)
        clauses.append(stripped.ilike(f"%{squashed}%"))
    return or_(*clauses)


def _replace(column, ch: str):
    from sqlalchemy import func
    return func.replace(column, ch, "")


def _items_match(table: str, like: str, param: str):
    """Does any line on this document mention the thing being searched for?

    The documents keep their lines as a JSONB array, so this walks it and
    looks at the fields a person would actually recognise a product by. A
    missing key yields NULL and simply doesn't match, which is why no key
    needs to exist on every document type.
    """
    return text(
        f"EXISTS (SELECT 1 FROM jsonb_array_elements({table}.items) AS _line "
        f"WHERE _line->>'description' ILIKE :{param} "
        f"   OR _line->>'spec' ILIKE :{param} "
        f"   OR _line->>'sku' ILIKE :{param} "
        f"   OR _line->>'part_no' ILIKE :{param})"
    ).bindparams(**{param: like})


def _matching_line(items, q: str) -> str | None:
    """The line that caused the hit, for the subtitle. Same fields, same
    order, so what the user reads back is what the query matched."""
    needle = (q or "").strip().lower()
    if not needle or not isinstance(items, list):
        return None
    for line in items:
        if not isinstance(line, dict):
            continue
        for key in ("description", "spec", "sku", "part_no"):
            val = line.get(key)
            if val and needle in str(val).lower():
                qty, uom = line.get("qty"), line.get("uom")
                tail = f" · {qty:g} {uom}" if isinstance(qty, (int, float)) and uom else ""
                return f"{val}{tail}"
    return None


def _join(*parts) -> str:
    return " · ".join(str(p) for p in parts if p)


@router.get("")
async def search(
    q: str = Query("", min_length=0, max_length=120),
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Return grouped results across the system, scoped to the caller's role."""
    if not q or not q.strip():
        return {"query": q, "groups": []}
    term = q.strip()
    like = f"%{term}%"
    role = Role(me.role)
    is_sales = role is Role.SALES
    groups: list[dict] = []

    def add(label: str, items: list[dict]) -> None:
        if items:
            groups.append({"label": label, "items": items})

    # Who can be offered what. Each set mirrors the roles that can open the
    # page the result links to.
    sees_purchasing = role in (Role.PURCHASING, Role.ADMIN, Role.MANAGER, Role.DIRECTOR)
    sees_supplier_po = role in (Role.PURCHASING, Role.FINANCE, Role.MANAGER, Role.DIRECTOR)
    sees_finance = role in (Role.FINANCE, Role.ADMIN, Role.MANAGER, Role.DIRECTOR)

    # ── Customers ────────────────────────────────────────────────────────
    c_stmt = (
        select(Customer)
        .where(Customer.is_deleted.is_(False))
        .where(or_(Customer.company_name.ilike(like), Customer.pic_name.ilike(like)))
        .order_by(Customer.company_name.asc())
        .limit(limit)
    )
    if is_sales:
        c_stmt = c_stmt.where(Customer.sales_pic_id == me.id)
    add("Customers", [
        {
            "id": str(c.id),
            "label": c.company_name,
            "sublabel": _join(c.industry, c.stage),
            "link": f"/customers/{c.id}",
        }
        for c in (await db.scalars(c_stmt)).all()
    ])

    # ── Price requests ───────────────────────────────────────────────────
    # The thing most often searched for by number, and until now missing
    # from this endpoint entirely.
    if role in (Role.SALES, Role.PURCHASING, Role.MANAGER, Role.DIRECTOR):
        pr_stmt = (
            select(PriceRequest)
            .where(or_(
                _number_match(PriceRequest.number, term),
                PriceRequest.notes.ilike(like),
                _items_match("price_requests", like, "pr_like"),
            ))
            .order_by(PriceRequest.created_at.desc())
            .limit(limit)
        )
        if is_sales:
            pr_stmt = pr_stmt.where(PriceRequest.sales_pic_id == me.id)
        prs = (await db.scalars(pr_stmt)).all()
        cust_names = await _customer_names(db, [p.customer_id for p in prs])
        add("Price requests", [
            {
                "id": str(p.id),
                "label": p.number,
                "sublabel": _join(p.status, cust_names.get(p.customer_id),
                                  _matching_line(p.items, term)),
                "link": f"/price-requests?open={p.id}",
            }
            for p in prs
        ])

    # ── Quotations ───────────────────────────────────────────────────────
    # Line descriptions live in their own table here, so the match is a
    # subquery rather than a JSONB walk.
    line_hit = (
        select(QuotationItem.quotation_id)
        .where(QuotationItem.description.ilike(like))
        .scalar_subquery()
    )
    q_stmt = (
        select(Quotation)
        .where(or_(
            _number_match(Quotation.number, term),
            Quotation.notes.ilike(like),
            Quotation.id.in_(line_hit),
        ))
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if is_sales:
        q_stmt = q_stmt.where(Quotation.sales_pic_id == me.id)
    quotations = (await db.scalars(q_stmt)).all()
    q_lines = await _quotation_lines(db, [qt.id for qt in quotations], like)
    add("Quotations", [
        {
            "id": str(qt.id),
            "label": qt.number,
            "sublabel": _join(qt.status, qt.variant, q_lines.get(qt.id)),
            "link": f"/quotations/{qt.id}",
        }
        for qt in quotations
    ])

    # ── Customer POs ─────────────────────────────────────────────────────
    cpo_stmt = (
        select(CustomerPO)
        .where(or_(
            _number_match(CustomerPO.number, term),
            CustomerPO.notes.ilike(like),
            _items_match("customer_pos", like, "cpo_like"),
        ))
        .order_by(CustomerPO.created_at.desc())
        .limit(limit)
    )
    if is_sales:
        cpo_stmt = cpo_stmt.where(CustomerPO.customer_id.in_(
            select(Customer.id).where(Customer.sales_pic_id == me.id)))
    cpos = (await db.scalars(cpo_stmt)).all()
    cpo_names = await _customer_names(db, [p.customer_id for p in cpos])
    add("Customer POs", [
        {
            "id": str(p.id),
            "label": p.number,
            "sublabel": _join(p.status, cpo_names.get(p.customer_id),
                              _matching_line(p.items, term)),
            "link": f"/customer-pos/{p.id}",
        }
        for p in cpos
    ])

    # ── Projects ─────────────────────────────────────────────────────────
    p_stmt = (
        select(Project)
        .where(Project.is_deleted.is_(False))
        .where(or_(
            _number_match(Project.code, term),
            _number_match(Project.po_number, term),
        ))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    if is_sales:
        p_stmt = p_stmt.where(Project.customer_id.in_(
            select(Customer.id).where(Customer.sales_pic_id == me.id)))
    add("Projects", [
        {
            "id": str(p.id),
            "label": p.code,
            "sublabel": _join(p.status, p.po_number),
            # This used to point at the list rather than the project, so
            # every project result landed you on the same page.
            "link": f"/projects/{p.id}",
        }
        for p in (await db.scalars(p_stmt)).all()
    ])

    # ── Invoices ─────────────────────────────────────────────────────────
    if sees_finance:
        inv_stmt = (
            select(Invoice)
            .where(or_(
                _number_match(Invoice.number, term),
                _number_match(Invoice.faktur_pajak_no, term),
                Invoice.notes.ilike(like),
            ))
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
        invoices = (await db.scalars(inv_stmt)).all()
        inv_names = await _customer_names(db, [i.customer_id for i in invoices])
        add("Invoices", [
            {
                "id": str(i.id),
                "label": i.number,
                "sublabel": _join(i.status, inv_names.get(i.customer_id),
                                  f"FP {i.faktur_pajak_no}" if i.faktur_pajak_no else None),
                "link": f"/invoices/{i.id}",
            }
            for i in invoices
        ])

    # ── Suppliers ────────────────────────────────────────────────────────
    if sees_purchasing or sees_supplier_po:
        s_stmt = (
            select(Supplier)
            .where(or_(Supplier.name.ilike(like), Supplier.category.ilike(like),
                       Supplier.email.ilike(like), Supplier.phone.ilike(like)))
            .order_by(Supplier.name.asc())
            .limit(limit)
        )
        add("Suppliers", [
            {
                "id": str(s.id),
                "label": s.name,
                "sublabel": _join(s.category, s.phone or s.email),
                "link": f"/suppliers/{s.id}",
            }
            for s in (await db.scalars(s_stmt)).all()
        ])

    # ── Supplier price requests ──────────────────────────────────────────
    if sees_purchasing:
        spr_stmt = (
            select(SupplierPriceRequest)
            .where(or_(
                _number_match(SupplierPriceRequest.number, term),
                SupplierPriceRequest.notes.ilike(like),
                _items_match("supplier_price_requests", like, "spr_like"),
            ))
            .order_by(SupplierPriceRequest.created_at.desc())
            .limit(limit)
        )
        sprs = (await db.scalars(spr_stmt)).all()
        sup_names = await _supplier_names(db, [x.supplier_id for x in sprs])
        add("Supplier price requests", [
            {
                "id": str(x.id),
                "label": x.number,
                "sublabel": _join(x.status, sup_names.get(x.supplier_id),
                                  _matching_line(x.items, term)),
                "link": f"/purchasing/price-requests/{x.id}",
            }
            for x in sprs
        ])

    # ── Supplier POs ─────────────────────────────────────────────────────
    if sees_supplier_po:
        spo_stmt = (
            select(SupplierPO)
            .where(or_(
                _number_match(SupplierPO.number, term),
                _items_match("supplier_pos", like, "spo_like"),
            ))
            .order_by(SupplierPO.created_at.desc())
            .limit(limit)
        )
        spos = (await db.scalars(spo_stmt)).all()
        spo_names = await _supplier_names(db, [x.supplier_id for x in spos])
        add("Purchasing POs", [
            {
                "id": str(x.id),
                "label": x.number,
                "sublabel": _join(x.status, spo_names.get(x.supplier_id),
                                  _matching_line(x.items, term)),
                "link": f"/purchase-orders/{x.id}",
            }
            for x in spos
        ])

    # ── Inventory ────────────────────────────────────────────────────────
    i_stmt = (
        select(InventoryItem)
        .where(or_(_number_match(InventoryItem.sku, term),
                   InventoryItem.name.ilike(like)))
        .order_by(InventoryItem.name.asc())
        .limit(limit)
    )
    add("Inventory", [
        {
            "id": str(it.id),
            "label": f"{it.sku} · {it.name}",
            "sublabel": f"{it.current_stock} {it.uom}",
            "link": "/inventory",
        }
        for it in (await db.scalars(i_stmt)).all()
    ])

    # ── Employees (HR + director) ────────────────────────────────────────
    if role in (Role.HR, Role.DIRECTOR):
        u_stmt = (
            select(User)
            .where(or_(User.full_name.ilike(like), User.email.ilike(like)))
            .where(User.is_active.is_(True))
            .order_by(User.full_name.asc())
            .limit(limit)
        )
        add("Employees", [
            {
                "id": str(u.id),
                "label": u.full_name,
                "sublabel": _join(u.role, u.email),
                "link": f"/employees/{u.id}",
            }
            for u in (await db.scalars(u_stmt)).all()
        ])

    # ── Chart of accounts (admin + director) ─────────────────────────────
    if role in (Role.ADMIN, Role.DIRECTOR):
        a_stmt = (
            select(Account)
            .where(or_(_number_match(Account.account_no, term),
                       Account.name.ilike(like)))
            .order_by(Account.account_no.asc())
            .limit(limit)
        )
        add("Chart of Accounts", [
            {
                "id": str(a.id),
                "label": f"{a.account_no} · {a.name}",
                "sublabel": a.account_type,
                "link": "/accounts",
            }
            for a in (await db.scalars(a_stmt)).all()
        ])

    return {
        "query": q,
        "groups": groups,
        "total": sum(len(g["items"]) for g in groups),
    }


async def _customer_names(db: AsyncSession, ids) -> dict[UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = (await db.execute(
        select(Customer.id, Customer.company_name).where(Customer.id.in_(wanted))
    )).all()
    return {r[0]: r[1] for r in rows}


async def _supplier_names(db: AsyncSession, ids) -> dict[UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = (await db.execute(
        select(Supplier.id, Supplier.name).where(Supplier.id.in_(wanted))
    )).all()
    return {r[0]: r[1] for r in rows}


async def _quotation_lines(db: AsyncSession, ids, like: str) -> dict[UUID, str]:
    """The quotation line that matched, for the subtitle."""
    if not ids:
        return {}
    rows = (await db.execute(
        select(QuotationItem.quotation_id, QuotationItem.description,
               QuotationItem.qty, QuotationItem.uom)
        .where(QuotationItem.quotation_id.in_(ids),
               QuotationItem.description.ilike(like))
    )).all()
    out: dict[UUID, str] = {}
    for qid, desc, qty, uom in rows:
        if qid in out:
            continue
        tail = f" · {float(qty):g} {uom}" if qty is not None and uom else ""
        out[qid] = f"{desc}{tail}"
    return out
