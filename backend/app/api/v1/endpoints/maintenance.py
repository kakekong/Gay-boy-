"""Director-only data maintenance.

One job today: clear out the records left behind while the system was being
built, keeping the real ones. The system ran alongside its own development for
months, so the database holds a mix of genuine deals and throwaway test rows,
and there is no flag on a row saying which is which.

**What counts as real is decided per customer, not per row.** That is not a
shortcut — it is the only rule that works here. A project is created by
whoever *approves* the customer PO (finance or the director), and an invoice is
issued by finance or admin, so "rows created by the sales rep" would miss most
of that rep's own pipeline and delete live projects. Every document in the four
families hangs off one customer, though, so the customer is the honest anchor:
a customer is real if the people you name touched it anywhere in its lineage,
and everything under a real customer stays.

Deleting a customer means deleting its whole history — quotations, POs,
projects, invoices, payments, ledger entries. The foreign keys enforce that
anyway (`ON DELETE RESTRICT` on every customer_id), so there is no version of
this that keeps the money records and drops the customer. The preview says so
in numbers before anything happens.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, delete as sqldelete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest
from app.models.attachment import Attachment
from app.models.comment import EntityComment
from app.models.crm import Customer, CustomerContact
from app.models.customer_po import CustomerPO
from app.models.finance import Invoice, LedgerEntry, Payment
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder
from app.models.price_request import PriceRequest
from app.models.purchasing import PurchaseRequest, RFQ, SupplierPO
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User

router = APIRouter(dependencies=[Depends(require(Role.DIRECTOR))])

# Typed by hand in the UI before the delete will run. Deliberately not
# translated: it should be awkward, and it should look the same in every
# screenshot of the confirmation.
CONFIRM_PHRASE = "DELETE TEST DATA"


class PurgeIn(BaseModel):
    """Whose data survives. Everyone else's customers go."""

    keep_user_ids: list[UUID] = []
    confirm: str | None = None


async def _ids(db: AsyncSession, stmt) -> set[UUID]:
    return {r for (r,) in (await db.execute(stmt)).all() if r}


async def _require_real_director(db: AsyncSession, me: User) -> None:
    """A custom role that merely *inherits* director must not reach this.

    `require(Role.DIRECTOR)` passes on the base role, which a director-based
    custom role also carries. That is right for reading the KPI page and wrong
    for deleting the company's history.
    """
    if getattr(me, "custom_role_id", None):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This is limited to the director account itself, not a custom role.",
        )


