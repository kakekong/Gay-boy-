"""Customer Purchase Orders — the PO the customer sends us.

**Filing or approving one of these does not start a job.** The PO comes
first and is the evidence Won needs; marking the quotation Won is what
mints the project. The director's signature here says the paperwork is
right, not that the work has begun — so on approval this attaches to the
project the Won already made, and when the deal has not been Won yet the
PO is simply on file and waits.

The single exception is the **down-payment** flow. A deposit order
deliberately does not start at Won — not beginning work before the money
arrives is the entire point of a deposit — so sales confirming the deposit
landed is its starting gun, and that step mints the project instead.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require, require_min
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.crm import Customer, CustomerContact
from app.models.customer_po import CustomerPO
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User
from app.schemas.customer_po import (
    CustomerPOCreate,
    CustomerPOOut,
    CustomerPOPatch,
)

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

_any_internal = require(
    Role.SALES, Role.MANAGER, Role.ADMIN, Role.HR, Role.DIRECTOR,
    # Finance approves DP POs and issues the DP invoice — they need read
    # access to the PO list/detail like every other internal role.
    Role.FINANCE,
    # Purchasing is NOT here. The customer's own order is the customer side
    # of the job, and its number is customer identity in all but words —
    # the same reason they never see a company name on a price request.
    # They source against the price request and the project; what the
    # customer ordered under their own paperwork is not theirs to read.
)
_director_only = require(Role.DIRECTOR)


def _items_total(items: list[dict]) -> float:
    return sum(
        float(it.get("qty", 0) or 0) * float(it.get("unit_price", 0) or 0)
        for it in items
    )


async def _enrich(db: AsyncSession, po: CustomerPO) -> dict:
    cust = await db.get(Customer, po.customer_id) if po.customer_id else None
    quote = await db.get(Quotation, po.quotation_id) if po.quotation_id else None
    project = await db.get(Project, po.project_id) if po.project_id else None
    sales_pic = None
    if cust and cust.sales_pic_id:
        rep = await db.get(User, cust.sales_pic_id)
        if rep:
            sales_pic = {"id": str(rep.id), "name": rep.full_name}
    return {
        "id": po.id,
        "customer_id": po.customer_id,
        "customer_name": cust.company_name if cust else None,
        "sales_pic_id": sales_pic["id"] if sales_pic else None,
        "sales_pic_name": sales_pic["name"] if sales_pic else None,
        "quotation_id": po.quotation_id,
        "quotation_number": quote.number if quote else None,
        "number": po.number,
        "po_date": po.po_date,
        "items": po.items or [],
        "total": float(po.total or 0),
        "notes": po.notes,
        "status": po.status,
        "is_downpayment": bool(po.is_downpayment),
        "dp_finance_approved_at": po.dp_finance_approved_at,
        "dp_payment_confirmed_at": po.dp_payment_confirmed_at,
        "project_id": po.project_id,
        "project_code": project.code if project else None,
        "decided_by": po.decided_by,
        "decided_at": po.decided_at,
        "decision_notes": po.decision_notes,
        "created_at": po.created_at,
    }


@router.get("", response_model=list[CustomerPOOut])
async def list_customer_pos(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
    customer_id: UUID | None = None,
    status_eq: str | None = None,
    sales_pic_id: UUID | None = None,
):
    stmt = select(CustomerPO).order_by(CustomerPO.created_at.desc())
    if customer_id:
        stmt = stmt.where(CustomerPO.customer_id == customer_id)
    if status_eq:
        stmt = stmt.where(CustomerPO.status == status_eq)
    # Sales sees only their own customers' POs (matches the rest of the
    # CRM scope rules). A sales_pic_id filter lets management scope by rep.
    if Role(user.role) == Role.SALES:
        stmt = stmt.join(
            Customer, Customer.id == CustomerPO.customer_id
        ).where(Customer.sales_pic_id == user.id)
    elif sales_pic_id:
        stmt = stmt.join(
            Customer, Customer.id == CustomerPO.customer_id
        ).where(Customer.sales_pic_id == sales_pic_id)
    rows = (await db.scalars(stmt)).all()
    return [await _enrich(db, r) for r in rows]


async def _export_sections(
    db: AsyncSession, user: User,
    status_eq: str | None, sales_pic_id: UUID | None,
) -> list[dict]:
    stmt = select(CustomerPO).order_by(CustomerPO.created_at.desc())
    if status_eq:
        stmt = stmt.where(CustomerPO.status == status_eq)
    if Role(user.role) == Role.SALES:
        stmt = stmt.join(
            Customer, Customer.id == CustomerPO.customer_id
        ).where(Customer.sales_pic_id == user.id)
    elif sales_pic_id:
        stmt = stmt.join(
            Customer, Customer.id == CustomerPO.customer_id
        ).where(Customer.sales_pic_id == sales_pic_id)
    rows = (await db.scalars(stmt)).all()
    from app.services.tabular_export import _fmt_cell  # noqa: F401
    body = []
    for po in rows:
        e = await _enrich(db, po)
        body.append([
            e["number"], e.get("customer_name") or "—",
            e.get("sales_pic_name") or "—",
            e.get("quotation_number") or "—",
            e.get("project_code") or "—",
            e.get("po_date") or "—",
            e["status"],
            f"Rp {int(round(e['total'] or 0)):,}".replace(",", "."),
        ])
    return [{
        "name": "Customer POs",
        "headers": ["PO number", "Customer", "Sales rep", "Quotation",
                    "Project", "PO date", "Status", "Total"],
        "rows": body,
    }]


@router.get("/export.pdf")
async def export_customer_pos_pdf(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
    status_eq: str | None = None,
    sales_pic_id: UUID | None = None,
):
    from fastapi.responses import Response
    from app.services.tabular_export import render_pdf
    data = render_pdf("Customer POs", await _export_sections(db, user, status_eq, sales_pic_id))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="customer-pos.pdf"'})


@router.get("/export.xlsx")
async def export_customer_pos_xlsx(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
    status_eq: str | None = None,
    sales_pic_id: UUID | None = None,
):
    from fastapi.responses import Response
    from app.services.tabular_export import render_xlsx
    data = render_xlsx("Customer POs", await _export_sections(db, user, status_eq, sales_pic_id))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customer-pos.xlsx"'},
    )


@router.get("/{po_id}", response_model=CustomerPOOut)
async def get_customer_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if Role(user.role) == Role.SALES:
        cust = await db.get(Customer, po.customer_id)
        if not cust or cust.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    out = await _enrich(db, po)
    # Surface any DP invoices issued against this PO so the detail page can
    # show them before the project exists (detail-only — lists skip this).
    if po.is_downpayment:
        from app.models.finance import Invoice
        out["dp_invoices"] = [
            {
                "id": str(i.id), "number": i.number, "status": i.status,
                "total": float(i.total or 0), "issue_date": i.issue_date,
                "due_date": i.due_date,
                "faktur_pajak_no": i.faktur_pajak_no,
            }
            for i in (await db.scalars(
                select(Invoice)
                .where(Invoice.customer_po_id == po.id)
                .order_by(Invoice.created_at.asc())
            )).all()
        ]
    return out


@router.post("", response_model=CustomerPOOut, status_code=201)
async def create_customer_po(
    payload: CustomerPOCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """File a customer PO. Director-only is the goal here long-term, but
    sales / manager / purchasing / admin can submit because they're the
    ones who handle incoming customer paperwork. Either way the PO must
    be approved by the director before it spawns a project."""
    customer = await db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown customer")
    # Sales is scoped to their own customers.
    if Role(user.role) == Role.SALES and customer.sales_pic_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sales can only file POs for their own customers",
        )
    quotation = await db.get(Quotation, payload.quotation_id)
    if not quotation or quotation.customer_id != payload.customer_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Quotation does not belong to this customer",
        )
    # The PO comes BEFORE the win, not after it. "Won" means the customer
    # actually ordered, and their PO is the evidence of that — requiring the
    # win first meant a rep ticked Won on their own say-so and the paperwork
    # caught up later, or didn't. So a PO may be filed against any quotation
    # the customer has actually been given: approved, sent, or already won
    # (a second PO against a won quote is normal — staged orders).
    _PO_READY = ("approved", "sent", "won")
    if quotation.status not in _PO_READY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Quotation status is '{quotation.status}' — a customer PO can "
            "only be filed against a quotation the customer has been given "
            "(approved or sent).",
        )
    if not payload.number.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PO number required")

    # Uniqueness scoped to the customer — two different customers using
    # the same PO number "001" is fine, but the same customer can't have
    # two POs sharing a number.
    clash = await db.scalar(
        select(CustomerPO).where(
            CustomerPO.customer_id == payload.customer_id,
            CustomerPO.number == payload.number.strip(),
        )
    )
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Customer PO '{payload.number}' already exists for this customer",
        )

    items = [it.model_dump() for it in payload.items]
    total = _items_total(items)
    is_director = Role(user.role) == Role.DIRECTOR
    is_dp = bool(payload.is_downpayment)

    # DP POs route through finance approve → payment confirm → project.
    # Non-DP POs
    # keep the historical director-approves-then-project path.
    if is_dp:
        initial_status = "pending_finance"
    elif is_director:
        initial_status = "approved"
    else:
        initial_status = "pending_approval"

    po = CustomerPO(
        number=payload.number.strip(),
        po_date=payload.po_date,
        customer_id=payload.customer_id,
        quotation_id=payload.quotation_id,
        items=items,
        total=total,
        notes=payload.notes,
        is_downpayment=is_dp,
        status=initial_status,
        created_by=user.id, updated_by=user.id,
    )
    db.add(po)
    await db.flush()

    if is_dp:
        # DP POs go to finance for approval; the director also always
        # sees the filing as an approval-request notification so they
        # know a customer PO has landed regardless of type.
        await request_approval(
            db,
            target_type="customer_po",
            target_id=po.id,
            requested_by=user.id,
            required_role=Role.FINANCE,
            reason=(
                f"Down-payment PO {po.number} from {customer.company_name} "
                "— finance approval required before DP invoicing."
            ),
            payload={"action": "dp_finance_approve"},
        )
    elif is_director:
        # Director direct submission applies immediately.
        po.decided_by = user.id
        from datetime import UTC, datetime as _dt
        po.decided_at = _dt.now(UTC)
        # Attaches if the deal has already been Won; otherwise the PO is
        # simply on file and the job waits for the win.
        await _spawn_project(db, po, user)
        await db.flush()
    else:
        await request_approval(
            db,
            target_type="customer_po",
            target_id=po.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Customer PO {po.number} from {customer.company_name}",
            payload={"action": "create"},
        )

    return await _enrich(db, po)


@router.patch("/{po_id}", response_model=CustomerPOOut)
async def update_customer_po(
    po_id: UUID,
    payload: CustomerPOPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """Edit a customer PO that's still pending approval. Once it's
    approved (and a project spawned) the PO is frozen — edit the project
    instead."""
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if Role(user.role) == Role.SALES:
        cust = await db.get(Customer, po.customer_id)
        if not cust or cust.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    # A rejected PO has to be editable, or "send it back with a reason" is a
    # dead end: the reason says what to fix and nothing can be fixed.
    if po.status not in ("pending_approval", "rejected") and Role(user.role) != Role.DIRECTOR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Customer PO is no longer pending — edit the project it spawned instead.",
        )

    data = payload.model_dump(exclude_unset=True)
    if "number" in data:
        new_num = (data["number"] or "").strip()
        if not new_num:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "PO number required")
        if new_num != po.number:
            clash = await db.scalar(
                select(CustomerPO).where(
                    CustomerPO.customer_id == po.customer_id,
                    CustomerPO.number == new_num,
                    CustomerPO.id != po_id,
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Customer PO '{new_num}' already exists for this customer",
                )
            po.number = new_num
    if "po_date" in data:
        po.po_date = data["po_date"]
    if "items" in data and data["items"] is not None:
        po.items = data["items"]
        po.total = _items_total(po.items)
    if "notes" in data:
        po.notes = data["notes"]
    po.updated_by = user.id
    await db.flush()
    return await _enrich(db, po)


from pydantic import BaseModel as _BaseModel


class _DecisionIn(_BaseModel):
    notes: str | None = None


async def _decide_customer_po(
    po_id: UUID, approve: bool, notes: str | None,
    db: AsyncSession, user: User,
):
    """Approve or reject a pending customer PO right from its detail page.

    Mirrors the quotation page's Approve/Reject buttons. Finds the
    matching pending ApprovalRequest, runs decide() + apply_to_target()
    (which spawns the project on approval), and returns the enriched PO.
    """
    from app.core.approval import apply_to_target, decide
    from app.core.audit import record as audit_record
    # A regular customer PO is filed with required_role=DIRECTOR, so decide()
    # rejects a manager anyway — admitting them here only produced a second,
    # contradictory 403. Finance stays for the DP path it owns.
    if Role(user.role) not in (Role.DIRECTOR, Role.FINANCE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the director can approve / reject a customer PO.",
        )
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if po.status != "pending_approval":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Customer PO is already '{po.status}'.",
        )
    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "customer_po",
            ApprovalRequest.target_id == po_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if not req:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No pending approval request for this PO.",
        )
    try:
        await decide(
            db, request_id=req.id, decider_id=user.id,
            decider_role=Role(user.role), approve=approve, notes=notes,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    await apply_to_target(db, req, approve=approve)
    await audit_record(
        db, actor=user,
        action="approve_request" if approve else "reject_request",
        entity="customer_po", entity_id=po.id,
        after={"approval_request_id": str(req.id), "notes": notes},
    )
    await db.flush()
    return await _enrich(db, po)


@router.post("/{po_id}/approve", response_model=CustomerPOOut)
async def approve_customer_po(
    po_id: UUID,
    payload: _DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _decide_customer_po(po_id, True, payload.notes, db, user)


@router.post("/{po_id}/reject", response_model=CustomerPOOut)
async def reject_customer_po(
    po_id: UUID,
    payload: _DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not (payload.notes or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Please give a reason for rejecting — the requester will see it.",
        )
    return await _decide_customer_po(po_id, False, payload.notes, db, user)


# ─── Down-payment (DP) sub-flow ──────────────────────────────────────────────
#
# The DP path is: sales files DP PO → finance approves it → finance issues
# the DP invoice AGAINST THE PO (no project exists yet) → customer pays →
# sales confirms the deposit landed → project spawns and the DP invoice is
# re-linked to it. Rejection at either pending stage goes through
# dp/finance-reject. Every DP action also closes the ApprovalRequest that
# was filed at submission so no stale live-fire request lingers in the
# director's queue.


async def _close_dp_approval_request(
    db: AsyncSession, po_id: UUID, *, approve: bool, decider_id, notes: str | None,
) -> None:
    """Mark the DP PO's pending ApprovalRequest decided so the generic
    /approvals queue can't re-fire on a PO the DP endpoints already
    handled (double-approve used to spawn duplicate projects)."""
    from datetime import UTC
    from datetime import datetime as _dt

    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "customer_po",
            ApprovalRequest.target_id == po_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if req:
        req.status = (
            ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        ).value
        req.decided_by = decider_id
        req.decided_at = _dt.now(UTC)
        req.decision_notes = notes


@router.post("/{po_id}/dp/finance-approve", response_model=CustomerPOOut)
async def dp_finance_approve(
    po_id: UUID,
    payload: _DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance approves a DP PO. Moves it to `pending_payment_confirm`,
    at which point finance issues the DP invoice and — once the money
    is actually in the bank — confirms receipt, which is what spawns
    the project."""
    from datetime import UTC
    from datetime import datetime as _dt

    if Role(user.role) not in (Role.FINANCE, Role.DIRECTOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only finance (or director) can approve a DP PO.",
        )
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if not po.is_downpayment:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This isn't a down-payment PO — use the standard approve flow.",
        )
    if po.status != "pending_finance":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"DP PO is at status '{po.status}', not pending_finance.",
        )
    po.dp_finance_approved_by = user.id
    po.dp_finance_approved_at = _dt.now(UTC)
    if payload.notes:
        po.decision_notes = payload.notes
    po.status = "pending_payment_confirm"
    await _close_dp_approval_request(
        db, po_id, approve=True, decider_id=user.id, notes=payload.notes,
    )
    await db.flush()
    return await _enrich(db, po)


