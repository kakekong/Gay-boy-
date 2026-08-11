"""Director-only data maintenance.

Two ways to delete, for two different problems.

**By owner** — the original. The system ran alongside its own development for
months, so the database holds a mix of genuine deals and throwaway test rows
with no flag saying which is which. Naming the people whose data is real sorts
thousands of rows in one pass.

**By record** — pick this price request, that customer PO, and delete exactly
those. The sweep is the wrong tool once the bulk is gone and what is left is
three quotations someone entered twice. It is also the only tool for a test row
belonging to a real person, which the sweep deliberately protects.

Both end in the same place: `_execute_plan` deletes from one set of ids in one
transaction, so there is exactly one piece of code that knows the order the
foreign keys demand.

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
from sqlalchemy import delete as sqldelete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest
from app.models.attachment import Attachment
from app.models.comment import EntityComment
from app.models.crm import Customer, CustomerContact
from app.models.customer_po import CustomerPO
from app.models.account import Account
from app.models.finance import Invoice, LedgerEntry, Payment
from app.models.inventory import InventoryItem
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder
from app.models.price_request import PriceRequest
from app.models.purchasing import (
    PurchaseRequest, RFQ, SupplierPO, SupplierPriceRequest,
)
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
    # The buy-side quotes raised to cost a doomed price request. Their FK is
    # SET NULL, so leaving them would strand a quote pointing at nothing —
    # and one whose whole meaning was "this is what that job cost us".
    sprs = await _ids(db, select(SupplierPriceRequest.id).where(
        SupplierPriceRequest.price_request_id.in_(prs)))

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
                  | rfqs | sprs | contacts | work_orders | drawings | dos)

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
        "sprs": sprs,
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
            "supplier_price_requests": len(sprs),
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

    files = await _execute_plan(db, plan)
    await record(
        db, actor=me, action="purge_test_data", entity="database", entity_id=None,
        after={"kept_user_ids": [str(u) for u in keep_ids], "counts": plan["counts"]},
    )
    await db.commit()
    await _drop_files(files)
    return {"deleted": plan["counts"], "files_cleared": len(files)}


async def _execute_plan(db: AsyncSession, plan: dict) -> list[str]:
    """Delete everything the plan names, in the order the keys allow.

    Returns the storage paths of the attachments that went, for the caller to
    clean up **after** it commits — the objects outlive a rollback, so a row
    must never be left pointing at a file that is already gone.

    Every delete path goes through here. Both callers build the same shaped
    plan precisely so that the ordering below is written once: the order is not
    obvious, it is enforced by `ON DELETE RESTRICT` on every `customer_id`, and
    a second copy of it would rot.
    """
    paths = [p for (p,) in (await db.execute(
        select(Attachment.storage_path).where(Attachment.id.in_(plan["attachments"]))
    )).all() if p]

    async def wipe(model, column, ids):
        if ids:
            await db.execute(sqldelete(model).where(column.in_(ids)))

    async def detach(model, column, ids):
        """Clear a soft reference on rows that are *staying*.

        Several links between documents are plain uuid columns with no foreign
        key, so the database will not clean them up and will not complain. A
        price request keeps `quotation_id` after its quotation is deleted, and
        then refuses to produce a new one — "this price request already has a
        quotation", for a quotation that no longer exists. Left alone that
        makes a deleted document quietly unrepeatable.
        """
        if ids:
            await db.execute(
                model.__table__.update().where(column.in_(ids)).values(**{column.key: None}))

    await detach(PriceRequest, PriceRequest.quotation_id, plan["quotes"])
    await detach(Quotation, Quotation.price_request_id, plan["prs"])
    await detach(Quotation, Quotation.project_id, plan["projects"])
    await detach(Project, Project.price_request_id, plan["prs"])
    await detach(SupplierPO, SupplierPO.price_request_id, plan["prs"])

    await wipe(LedgerEntry, LedgerEntry.id, plan["ledger"])
    await wipe(Attachment, Attachment.id, plan["attachments"])
    await wipe(EntityComment, EntityComment.id, plan["comments"])   # mentions cascade
    await wipe(ApprovalRequest, ApprovalRequest.id, plan["approvals"])
    await wipe(Invoice, Invoice.id, plan["invoices"])               # payments + claims cascade
    await wipe(SupplierPO, SupplierPO.id, plan["spos"])             # receipts + QC cascade
    await wipe(SupplierPriceRequest, SupplierPriceRequest.id, plan.get("sprs") or set())
    await wipe(RFQ, RFQ.id, plan["rfqs"])
    await wipe(PurchaseRequest, PurchaseRequest.id, plan["preqs"])
    await wipe(CustomerPO, CustomerPO.id, plan["cpos"])
    await wipe(Project, Project.id, plan["projects"])               # WO/drawings/DO cascade
    await wipe(Quotation, Quotation.id, plan["quotes"])             # items cascade
    await wipe(PriceRequest, PriceRequest.id, plan["prs"])
    await wipe(Customer, Customer.id, plan["doomed"])               # contacts/activities/reminders cascade
    # Flat records, deleted last because nothing else waits on them.
    await wipe(InventoryItem, InventoryItem.id, plan.get("items") or set())  # movements cascade
    await wipe(Account, Account.id, plan.get("accounts") or set())
    return paths


async def _drop_files(paths: list[str]) -> None:
    """Best effort, and only after the commit: the rows are gone for good, so a
    failure here costs bucket space, not data."""
    from app.services import storage
    for p in paths:
        try:
            await storage.delete(p)
        except Exception:  # noqa: BLE001 — never fail a delete over a stray file
            pass


# ═══ Deleting named records ══════════════════════════════════════════════════
#
# Deleting one document is never really one document. A price request becomes a
# quotation becomes a customer PO becomes a project becomes invoices, and the
# database will not let the parent go while the children point at it — or worse,
# for the columns that are `SET NULL`, it *will*, and leaves an invoice attached
# to a project that no longer exists.
#
# So a selection is expanded to its descendants before anything is counted, and
# the preview shows the whole tree. What the director picks is the root; what
# they are shown, and what goes, is everything downstream of it. Upstream is
# never touched: deleting a quotation must not take the price request it came
# from, because that request is a real thing that really happened.

RECORD_TYPES: dict[str, dict] = {
    "price_request": {"model": PriceRequest, "label": "Price request", "num": "number"},
    "quotation":     {"model": Quotation,    "label": "Quotation",     "num": "number"},
    "customer_po":   {"model": CustomerPO,   "label": "Customer PO",   "num": "number"},
    "project":       {"model": Project,      "label": "Project",       "num": "code"},
    "invoice":       {"model": Invoice,      "label": "Invoice",       "num": "number"},
    "supplier_po":   {"model": SupplierPO,   "label": "Supplier PO",   "num": "number"},
    "purchase_request": {"model": PurchaseRequest, "label": "Purchase request", "num": "number"},
    "supplier_price_request": {"model": SupplierPriceRequest,
                               "label": "Supplier price request", "num": "number"},
    "customer":      {"model": Customer,     "label": "Customer",      "num": "company_name"},
    # Flat records with nothing hanging off them. They are here because an
    # import is the main way they arrive in bulk, and a test batch you cannot
    # remove is a test you only get to run once.
    "inventory_item": {"model": InventoryItem, "label": "Part", "num": "sku"},
    "account":        {"model": Account,       "label": "Account", "num": "account_no"},
}


class Target(BaseModel):
    type: str
    id: UUID


class RecordsIn(BaseModel):
    targets: list[Target] = []
    confirm: str | None = None
    # Deleting an invoice that has been paid, or one already posted to the
    # ledger, is a different act from deleting a draft — it removes money that
    # the books say arrived. It needs its own yes.
    allow_financial: bool = False


async def _closure(db: AsyncSession, targets: list[Target]) -> dict:
    """Everything that must go if these records go. Nothing is deleted here.

    Walked to a fixed point rather than in one pass, because the graph is not
    a tree: a customer PO reaches invoices directly *and* through its project,
    and a purchase request reaches supplier POs through its RFQs.
    """
    prs: set[UUID] = set()
    quotes: set[UUID] = set()
    cpos: set[UUID] = set()
    projects: set[UUID] = set()
    invoices: set[UUID] = set()
    spos: set[UUID] = set()
    preqs: set[UUID] = set()
    rfqs: set[UUID] = set()
    picked_sprs: set[UUID] = set()     # buy-side quotes named directly
    doomed: set[UUID] = set()          # customers
    parts: set[UUID] = set()           # inventory parts — nothing hangs off them
    accounts: set[UUID] = set()        # chart-of-accounts rows, likewise

    bucket = {
        "price_request": prs, "quotation": quotes, "customer_po": cpos,
        "project": projects, "invoice": invoices, "supplier_po": spos,
        "purchase_request": preqs, "customer": doomed,
        "supplier_price_request": picked_sprs,
        "inventory_item": parts, "account": accounts,
    }
    for t in targets:
        if t.type in bucket:
            bucket[t.type].add(t.id)

    # A named customer is the sweep's job, and it already knows how: pull its
    # whole lineage in rather than reimplementing it here.
    for cid in list(doomed):
        prs |= await _ids(db, select(PriceRequest.id).where(PriceRequest.customer_id == cid))
        quotes |= await _ids(db, select(Quotation.id).where(Quotation.customer_id == cid))
        cpos |= await _ids(db, select(CustomerPO.id).where(CustomerPO.customer_id == cid))
        projects |= await _ids(db, select(Project.id).where(Project.customer_id == cid))
        invoices |= await _ids(db, select(Invoice.id).where(Invoice.customer_id == cid))

    for _ in range(6):                 # deeper than the chain actually is
        before = (len(prs), len(quotes), len(cpos), len(projects),
                  len(invoices), len(spos), len(preqs), len(rfqs))

        if prs:
            quotes |= await _ids(db, select(Quotation.id).where(
                Quotation.price_request_id.in_(prs)))
            quotes |= await _ids(db, select(PriceRequest.quotation_id).where(
                PriceRequest.id.in_(prs)))
            spos |= await _ids(db, select(SupplierPO.id).where(
                SupplierPO.price_request_id.in_(prs)))
        if quotes:
            # A revision points at the quotation it replaced; deleting the
            # original without its revisions leaves them orphaned mid-chain.
            quotes |= await _ids(db, select(Quotation.id).where(
                Quotation.parent_id.in_(quotes)))
            cpos |= await _ids(db, select(CustomerPO.id).where(
                CustomerPO.quotation_id.in_(quotes)))
            projects |= await _ids(db, select(Project.id).where(
                Project.quotation_id.in_(quotes)))
        if cpos:
            projects |= await _ids(db, select(CustomerPO.project_id).where(
                CustomerPO.id.in_(cpos)))
            invoices |= await _ids(db, select(Invoice.id).where(
                Invoice.customer_po_id.in_(cpos)))
        if projects:
            invoices |= await _ids(db, select(Invoice.id).where(
                Invoice.project_id.in_(projects)))
            spos |= await _ids(db, select(SupplierPO.id).where(
                SupplierPO.project_id.in_(projects)))
            preqs |= await _ids(db, select(PurchaseRequest.id).where(
                PurchaseRequest.project_id.in_(projects)))
        if preqs:
            rfqs |= await _ids(db, select(RFQ.id).where(RFQ.pr_id.in_(preqs)))
        if rfqs:
            spos |= await _ids(db, select(SupplierPO.id).where(
                SupplierPO.rfq_id.in_(rfqs)))

        after = (len(prs), len(quotes), len(cpos), len(projects),
                 len(invoices), len(spos), len(preqs), len(rfqs))
        if before == after:
            break

    # Buy-side quotes raised against a doomed price request. Their FK is SET
    # NULL, so they survive the delete pointing at nothing — a supplier quote
    # whose only meaning was the job it was costing.
    sprs = picked_sprs | (await _ids(db, select(SupplierPriceRequest.id).where(
        SupplierPriceRequest.price_request_id.in_(prs))) if prs else set())

    # Cascade children — the database removes them, but the preview should say
    # how many, because "12 delivery orders" is what a director recognises.
    contacts = await _ids(db, select(CustomerContact.id).where(
        CustomerContact.customer_id.in_(doomed)))
    work_orders = await _ids(db, select(WorkOrder.id).where(WorkOrder.project_id.in_(projects)))
    drawings = await _ids(db, select(Drawing.id).where(Drawing.project_id.in_(projects)))
    dos = await _ids(db, select(DeliveryOrder.id).where(DeliveryOrder.project_id.in_(projects)))
    payments = await db.scalar(
        select(func.count(Payment.id)).where(Payment.invoice_id.in_(invoices))) or 0
    line_count = await db.scalar(
        select(func.count(QuotationItem.id)).where(QuotationItem.quotation_id.in_(quotes))) or 0

    doomed_ids = (doomed | projects | quotes | prs | cpos | invoices | spos | preqs
                  | rfqs | sprs | contacts | work_orders | drawings | dos)
    attachments = await _ids(db, select(Attachment.id).where(
        Attachment.owner_id.in_(doomed_ids)))
    comments = await _ids(db, select(EntityComment.id).where(
        EntityComment.owner_id.in_(doomed_ids)))
    approvals = await _ids(db, select(ApprovalRequest.id).where(
        ApprovalRequest.target_id.in_(doomed_ids)))
    ledger = await _ids(db, select(LedgerEntry.id).where(or_(
        LedgerEntry.source_id.in_(doomed_ids),
        # A ledger entry names its customer in its own column as well as its
        # source document; a customer deleted here must not stay named in the
        # books by a row nothing else points at.
        LedgerEntry.customer_id.in_(doomed))))

    return {
        "keep_customers": set(), "by_rule": {},
        "doomed": doomed,
        "items": parts, "accounts": accounts,
        "projects": projects, "quotes": quotes, "prs": prs, "cpos": cpos,
        "invoices": invoices, "spos": spos, "preqs": preqs, "rfqs": rfqs,
        "sprs": sprs,
        "contacts": contacts, "work_orders": work_orders, "drawings": drawings,
        "dos": dos, "attachments": attachments, "comments": comments,
        "approvals": approvals, "ledger": ledger,
        "counts": {
            "customers": len(doomed), "price_requests": len(prs),
            "quotations": len(quotes), "quotation_items": line_count,
            "customer_pos": len(cpos), "projects": len(projects),
            "work_orders": len(work_orders), "drawings": len(drawings),
            "delivery_orders": len(dos), "contacts": len(contacts),
            "invoices": len(invoices), "payments": payments,
            "ledger_entries": len(ledger), "supplier_pos": len(spos),
            "purchase_requests": len(preqs), "rfqs": len(rfqs),
            "supplier_price_requests": len(sprs),
            "attachments": len(attachments), "discussion_messages": len(comments),
            "approval_requests": len(approvals),
            "inventory_items": len(parts), "accounts": len(accounts),
        },
    }


async def _describe(db: AsyncSession, plan: dict) -> list[dict]:
    """Name every document in the plan, so the preview is a list of documents
    rather than a column of numbers."""
    out: list[dict] = []
    for kind, ids in (("price_request", plan["prs"]), ("quotation", plan["quotes"]),
                      ("customer_po", plan["cpos"]), ("project", plan["projects"]),
                      ("invoice", plan["invoices"]), ("supplier_po", plan["spos"]),
                      ("purchase_request", plan["preqs"]), ("customer", plan["doomed"]),
                      ("supplier_price_request", plan.get("sprs", set())),
                      ("inventory_item", plan.get("items", set())),
                      ("account", plan.get("accounts", set()))):
        if not ids:
            continue
        spec = RECORD_TYPES[kind]
        model, num = spec["model"], spec["num"]
        rows = (await db.scalars(
            select(model).where(model.id.in_(list(ids)[:300]))
        )).all()
        for r in rows:
            out.append({
                "type": kind,
                "type_label": spec["label"],
                "id": str(r.id),
                "number": getattr(r, num, None),
                "status": getattr(r, "status", None),
                "total": float(getattr(r, "total", 0) or 0),
            })
    return out


async def _financial_warnings(db: AsyncSession, plan: dict) -> list[str]:
    """The things that make a delete different in kind, not just in size."""
    warns: list[str] = []
    if plan["invoices"]:
        paid = await db.scalar(select(func.count(Payment.id)).where(
            Payment.invoice_id.in_(plan["invoices"]))) or 0
        if paid:
            warns.append(
                f"{paid} payment(s) have been received against these invoices. "
                f"Deleting them removes money the books say arrived.")
    if plan["ledger"]:
        warns.append(
            f"{len(plan['ledger'])} ledger entries go with this. Any financial "
            f"report already run for those periods will change.")
    if plan.get("accounts"):
        # `LedgerEntry.account_no` is a string, not a foreign key, so deleting
        # an account that has been posted to leaves those entries naming an
        # account that is not in the chart — the trial balance still adds up,
        # but the line has no name. Worth a yes of its own.
        nos = [n for (n,) in (await db.execute(
            select(Account.account_no).where(Account.id.in_(plan["accounts"])))).all()]
        posted = await db.scalar(select(func.count(LedgerEntry.id)).where(
            LedgerEntry.account_no.in_(nos))) or 0
        if posted:
            warns.append(
                f"{posted} ledger entries have been posted to these accounts. "
                f"Deleting them leaves those entries without an account name.")
    return warns


@router.get("/records")
async def list_records(
    type: str,
    q: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Find documents of one kind, to pick from. Read-only."""
    spec = RECORD_TYPES.get(type)
    if not spec:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown record type. Try one of: {', '.join(RECORD_TYPES)}")
    model, num = spec["model"], spec["num"]
    stmt = select(model).order_by(model.created_at.desc()).limit(min(limit, 200))
    if q:
        stmt = stmt.where(getattr(model, num).ilike(f"%{q}%"))
    if hasattr(model, "is_deleted"):
        stmt = stmt.where(model.is_deleted.is_(False))
    rows = (await db.scalars(stmt)).all()

    # Name the customer alongside the number — "QUO-2026-0007" identifies
    # nothing on its own when you are deciding whether to delete it.
    cust_ids = {getattr(r, "customer_id", None) for r in rows}
    names = {
        cid: nm for cid, nm in (await db.execute(
            select(Customer.id, Customer.company_name)
            .where(Customer.id.in_([c for c in cust_ids if c]))
        )).all()
    }
    return [{
        "type": type,
        "id": str(r.id),
        "number": getattr(r, num, None),
        "status": getattr(r, "status", None),
        "total": float(getattr(r, "total", 0) or 0),
        "customer": names.get(getattr(r, "customer_id", None)),
        "created_at": getattr(r, "created_at", None),
    } for r in rows]