async def _build_plan(db: AsyncSession, keep_ids: set[UUID]) -> dict:
    """Work out which customers are real, and everything that hangs off the rest.

    Returns the id sets plus the counts the preview reports. Nothing is deleted
    here — `execute` calls this first and then acts on exactly these ids, so the
    preview and the delete can never disagree about what is in scope.
    """
    # ── 1. Which customers count as real? Any of five ways in. ───────────────
    by_rule: dict[str, set[UUID]] = {
        "owns the customer": await _ids(db, select(Customer.id).where(or_(
            Customer.sales_pic_id.in_(keep_ids), Customer.created_by.in_(keep_ids)))),
        "raised a price request": await _ids(db, select(PriceRequest.customer_id).where(or_(
            PriceRequest.sales_pic_id.in_(keep_ids), PriceRequest.created_by.in_(keep_ids)))),
        "wrote a quotation": await _ids(db, select(Quotation.customer_id).where(or_(
            Quotation.sales_pic_id.in_(keep_ids), Quotation.created_by.in_(keep_ids)))),
        "entered a customer PO": await _ids(db, select(CustomerPO.customer_id).where(
            CustomerPO.created_by.in_(keep_ids))),
    }
    # There is deliberately no "created a project" rule. `projects.created_by`
    # is whoever *approved* the customer PO — nearly always the director — so it
    # says nothing about who originated the deal, and as a keep-rule it would
    # rescue every test customer that ever reached the project stage. The
    # customer PO above is the same deal at the point the originator entered it.
    keep_customers: set[UUID] = set().union(*by_rule.values()) if by_rule else set()
    all_customers = await _ids(db, select(Customer.id))
    doomed = all_customers - keep_customers

    # ── 2. Everything hanging off the doomed customers ───────────────────────
    projects = await _ids(db, select(Project.id).where(Project.customer_id.in_(doomed)))
    quotes = await _ids(db, select(Quotation.id).where(Quotation.customer_id.in_(doomed)))
    prs = await _ids(db, select(PriceRequest.id).where(PriceRequest.customer_id.in_(doomed)))
    cpos = await _ids(db, select(CustomerPO.id).where(CustomerPO.customer_id.in_(doomed)))
    # An invoice can reach its customer three ways; take all of them so none is
    # left pointing at a deleted parent.
    invoices = await _ids(db, select(Invoice.id).where(or_(
        Invoice.customer_id.in_(doomed),
        Invoice.project_id.in_(projects),
        Invoice.customer_po_id.in_(cpos))))
    # Procurement hangs off the project, and its FK is SET NULL — deleting the
    # project alone would leave a supplier PO floating with no project.
    spos = await _ids(db, select(SupplierPO.id).where(SupplierPO.project_id.in_(projects)))
    preqs = await _ids(db, select(PurchaseRequest.id).where(
        PurchaseRequest.project_id.in_(projects)))
    rfqs = await _ids(db, select(RFQ.id).where(RFQ.pr_id.in_(preqs)))

    # Cascade children — deleted by the database, but the preview should still
    # say how many, because "12 delivery orders" is what the director recognises.
    contacts = await _ids(db, select(CustomerContact.id).where(
        CustomerContact.customer_id.in_(doomed)))
    work_orders = await _ids(db, select(WorkOrder.id).where(WorkOrder.project_id.in_(projects)))
    drawings = await _ids(db, select(Drawing.id).where(Drawing.project_id.in_(projects)))
    dos = await _ids(db, select(DeliveryOrder.id).where(DeliveryOrder.project_id.in_(projects)))
    payments = await db.scalar(
        select(func.count(Payment.id)).where(Payment.invoice_id.in_(invoices))) or 0
    items = await db.scalar(
        select(func.count(QuotationItem.id)).where(QuotationItem.quotation_id.in_(quotes))) or 0

    # ── 3. The rows that point at all of the above without a foreign key ─────
    # Attachments, discussions, approvals and ledger entries are polymorphic:
    # (owner_type, owner_id) with nothing for the database to cascade. Matching
    # on the id alone is deliberate — uuids don't collide across tables, and it
    # catches owner types nobody remembered to list here.
    doomed_ids = (doomed | projects | quotes | prs | cpos | invoices | spos | preqs
                  | rfqs | contacts | work_orders | drawings | dos)

    attachments = await _ids(db, select(Attachment.id).where(
        Attachment.owner_id.in_(doomed_ids)))
    comments = await _ids(db, select(EntityComment.id).where(
        EntityComment.owner_id.in_(doomed_ids)))
    approvals = await _ids(db, select(ApprovalRequest.id).where(
        ApprovalRequest.target_id.in_(doomed_ids)))
    ledger = await _ids(db, select(LedgerEntry.id).where(
        LedgerEntry.source_id.in_(doomed_ids)))

    return {
        "keep_customers": keep_customers,
        "by_rule": by_rule,
        "doomed": doomed,
        "projects": projects, "quotes": quotes, "prs": prs, "cpos": cpos,
        "invoices": invoices, "spos": spos, "preqs": preqs, "rfqs": rfqs,
        "contacts": contacts, "work_orders": work_orders, "drawings": drawings,
        "dos": dos, "attachments": attachments, "comments": comments,
        "approvals": approvals, "ledger": ledger,
        "counts": {
            "customers": len(doomed), "price_requests": len(prs),
            "quotations": len(quotes), "quotation_items": items,
            "customer_pos": len(cpos), "projects": len(projects),
            "work_orders": len(work_orders), "drawings": len(drawings),
            "delivery_orders": len(dos), "contacts": len(contacts),
            "invoices": len(invoices), "payments": payments,
            "ledger_entries": len(ledger), "supplier_pos": len(spos),
            "purchase_requests": len(preqs), "rfqs": len(rfqs),
            "attachments": len(attachments), "discussion_messages": len(comments),
            "approval_requests": len(approvals),
        },
    }


async def _customer_rows(db: AsyncSession, ids: set[UUID], plan: dict,
                         limit: int = 400) -> list[dict]:
    """Name the customers, and say which rule kept the ones being kept."""
    if not ids:
        return []
    rows = (await db.scalars(
        select(Customer).where(Customer.id.in_(list(ids)[:limit]))
        .order_by(Customer.company_name)
    )).all()
    out = []
    for cst in rows:
        why = [name for name, hit in plan["by_rule"].items() if cst.id in hit]
        out.append({
            "id": str(cst.id),
            "name": cst.company_name,
            "stage": cst.stage,
            "why": why,
        })
    return out