@router.post("/{po_id}/dp/finance-reject", response_model=CustomerPOOut)
async def dp_finance_reject(
    po_id: UUID,
    payload: _DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance (or director) rejects a DP PO — at either DP stage.

    pending_finance: the PO itself is wrong (bad number, wrong items).
    pending_payment_confirm: the deposit never arrived, deal fell through.
    A reason is required; it lands in decision_notes so sales sees why.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    if Role(user.role) not in (Role.FINANCE, Role.DIRECTOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only finance (or director) can reject a DP PO.",
        )
    if not (payload.notes or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Please give a reason for rejecting — the requester will see it.",
        )
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if not po.is_downpayment:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This isn't a down-payment PO — use the standard reject flow.",
        )
    if po.status not in ("pending_finance", "pending_payment_confirm"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"DP PO is already '{po.status}' — nothing to reject.",
        )
    po.status = "rejected"
    po.decided_by = user.id
    po.decided_at = _dt.now(UTC)
    po.decision_notes = payload.notes
    await _close_dp_approval_request(
        db, po_id, approve=False, decider_id=user.id, notes=payload.notes,
    )
    await db.flush()
    return await _enrich(db, po)


@router.post("/{po_id}/resubmit", response_model=CustomerPOOut)
async def resubmit_customer_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """Send a rejected customer PO back for a decision.

    Rejecting one already demands a reason, and that reason is shown on the
    PO — but until now there was nothing to do about it. The PO sat rejected
    with no way forward except filing a second one under a new number, which
    left two records of the same order.

    The reason the director gave is kept, not cleared: they are about to look
    at this again and what they asked for last time is the most useful thing
    on the page.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    from app.core.audit import record as audit_record

    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    customer = await db.get(Customer, po.customer_id)
    if Role(user.role) == Role.SALES:
        if not customer or customer.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    if po.status != "rejected":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only a rejected PO can be resubmitted — this one is '{po.status}'.")

    is_director = Role(user.role) == Role.DIRECTOR
    if po.is_downpayment:
        po.status = "pending_finance"
        await request_approval(
            db, target_type="customer_po", target_id=po.id,
            requested_by=user.id, required_role=Role.FINANCE,
            reason=(f"Down-payment PO {po.number} from "
                    f"{customer.company_name if customer else 'a customer'} "
                    "— resubmitted after being sent back."),
            payload={"action": "dp_finance_approve"},
        )
    elif is_director:
        # The director resubmitting their own is the decision.
        po.status = "approved"
        po.decided_by = user.id
        po.decided_at = _dt.now(UTC)
        await _spawn_project(db, po, user)
    else:
        po.status = "pending_approval"
        await request_approval(
            db, target_type="customer_po", target_id=po.id,
            requested_by=user.id, required_role=Role.DIRECTOR,
            reason=(f"Customer PO {po.number} from "
                    f"{customer.company_name if customer else 'a customer'} "
                    "— resubmitted after being sent back."),
            payload={"action": "create"},
        )
    po.updated_by = user.id
    await audit_record(db, actor=user, action="resubmit", entity="customer_po",
                       entity_id=po.id, after={"status": po.status})
    await db.flush()
    return await _enrich(db, po)


@router.post("/{po_id}/dp-invoice", status_code=201)
async def issue_dp_invoice(
    po_id: UUID,
    amount: float | None = Form(None),
    tax_amount: float | None = Form(None),
    due_date: str | None = Form(None),
    invoice_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance issues the DP invoice AGAINST THE CUSTOMER PO — before the
    project exists. This resolves the chicken-and-egg in the DP flow: the
    customer pays the deposit against this invoice, and only then does
    sales confirm receipt (which spawns the project and re-links this
    invoice to it via customer_po_id).

    The invoice parks at `pending_finance` like every other invoice, so
    the faktur pajak number is still entered at the finance-approve step.
    """
    from datetime import date as _date

    from app.models.finance import Invoice

    if Role(user.role) not in (Role.FINANCE, Role.DIRECTOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only finance (or director) can issue a DP invoice.",
        )
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if not po.is_downpayment:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This PO isn't a down payment — issue the invoice from the project page.",
        )
    if po.status not in ("pending_finance", "pending_payment_confirm"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"DP PO is at status '{po.status}' — the DP invoice is issued "
            "while the deposit is being collected. Once the project exists, "
            "use the project page.",
        )

    parsed_due = None
    if due_date:
        try:
            parsed_due = _date.fromisoformat(due_date)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "due_date must be YYYY-MM-DD",
            ) from e

    from app.api.v1.endpoints.operation import _next_doc_number, _save_attachment

    inv_amount = amount if amount is not None else float(po.total or 0)
    inv_tax = tax_amount or 0.0
    inv = Invoice(
        number=await _next_doc_number(db, Invoice, "INV"),
        project_id=None,
        customer_po_id=po.id,
        customer_id=po.customer_id,
        type="dp",
        issue_date=_date.today(),
        due_date=parsed_due,
        amount=inv_amount,
        tax_amount=inv_tax,
        total=inv_amount + inv_tax,
        status="pending_finance",
        faktur_pajak_no=None,
        faktur_pajak_status="none",
        issued_by=user.id,
    )
    db.add(inv)
    await db.flush()
    if invoice_file is not None:
        await _save_attachment(
            db, file=invoice_file, owner_type="invoice",
            owner_id=inv.id, user=user, label="dp_invoice",
        )
    return {
        "id": str(inv.id), "number": inv.number, "status": inv.status,
        "type": inv.type, "total": float(inv.total or 0),
        "customer_po_id": str(po.id),
    }


