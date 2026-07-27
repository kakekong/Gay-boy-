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


@router.get("/pending-documents")
async def pending_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    """Director-decision documents that DON'T flow through ApprovalRequest.

    Drawings, logistics/import docs, delivery-proof verification and
    pending-director price requests are all status-based queues decided on
    other pages — they never used to appear in the approvals inbox, so
    they silently piled up unless the director happened to open the right
    project. This aggregates them (read-only, with deep links to where the
    decision actually happens) so the inbox is the one place to check.
    """
    from app.models.operation import DeliveryOrder, Drawing, Project
    from app.models.price_request import PriceRequest

    items: list[dict] = []
    # Once a project is delivered/paid/closed, its documents are historical —
    # a still-"pending" drawing / shipping doc / unverified delivery proof is
    # stale and should drop out of the decision queue (this is why a delivery
    # proof kept showing after the project closed).
    DONE_PROJECT = ("delivered", "paid", "closed")

    # 1. Drawings awaiting sign-off (decided on the project page).
    drows = (await db.execute(
        select(Drawing, Project)
        .join(Project, Drawing.project_id == Project.id)
        .where(Drawing.status == "submitted",
               Project.status.not_in(DONE_PROJECT))
        .order_by(Drawing.created_at.asc())
        .limit(50)
    )).all()
    for d, p in drows:
        items.append({
            "kind": "drawing",
            "title": f"Drawing rev {d.revision} — {p.code}",
            "body": "Submitted, waiting for approval on the project page.",
            "link": f"/projects/{p.id}",
            "at": d.created_at,
        })

    # 2. Logistics / import documents at 'pending' (per-project JSONB).
    lrows = (await db.scalars(
        select(Project).where(
            Project.is_deleted.is_(False),
            Project.status.not_in(DONE_PROJECT),
        ).limit(500)
    )).all()
    for p in lrows:
        pending_keys = [
            k for k, v in (p.import_docs or {}).items()
            if isinstance(v, dict) and v.get("status") == "pending"
        ]
        if pending_keys:
            items.append({
                "kind": "import_doc",
                "title": f"{len(pending_keys)} shipping document(s) — {p.code}",
                "body": "Uploaded by purchasing, waiting for approval "
                        f"({', '.join(sorted(pending_keys))}).",
                "link": f"/projects/{p.id}",
                "at": p.updated_at or p.created_at,
            })

    # 3. Delivery proofs uploaded but not yet verified.
    dorows = (await db.execute(
        select(DeliveryOrder, Project)
        .join(Project, DeliveryOrder.project_id == Project.id)
        .where(DeliveryOrder.verified_at.is_(None),
               Project.status.not_in(DONE_PROJECT))
        .order_by(DeliveryOrder.created_at.asc())
        .limit(50)
    )).all()
    do_ids = [d.id for d, _ in dorows]
    proofed: set = set()
    if do_ids:
        arows = (await db.scalars(
            select(Attachment.owner_id).where(
                Attachment.owner_type == "delivery_order",
                Attachment.owner_id.in_(do_ids),
            )
        )).all()
        proofed = set(arows)
    for d, p in dorows:
        if d.id in proofed:
            items.append({
                "kind": "delivery_proof",
                "title": f"Delivery proof — {d.number} ({p.code})",
                "body": "Proof uploaded, waiting for verification on the project page.",
                "link": f"/projects/{p.id}",
                "at": d.created_at,
            })

    # 4. Price requests waiting on the director's sell price (director only).
    if Role(user.role) == Role.DIRECTOR:
        prows = (await db.scalars(
            select(PriceRequest).where(
                PriceRequest.is_deleted.is_(False),
                PriceRequest.status == "pending_director",
            ).order_by(PriceRequest.created_at.asc()).limit(50)
        )).all()
        for pr in prows:
            items.append({
                "kind": "price_request",
                "title": f"Price request {pr.number}",
                "body": "Costed by purchasing — set the sell price and approve.",
                "link": "/price-requests",
                "at": pr.priced_at or pr.created_at,
            })

    items.sort(key=lambda x: (x["at"] is None, x["at"]))
    return items


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

    # Supplier-PO approvals (create/update): resolve the PO number for the label.
    from app.models.purchasing import SupplierPO
    spo_ids = {r.target_id for r in rows if r.target_type == "supplier_po"}
    supplier_pos: dict[UUID, SupplierPO] = {}
    if spo_ids:
        sporows = (await db.scalars(
            select(SupplierPO).where(SupplierPO.id.in_(spo_ids))
        )).all()
        supplier_pos = {p.id: p for p in sporows}

    # ── Drop requests whose target already moved past needing a decision ──
    # A pending request can be orphaned when the same transition happens
    # outside the approval flow (e.g. the director marks a quote Won straight
    # from the quotation page, or a PO is decided on its own detail page).
    # Nothing is left to decide, so it should not clutter the queue. The
    # deciding endpoints close their own requests; this is the safety net that
    # also hides rows orphaned before that fix existed.
    from app.models.customer_po import CustomerPO
    all_quote_ids = {r.target_id for r in rows
                     if r.target_type in ("quotation", "discount",
                                          "quotation_edit", "quotation_won")}
    all_quotes: dict[UUID, Quotation] = {}
    if all_quote_ids:
        all_quotes = {q.id: q for q in (await db.scalars(
            select(Quotation).where(Quotation.id.in_(all_quote_ids)))).all()}
    cpo_ids = {r.target_id for r in rows if r.target_type == "customer_po"}
    cpos: dict[UUID, CustomerPO] = {}
    if cpo_ids:
        cpos = {p.id: p for p in (await db.scalars(
            select(CustomerPO).where(CustomerPO.id.in_(cpo_ids)))).all()}

    _QUOTE_CLOSED = ("won", "lost", "cancelled", "superseded")
    _CPO_OPEN = ("pending_approval", "pending_finance", "pending_sales_confirm")

    def _stale(r) -> bool:
        t = r.target_type
        if t == "quotation_won":
            q = all_quotes.get(r.target_id)
            return bool(q and q.status in _QUOTE_CLOSED)
        if t in ("quotation", "discount"):
            # Only a draft/pending quote still needs an approve/reject.
            q = all_quotes.get(r.target_id)
            return bool(q and q.status not in ("draft", "pending_approval"))
        if t == "quotation_edit":
            q = all_quotes.get(r.target_id)
            return bool(q and q.status in ("cancelled", "superseded"))
        if t == "customer_po":
            po = cpos.get(r.target_id)
            return bool(po and po.status not in _CPO_OPEN)
        if t == "supplier_po":
            spo = supplier_pos.get(r.target_id)
            return bool(spo and spo.status != "pending_approval")
        if t == "purchase_request":
            pr = prs.get(r.target_id)
            return bool(pr and pr.status != "pending_approval")
        if t == "project":
            p = projects.get(r.target_id)
            return bool(p and p.is_deleted)
        if t in ("customer", "followup"):
            cst = customers.get(r.target_id)
            return bool(cst and cst.is_deleted)
        return False

    rows = [r for r in rows if not _stale(r)]
    if not rows:
        return []

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
        elif r.target_type == "supplier_po":
            sp = supplier_pos.get(r.target_id)
            target_label = sp.number if sp else None
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