@router.get("/data-owners")
async def data_owners(db: AsyncSession = Depends(get_db)):
    """Everyone who has entered anything, with how much — so the director can
    see at a glance who the real data belongs to before choosing."""
    users = (await db.scalars(
        select(User).where(User.role.notin_([Role.CUSTOMER.value, Role.SUPPLIER.value]))
        .order_by(User.full_name)
    )).all()

    async def n(stmt) -> int:
        return await db.scalar(stmt) or 0

    out = []
    for u in users:
        out.append({
            "id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "customers": await n(select(func.count(Customer.id)).where(or_(
                Customer.sales_pic_id == u.id, Customer.created_by == u.id))),
            "price_requests": await n(select(func.count(PriceRequest.id)).where(or_(
                PriceRequest.sales_pic_id == u.id, PriceRequest.created_by == u.id))),
            "quotations": await n(select(func.count(Quotation.id)).where(or_(
                Quotation.sales_pic_id == u.id, Quotation.created_by == u.id))),
            "customer_pos": await n(select(func.count(CustomerPO.id)).where(
                CustomerPO.created_by == u.id)),
            "projects": await n(select(func.count(Project.id)).where(
                Project.created_by == u.id)),
        })
    return out


@router.post("/purge/preview")
async def purge_preview(payload: PurgeIn, db: AsyncSession = Depends(get_db)):
    """Exactly what the delete would do, without doing any of it."""
    keep_ids = set(payload.keep_user_ids)
    if not keep_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Choose at least one person whose data is real.")
    plan = await _build_plan(db, keep_ids)
    keepers = (await db.scalars(select(User).where(User.id.in_(keep_ids)))).all()
    return {
        "confirm_phrase": CONFIRM_PHRASE,
        "keeping": [{"id": str(u.id), "full_name": u.full_name, "role": u.role}
                    for u in keepers],
        "counts": plan["counts"],
        "customers_to_delete": await _customer_rows(db, plan["doomed"], plan),
        "customers_to_keep": await _customer_rows(db, plan["keep_customers"], plan),
        "kept_customer_count": len(plan["keep_customers"]),
    }


@router.post("/purge/execute")
async def purge_execute(payload: PurgeIn, db: AsyncSession = Depends(get_db),
                        me: User = Depends(require(Role.DIRECTOR))):
    """Do it. One transaction — it either all lands or none of it does."""
    await _require_real_director(db, me)
    if (payload.confirm or "").strip() != CONFIRM_PHRASE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f'Type "{CONFIRM_PHRASE}" to confirm.')
    keep_ids = set(payload.keep_user_ids)
    if not keep_ids:
        # Without this, an empty selection is a request to delete every customer
        # in the company. Never do that by omission.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Choose at least one person whose data is real.")

    plan = await _build_plan(db, keep_ids)
    if not plan["doomed"]:
        return {"deleted": plan["counts"], "files_removed": 0,
                "message": "Nothing to delete — every customer belongs to the people you kept."}

    # Grab the stored file paths before the rows go; the objects themselves are
    # removed after the transaction commits, so a rollback can't strand a row
    # whose file is already gone.
    paths = [p for (p,) in (await db.execute(
        select(Attachment.storage_path).where(Attachment.id.in_(plan["attachments"]))
    )).all() if p]

    async def wipe(model, column, ids):
        if ids:
            await db.execute(sqldelete(model).where(column.in_(ids)))

    # Order matters: every customer_id is ON DELETE RESTRICT, so the customer
    # cannot go until its whole history has.
    await wipe(LedgerEntry, LedgerEntry.id, plan["ledger"])
    await wipe(Attachment, Attachment.id, plan["attachments"])
    await wipe(EntityComment, EntityComment.id, plan["comments"])   # mentions cascade
    await wipe(ApprovalRequest, ApprovalRequest.id, plan["approvals"])
    await wipe(Invoice, Invoice.id, plan["invoices"])               # payments + claims cascade
    await wipe(SupplierPO, SupplierPO.id, plan["spos"])             # receipts + QC cascade
    await wipe(RFQ, RFQ.id, plan["rfqs"])
    await wipe(PurchaseRequest, PurchaseRequest.id, plan["preqs"])
    await wipe(CustomerPO, CustomerPO.id, plan["cpos"])
    await wipe(Project, Project.id, plan["projects"])               # WO/drawings/DO cascade
    await wipe(Quotation, Quotation.id, plan["quotes"])             # items cascade
    await wipe(PriceRequest, PriceRequest.id, plan["prs"])
    await wipe(Customer, Customer.id, plan["doomed"])               # contacts/activities/reminders cascade

    await record(
        db, actor=me, action="purge_test_data", entity="database", entity_id=None,
        after={"kept_user_ids": [str(u) for u in keep_ids], "counts": plan["counts"]},
    )
    await db.commit()

    # Best effort, and only now: the rows are gone for good, so a failure here
    # costs bucket space, not data. `storage.delete` swallows its own errors, so
    # this counts files handed to it, not files provably gone.
    from app.services import storage
    for p in paths:
        try:
            await storage.delete(p)
        except Exception:  # noqa: BLE001 — never fail the purge over a stray file
            pass

    return {"deleted": plan["counts"], "files_cleared": len(paths)}