@router.post("/{po_id}/dp/payment-confirm", response_model=CustomerPOOut)
# The name this step had when sales owned it. Kept so a browser tab left
# open on the old page finishes its job instead of 404-ing halfway through
# a deposit — it runs the same handler, under the same finance-only gate.
@router.post("/{po_id}/dp/sales-confirm", response_model=CustomerPOOut,
             include_in_schema=False)
async def dp_payment_confirm(
    po_id: UUID,
    payload: _DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance confirms the deposit has landed. This is the trigger that
    spawns the project on a DP PO. Any DP invoices issued against the PO
    are re-linked to the new project.

    Finance's, not sales'. Whether money arrived is a fact about the bank
    account, and finance is who can see it — whereas sales is the person
    with the most reason to want the job started. Both DP steps therefore
    sit with the same desk that approved the PO and issued the invoice, and
    the answer to "did it arrive" has one owner rather than two.

    The *no* is the sibling of this endpoint, not a missing feature:
    /dp/finance-reject at this status records that the deposit never came.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    if Role(user.role) not in (Role.FINANCE, Role.DIRECTOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only finance (or director) can confirm a deposit has been "
            "received.",
        )
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if not po.is_downpayment:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This isn't a down-payment PO — there is no deposit to confirm.",
        )
    if po.status != "pending_payment_confirm":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"DP PO is at status '{po.status}', not awaiting payment "
            "confirmation.",
        )
    po.dp_payment_confirmed_by = user.id
    po.dp_payment_confirmed_at = _dt.now(UTC)
    po.status = "approved"
    po.decided_by = user.id
    po.decided_at = _dt.now(UTC)
    if payload.notes:
        po.decision_notes = payload.notes
    # A deposit order does not start at Won — that is what a deposit is for.
    # Confirming the money landed is its starting gun, so this is the one
    # place a customer PO may mint the job.
    project = await _spawn_project(db, po, user, create_if_missing=True)
    # Re-link DP invoices issued against this PO to the new project so
    # they show up on the project page and its payment tracking.
    from app.models.finance import Invoice
    for inv in (await db.scalars(
        select(Invoice).where(
            Invoice.customer_po_id == po.id,
            Invoice.project_id.is_(None),
        )
    )).all():
        inv.project_id = project.id
    # Defensive: the request should already be closed by finance-approve,
    # but clean up any pending one so the director's queue can't re-fire.
    await _close_dp_approval_request(
        db, po_id, approve=True, decider_id=user.id, notes=payload.notes,
    )
    await db.flush()
    return await _enrich(db, po)