@router.post("/records/preview")
async def records_preview(payload: RecordsIn, db: AsyncSession = Depends(get_db)):
    """Everything that would go if these records went. Writes nothing."""
    if not payload.targets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing selected.")
    bad = {t.type for t in payload.targets} - set(RECORD_TYPES)
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown record type(s): {', '.join(sorted(bad))}")

    plan = await _closure(db, payload.targets)
    picked = {(t.type, str(t.id)) for t in payload.targets}
    documents = await _describe(db, plan)
    return {
        "confirm_phrase": CONFIRM_PHRASE,
        "counts": plan["counts"],
        "documents": documents,
        # What the director did not pick but would lose anyway. This is the
        # number that changes minds, so it is reported on its own.
        "pulled_in": sum(1 for d in documents if (d["type"], d["id"]) not in picked),
        "warnings": await _financial_warnings(db, plan),
    }


@router.post("/records/delete")
async def records_delete(payload: RecordsIn, db: AsyncSession = Depends(get_db),
                         me: User = Depends(require(Role.DIRECTOR))):
    """Delete the named records and everything created from them."""
    await _require_real_director(db, me)
    if (payload.confirm or "").strip() != CONFIRM_PHRASE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f'Type "{CONFIRM_PHRASE}" to confirm.')
    if not payload.targets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing selected.")
    bad = {t.type for t in payload.targets} - set(RECORD_TYPES)
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown record type(s): {', '.join(sorted(bad))}")

    plan = await _closure(db, payload.targets)
    warnings = await _financial_warnings(db, plan)
    if warnings and not payload.allow_financial:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This touches money that has already been recorded: "
            + " ".join(warnings)
            + " Tick the financial-records box to go ahead.")

    files = await _execute_plan(db, plan)
    await record(
        db, actor=me, action="delete_records", entity="database", entity_id=None,
        after={"targets": [{"type": t.type, "id": str(t.id)} for t in payload.targets],
               "counts": plan["counts"]},
    )
    await db.commit()
    await _drop_files(files)
    return {"deleted": plan["counts"], "files_cleared": len(files)}
