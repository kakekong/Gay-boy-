from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import apply_to_target, decide
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.attachment import Attachment
from app.models.crm import Customer
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("")
async def inbox(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.status == ApprovalStatus.PENDING.value
    )
    if Role(user.role) == Role.MANAGER:
        # manager sees manager-level approvals; director sees all
        stmt = stmt.where(ApprovalRequest.required_role == Role.MANAGER.value)
    rows = (await db.scalars(stmt.order_by(ApprovalRequest.created_at.asc()))).all()
    if not rows:
        return []

    # Bulk-load target customers (stage moves + follow-up requests both point
    # at a customer) and quotations (mark-won requests point at a quotation).
    cust_ids = {r.target_id for r in rows if r.target_type in ("customer", "followup")}
    customers: dict[UUID, Customer] = {}
    if cust_ids:
        crows = (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all()
        customers = {c.id: c for c in crows}

    quote_ids = {r.target_id for r in rows if r.target_type == "quotation_won"}
    quotations: dict[UUID, Quotation] = {}
    if quote_ids:
        qrows = (await db.scalars(
            select(Quotation).where(Quotation.id.in_(quote_ids))
        )).all()
        quotations = {q.id: q for q in qrows}

    # Purchase-request approvals: resolve the PR number for the label.
    from app.models.purchasing import PurchaseRequest
    pr_ids = {r.target_id for r in rows if r.target_type == "purchase_request"}
    prs: dict[UUID, PurchaseRequest] = {}
    if pr_ids:
        prrows = (await db.scalars(
            select(PurchaseRequest).where(PurchaseRequest.id.in_(pr_ids))
        )).all()
        prs = {p.id: p for p in prrows}

    # Project (shipping) approvals: resolve the project code for the label.
    from app.models.operation import Project
    proj_ids = {r.target_id for r in rows if r.target_type == "project"}
    projects: dict[UUID, Project] = {}
    if proj_ids:
        projrows = (await db.scalars(
            select(Project).where(Project.id.in_(proj_ids))
        )).all()
        projects = {p.id: p for p in projrows}

    # Bulk-load requester names
    requester_ids = {r.requested_by for r in rows}
    requesters: dict[UUID, User] = {}
    if requester_ids:
        urows = (await db.scalars(
            select(User).where(User.id.in_(requester_ids))
        )).all()
        requesters = {u.id: u for u in urows}

    # Bulk-load supporting attachments tied to these requests
    att_map: dict[UUID, list[dict]] = {}
    arows = (await db.scalars(
        select(Attachment).where(
            Attachment.owner_type == "approval_request",
            Attachment.owner_id.in_([r.id for r in rows]),
        ).order_by(Attachment.created_at.asc())
    )).all()
    for a in arows:
        att_map.setdefault(a.owner_id, []).append({
            "id": str(a.id),
            "filename": a.filename,
            "size": a.size,
            "content_type": a.content_type,
            "uploaded_at": a.created_at,
        })

    out = []
    for r in rows:
        cust = customers.get(r.target_id) if r.target_type == "customer" else None
        requester = requesters.get(r.requested_by)
        payload = dict(r.payload or {})
        # Back-fill from_stage on legacy approvals (created via the old
        # PATCH /customers/:id path) so the director sees what's about to
        # change. Use the customer's CURRENT stage as the "from" since the
        # request didn't capture it.
        if (
            cust is not None
            and payload.get("changes", {}).get("stage")
            and not payload.get("from_stage")
        ):
            payload["from_stage"] = cust.stage
            payload["to_stage"] = payload["changes"]["stage"]
        if r.target_type == "quotation_won":
            qq = quotations.get(r.target_id)
            target_label = qq.number if qq else None
        elif r.target_type == "purchase_request":
            pp = prs.get(r.target_id)
            target_label = pp.number if pp else None
        elif r.target_type == "inventory_item":
            n = len((r.payload or {}).get("items") or [])
            target_label = f"{n} new item(s)"
        elif r.target_type == "project":
            pj = projects.get(r.target_id)
            target_label = pj.code if pj else None
        elif r.target_type in ("customer", "followup"):
            c = customers.get(r.target_id)
            target_label = c.company_name if c else None
        else:
            target_label = cust.company_name if cust else None
        out.append({
            "id": str(r.id),
            "target_type": r.target_type,
            "target_id": str(r.target_id),
            "target_label": target_label,
            "required_role": r.required_role,
            "reason": r.reason,
            "payload": payload,
            "requested_by": str(r.requested_by),
            "requester_name": requester.full_name if requester else None,
            "created_at": r.created_at,
            "attachments": att_map.get(r.id, []),
        })
    return out


@router.post("/{req_id}/approve")
async def approve(
    req_id: UUID,
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    try:
        req = await decide(
            db, request_id=req_id, decider_id=user.id,
            decider_role=Role(user.role), approve=True, notes=notes,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    applied = await apply_to_target(db, req, approve=True)
    await audit_record(
        db, actor=user, action="approve_request", entity=req.target_type,
        entity_id=req.target_id,
        after={"approval_request_id": str(req.id), "applied": applied},
    )
    return {"id": str(req.id), "status": req.status, "applied": applied}


@router.post("/{req_id}/reject")
async def reject(
    req_id: UUID,
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    try:
        req = await decide(
            db, request_id=req_id, decider_id=user.id,
            decider_role=Role(user.role), approve=False, notes=notes,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    applied = await apply_to_target(db, req, approve=False)
    await audit_record(
        db, actor=user, action="reject_request", entity=req.target_type,
        entity_id=req.target_id,
        after={"approval_request_id": str(req.id), "notes": notes, "applied": applied},
    )
    return {"id": str(req.id), "status": req.status, "applied": applied}
