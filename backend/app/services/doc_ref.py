"""What a document is *called*, for the people who browse the bucket.

Every attachment row knows what it belongs to as `(owner_type, owner_id)` —
which is exactly right for the program and useless for a person. `owner_id` is
a UUID; nobody has ever walked up to the filing cabinet asking for
`8f3a1c22-…`. They ask for the scans on PO-2026-0043, or the drawings on
PRJ-BUKIT-7, or Budi's contract.

This module answers the second question. Given an owner, it returns the label
that document is known by in conversation — a number where the document has
one, a name where it does not — and `build_key` in `storage.py` files the
object under it.

Three things are deliberate:

* **A reference may name more than one level**, and says so by being a tuple
  rather than a string: `customer_contact` returns `(company, person)`,
  because a PIC's ID card belongs under the company before it belongs under
  the person. A plain string is always exactly one folder, slashes and all —
  a customer PO number is the customer's own and often looks like
  `001/PO/IX/2026`, which must not become four folders.

* **An approval request borrows its target's reference.** The paperwork filed
  to justify releasing a delivery order is *about* that delivery order; filing
  it under the approval's own UUID buries it one indirection away from the
  only thing anybody would look under. Resolution therefore recurses exactly
  once — an approval about an approval is not a thing, and one hop cannot
  loop.

* **None is a normal answer.** A row that has been deleted, an owner type
  nothing here knows about, a number not yet issued: all of them return None
  and the caller falls back to the UUID. A file that lands in a less
  convenient folder is a filing inconvenience; an upload that fails because a
  lookup did is an outage. Nothing in here is allowed to raise.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _lookup(db: AsyncSession, model, owner_id) -> object | None:
    """`db.get`, without letting a half-built unit of work flush underneath us.

    Callers resolve the reference on the way to writing an attachment row, so
    the session usually has pending objects. An autoflush here would push them
    out early, in the middle of somebody else's transaction.
    """
    try:
        oid = owner_id if isinstance(owner_id, UUID) else UUID(str(owner_id))
    except (TypeError, ValueError):
        return None
    with db.no_autoflush:
        return await db.get(model, oid)


async def document_ref(db: AsyncSession, owner_type: str | None,
                       owner_id: object | None, *,
                       _depth: int = 0) -> str | tuple[str, ...] | None:
    """The human name for `(owner_type, owner_id)`, or None if there isn't one.

    A tuple means "nest these", one folder per element. Never raises: every
    failure mode is "file it under the UUID instead".
    """
    if not owner_type or owner_id is None:
        return None

    try:
        return await _resolve(db, owner_type, owner_id, _depth)
    except Exception:                       # noqa: BLE001 — see module docstring
        logger.warning("doc_ref: could not name %s/%s", owner_type, owner_id,
                       exc_info=True)
        return None


async def _resolve(db: AsyncSession, owner_type: str, owner_id: object,
                   depth: int) -> str | tuple[str, ...] | None:
    # ── documents that carry their own number ────────────────────────────
    if owner_type == "quotation":
        from app.models.quotation import Quotation
        row = await _lookup(db, Quotation, owner_id)
        return row.number if row else None

    if owner_type == "price_request":
        from app.models.price_request import PriceRequest
        row = await _lookup(db, PriceRequest, owner_id)
        return row.number if row else None

    if owner_type == "supplier_price_request":
        from app.models.purchasing import SupplierPriceRequest
        row = await _lookup(db, SupplierPriceRequest, owner_id)
        return row.number if row else None

    if owner_type == "supplier_po":
        from app.models.purchasing import SupplierPO
        row = await _lookup(db, SupplierPO, owner_id)
        return row.number if row else None

    if owner_type == "customer_po":
        # The only number here the customer chose rather than us. It is not
        # unique across customers — "001/PO/IX/2026" is a common shape — so two
        # of them can share a folder. That is a display collision and nothing
        # worse: the uuid prefix on each object key still keeps the files apart.
        from app.models.customer_po import CustomerPO
        row = await _lookup(db, CustomerPO, owner_id)
        return row.number if row else None

    if owner_type == "invoice":
        from app.models.finance import Invoice
        row = await _lookup(db, Invoice, owner_id)
        return row.number if row else None

    if owner_type == "delivery_order":
        from app.models.operation import DeliveryOrder
        row = await _lookup(db, DeliveryOrder, owner_id)
        return row.number if row else None

    if owner_type == "project":
        from app.models.operation import Project
        row = await _lookup(db, Project, owner_id)
        return row.code if row else None

    # ── parties, which go by name ────────────────────────────────────────
    if owner_type == "customer":
        from app.models.crm import Customer
        row = await _lookup(db, Customer, owner_id)
        return row.company_name if row else None

    if owner_type == "supplier":
        from app.models.purchasing import Supplier
        row = await _lookup(db, Supplier, owner_id)
        return row.name if row else None

    if owner_type == "customer_contact":
        from app.models.crm import Customer, CustomerContact
        row = await _lookup(db, CustomerContact, owner_id)
        if not row:
            return None
        parent = await _lookup(db, Customer, row.customer_id)
        return (parent.company_name, row.name) if parent else row.name

    if owner_type == "supplier_contact":
        from app.models.purchasing import Supplier, SupplierContact
        row = await _lookup(db, SupplierContact, owner_id)
        if not row:
            return None
        parent = await _lookup(db, Supplier, row.supplier_id)
        return (parent.name, row.name) if parent else row.name

    if owner_type == "employee":
        # Number first so the folder sorts by it, name after so it can be read.
        from app.models.employee import Employee
        row = await _lookup(db, Employee, owner_id)
        return f"{row.employee_no} {row.full_name}" if row else None

    if owner_type == "user":
        from app.models.user import User
        row = await _lookup(db, User, owner_id)
        return row.full_name if row else None

    if owner_type == "daily_log":
        # The one place a date genuinely identifies the document rather than
        # merely recording when it was filed. Person first: "what did Budi
        # hand in" is the question, and the dates then sort under it.
        from app.models.daily_log import DailyLog
        from app.models.user import User
        row = await _lookup(db, DailyLog, owner_id)
        if not row:
            return None
        who = await _lookup(db, User, row.user_id)
        day = f"{row.date:%Y-%m-%d}"
        return (who.full_name, day) if who else day

    if owner_type == "approval_request":
        # Files under whatever the approval is ABOUT — see the module docstring.
        if depth:
            return None
        from app.models.approval import ApprovalRequest
        row = await _lookup(db, ApprovalRequest, owner_id)
        if not row:
            return None
        target = _APPROVAL_TARGET_ALIASES.get(row.target_type, row.target_type)
        return await document_ref(db, target, row.target_id, _depth=1)

    return None


# An approval's `target_type` says which *decision* is being asked for, not
# which table the id points at — "quotation_won" and "quotation_edit" are both
# questions about a quotation. Only the ones that resolve to a document belong
# here; the rest (followup, cross_dept_chat) have no filing cabinet of their
# own and fall back to the UUID.
_APPROVAL_TARGET_ALIASES = {
    "quotation_won": "quotation",
    "quotation_edit": "quotation",
    "price_request_revision": "price_request",
}