async def _spawn_project(
    db: AsyncSession, po: CustomerPO, user: User,
    *, create_if_missing: bool = False,
) -> Project | None:
    """Link this customer PO to its project. Does **not** normally make one.

    Filing or approving a PO is not what starts a job — marking the
    quotation Won is. The PO comes first and is the evidence Won needs; the
    director's signature on it says the paperwork is right, not that the
    work has begun. So this attaches to the project Won already made, and
    returns None when the deal has not been Won yet: the PO is approved and
    simply waits, which is the whole point of the order.

    `create_if_missing` is for the one caller that *is* the starting gun:
    sales confirming a down-payment landed. A deposit order deliberately
    does not start at Won — not beginning work before the money arrives is
    what a deposit is for — so that step mints the job instead.
    """
    from app.ai.orchestrator import emit
    from app.services.project_factory import create_project, project_for_quotation

    project = await project_for_quotation(db, po.quotation_id)
    if project is not None:
        # Made at Won, before this PO was signed off. Give it the paperwork
        # it could not have had then, without overwriting anything set since.
        if not project.po_number:
            project.po_number = po.number
        if project.po_date is None:
            project.po_date = po.po_date
        if project.po_value is None:
            project.po_value = po.total
        po.project_id = project.id
        await db.flush()
    elif create_if_missing:
        # Carry the approved price request through (via the linked quotation)
        # so purchasing knows exactly what order it's sourcing.
        price_request_id = None
        if po.quotation_id:
            quote = await db.get(Quotation, po.quotation_id)
            price_request_id = quote.price_request_id if quote else None
        project = await create_project(
            db, user=user, customer_id=po.customer_id,
            quotation_id=po.quotation_id, price_request_id=price_request_id,
            po=po,
        )
        po.project_id = project.id
    # Fused pipeline: an approved customer PO advances the deal to 'po' —
    # the PO approval is the sign-off, no separate stage-move request. This
    # happens whether or not there is a project yet: the stage is about the
    # deal, and the deal has its order.
    from app.core.stage_playbook import bump_customer_stage
    from app.core.stage_tasks import ensure_stage_tasks
    cust = await db.get(Customer, po.customer_id) if po.customer_id else None
    if cust and bump_customer_stage(cust, "po"):
        await ensure_stage_tasks(db, cust, "po")
    # The receiving work order is no longer created here — purchasing spawns
    # it by confirming the delivery date (see operation.confirm_delivery),
    # which matches the post-drawing logistics flow.
    await emit(db, "customer_po.approved", {
        "customer_po_id": str(po.id),
        "project_id": str(project.id) if project else None,
    })
    return project


