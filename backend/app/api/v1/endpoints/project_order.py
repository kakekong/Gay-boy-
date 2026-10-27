"""A project's order — its price-request lines — arranged and amended.

The customer's sales rep and the director are the ones who arrange a won
job's order: the sequence its lines are listed in, what a line is (its item
name, quantity, unit and spec) and its selling price, and a line added to
it. The director's change applies at once; the
rep's goes to the director as one proposal (revised, not stacked, if they
change it again while it waits), and applies only when approved.

An added line is usually the same item again — another of a part already on
the order — so a line with the same name as an existing one takes its cost
from it. A genuinely new item has no cost yet; the director sees that when
deciding, and can enter one.

Only the project's order changes (the price-request lines it reads, and the
order they are listed in). The customer's PO and the quotation stay as
signed; the deal check flags any difference so a revision can follow.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.crm import Customer
from app.models.operation import Project
from app.models.user import User

router = APIRouter()

TARGET = "project_order"


class OrderLineIn(BaseModel):
    # An existing line is named by its number; a new one has none.
    line_no: int | None = None
    description: str | None = None
    qty: float | None = None
    uom: str | None = None
    spec: str | None = None
    sell_price: float | None = None
    # Director only — what a new item costs, when it is known.
    cost_price: float | None = None


class OrderChangeIn(BaseModel):
    # Every line, in the order to list them.
    lines: list[OrderLineIn]
    note: str | None = None


def _key(name: str | None) -> str:
    return " ".join((name or "").lower().split())


async def _load(db: AsyncSession, project_id: UUID):
    from app.models.price_request import PriceRequest

    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    pr = await db.get(PriceRequest, p.price_request_id) if p.price_request_id else None
    if not pr:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project has no order lines")
    return p, pr


async def _may_arrange(db: AsyncSession, user: User, p: Project) -> bool:
    """The director, or the sales rep in charge of this customer."""
    role = Role(user.role)
    if role == Role.DIRECTOR:
        return True
    if role != Role.SALES:
        return False
    cust = await db.get(Customer, p.customer_id) if p.customer_id else None
    return bool(cust and cust.sales_pic_id == user.id)


def _ordered(pr, p: Project) -> list[dict]:
    """The request's lines in the order the project lists them."""
    items = list(pr.items or [])
    order = [int(x) for x in (p.item_order or []) if str(x).lstrip("-").isdigit()]
    pos = {ln: i for i, ln in enumerate(order)}
    return [it for _, it in sorted(
        enumerate(items), key=lambda ii: (pos.get(ii[1].get("line_no"), len(order)), ii[0]))]


def _plan(pr, p: Project, lines: list[OrderLineIn], *, director: bool) -> dict:
    """Check a proposed order against the request and work out what it does.

    Returns the lines as they would be stored, the order, and a summary a
    person can read — the same whether it is applied now or decided later."""
    current = {it.get("line_no"): it for it in (pr.items or [])}
    named = [ln.line_no for ln in lines if ln.line_no is not None]
    if sorted(named) != sorted(current):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Every line already on the order has to stay, once — lines can be "
            "moved, edited or added, not removed. Refresh and try again.")
    by_name = {}
    for it in pr.items or []:
        by_name.setdefault(_key(it.get("description")), it)

    next_no = max([int(n) for n in current] or [0]) + 1
    items: dict[int, dict] = {n: dict(it) for n, it in current.items()}
    order: list[int] = []
    summary: list[str] = []
    for ln in lines:
        if ln.line_no is not None:
            it = items[ln.line_no]
            name = it.get("description")
            if ln.description is not None:
                desc = ln.description.strip()
                if not desc:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                        f"Line “{name}” needs a description")
                if desc != (name or ""):
                    it["description"] = desc
                    summary.append(f"Rename “{name}” → “{desc}”")
            if ln.qty is not None:
                if ln.qty <= 0:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                        f"“{it.get('description')}” needs a quantity above zero")
                old = it.get("qty")
                if old is None or abs(float(old) - float(ln.qty)) > 1e-9:
                    it["qty"] = float(ln.qty)
                    summary.append(f"Quantity of “{it.get('description')}”: "
                                   f"{_num(old)} → {float(ln.qty):g}")
            if ln.uom is not None and ln.uom.strip() and ln.uom.strip() != (it.get("uom") or ""):
                summary.append(f"Unit of “{it.get('description')}”: "
                               f"{it.get('uom') or '—'} → {ln.uom.strip()}")
                it["uom"] = ln.uom.strip()
            if ln.spec is not None and (ln.spec.strip() or None) != (it.get("spec") or None):
                it["spec"] = ln.spec.strip() or None
                summary.append(f"Spec of “{it.get('description')}” changed")
            if ln.sell_price is not None:
                old = it.get("sell_price")
                new = round(float(ln.sell_price), 2)
                if new < 0:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "A price can't be negative")
                if old is None or abs(float(old) - new) >= 0.005:
                    it["sell_price"] = new
                    summary.append(f"Price of “{it.get('description')}”: "
                                   f"{_rp(old)} → {_rp(new)}")
            order.append(ln.line_no)
            continue
        desc = (ln.description or "").strip()
        if not desc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A new line needs a description")
        if not ln.qty or ln.qty <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"“{desc}” needs a quantity above zero")
        if ln.sell_price is None or ln.sell_price < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"“{desc}” needs a selling price")
        same = by_name.get(_key(desc))
        new = {
            "line_no": next_no, "description": desc, "qty": float(ln.qty),
            "uom": (ln.uom or (same or {}).get("uom") or "pcs"),
            "spec": (ln.spec if ln.spec is not None else (same or {}).get("spec")),
            "sell_price": round(float(ln.sell_price), 2), "sell_basis": "unit",
        }
        if same:
            # The same part again: it costs what it cost on the line before.
            for k in ("sku", "category", "category_note", "link", "cost_price", "cost_basis"):
                if same.get(k) is not None:
                    new[k] = same.get(k)
            source = f"cost from line {same.get('line_no')}"
        elif director and ln.cost_price is not None:
            new["cost_price"] = round(float(ln.cost_price), 2)
            new["cost_basis"] = "unit"
            source = "cost entered by the director"
        else:
            source = "new item — no cost yet"
        items[next_no] = new
        order.append(next_no)
        summary.append(f"Add “{desc}” × {float(ln.qty):g} at {_rp(new['sell_price'])} ({source})")
        next_no += 1

    before = [it.get("line_no") for it in _ordered(pr, p)]
    if [n for n in order if n in current] != before:
        summary.insert(0, "Lines put in a new order")
    return {"items": [items[n] for n in sorted(items)], "order": order, "summary": summary}


