from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import apply_to_target, decide
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require, require_min
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.attachment import Attachment
from app.models.crm import Customer
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


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
               Project.is_deleted.is_(False),
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
               Project.is_deleted.is_(False),
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
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR, Role.FINANCE)),
):
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.status == ApprovalStatus.PENDING.value
    )
    if Role(user.role) == Role.MANAGER:
        # manager sees manager-level approvals; director sees all
        stmt = stmt.where(ApprovalRequest.required_role == Role.MANAGER.value)
    elif Role(user.role) == Role.FINANCE:
        # DP customer-PO approvals are addressed to finance (decide() already
        # enforces it) — without this they were filed to a queue finance
        # couldn't open.
        stmt = stmt.where(ApprovalRequest.required_role == Role.FINANCE.value)
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
            if not spo:
                return False
            # Two different requests share this target type and only one of
            # them is answered by the PO's status. A *create* is settled the
            # moment the order leaves pending_approval — that was the director
            # deciding it. An *edit* is filed against an order that is already
            # open, so the same test marked every edit stale the instant it was
            # filed and the director never saw one: purchasing was told
            # "submitted for approval" and nothing arrived. An edit only goes
            # stale when the order it edits is finished with.
            if (r.payload or {}).get("action") == "update":
                return spo.status in ("cancelled", "closed")
            return spo.status != "pending_approval"
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
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR, Role.FINANCE)),
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
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR, Role.FINANCE)),
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


# ─── What am I actually approving? ───────────────────────────────────────────
# The queue used to show a title and two buttons. For a PO or a purchase
# request that is not enough to decide on — you want the lines, the money, and
# the files the requester attached. This returns one normalised shape so the UI
# has a single renderer regardless of what is being approved.

async def _attachments_for(db: AsyncSession, owner_type: str, owner_id) -> list[dict]:
    from app.models.attachment import Attachment
    rows = (await db.scalars(
        select(Attachment).where(
            Attachment.owner_type == owner_type, Attachment.owner_id == owner_id,
        ).order_by(Attachment.created_at.desc())
    )).all()
    return [{"id": str(a.id), "filename": a.filename,
             "description": a.description, "external_url": a.external_url,
             "size": a.size, "content_type": a.content_type}
            for a in rows]


def _money(n) -> float:
    try:
        return float(n or 0)
    except Exception:
        return 0.0


def _rupiah(n) -> str:
    """Rp 8.900.000 — thousands separated the Indonesian way, as everywhere
    else in the app. A field formatted with commas beside a table formatted
    with dots reads as two different currencies."""
    return "Rp " + f"{round(_money(n)):,}".replace(",", ".")