# ─── Order confirmation sheet ────────────────────────────────────────────────
# Where it ships and who owns the order are decided per shipment, not stored on
# the PO: the same customer takes goods at a site and paperwork at head office,
# and which of their people is responsible changes order to order. So both are
# picked at download time and printed onto the sheet.

@router.get("/{po_id}/pdf-options")
async def customer_po_pdf_options(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """The addresses and contacts this PO could be printed against."""
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if Role(user.role) == Role.SALES:
        c = await db.get(Customer, po.customer_id)
        if not c or c.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")

    from app.services.print_address import address_options, contact_options

    cust = await db.get(Customer, po.customer_id)
    contacts = (await db.scalars(
        select(CustomerContact).where(CustomerContact.customer_id == po.customer_id)
        .order_by(CustomerContact.is_primary.desc(), CustomerContact.name)
    )).all()
    # `ship_to` is kept as the field name here because that is what the PO
    # sheet calls the block it prints; the list itself now comes from the same
    # place the quotation's does, so the two cannot drift apart.
    return {
        "customer_name": cust.company_name if cust else "—",
        "ship_to": address_options(cust),
        "addresses": address_options(cust),
        "pics": contact_options(cust, contacts),
        "default_address": "delivery",
        "keterangan": po.notes or "",
    }


@router.get("/{po_id}/export.pdf")
async def export_customer_po_pdf(
    po_id: UUID,
    ship_to: str = "delivery",
    contact_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    cust = await db.get(Customer, po.customer_id)
    if Role(user.role) == Role.SALES and (not cust or cust.sales_pic_id != user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    from app.services.print_address import VALID_KEYS, resolve_address
    if ship_to not in VALID_KEYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"ship_to must be one of {', '.join(sorted(VALID_KEYS))}")
    # Falls back to the office address rather than printing a blank block —
    # a sheet with no destination on it is worse than the wrong heading.
    resolved = resolve_address(cust, ship_to)
    label, address = resolved.label, resolved.address

    if contact_id:
        ct = await db.get(CustomerContact, contact_id)
        if not ct or ct.customer_id != po.customer_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "That contact doesn't belong to this customer")
        pic = (ct.name, ct.position or "", ct.phone or "", ct.email or "")
    else:
        pic = ((cust.pic_name if cust else "") or "",
               (cust.pic_position if cust else "") or "",
               (cust.phone if cust else "") or "",
               (cust.email if cust else "") or "")

    quote_no = None
    if po.quotation_id:
        from app.models.quotation import Quotation
        q = await db.get(Quotation, po.quotation_id)
        quote_no = q.number if q else None

    sales_name = ""
    rep = None
    if cust and cust.sales_pic_id:
        rep = await db.get(User, cust.sales_pic_id)
        sales_name = rep.full_name if rep else ""
    # Whoever's name is printed is whose signature goes on it — falling back
    # to the person generating the document, exactly as the name does.
    from app.services.signature import load_for as _load_signature
    signer = rep if sales_name else user

    from app.services.customer_po_pdf import build_customer_po_pdf
    pdf = build_customer_po_pdf(
        number=po.number,
        po_date=po.po_date.strftime("%d %B %Y") if po.po_date else "—",
        customer_name=cust.company_name if cust else "—",
        ship_to_label=label, ship_to_address=address,
        pic_name=pic[0], pic_position=pic[1], pic_phone=pic[2], pic_email=pic[3],
        quotation_number=quote_no,
        rows=list(po.items or []),
        total=float(po.total or 0),
        keterangan=po.notes,
        sales_pic=sales_name or (user.full_name or ""),
        signer_signature=await _load_signature(signer),
    )
    from fastapi.responses import Response
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="KonfirmasiPesanan-{po.number}.pdf"'},
    )
