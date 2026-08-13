"""Operation: projects, work orders, drawings, deliveries."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile, status,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.attachment import Attachment
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import (
    DeliveryOrder, Drawing, Project, WorkOrder, advance_project_status,
)
from app.models.purchasing import PurchaseRequest
from app.models.quotation import Quotation
from app.models.user import User
from app.services import storage

# Operations data (projects, work orders, deliveries) is internal-only.
# External portal users (customer/supplier) get their scoped views via the
# portal router, never the raw operation endpoints. require_min(SALES) admits
# every internal employee (sales tier and up) and blocks the tier-0 externals.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])


def _can_see_project_money(user: User) -> bool:
    """Whether this user may see a project's deal economics.

    Purchasing works the procurement side — items requested, suppliers,
    goods receipt, QC — and has no business reason to see PO value,
    margins, or invoice amounts. Everyone else (sales on their own
    customers, admin, finance, manager, director) may. We blank the
    numbers to None rather than dropping the keys so the API shape stays
    stable for the frontend.
    """
    return Role(user.role) != Role.PURCHASING


def _can_see_project_cost(user: User) -> bool:
    """Whether this user may see what the goods cost us.

    Purchasing obviously may — it is their number. **Admin may not.** They run
    the customer side of a job: drawings for the customer, logistics, delivery,
    invoicing. What we paid the vendor is not part of any of that, and it is
    the one figure that maps a customer to a supplier's price.

    The margin fields go with it rather than being gated separately, because a
    margin next to a PO value *is* the cost — subtract one from the other.
    """
    return Role(user.role) not in (Role.ADMIN,)


def _drawing_row(d, deciders: dict) -> dict:
    return {
        "id": str(d.id), "revision": d.revision, "file_url": d.file_url,
        "kind": d.kind, "status": d.status, "notes": d.notes,
        "source_drawing_id": str(d.source_drawing_id) if d.source_drawing_id else None,
        "customer_decision_at": d.customer_decision_at,
        "decided_at": d.decided_at,
        "decided_by": str(d.decided_by) if d.decided_by else None,
        "decided_by_name": deciders.get(d.decided_by) if d.decided_by else None,
        "uploaded_by": str(d.uploaded_by) if d.uploaded_by else None,
        "uploaded_by_name": deciders.get(d.uploaded_by) if d.uploaded_by else None,
        "created_at": d.created_at,
    }


def _can_see_project_customer(user: User) -> bool:
    """Whether this user may see the customer identity behind a project.

    Same customer-blindness rule as the PO screens — purchasing shouldn't
    map customer ↔ supplier. Blank the name (surface a neutral code
    fallback client-side) but keep the API shape.
    """
    return Role(user.role) != Role.PURCHASING


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    stmt = (
        select(Project)
        .where(Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
    )
    # Sales only sees projects belonging to their own customers
    if Role(user.role) == Role.SALES:
        stmt = stmt.join(Customer, Project.customer_id == Customer.id).where(
            Customer.sales_pic_id == user.id
        )
    rows = (await db.scalars(stmt)).all()
    # Batch-load customer records so the list can show the customer name and
    # the customer's sales rep in a single trip (the previous version had to
    # N+1 to render the sales-rep column and just skipped it).
    cust_ids = {p.customer_id for p in rows if p.customer_id}
    customers_by_id: dict = {}
    if cust_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all():
            customers_by_id[c.id] = c
    sales_ids = {
        c.sales_pic_id for c in customers_by_id.values() if c.sales_pic_id
    }
    sales_by_id: dict = {}
    if sales_ids:
        for u in (await db.scalars(
            select(User).where(User.id.in_(sales_ids))
        )).all():
            sales_by_id[u.id] = u.full_name
    show_money = _can_see_project_money(user)
    # A margin is the sell price minus the cost, so it needs both
    # permissions — showing it to someone barred from either half
    # hands them the half they were barred from.
    show_margin = show_money and _can_see_project_cost(user)
    show_customer = _can_see_project_customer(user)
    out = []
    for p in rows:
        cust = customers_by_id.get(p.customer_id)
        rep_id = cust.sales_pic_id if cust else None
        out.append({
            "id": str(p.id), "code": p.code,
            # Purchasing sees a neutral "Order {code}" placeholder — the
            # customer identity + the sales rep are both hidden so no
            # customer ↔ supplier map can be inferred.
            "customer_id": str(p.customer_id) if show_customer else None,
            "customer_name": (cust.company_name if cust else None)
                             if show_customer else f"Order {p.code}",
            "sales_pic_id": str(rep_id) if (rep_id and show_customer) else None,
            "sales_pic_name": sales_by_id.get(rep_id) if (rep_id and show_customer) else None,
            "status": p.status,
            "po_value": float(p.po_value) if show_money else None,
            "target_delivery": p.target_delivery, "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate) if show_margin else None,
            "margin_actual": float(p.margin_actual) if show_margin else None,
        })
    return out


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    customer = await db.get(Customer, p.customer_id) if p.customer_id else None
    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None
    if Role(user.role) == Role.SALES and (
        not customer or customer.sales_pic_id != user.id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    show_money = _can_see_project_money(user)
    # A margin is the sell price minus the cost, so it needs both
    # permissions — showing it to someone barred from either half
    # hands them the half they were barred from.
    show_margin = show_money and _can_see_project_cost(user)
    show_customer = _can_see_project_customer(user)
    return {
        "id": str(p.id), "code": p.code, "status": p.status,
        "po_number": p.po_number, "po_date": p.po_date,
        "po_value": float(p.po_value or 0) if show_money else None,
        "start_date": p.start_date,
        "target_delivery": p.target_delivery,
        "actual_delivery": p.actual_delivery,
        "margin_estimate": float(p.margin_estimate or 0) if show_margin else None,
        "margin_actual": float(p.margin_actual or 0) if show_margin else None,
        # Shipping timeline + import flags — exposed so the timeline editor
        # can pre-fill the form instead of making purchasing retype every save.
        "is_import": bool(p.is_import),
        "origin_location": p.origin_location,
        "est_ship_from_origin": p.est_ship_from_origin,
        "act_ship_from_origin": p.act_ship_from_origin,
        "est_arrive_our_warehouse": p.est_arrive_our_warehouse,
        "act_arrive_our_warehouse": p.act_arrive_our_warehouse,
        "est_arrive_customer": p.est_arrive_customer,
        "act_arrive_customer": p.act_arrive_customer,
        # Purchasing gets a neutral placeholder — no customer identity leaks.
        "customer": (
            {
                "id": str(customer.id), "company_name": customer.company_name,
                "industry": customer.industry, "stage": customer.stage,
            } if (customer and show_customer)
            else ({"id": None, "company_name": f"Order {p.code}",
                   "industry": None, "stage": None} if customer else None)
        ),
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status,
            "total": float(quotation.total or 0) if show_money else None,
        } if quotation else None,
        "created_at": p.created_at,
    }


@router.get("/projects/{project_id}/full")
async def project_full(project_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Project + all related records, used by the project detail page."""
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    customer = await db.get(Customer, p.customer_id) if p.customer_id else None
    # Sales may only open their OWN customers' projects — the same scope
    # get_project enforces. Without this, /full (what the detail page actually
    # calls) leaked another rep's margins, invoices and supplier POs.
    if Role(user.role) == Role.SALES and (
        not customer or customer.sales_pic_id != user.id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None

    work_orders = (await db.scalars(
        select(WorkOrder).where(WorkOrder.project_id == project_id)
        .order_by(WorkOrder.created_at.asc())
    )).all()
    deliveries = (await db.scalars(
        select(DeliveryOrder).where(DeliveryOrder.project_id == project_id)
        .order_by(DeliveryOrder.split_index.asc())
    )).all()
    invoices = (await db.scalars(
        select(Invoice).where(Invoice.project_id == project_id)
        .order_by(Invoice.issue_date.asc().nullslast())
    )).all()
    drawings = (await db.scalars(
        select(Drawing).where(Drawing.project_id == project_id)
        .order_by(Drawing.revision.desc())
    )).all()
    # User-id set for any name we render alongside a drawing/delivery action.
    # Must run AFTER drawings + deliveries are loaded.
    drawing_user_ids = {d.decided_by for d in drawings if d.decided_by} | {
        d.uploaded_by for d in drawings if d.uploaded_by
    } | {
        do.verified_by for do in deliveries if do.verified_by
    }
    deciders: dict[UUID, str] = {}
    if drawing_user_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(drawing_user_ids)))).all():
            deciders[u.id] = u.full_name

    # Batch-load invoice + delivery-order attachments so we can surface View
    # links on the project page without N+1 lookups. Must run AFTER invoices +
    # deliveries are loaded.
    from app.models.finance import Payment
    from app.models.payment_claim import PaymentClaim
    inv_files: dict[UUID, list[dict]] = {}
    do_files: dict[UUID, list[dict]] = {}
    # Payment claims + verified payments for each invoice — lets admin see
    # progress toward 'paid' on the project page and record new ones inline.
    claims_by_inv: dict[UUID, list[dict]] = {}
    paid_by_inv: dict[UUID, float] = {}
    inv_ids = [i.id for i in invoices]
    do_ids = [d.id for d in deliveries]
    if inv_ids:
        for a in (await db.scalars(
            select(Attachment).where(
                Attachment.owner_type == "invoice",
                Attachment.owner_id.in_(inv_ids),
            ).order_by(Attachment.created_at.asc())
        )).all():
            inv_files.setdefault(a.owner_id, []).append({
                "id": str(a.id), "filename": a.filename,
                "kind": (a.description or "").strip("[]").split("]")[0] or None,
                "download_url": f"/api/v1/attachments/{a.id}/download",
            })
    if do_ids:
        for a in (await db.scalars(
            select(Attachment).where(
                Attachment.owner_type == "delivery_order",
                Attachment.owner_id.in_(do_ids),
            ).order_by(Attachment.created_at.asc())
        )).all():
            do_files.setdefault(a.owner_id, []).append({
                "id": str(a.id), "filename": a.filename,
                "download_url": f"/api/v1/attachments/{a.id}/download",
            })

    if inv_ids:
        for c in (await db.scalars(
            select(PaymentClaim).where(PaymentClaim.invoice_id.in_(inv_ids))
            .order_by(PaymentClaim.created_at.asc())
        )).all():
            claims_by_inv.setdefault(c.invoice_id, []).append({
                "id": str(c.id), "amount": float(c.amount or 0),
                "paid_at": c.paid_at, "method": c.method,
                "reference": c.reference, "notes": c.notes,
                "status": c.status,
            })
        for row in (await db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(inv_ids))
            .group_by(Payment.invoice_id)
        )).all():
            paid_by_inv[row[0]] = float(row[1] or 0)
    # Customer PO that spawned this project — for the traceability chain
    # from quotation → PO → project so the header links back one step.
    from app.models.customer_po import CustomerPO
    customer_po = (await db.scalars(
        select(CustomerPO).where(CustomerPO.project_id == project_id)
        .order_by(CustomerPO.created_at.desc()).limit(1)
    )).first()

    purchase_requests = (await db.scalars(
        select(PurchaseRequest).where(PurchaseRequest.project_id == project_id)
        .order_by(PurchaseRequest.created_at.desc())
    )).all()
    from app.models.purchasing import Supplier, SupplierPO
    supplier_pos = (await db.scalars(
        select(SupplierPO).where(SupplierPO.project_id == project_id)
        .order_by(SupplierPO.created_at.desc())
    )).all()
    supplier_name_by_id: dict[UUID, str] = {}
    if supplier_pos:
        sup_ids = {p.supplier_id for p in supplier_pos if p.supplier_id}
        if sup_ids:
            for s in (await db.scalars(
                select(Supplier).where(Supplier.id.in_(sup_ids))
            )).all():
                supplier_name_by_id[s.id] = s.name

    show_money = _can_see_project_money(user)
    # A margin is the sell price minus the cost, so it needs both
    # permissions — showing it to someone barred from either half
    # hands them the half they were barred from.
    show_margin = show_money and _can_see_project_cost(user)
    show_cost = _can_see_project_cost(user)
    _role = Role(user.role)
    # The approved price request behind this project — so purchasing can see
    # exactly what to source. The selling price is gated to money-viewers
    # (hidden from purchasing); the buying cost to cost-viewers (hidden from
    # admin, who work the customer side and invoice against the sell price).
    price_request = None
    if p.price_request_id:
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, p.price_request_id)
        if pr:
            pr_items = []
            for it in (pr.items or []):
                row = {
                    "line_no": it.get("line_no"), "description": it.get("description"),
                    "qty": it.get("qty"), "uom": it.get("uom"), "spec": it.get("spec"),
                }
                if show_cost:
                    row["cost_price"] = it.get("cost_price")
                if show_money:
                    row["sell_price"] = it.get("sell_price")
                pr_items.append(row)
            price_request = {"id": str(pr.id), "number": pr.number, "items": pr_items}
    # Sales rep in charge (the customer's account owner) so the detail page can
    # show who owns the deal.
    sales_rep = None
    if customer and customer.sales_pic_id:
        rep = await db.get(User, customer.sales_pic_id)
        if rep:
            sales_rep = {"id": str(rep.id), "name": rep.full_name}

    return {
        "project": {
            "id": str(p.id), "code": p.code, "status": p.status,
            "po_number": p.po_number, "po_date": p.po_date,
            "po_value": float(p.po_value or 0) if show_money else None,
            "start_date": p.start_date,
            "target_delivery": p.target_delivery,
            "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate or 0) if show_margin else None,
            "margin_actual": float(p.margin_actual or 0) if show_margin else None,
            "qc_decision": p.qc_decision,
            "qc_passed_at": p.qc_passed_at,
            "qc_findings": (p.meta or {}).get("qc_findings"),
            "customer_received_at": p.customer_received_at,
            "created_at": p.created_at,
        },
        "price_request": price_request,
        "logistics": _logistics_payload(p),
        "invoices": [
            {
                "id": str(inv.id), "number": inv.number, "status": inv.status,
                "type": inv.type, "termin_index": inv.termin_index,
                "issue_date": inv.issue_date, "due_date": inv.due_date,
                "amount": float(inv.amount or 0) if show_money else None,
                "tax_amount": float(inv.tax_amount or 0) if show_money else None,
                "total": float(inv.total or 0) if show_money else None,
                "faktur_pajak_no": inv.faktur_pajak_no,
                "faktur_pajak_status": inv.faktur_pajak_status,
                "approved_at": inv.approved_at,
                "notes": inv.notes,
                "files": inv_files.get(inv.id, []),
                "paid_amount": paid_by_inv.get(inv.id, 0.0) if show_money else None,
                "outstanding": (
                    max(0.0, float(inv.total or 0) - paid_by_inv.get(inv.id, 0.0))
                    if show_money else None
                ),
                "claims": claims_by_inv.get(inv.id, []),
            } for inv in invoices
        ],
        "sales_pic_id": sales_rep["id"] if (sales_rep and _can_see_project_customer(user)) else None,
        "sales_pic_name": sales_rep["name"] if (sales_rep and _can_see_project_customer(user)) else None,
        "customer": (
            {
                "id": str(customer.id), "company_name": customer.company_name,
                "industry": customer.industry, "stage": customer.stage,
            } if (customer and _can_see_project_customer(user))
            else ({"id": None, "company_name": f"Order {p.code}",
                   "industry": None, "stage": None} if customer else None)
        ),
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status,
            "total": float(quotation.total or 0) if show_money else None,
        } if quotation else None,
        "customer_po": {
            "id": str(customer_po.id), "number": customer_po.number,
            "status": customer_po.status,
            "po_date": customer_po.po_date,
        } if customer_po else None,
        "work_orders": [
            {
                "id": str(w.id), "code": w.code, "stage": w.stage, "notes": w.notes,
                "started_at": w.started_at, "completed_at": w.completed_at,
            } for w in work_orders
        ],
        # Two lists, filtered by what this role may open. `drawings` keeps its
        # old name and carries the customer's — the ones sales, admin and the
        # customer portal were always looking at — so nothing that reads it
        # starts showing vendor sheets to the wrong people if it is missed.
        "drawings": [_drawing_row(d, deciders) for d in drawings
                     if d.kind == "customer" and _may_see_drawing(_role, "customer")],
        "supplier_drawings": [_drawing_row(d, deciders) for d in drawings
                              if d.kind == "supplier"
                              and _may_see_drawing(_role, "supplier")],
        "may_upload_drawing": {
            k: _may_upload_drawing(_role, k) for k in DRAWING_KINDS
        },
        "deliveries": [
            {
                "id": str(do.id), "number": do.number, "split_index": do.split_index,
                "courier": do.courier, "tracking_no": do.tracking_no,
                "delivered_at": do.delivered_at, "status": do.status,
                "items": do.items,
                "files": do_files.get(do.id, []),
                "verified_at": do.verified_at,
                "verified_by": str(do.verified_by) if do.verified_by else None,
                "verified_by_name": deciders.get(do.verified_by) if do.verified_by else None,
            } for do in deliveries
        ],
        "purchase_requests": [
            {
                "id": str(pr.id), "number": pr.number, "status": pr.status,
                "items": pr.items, "created_at": pr.created_at,
            } for pr in purchase_requests
        ],
        # The orders placed with vendors for this job. Empty for admin — they
        # are barred from the supplier PO screens, and a card here listing the
        # vendor and its number would hand back everything those screens hold.
        # The shipments card is what they get instead: the dates, not the
        # vendor.
        "supplier_pos": [] if not show_cost else [
            {
                "id": str(p.id), "number": p.number, "status": p.status,
                "supplier_id": str(p.supplier_id) if p.supplier_id else None,
                "supplier_name": supplier_name_by_id.get(p.supplier_id),
                "po_date": p.po_date,
                "quoted_lead_days": p.quoted_lead_days,
                "total": float(p.total or 0) if show_money else None,
                "items": p.items,
                "created_at": p.created_at,
            } for p in supplier_pos
        ],
    }