def _num(v) -> str:
    return "—" if v is None else f"{float(v):g}"


def _rp(v) -> str:
    if v is None:
        return "—"
    return "Rp " + f"{float(v):,.0f}".replace(",", ".")


def apply_order(p: Project, pr, plan: dict) -> None:
    """Write a planned order onto the request and the project."""
    pr.items = [dict(it) for it in plan["items"]]      # a new list: JSONB change
    p.item_order = list(plan["order"])


async def pending_for(db: AsyncSession, project_id: UUID) -> ApprovalRequest | None:
    return await db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.target_type == TARGET,
        ApprovalRequest.target_id == project_id,
        ApprovalRequest.status == ApprovalStatus.PENDING.value))


@router.get("/projects/{project_id}/order-change")
async def get_order_change(project_id: UUID, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """The rep's proposal waiting for the director, if there is one — and
    whether this user may arrange the order at all."""
    p, _pr = await _load(db, project_id)
    if Role(user.role) == Role.SALES and not await _may_arrange(db, user, p):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    req = await pending_for(db, project_id)
    out = None
    if req:
        who = await db.get(User, req.requested_by) if req.requested_by else None
        out = {"id": str(req.id), "requested_by": who.full_name if who else None,
               "requested_at": req.created_at, "summary": (req.payload or {}).get("summary", []),
               "note": (req.payload or {}).get("note"),
               "lines": (req.payload or {}).get("lines", [])}
    return {"may_arrange": await _may_arrange(db, user, p),
            "is_director": Role(user.role) == Role.DIRECTOR, "pending": out}


@router.post("/projects/{project_id}/order-change")
async def change_order(project_id: UUID, payload: OrderChangeIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Arrange the order: move lines, edit or reprice them, add lines. The director's
    change applies now; the rep's goes to the director."""
    p, pr = await _load(db, project_id)
    if not await _may_arrange(db, user, p):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "The order is arranged by the customer's sales rep and the director.")
    director = Role(user.role) == Role.DIRECTOR
    plan = _plan(pr, p, payload.lines, director=director)
    if not plan["summary"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing changed")
    note = (payload.note or "").strip() or None

    if director:
        before = {"items": pr.items, "item_order": p.item_order}
        apply_order(p, pr, plan)
        # A proposal waiting on this order is answered by this: what the rep
        # asked for may be in it or not, but the order is decided now.
        req = await pending_for(db, project_id)
        if req:
            req.status = ApprovalStatus.REJECTED.value
            req.decided_by = user.id
            req.decided_at = datetime.now(UTC)
            req.decision_notes = "The director arranged the order on the project page"
        await audit_record(db, actor=user, action="order_change", entity="project",
                           entity_id=p.id, before=before,
                           after={"summary": plan["summary"], "item_order": p.item_order})
        await db.flush()
        return {"status": "applied", "summary": plan["summary"]}

    stored = {"lines": [ln.model_dump() for ln in payload.lines],
              "summary": plan["summary"], "note": note, "project_code": p.code}
    reason = (f"Change the order on {p.code}: " + "; ".join(plan["summary"])
              + (f" — {note}" if note else ""))
    req = await pending_for(db, project_id)
    if req:
        # One proposal per order: changing it again revises the one waiting.
        req.payload = stored
        req.reason = reason
        req.requested_by = user.id
    else:
        req = await request_approval(
            db, target_type=TARGET, target_id=p.id, requested_by=user.id,
            required_role=Role.DIRECTOR, reason=reason, payload=stored)
    await db.flush()
    return {"status": "pending_approval", "summary": plan["summary"],
            "message": "Sent to the director to approve."}


async def apply_approved(db: AsyncSession, req: ApprovalRequest, approve: bool) -> dict:
    """The director's answer from the Approvals inbox (core.approval)."""
    if not approve:
        return {"applied": False}
    p = await db.get(Project, req.target_id)
    if p is None:
        return {"skipped": "the project is gone — decision recorded only"}
    _p, pr = await _load(db, p.id)
    lines = [OrderLineIn(**ln) for ln in (req.payload or {}).get("lines", [])]
    try:
        plan = _plan(pr, p, lines, director=False)
    except HTTPException as e:
        # The order moved underneath the proposal (a line added since, say).
        return {"skipped": f"the order changed since this was asked: {e.detail}"}
    apply_order(p, pr, plan)
    return {"applied": True, "summary": plan["summary"]}