@router.get("/{req_id}/preview")
async def preview_request(
    req_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR, Role.FINANCE)),
):
    """The document behind an approval request — fields, lines, money, files."""
    req = await db.get(ApprovalRequest, req_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")

    out: dict = {
        "target_type": req.target_type, "title": None, "subtitle": None,
        "fields": [], "items": [], "total": None, "notes": None,
        "attachments": await _attachments_for(db, "approval_request", req.id),
        "link": None,
    }
    t, tid = req.target_type, req.target_id
    # Who asked. On an edit request this is half the decision — the director is
    # approving somebody's proposed change, not a document that changed itself.
    _asker = await db.get(User, req.requested_by) if req.requested_by else None
    requester_name = (_asker.full_name if _asker else None) or "—"

    if t in ("quotation", "quotation_won", "discount"):
        from app.models.quotation import Quotation, QuotationItem
        q = await db.get(Quotation, tid)
        if q:
            cust = await db.get(Customer, q.customer_id) if q.customer_id else None
            rows = (await db.scalars(select(QuotationItem)
                    .where(QuotationItem.quotation_id == q.id))).all()
            out.update(
                title=q.number, subtitle=cust.company_name if cust else None,
                link=f"/quotations/{q.id}", notes=q.notes,
                total=_money(q.total) if hasattr(q, "total") else None,
                items=[{"description": i.description, "qty": _money(i.qty),
                        "unit_price": _money(i.unit_price),
                        "line_total": _money(i.qty) * _money(i.unit_price)} for i in rows],
                fields=[{"label": "Status", "value": q.status},
                        {"label": "Valid until", "value": str(q.valid_until or "—")}],
            )
            out["attachments"] += await _attachments_for(db, "quotation", q.id)

    elif t == "customer_po":
        from app.models.customer_po import CustomerPO
        po = await db.get(CustomerPO, tid)
        if po:
            cust = await db.get(Customer, po.customer_id) if po.customer_id else None
            out.update(
                title=po.number, subtitle=cust.company_name if cust else None,
                link=f"/customer-pos/{po.id}", notes=po.notes,
                total=_money(po.total),
                items=[{"description": i.get("description"), "qty": _money(i.get("qty")),
                        "unit_price": _money(i.get("unit_price")),
                        "line_total": _money(i.get("qty")) * _money(i.get("unit_price"))}
                       for i in (po.items or [])],
                fields=[{"label": "PO date", "value": str(po.po_date or "—")},
                        {"label": "Down payment",
                         "value": "yes" if po.is_downpayment else "no"}],
            )
            out["attachments"] += await _attachments_for(db, "customer_po", po.id)

    elif t == "purchase_request":
        from app.models.purchasing import PurchaseRequest
        pr = await db.get(PurchaseRequest, tid)
        if pr:
            out.update(
                title=pr.number, subtitle=None, notes=pr.notes,
                link="/purchasing",
                items=[{"description": i.get("description"), "qty": _money(i.get("qty")),
                        "unit_price": None, "line_total": None}
                       for i in (pr.items or [])],
                fields=[{"label": "Status", "value": pr.status}],
            )

    elif t == "supplier_po":
        from app.models.purchasing import SupplierPO, Supplier
        sp = await db.get(SupplierPO, tid)
        if sp:
            sup = await db.get(Supplier, sp.supplier_id) if sp.supplier_id else None
            action = (req.payload or {}).get("action")
            changes = (req.payload or {}).get("changes") or {}
            cur = sp.currency or "IDR"
            # An *edit* request is the interesting case, and it used to render
            # as the PO exactly as it already is — the director was approving a
            # change they could not see. What is being changed lives in the
            # approval's payload, not on the row, so show that: each field with
            # the value it would replace beside it.
            is_update = action == "update" and changes
            fields = [{"label": "Status", "value": sp.status}]
            items = [{"description": i.get("description"), "qty": _money(i.get("qty")),
                      "unit_price": _money(i.get("unit_price")),
                      "line_total": _money(i.get("qty")) * _money(i.get("unit_price"))}
                     for i in (getattr(sp, "items", None) or [])]
            if is_update:
                labels = {
                    "number": "PO number", "po_date": "PO date",
                    "eta": "Expected arrival", "quoted_lead_days": "Lead time (days)",
                    "currency": "Currency", "total": "Total", "status": "Status",
                }

                def _show(key, val):
                    if val in (None, ""):
                        return "—"
                    if key == "total":
                        return _rupiah(val) if cur == "IDR" else f"{cur} {_money(val):,.2f}"
                    return str(val)

                fields = [{"label": "Change requested by", "value": requester_name}]
                for k, v in changes.items():
                    if k == "items":
                        continue                       # shown as the line table
                    fields.append({
                        "label": labels.get(k, k.replace("_", " ").capitalize()),
                        "value": f"{_show(k, getattr(sp, k, None))}  →  {_show(k, v)}",
                    })
                if "items" in changes:
                    was = {(i.get("description") or ""): i
                           for i in (getattr(sp, "items", None) or [])}
                    items = [{"description": i.get("description"),
                              "qty": _money(i.get("qty")),
                              "was_qty": (_money(was[i.get("description")].get("qty"))
                                          if i.get("description") in was else None),
                              "is_new": i.get("description") not in was,
                              "unit_price": _money(i.get("unit_price")),
                              "was_unit_price": (
                                  _money(was[i.get("description")].get("unit_price"))
                                  if i.get("description") in was else None),
                              "line_total": _money(i.get("qty")) * _money(i.get("unit_price"))}
                             for i in (changes.get("items") or [])]
                    fields.append({"label": "Lines",
                                   "value": f"{len(items)} proposed, replacing {len(was)}"})
            out.update(
                title=(f"{sp.number} — proposed changes" if is_update else sp.number),
                subtitle=sup.name if sup else None,
                # The specific order, not the list. A director deciding one of
                # eight queued edits should not have to go and find it.
                link=f"/purchase-orders/{sp.id}",
                total=_money(changes.get("total", getattr(sp, "total", 0))),
                items=items,
                fields=fields,
            )
            out["attachments"] += await _attachments_for(db, "supplier_po", sp.id)

    elif t == "price_request_revision":
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, tid)
        n = (req.payload or {}).get("revision_n")
        if pr:
            cust = await db.get(Customer, pr.customer_id) if pr.customer_id else None
            rev = next((r for r in (pr.revisions or []) if r.get("n") == n), None)
            proposed = (rev or {}).get("proposed_items") or []
            before = {(i.get("description") or ""): i for i in ((rev or {}).get("before_items") or [])}
            kind = (rev or {}).get("kind", "scope")
            # On a purchasing revision the cost is the whole decision, so it is
            # shown as the unit price with the old one beside it. A scope
            # revision leaves that column empty as before — the question there
            # is what is being bought, not what it costs.
            is_cost = kind == "cost"
            scope_used = len([r for r in (pr.revisions or [])
                              if r.get("status") == "approved"
                              and r.get("kind", "scope") != "cost"])
            fields = [{"label": "Requested by",
                       "value": (rev or {}).get("requested_by_name") or "—"}]
            if is_cost:
                was_total = sum(_money(i.get("qty")) * _money(i.get("cost_price"))
                                for i in ((rev or {}).get("before_items") or []))
                now_total = sum(_money(i.get("qty")) * _money(i.get("cost_price"))
                                for i in proposed)
                fields += [
                    {"label": "Change", "value": "Cost correction by purchasing"},
                    # Dots, not commas: the whole app prints rupiah id-ID, and
                    # two conventions in one card reads as two currencies.
                    {"label": "Total cost was", "value": _rupiah(was_total)},
                    {"label": "Total cost becomes", "value": _rupiah(now_total)},
                ]
            else:
                fields.append({"label": "Revisions used",
                               "value": f"{scope_used} of 3"})
            out.update(
                title=(f"{pr.number} — cost revision {n}" if is_cost
                       else f"{pr.number} — revision {n}"),
                subtitle=cust.company_name if cust else None,
                link=f"/price-requests?open={pr.id}",
                notes=(rev or {}).get("reason"),
                # Show the proposal, with the old quantity beside anything that
                # moved — the decision is about the change, not the whole list.
                items=[{"description": i.get("description"), "qty": _money(i.get("qty")),
                        "was_qty": _money(before[i.get("description")].get("qty"))
                        if i.get("description") in before else None,
                        "is_new": i.get("description") not in before,
                        "unit_price": _money(i.get("cost_price")) if is_cost else None,
                        "was_unit_price": (
                            _money(before[i.get("description")].get("cost_price"))
                            if is_cost and i.get("description") in before else None),
                        "line_total": (_money(i.get("qty")) * _money(i.get("cost_price"))
                                       if is_cost else None)}
                       for i in proposed],
                fields=fields,
            )
            out["attachments"] += await _attachments_for(db, "price_request", pr.id)

    elif t == "cross_dept_chat":
        requester = await db.get(User, req.requested_by)
        other = await db.get(User, tid)
        out.update(
            title="Cross-department conversation",
            subtitle=(f"{requester.full_name if requester else '?'} → "
                      f"{other.full_name if other else '?'}"),
            notes=(req.payload or {}).get("reason"),
            fields=[{"label": "From", "value": (requester.role if requester else "—")},
                    {"label": "To", "value": (other.role if other else "—")}],
        )

    elif t == "project":
        from app.models.operation import Project
        p = await db.get(Project, tid)
        if p:
            cust = await db.get(Customer, p.customer_id) if p.customer_id else None
            out.update(title=p.code, subtitle=cust.company_name if cust else None,
                       link=f"/projects/{p.id}", total=_money(p.po_value),
                       fields=[{"label": "Status", "value": p.status}])
            out["attachments"] += await _attachments_for(db, "project", p.id)

    elif t in ("customer", "followup"):
        cust = await db.get(Customer, tid)
        if cust:
            out.update(title=cust.company_name, link=f"/customers/{cust.id}",
                       fields=[{"label": "Stage", "value": cust.stage}])

    if not out["title"]:
        # Never leave the panel blank — the raw request is better than nothing.
        out["title"] = req.reason or req.target_type
    return out