# ─── Mutations ───────────────────────────────────────────────────────────────

class ProjectPatch(BaseModel):
    status: str | None = None
    po_number: str | None = None
    start_date: str | None = None
    target_delivery: str | None = None
    actual_delivery: str | None = None
    margin_estimate: float | None = None
    margin_actual: float | None = None
    # Shipping timeline
    est_ship_from_origin: str | None = None
    act_ship_from_origin: str | None = None
    est_arrive_our_warehouse: str | None = None
    act_arrive_our_warehouse: str | None = None
    est_arrive_customer: str | None = None
    act_arrive_customer: str | None = None
    origin_location: str | None = None
    is_import: bool | None = None


DATE_FIELDS_PROTECTED = {
    "start_date", "target_delivery", "actual_delivery",
    "est_ship_from_origin", "act_ship_from_origin",
    "est_arrive_our_warehouse", "act_arrive_our_warehouse",
    "est_arrive_customer", "act_arrive_customer",
}
# Shipping / delivery dates that customers see — changes are director-gated.
SHIPPING_FIELDS = {
    "target_delivery", "actual_delivery",
    "est_ship_from_origin", "act_ship_from_origin",
    "est_arrive_our_warehouse", "act_arrive_our_warehouse",
    "est_arrive_customer", "act_arrive_customer",
}


def _apply_project_changes(p: Project, data: dict) -> None:
    # exclude_unset alone isn't enough: the frontend often sends an explicit
    # null for the date fields it isn't editing. Drop those nulls for date
    # columns so we never wipe an existing date by accident.
    for k, v in data.items():
        if v is None and k in DATE_FIELDS_PROTECTED:
            continue
        if not hasattr(p, k):
            continue
        # Date columns need real date objects under asyncpg — coerce ISO
        # strings (which arrive from the approval payload as JSON strings,
        # and from the PATCH schema as `str | None`).
        if k in DATE_FIELDS_PROTECTED and isinstance(v, str):
            try:
                v = date.fromisoformat(v)
            except ValueError as e:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{k} must be a YYYY-MM-DD date",
                ) from e
        setattr(p, k, v)


@router.patch("/projects/{project_id}")
async def update_project(project_id: UUID,
                         payload: ProjectPatch,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Sales may only edit their OWN customers' projects (mirrors get_project).
    if Role(user.role) == Role.SALES:
        _cust = await db.get(Customer, p.customer_id) if p.customer_id else None
        if not _cust or _cust.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN)
    data = payload.model_dump(exclude_unset=True)
    # The project status is driven by real events (advance_project_status),
    # never by a dropdown — writing it here would skip stages or move the
    # pipeline backwards. Only the director may force it as an escape hatch.
    if "status" in data and Role(user.role) != Role.DIRECTOR:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Project status follows the workflow — it can't be set directly.",
        )

    # Per-role shipping-leg ownership. Manager + director stay unrestricted
    # (they're the fallback for anything that goes sideways in ops).
    # - Purchasing books the origin leg: Est. + Actual shipped-from-origin,
    #   plus the is_import / origin_location metadata.
    # - Admin owns both arrival legs end to end: estimated AND actual
    #   arrival at our warehouse + at the customer's site. Nothing else
    #   on the shipping strip.
    # Attempting to write outside your lane returns a 403 so the API
    # matches the disabled fields in the UI.
    _PURCHASING_SHIPPING = {"est_ship_from_origin", "act_ship_from_origin"}
    _PURCHASING_META = {"is_import", "origin_location"}
    _ADMIN_SHIPPING = {
        "est_arrive_our_warehouse", "act_arrive_our_warehouse",
        "est_arrive_customer", "act_arrive_customer",
    }
    user_role = Role(user.role)
    if user_role == Role.SALES:
        # Sales has no lane on the shipping strip at all — not even a queued
        # one. Every date here is a promise about physical goods that sales is
        # not the one moving: purchasing books the origin leg, admin owns both
        # arrival legs, and the customer-facing target/actual delivery is the
        # director's. Letting a rep *propose* a date was worse than useless —
        # it looked like an edit to them, and arrived in the director's inbox
        # as a decision about a shipment the requester has no visibility of.
        bad = sorted(k for k in data
                     if k in SHIPPING_FIELDS or k in {"is_import", "origin_location"})
        if bad:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Delivery and shipping dates aren't sales' to set — "
                f"ask purchasing (origin) or admin (arrival). Got {bad}.",
            )
    if user_role == Role.PURCHASING:
        allowed = _PURCHASING_SHIPPING | _PURCHASING_META
        gated_keys = SHIPPING_FIELDS | {"is_import", "origin_location"}
        bad = sorted(k for k in data if k in gated_keys and k not in allowed)
        if bad:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Purchasing may only edit {sorted(allowed)} on the shipping "
                f"strip — got {bad}.",
            )
    elif user_role == Role.ADMIN:
        gated_keys = SHIPPING_FIELDS | {"is_import", "origin_location"}
        bad = sorted(k for k in data if k in gated_keys and k not in _ADMIN_SHIPPING)
        if bad:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Admin may only edit {sorted(_ADMIN_SHIPPING)} on the "
                f"shipping strip — got {bad}.",
            )

    # Changing a shipping/delivery date is director-gated: a non-director's
    # edit is filed for approval (with the whole patch) and applied only when
    # the director signs off. Director edits apply immediately.
    touches_shipping = any(k in SHIPPING_FIELDS for k in data)
    if touches_shipping and Role(user.role) != Role.DIRECTOR:
        # Don't queue a null that would only clear a protected date.
        queued = {k: v for k, v in data.items()
                  if not (v is None and k in DATE_FIELDS_PROTECTED)}
        await request_approval(
            db,
            target_type="project",
            target_id=p.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Shipping update for {p.code}: {', '.join(sorted(queued))}",
            payload={"action": "update", "changes": queued},
        )
        return {"ok": True, "id": str(p.id), "pending_approval": True}

    _apply_project_changes(p, data)
    return {"ok": True, "id": str(p.id), "pending_approval": False}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Soft-delete a project. Director-only escape hatch for cleaning up
    stale records (typically test data or projects created before a
    workflow reorder). The row stays in the DB with is_deleted=True so
    the historical PO / quotation / invoice chain isn't orphaned — the
    list endpoint already filters is_deleted=False.
    """
    if Role(user.role) != Role.DIRECTOR:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the director can delete a project.",
        )
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if p.is_deleted:
        return None
    p.is_deleted = True
    p.deleted_at = datetime.now(UTC)
    # Unlink from the customer PO so a director can re-file the same PO
    # later without a duplicate-project constraint clash.
    from app.models.customer_po import CustomerPO
    for po in (await db.scalars(
        select(CustomerPO).where(CustomerPO.project_id == project_id)
    )).all():
        po.project_id = None
    await db.flush()
    from app.core.audit import record as audit_record
    await audit_record(
        db, actor=user, action="delete", entity="project",
        entity_id=p.id,
        before={"code": p.code, "status": p.status,
                "customer_id": str(p.customer_id) if p.customer_id else None},
    )
    return None


# ─── Post-drawing logistics (purchasing) ─────────────────────────────────────
# Which import documents each delivery mode requires. Two weeks before the
# estimated delivery, purchasing must have these collected.
DOC_LABELS = {
    "invoice": "Invoice",
    "packing_list": "Packing list",
    "form_e": "Form E",
    "bill_of_lading": "Bill of Lading",
    "agent": "Agent details",
}
REQUIRED_DOCS = {
    "local":         ["invoice", "packing_list"],
    "direct_import": ["invoice", "packing_list", "form_e", "bill_of_lading"],
    "agent":         ["invoice", "packing_list", "agent"],
}
_LOGISTICS_ROLES = {Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.ADMIN}
DOCS_DUE_WINDOW_DAYS = 14

# ── Drawings, and who they belong to ─────────────────────────────────────────
#
# Two documents, not one pile. The **supplier drawing** is what the vendor sent
# us — it is procurement's side of the job and names the vendor. The **customer
# drawing** is what we put in front of the customer for approval, and it is
# *drawn up from* the supplier's rather than being the same sheet forwarded on.
#
# So the two have different authors and different readers, and the walls are
# the same ones the rest of the app already keeps:
#
#   * **Sales** may see the customer drawing (they are the ones showing it to
#     the customer) but never file one, and never see the supplier's at all —
#     that is the vendor relationship, which sales is kept out of.
#   * **Purchasing** sees the supplier drawing; the customer drawing carries
#     the customer, and purchasing stays blind to it.
#   * **Admin** works the customer side — they file the customer drawing and
#     see only that.
#   * **Manager / director** see both, which is what makes the handoff
#     possible: they take the supplier drawing and produce the customer one
#     from it, and **the director is who files the supplier drawing** — asked
#     for explicitly, and "for right now", so this is the line to move when
#     that changes rather than anything downstream of it.
DRAWING_KINDS = ("customer", "supplier")

_DRAWING_UPLOAD_ROLES: dict[str, set[Role]] = {
    "customer": {Role.ADMIN, Role.MANAGER, Role.DIRECTOR},
    "supplier": {Role.MANAGER, Role.DIRECTOR},
}
# The portal roles belong in here too, and not as an afterthought: the whole
# point of the customer drawing is that the customer opens and approves it, and
# the supplier drawing is the vendor's own upload. These sets are consulted
# when a *file* is fetched (`attachments.py`), which is the one path both
# portals reach — the operation router itself never admits them.
_DRAWING_VIEW_ROLES: dict[str, set[Role]] = {
    "customer": {Role.SALES, Role.ADMIN, Role.MANAGER, Role.DIRECTOR,
                 Role.FINANCE, Role.CUSTOMER},
    "supplier": {Role.PURCHASING, Role.MANAGER, Role.DIRECTOR, Role.SUPPLIER},
}
_DRAWING_APPROVE_ROLES = {Role.DIRECTOR, Role.MANAGER, Role.ADMIN}


def _may_upload_drawing(role: Role, kind: str) -> bool:
    return role in _DRAWING_UPLOAD_ROLES.get(kind, set())


def _may_see_drawing(role: Role, kind: str) -> bool:
    return role in _DRAWING_VIEW_ROLES.get(kind or "customer", set())


def _logistics_payload(p: Project) -> dict:
    mode = p.delivery_mode or "local"
    required = REQUIRED_DOCS.get(mode, REQUIRED_DOCS["local"])
    docs = p.import_docs or {}
    rows = []
    for key in required:
        d = docs.get(key) or {}
        rows.append({
            "key": key,
            "label": DOC_LABELS.get(key, key),
            "collected": bool(d.get("collected")),
            "attachment_id": d.get("attachment_id"),
            "filename": d.get("filename"),
            "note": d.get("note"),
            "status": d.get("status"),          # None | pending | approved | rejected
            "decided_at": d.get("decided_at"),
        })
    all_collected = all(r["collected"] for r in rows) if rows else True
    all_approved = all(r["status"] == "approved" for r in rows) if rows else True
    days_to = (p.est_delivery_date - date.today()).days if p.est_delivery_date else None
    return {
        "delivery_mode": mode,
        "est_delivery_date": p.est_delivery_date,
        "delivery_confirmed_at": p.delivery_confirmed_at,
        "required_docs": rows,
        "docs_complete": all_collected,
        "docs_approved": all_approved,
        "days_to_delivery": days_to,
        # Documents are "due" once we're within the window and not yet complete.
        "docs_due": (
            days_to is not None and days_to <= DOCS_DUE_WINDOW_DAYS and not all_collected
        ),
    }


async def _has_approved_drawing(db: AsyncSession, project_id: UUID) -> bool:
    """Has the *customer* signed off a drawing? Theirs is the only approval
    that unblocks the job — a signed-off vendor sheet is an internal step, and
    counting it here would let logistics start on a drawing the customer has
    never seen."""
    d = await db.scalar(
        select(Drawing).where(
            Drawing.project_id == project_id, Drawing.status == "approved",
            Drawing.kind == "customer",
        ).limit(1)
    )
    return d is not None


@router.post("/projects/{project_id}/drawings", status_code=201)
async def upload_drawing(
    project_id: UUID,
    notes: str | None = Form(None),
    kind: str = Form("customer"),
    source_drawing_id: UUID | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """File a drawing — purchasing the supplier's, admin the customer's.

    It lands as 'submitted', awaiting the director's sign-off. `kind` decides
    who may file it at all (see `_DRAWING_UPLOAD_ROLES`): sales are readers of
    the customer drawing, not its authors, and never touch the supplier's.
    """
    kind = (kind or "customer").strip().lower()
    if kind not in DRAWING_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"kind must be one of {list(DRAWING_KINDS)}")
    role = Role(user.role)
    if not _may_upload_drawing(role, kind):
        who = ", ".join(sorted(r.value for r in _DRAWING_UPLOAD_ROLES[kind]))
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"A {kind} drawing is filed by {who} — not {role.value}.")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    # A customer drawing may be drawn up *from* a supplier's; keep the link so
    # the lineage survives, and refuse a source the caller cannot even open.
    src = None
    if source_drawing_id:
        src = await db.get(Drawing, source_drawing_id)
        if not src or src.project_id != p.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Source drawing not found")
        if not _may_see_drawing(role, src.kind):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "That drawing isn't yours to work from")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Max 20 MB")

    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    storage_path = await storage.save(data, filename=safe, label="drawing",
                                      owner_type="project", owner_id=p.id)

    a = Attachment(
        owner_type="project", owner_id=p.id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=storage_path,
        description=f"[drawing:{kind}] {notes or ''}".strip(),
        uploaded_by=user.id,
    )
    db.add(a)
    await db.flush()

    # Revisions run per kind: the supplier's third sheet and the customer's
    # first are not revisions of each other.
    prior = (await db.scalars(
        select(Drawing).where(Drawing.project_id == p.id, Drawing.kind == kind)
    )).all()
    next_rev = (max((d.revision for d in prior), default=0) or 0) + 1
    drw = Drawing(
        project_id=p.id,
        revision=next_rev,
        kind=kind,
        source_drawing_id=src.id if src else None,
        file_url=f"/api/v1/attachments/{a.id}/download",
        status="submitted",
        notes=notes,
        uploaded_by=user.id,
    )
    db.add(drw)
    # Reflect that a drawing is now in review (never moves the status backward).
    advance_project_status(p, "drawing")
    await db.flush()
    return {
        "id": str(drw.id), "revision": drw.revision, "status": drw.status,
        "kind": drw.kind, "file_url": drw.file_url,
        "source_drawing_id": str(drw.source_drawing_id) if drw.source_drawing_id else None,
    }


class DrawingDecision(BaseModel):
    decision: str                  # 'approve' | 'request_revision'
    notes: str | None = None


@router.post("/drawings/{drawing_id}/decide")
async def decide_drawing(
    drawing_id: UUID,
    payload: DrawingDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The director signs off (or sends back) a submitted drawing. Approving
    advances the project to 'drawing_approved' so logistics can begin."""
    if Role(user.role) not in _DRAWING_APPROVE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the director can approve drawings")
    d = await db.get(Drawing, drawing_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    # Admin approves drawings, but only the ones they may open — signing off a
    # vendor sheet you cannot see is not a decision.
    if not _may_see_drawing(Role(user.role), d.kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"A {d.kind} drawing isn't yours to decide")
    project = await db.get(Project, d.project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    if payload.decision == "approve":
        d.status = "approved"
        # Only the *customer's* drawing being signed off means the job can move
        # on — that is the approval the customer is waiting on. Approving a
        # supplier sheet is an internal step; it must not skip the project past
        # the drawing the customer has not seen yet.
        if d.kind == "customer":
            advance_project_status(project, "drawing_approved")
    elif payload.decision == "request_revision":
        d.status = "revision_requested"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "decision must be approve|request_revision")
    d.decided_by = user.id
    d.decided_at = datetime.now(UTC)
    if payload.notes:
        d.notes = ((d.notes or "") + f"\n[{user.full_name}] {payload.notes}").strip()
    await db.flush()
    return {"ok": True, "drawing_id": str(d.id), "status": d.status}


@router.post("/drawings/{drawing_id}/reupload")
async def reupload_drawing(
    drawing_id: UUID,
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-upload a revised file after the director requested a revision.

    Allowed for the account that posted the drawing (or management). Replaces
    the file in place and sends it back to the director as 'submitted'.
    """
    d = await db.get(Drawing, drawing_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    if d.status != "revision_requested":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only a drawing with a requested revision can be re-uploaded")
    # A rejected drawing may be re-uploaded ONLY by the account that posted it —
    # uploads are tied to their owner. (Legacy rows with no recorded uploader
    # can't be revised; delete them and post a fresh drawing instead.)
    if not _may_see_drawing(Role(user.role), d.kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"A {d.kind} drawing isn't yours to revise")
    if d.uploaded_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the account that uploaded this drawing can re-upload it")
    p = await db.get(Project, d.project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Max 20 MB")

    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    storage_path = await storage.save(data, filename=safe, label="drawing",
                                      owner_type="project", owner_id=p.id)

    a = Attachment(
        owner_type="project", owner_id=p.id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=storage_path,
        description=f"[drawing:{d.kind}] {notes or 'revised'}".strip(),
        uploaded_by=user.id,
    )
    db.add(a)
    await db.flush()

    # Replace the file in place and send it back for review. Clear the prior
    # decision so the director sees a fresh "submitted" drawing.
    d.file_url = f"/api/v1/attachments/{a.id}/download"
    d.status = "submitted"
    d.uploaded_by = user.id
    d.decided_by = None
    d.decided_at = None
    d.customer_decision_at = None
    if notes:
        d.notes = ((d.notes or "") + f"\n[revised by {user.full_name}] {notes}").strip()
    await db.flush()
    return {"ok": True, "drawing_id": str(d.id), "status": d.status,
            "revision": d.revision, "file_url": d.file_url}


@router.delete("/drawings/{drawing_id}")
async def delete_drawing(
    drawing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a drawing revision. Allowed for the account that posted it or for
    management. Best-effort removes the underlying file too."""
    import os
    import re

    d = await db.get(Drawing, drawing_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    # Management may delete, but not a kind they cannot open — admin deleting
    # the vendor's sheet they were never shown is worse than leaving it.
    if not _may_see_drawing(Role(user.role), d.kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"A {d.kind} drawing isn't yours to delete")
    is_owner = d.uploaded_by == user.id
    is_mgmt = Role(user.role) in {Role.DIRECTOR, Role.MANAGER, Role.ADMIN}
    if not (is_owner or is_mgmt):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the account that posted this drawing (or management) can delete it")

    # Best-effort: drop the underlying attachment + file so we don't orphan it.
    m = re.search(r"/attachments/([0-9a-fA-F-]+)/download", d.file_url or "")
    if m:
        att = await db.get(Attachment, UUID(m.group(1)))
        if att:
            try:
                await storage.delete(att.storage_path)
            except OSError:
                pass
            await db.delete(att)

    await db.delete(d)
    await db.flush()
    return {"ok": True, "deleted": str(drawing_id)}


class LogisticsPatch(BaseModel):
    delivery_mode: str | None = None
    est_delivery_date: date | None = None


@router.patch("/projects/{project_id}/logistics")
async def update_logistics(project_id: UUID, payload: LogisticsPatch,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Purchasing sets the delivery mode + estimated delivery date once the
    drawing is approved."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not await _has_approved_drawing(db, project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Set logistics only after the drawing is approved.",
        )
    if payload.delivery_mode is not None:
        if payload.delivery_mode not in REQUIRED_DOCS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"delivery_mode must be one of {list(REQUIRED_DOCS)}")
        p.delivery_mode = payload.delivery_mode
    if payload.est_delivery_date is not None:
        p.est_delivery_date = payload.est_delivery_date
    await db.flush()
    return _logistics_payload(p)


class ImportDocPatch(BaseModel):
    key: str
    collected: bool = True
    attachment_id: str | None = None
    note: str | None = None


@router.patch("/projects/{project_id}/import-docs")
async def update_import_doc(project_id: UUID, payload: ImportDocPatch,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """Update an import document's collected flag / note, preserving any
    uploaded file + approval state already on it."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if payload.key not in DOC_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown document '{payload.key}'")
    docs = dict(p.import_docs or {})
    entry = dict(docs.get(payload.key) or {})
    entry["collected"] = payload.collected
    if payload.attachment_id is not None:
        entry["attachment_id"] = payload.attachment_id
    if payload.note is not None:
        entry["note"] = payload.note
    docs[payload.key] = entry
    p.import_docs = docs
    await db.flush()
    return _logistics_payload(p)


@router.post("/projects/{project_id}/import-docs/{key}/upload")
async def upload_import_doc(
    project_id: UUID,
    key: str,
    note: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Purchasing uploads the actual file for a required import document. It
    lands as 'pending', awaiting the director's approval."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if key not in DOC_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown document '{key}'")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Max 20 MB")

    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    storage_path = await storage.save(data, filename=safe, label=key,
                                      owner_type="project", owner_id=p.id)

    a = Attachment(
        owner_type="project", owner_id=p.id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=storage_path,
        description=f"[import-doc:{key}] {note or ''}".strip(),
        uploaded_by=user.id,
    )
    db.add(a)
    await db.flush()

    docs = dict(p.import_docs or {})
    docs[key] = {
        "collected": True,
        "attachment_id": str(a.id),
        "filename": safe,
        "note": note,
        "status": "pending",          # awaiting director approval
        "uploaded_by": str(user.id),
        "decided_by": None,
        "decided_at": None,
    }
    p.import_docs = docs
    await db.flush()
    return _logistics_payload(p)


class ImportDocDecision(BaseModel):
    decision: str          # 'approve' | 'reject'
    note: str | None = None


@router.post("/projects/{project_id}/import-docs/{key}/decide")
async def decide_import_doc(
    project_id: UUID,
    key: str,
    payload: ImportDocDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Director approves (or rejects) an uploaded import document."""
    if Role(user.role) not in _DRAWING_APPROVE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the director can approve documents")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    docs = dict(p.import_docs or {})
    entry = dict(docs.get(key) or {})
    if not entry.get("attachment_id"):
        raise HTTPException(status.HTTP_409_CONFLICT, "No file uploaded for this document yet")
    if payload.decision == "approve":
        entry["status"] = "approved"
    elif payload.decision == "reject":
        entry["status"] = "rejected"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approve|reject")
    entry["decided_by"] = str(user.id)
    entry["decided_at"] = datetime.now(UTC).isoformat()
    if payload.note:
        entry["note"] = ((entry.get("note") or "") + f"\n[{user.full_name}] {payload.note}").strip()
    docs[key] = entry
    p.import_docs = docs
    await db.flush()
    return _logistics_payload(p)


@router.post("/projects/{project_id}/confirm-delivery")
async def confirm_delivery(project_id: UUID,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Confirm the delivery date — this spawns the receiving work order on the
    operations board (idempotent)."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not p.est_delivery_date:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Set the estimated delivery date first.")
    # Every required import document must be director-approved first.
    if not _logistics_payload(p)["docs_approved"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "All required documents must be approved by the director first.",
        )
    p.delivery_confirmed_at = datetime.now(UTC)
    # Under the reordered pipeline, drawing_approved → production is a
    # direct step. Confirming delivery is the trigger — the goods are on
    # the way, the ops board should be live. advance_project_status caps
    # at one step, so it's safe if the project is already ahead.
    advance_project_status(p, "production")
    # Spawn the receiving WO if the operations board doesn't have one yet.
    existing = await db.scalar(
        select(WorkOrder).where(
            WorkOrder.project_id == project_id, WorkOrder.stage == "receiving"
        ).limit(1)
    )
    created_wo = None
    if not existing:
        wo = WorkOrder(project_id=project_id, code=f"WO-{p.code}-RCV", stage="receiving")
        db.add(wo)
        await db.flush()
        created_wo = {"id": str(wo.id), "code": wo.code}
    return {"ok": True, "delivery_confirmed_at": p.delivery_confirmed_at,
            "receiving_work_order": created_wo,
            "logistics": _logistics_payload(p)}


# Operations (the ops board) — manager/admin/director.
_OPS_ROLES = {Role.MANAGER, Role.DIRECTOR, Role.ADMIN}
# Admin desk — issues the delivery order + invoice, confirms customer receipt.
_ADMIN_ROLES = {Role.ADMIN, Role.DIRECTOR}


async def _next_doc_number(db: AsyncSession, model, prefix: str) -> str:
    """One past the highest number issued this year, never a row count.

    A count walks backwards the moment a document is deleted and hands the
    next one a number that is still in use — the insert then fails on the
    unique index. See `app/services/numbering.py`.
    """
    from datetime import datetime as _dt
    from app.services.numbering import _next_suffix
    pre = f"{prefix}-{_dt.utcnow().year}-"
    return f"{pre}{await _next_suffix(db, model.number, pre):04d}"


async def _save_attachment(
    db: AsyncSession, *, file: UploadFile, owner_type: str, owner_id: UUID,
    user: User, label: str,
) -> Attachment | None:
    data = await file.read()
    if not data:
        return None
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"{label}: max 20 MB")
    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    storage_path = await storage.save(data, filename=safe, label=label,
                                      owner_type=owner_type, owner_id=owner_id)
    a = Attachment(
        owner_type=owner_type, owner_id=owner_id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=storage_path,
        description=f"[{label}]",
        uploaded_by=user.id,
    )
    db.add(a)
    await db.flush()
    return a


# Finance owns invoice issuance now — admin used to be able to file the
# invoice + DO, but the admin scope is projects/ops/inventory only. Manager
# gets no direct issuance either; director stays as backstop.
_INVOICE_ISSUER_ROLES = {Role.FINANCE, Role.DIRECTOR, Role.ADMIN}


@router.post("/projects/{project_id}/issue-invoice", status_code=201)
async def issue_invoice(
    project_id: UUID,
    amount: float | None = Form(None),
    tax_amount: float | None = Form(None),
    due_date: str | None = Form(None),
    courier: str | None = Form(None),
    create_delivery_order: bool = Form(True),
    invoice_type: str = Form(
        "final",
        description=(
            "'dp' for a down-payment invoice issued before delivery, "
            "'final' for the post-delivery invoice, 'single' for a "
            "one-shot invoice."
        ),
    ),
    invoice_file: UploadFile | None = File(None),
    delivery_order_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance issues the delivery order + invoice.

    Two flavours: a **down-payment ('dp')** invoice can be filed anytime after
    the customer PO is approved — the customer pays a deposit before we start
    delivery — and a **final ('final')** invoice which is issued after QC
    passes to bill the remaining balance. 'single' is the legacy one-shot mode
    (whole amount in a single invoice, issued post-QC).

    Finance is the one who uploads the invoice file so the tax record can't be
    corrupted by an admin misclick at issue time. The faktur pajak number is
    still entered by finance during the approve step so the number is committed
    at the moment finance signs off, not at upload time.

    The invoice parks at `pending_finance` regardless of type.
    """
    if Role(user.role) not in _INVOICE_ISSUER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Finance/admin/director only")
    itype = (invoice_type or "final").strip().lower()
    if itype not in {"dp", "final", "single"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "invoice_type must be 'dp', 'final', or 'single'")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # DP invoices are issued BEFORE delivery, so no QC gate; final/single stay
    # gated on QC to preserve the post-delivery billing flow.
    if itype != "dp" and not p.qc_passed_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The final invoice can only be issued after QC has passed. "
            "Issue a down-payment ('dp') invoice if you need to bill before delivery.",
        )
    if not p.customer_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project has no customer.")

    parsed_due: date | None = None
    if due_date:
        try:
            parsed_due = date.fromisoformat(due_date)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "due_date must be YYYY-MM-DD") from e

    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None
    # Invoice.amount is the DPP (net, pre-tax) everywhere else — the e-Faktur
    # export files it as JUMLAH_DPP with tax_amount as JUMLAH_PPN, and the DP
    # sibling defaults from the PO total (Σ qty × unit_price, net).
    # Quotation.total is GROSS (after_discount + PPN), so defaulting from it
    # put tax inside the DPP and then added PPN again on top.
    if amount is not None:
        inv_amount = float(amount)
    elif quotation is not None:
        inv_amount = float(quotation.subtotal or 0) - float(quotation.discount_amount or 0)
    else:
        inv_amount = float(p.po_value or 0)
    # Default the PPN from the quotation's tax rate when finance didn't type one.
    if tax_amount is not None:
        inv_tax = float(tax_amount)
    elif quotation is not None:
        inv_tax = inv_amount * float(quotation.tax_pct or 0) / 100.0
    else:
        inv_tax = 0.0
    total = inv_amount + inv_tax

    inv = Invoice(
        number=await _next_doc_number(db, Invoice, "INV"),
        project_id=project_id, customer_id=p.customer_id,
        type=itype,
        issue_date=date.today(), due_date=parsed_due,
        amount=inv_amount, tax_amount=inv_tax, total=total,
        status="pending_finance",
        # Faktur pajak is filled in by finance on approval, not on issue.
        faktur_pajak_no=None,
        faktur_pajak_status="none",
        issued_by=user.id,
    )
    db.add(inv)
    await db.flush()

    if invoice_file is not None:
        await _save_attachment(db, file=invoice_file, owner_type="invoice",
                               owner_id=inv.id, user=user, label="invoice")

    # A DP invoice comes before the DO, so don't auto-create a delivery order
    # when the type is 'dp' — the DO is filed on the final invoice.
    do = None
    if create_delivery_order and itype != "dp":
        do = DeliveryOrder(
            project_id=project_id,
            number=await _next_doc_number(db, DeliveryOrder, "DO"),
            courier=courier, status="pending",
        )
        db.add(do)
        await db.flush()
        if delivery_order_file is not None:
            await _save_attachment(db, file=delivery_order_file,
                                   owner_type="delivery_order",
                                   owner_id=do.id, user=user,
                                   label="delivery_order")
    return {
        "invoice": {"id": str(inv.id), "number": inv.number, "status": inv.status,
                    "type": inv.type, "total": float(inv.total or 0),
                    "faktur_pajak_no": inv.faktur_pajak_no},
        "delivery_order": {"id": str(do.id), "number": do.number} if do else None,
    }


@router.post("/projects/{project_id}/customer-received")
async def mark_customer_received(project_id: UUID,
                                 db: AsyncSession = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """Admin confirms the customer received the goods — the final step."""
    if Role(user.role) not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    p.customer_received_at = datetime.now(UTC)
    # Mark any outstanding delivery orders delivered.
    for do in (await db.scalars(
        select(DeliveryOrder).where(
            DeliveryOrder.project_id == project_id,
            DeliveryOrder.status != "delivered",
        )
    )).all():
        do.status = "delivered"
        if not do.delivered_at:
            do.delivered_at = datetime.now(UTC)
    # Customer-received is the trigger for the 'delivered' project status.
    advance_project_status(p, "delivered")
    await db.flush()
    return {"ok": True, "customer_received_at": p.customer_received_at}


class QCDecision(BaseModel):
    decision: str  # "pass" | "fail"
    findings: str | None = None


@router.post("/projects/{project_id}/qc")
async def record_qc(project_id: UUID, payload: QCDecision,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Operations records the final QC check. Passing hands the project to
    admin (status → qc) to issue the delivery order + invoice; failing parks
    it with findings."""
    if Role(user.role) not in _OPS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operations only")
    if payload.decision not in ("pass", "fail"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be pass|fail")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    p.qc_decision = payload.decision
    meta = dict(p.meta or {})
    if payload.findings is not None:
        meta["qc_findings"] = payload.findings
    p.meta = meta
    if payload.decision == "pass":
        p.qc_passed_at = datetime.now(UTC)
        advance_project_status(p, "qc")
        # Close any still-open work orders — operations is done with the goods.
        for wo in (await db.scalars(
            select(WorkOrder).where(
                WorkOrder.project_id == project_id,
                WorkOrder.completed_at.is_(None),
            )
        )).all():
            wo.completed_at = datetime.now(UTC)
    else:
        p.qc_passed_at = None
    await db.flush()
    return {"ok": True, "qc_decision": p.qc_decision,
            "qc_passed_at": p.qc_passed_at, "status": p.status}


class WorkOrderIn(BaseModel):
    code: str
    stage: str = "receiving"
    notes: str | None = None


# Work-order stages that map to a project status. When a WO of one of these
# stages is created / staged-into / completed, the project advances to the
# matching status (forward-only via advance_project_status).
_WO_STAGE_TO_PROJECT_STATUS = {"qc": "qc", "packaging": "packaging"}

_ALLOWED_WO_STAGES = {"receiving", "warehousing", "qc", "packaging", "delivery"}

# Who may create / mutate work orders. Purchasing handles the material-side
# stages, admin runs the ops board, director oversees. Sales/HR/finance don't
# touch WOs — the endpoint used to let anyone with a session file one, which
# is what let production stages be created out of step with the project.
_WO_MUTATOR_ROLES = {Role.PURCHASING, Role.ADMIN, Role.DIRECTOR}

# The minimum project stage required before a WO of the given kind can exist.
# The rule enforced below is stricter — the WO can move the project by AT MOST
# one status forward (via advance_project_status), so trying to file a
# packaging WO on a project that's still at 'drawing' is rejected outright
# rather than silently creating a mismatched record.
_WO_STAGE_MIN_PROJECT_STATUS = {
    "receiving":   "production",
    "warehousing": "production",
    "qc":          "production",   # creating the QC WO bumps project 'production' → 'qc'
    "packaging":   "qc",           # creating the packaging WO bumps 'qc' → 'packaging'
    "delivery":    "packaging",    # delivery WO ships out after packaging
}


def _project_stage_idx(status: str) -> int:
    from app.models.operation import PROJECT_STATUS_ORDER as _order
    try:
        return _order.index(status)
    except ValueError:
        return -1


def _assert_wo_allowed_for_project(p: "Project", stage: str) -> None:
    """Raise if the WO's stage isn't consistent with the project's current
    position on the pipeline. The rule is 'at most one project-stage ahead'
    so the WO board can't get decoupled from the project status."""
    stage = (stage or "").lower()
    if stage not in _ALLOWED_WO_STAGES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown work-order stage '{stage}'. "
            f"Use one of: {', '.join(sorted(_ALLOWED_WO_STAGES))}.",
        )
    min_required = _WO_STAGE_MIN_PROJECT_STATUS[stage]
    cur_idx = _project_stage_idx(p.status)
    min_idx = _project_stage_idx(min_required)
    if cur_idx < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Project status '{p.status}' isn't part of the operations pipeline.",
        )
    if cur_idx < min_idx:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Can't file a '{stage}' work order while the project is still "
            f"at '{p.status}'. The project has to reach '{min_required}' "
            "first — advance the previous stages (purchasing → drawing → "
            "drawing_approved → production …) before jumping ahead.",
        )


@router.post("/projects/{project_id}/work-orders", status_code=201)
async def add_work_order(project_id: UUID, payload: WorkOrderIn,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    if Role(user.role) not in _WO_MUTATOR_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only purchasing, admin or director can file a work order.",
        )
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Refuse the WO outright if the project's still in pre-production
    # (purchasing / drawing / drawing_approved). Ops WOs only make sense
    # once physical work is starting.
    _assert_wo_allowed_for_project(p, payload.stage)
    w = WorkOrder(project_id=project_id, code=payload.code,
                  stage=payload.stage, notes=payload.notes)
    db.add(w)
    # The WO is now legitimately at-or-just-past the project's stage, so
    # advance the project to the milestone the event represents — advance_project_status
    # is forward-only (it never regresses). A qc WO on a production project bumps
    # to qc; a packaging WO on a qc project bumps to packaging.
    bump = _WO_STAGE_TO_PROJECT_STATUS.get((payload.stage or "").lower())
    if bump:
        advance_project_status(p, bump)
    await db.flush()
    return {"id": str(w.id), "code": w.code, "stage": w.stage}


@router.patch("/work-orders/{wo_id}")
async def update_work_order(wo_id: UUID, stage: str | None = None,
                            notes: str | None = None, completed: bool = False,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    w = await db.get(WorkOrder, wo_id)
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if Role(user.role) not in _WO_MUTATOR_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only purchasing, admin or director can modify a work order.",
        )
    # Advancing a WO's own stage has to obey the same 'one project-stage
    # ahead at most' rule as creation — otherwise a WO can be dragged
    # straight to 'delivery' regardless of where the project actually is.
    if stage is not None and w.project_id:
        p_for_check = await db.get(Project, w.project_id)
        if p_for_check:
            _assert_wo_allowed_for_project(p_for_check, stage)
    if stage is not None:  w.stage = stage
    if notes is not None:  w.notes = notes
    if completed and not w.completed_at:
        w.completed_at = datetime.now(UTC)
    # Changing a WO into (or completing one already at) a project-mapped
    # stage advances the project — covers QC and packaging symmetrically.
    if w.project_id:
        bump = _WO_STAGE_TO_PROJECT_STATUS.get((stage or "").lower())
        if not bump and completed:
            bump = _WO_STAGE_TO_PROJECT_STATUS.get((w.stage or "").lower())
        if bump:
            p = await db.get(Project, w.project_id)
            if p:
                advance_project_status(p, bump)
                # Completing a QC work order also counts as "QC passed" so
                # finance can issue the invoice — issue_invoice gates on this.
                # NEVER when QC was explicitly failed: that would forge a pass
                # (qc_passed_at set while qc_decision stays "fail") and unlock
                # billing for goods that failed inspection. A failed QC has to
                # be re-recorded via POST /projects/{id}/qc.
                if (bump == "qc" and completed and not p.qc_passed_at
                        and p.qc_decision != "fail"):
                    p.qc_passed_at = datetime.now(UTC)
                    if not p.qc_decision:
                        p.qc_decision = "pass"
    return {"ok": True, "id": str(w.id), "stage": w.stage,
            "completed_at": w.completed_at}


@router.get("/work-orders")
async def list_work_orders(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    stage: str | None = None,
    completed: bool | None = None,
    project_id: UUID | None = None,
):
    """List work orders, optionally scoped to a stage / completion / project.

    Used by the Operation board's per-stage screens — pass ?stage=receiving
    to render a focused view of just that column."""
    from app.models.crm import Customer
    # Work orders on a deleted project are gone; on a finished project an
    # incomplete WO is historical, not open work.
    stmt = (
        select(WorkOrder)
        .join(Project, WorkOrder.project_id == Project.id)
        .where(Project.is_deleted.is_(False))
        .order_by(WorkOrder.created_at.desc())
    )
    if completed is False:
        stmt = stmt.where(Project.status.not_in(("delivered", "paid", "closed")))
    if stage:
        stmt = stmt.where(WorkOrder.stage == stage)
    if project_id:
        stmt = stmt.where(WorkOrder.project_id == project_id)
    if completed is True:
        stmt = stmt.where(WorkOrder.completed_at.is_not(None))
    elif completed is False:
        stmt = stmt.where(WorkOrder.completed_at.is_(None))
    rows = (await db.scalars(stmt)).all()

    # Batch-load project + customer info for the table view.
    project_ids = {w.project_id for w in rows if w.project_id}
    projects: dict[UUID, Project] = {}
    if project_ids:
        for p in (await db.scalars(
            select(Project).where(Project.id.in_(project_ids))
        )).all():
            projects[p.id] = p
    _show_customer = _can_see_project_customer(_user)
    customer_ids = {p.customer_id for p in projects.values() if p.customer_id}
    customers: dict[UUID, Customer] = {}
    if customer_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        )).all():
            customers[c.id] = c

    out = []
    for w in rows:
        proj = projects.get(w.project_id) if w.project_id else None
        cust = customers.get(proj.customer_id) if proj else None
        out.append({
            "id": str(w.id),
            "code": w.code,
            "stage": w.stage,
            "notes": w.notes,
            "started_at": w.started_at,
            "completed_at": w.completed_at,
            "created_at": w.created_at,
            "project_id": str(w.project_id) if w.project_id else None,
            "project_code": proj.code if proj else None,
            "project_status": proj.status if proj else None,
            "project_target_delivery": proj.target_delivery if proj else None,
            # Purchasing stays customer-blind here like everywhere else —
            # this list was the one surface still leaking the company name.
            "customer_id": str(cust.id) if (cust and _show_customer) else None,
            "customer_name": (cust.company_name if (cust and _show_customer)
                              else (f"Order {proj.code}" if proj else None)),
        })
    return out


class DeliveryIn(BaseModel):
    number: str
    split_index: int = 1
    courier: str | None = None
    tracking_no: str | None = None


@router.post("/projects/{project_id}/delivery", status_code=201)
async def create_delivery(project_id: UUID, payload: DeliveryIn,
                          db: AsyncSession = Depends(get_db),
                          _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    d = DeliveryOrder(
        project_id=project_id, number=payload.number,
        split_index=payload.split_index, courier=payload.courier,
        tracking_no=payload.tracking_no, status="pending",
    )
    db.add(d)
    await db.flush()
    return {"id": str(d.id), "number": d.number}


@router.patch("/deliveries/{do_id}/delivered")
async def mark_delivered(do_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Mark a DO delivered. Requires director verification of the shipping
    proof first — director's own click verifies + marks in one step."""
    d = await db.get(DeliveryOrder, do_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    is_director = Role(user.role) == Role.DIRECTOR
    if not d.verified_at and not is_director:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Director must verify the shipping proof first.",
        )
    if not d.verified_at and is_director:
        d.verified_by = user.id
        d.verified_at = datetime.now(UTC)
    d.status = "delivered"
    d.delivered_at = datetime.now(UTC)
    await db.flush()

    # When every delivery order on the project is delivered, nudge the project
    # forward one stage (advance is forward-only to the milestone the event represents, so a project at
    # 'invoiced' → 'delivered', while 'qc' or earlier would walk one step only).
    if d.project_id:
        remaining = await db.scalar(
            select(func.count(DeliveryOrder.id)).where(
                DeliveryOrder.project_id == d.project_id,
                DeliveryOrder.status != "delivered",
            )
        ) or 0
        if remaining == 0:
            project = await db.get(Project, d.project_id)
            if project:
                advance_project_status(project, "delivered")
    return {"ok": True, "delivered_at": d.delivered_at,
            "verified_at": d.verified_at}


@router.post("/deliveries/{do_id}/proof")
async def upload_delivery_proof(
    do_id: UUID,
    courier: str | None = Form(None),
    tracking_no: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Admin uploads the shipping/delivery proof (POD, courier slip, …) so the
    director can verify it. Optional courier + tracking number fields update
    the DO at the same time. Clears any prior verification so the director
    has to re-confirm the new proof."""
    if Role(user.role) not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    d = await db.get(DeliveryOrder, do_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery order not found")

    await _save_attachment(db, file=file, owner_type="delivery_order",
                           owner_id=d.id, user=user, label="proof")
    if courier is not None:
        d.courier = courier or None
    if tracking_no is not None:
        d.tracking_no = tracking_no or None
    # New proof → invalidate any prior verification.
    d.verified_by = None
    d.verified_at = None
    await db.flush()
    return {"ok": True, "id": str(d.id),
            "courier": d.courier, "tracking_no": d.tracking_no}


@router.post("/deliveries/{do_id}/verify")
async def verify_delivery(
    do_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Director verifies the uploaded shipping proof. After this, anyone can
    Mark delivered (or the director can do both in one click)."""
    if Role(user.role) not in {Role.DIRECTOR, Role.MANAGER, Role.ADMIN}:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the director (or management) can verify.")
    d = await db.get(DeliveryOrder, do_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    d.verified_by = user.id
    d.verified_at = datetime.now(UTC)
    await db.flush()
    return {"ok": True, "verified_at": d.verified_at}


@router.get("/projects/{project_id}/timeline")
async def project_timeline(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    # Stages in chronological order; "completed" if act date is set.
    stages = [
        {
            "key": "ship_from_origin",
            "label": "Shipped from origin" + (f" ({p.origin_location})" if p.origin_location else ""),
            "est": p.est_ship_from_origin,
            "actual": p.act_ship_from_origin,
        },
        {
            "key": "arrive_our_warehouse",
            "label": "Arrived at our warehouse",
            "est": p.est_arrive_our_warehouse,
            "actual": p.act_arrive_our_warehouse,
        },
        {
            "key": "arrive_customer",
            "label": "Arrived at customer's warehouse",
            "est": p.est_arrive_customer,
            "actual": p.act_arrive_customer,
        },
    ]
    # Mark the current stage as the first one without an actual date
    current_idx = next((i for i, s in enumerate(stages) if not s["actual"]), len(stages))
    for i, s in enumerate(stages):
        s["status"] = (
            "completed" if s["actual"]
            else "current" if i == current_idx
            else "future"
        )
    return {
        "project_id": str(p.id),
        "code": p.code,
        "is_import": bool(p.is_import),
        "origin_location": p.origin_location,
        "target_delivery": p.target_delivery,
        "actual_delivery": p.actual_delivery,
        "stages": stages,
    }
