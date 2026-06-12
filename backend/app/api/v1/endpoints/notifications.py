"""Live notifications aggregator.

Pulls live signals from across the system:
 - Approvals waiting (manager/director only)
 - At-risk deals owned by the caller
 - Overdue / due-soon invoices
 - Drawings awaiting customer approval
 - Chat unread count

Computed at request time — no separate notifications table.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.core.stage_playbook import playbook_for
from app.core.stage_tasks import parse_stage_task_kind
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.chat import ChatChannelMember, ChatMessage
from app.models.crm import Activity, Customer, Reminder
from app.models.finance import Invoice
from app.models.operation import Drawing
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    now = datetime.now(UTC)
    today = date.today()
    items: list[dict] = []
    role = Role(me.role)

    # 1. Approvals waiting (manager/director only)
    if role in (Role.MANAGER, Role.DIRECTOR):
        appr_stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
            .order_by(ApprovalRequest.created_at.desc())
        )
        if role == Role.MANAGER:
            appr_stmt = appr_stmt.where(ApprovalRequest.required_role == Role.MANAGER.value)
        for a in (await db.scalars(appr_stmt)).all():
            items.append({
                "id": f"approval:{a.id}",
                "kind": "approval",
                "severity": "high" if a.required_role == Role.DIRECTOR.value else "medium",
                "title": f"Approval needed: {a.target_type}",
                "body": a.reason or "",
                "link": "/approvals",
                "at": a.created_at,
            })

    # 1b. Decision on YOUR request (any role) — surface the outcome + the
    # reason the approver gave so the requester learns why.
    decided_stmt = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.requested_by == me.id,
            ApprovalRequest.status.in_([
                ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value,
            ]),
            ApprovalRequest.decided_at.is_not(None),
            ApprovalRequest.decided_at >= now - timedelta(days=7),
        )
        .order_by(ApprovalRequest.decided_at.desc())
        .limit(20)
    )
    for a in (await db.scalars(decided_stmt)).all():
        approved = a.status == ApprovalStatus.APPROVED.value
        verb = "approved" if approved else "rejected"
        reason = (a.decision_notes or "").strip()
        items.append({
            "id": f"approval-decided:{a.id}",
            "kind": "approval_decided",
            "severity": "low" if approved else "medium",
            "title": f"Your {a.target_type} request was {verb}",
            "body": (f"Reason: {reason}" if reason
                     else ("Approved." if approved
                           else "Rejected (no reason given).")),
            "link": "/approvals" if role in (Role.MANAGER, Role.DIRECTOR) else "/",
            "at": a.decided_at,
        })

    # 2. At-risk open quotations owned by the caller (or all if manager+)
    seven_days_ago = now - timedelta(days=7)
    q_stmt = (
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.status.in_(["sent", "pending_approval", "approved"]))
        .order_by(Quotation.created_at.desc())
        .limit(50)
    )
    if role == Role.SALES:
        q_stmt = q_stmt.where(Quotation.sales_pic_id == me.id)
    for q, c in (await db.execute(q_stmt)).all():
        last_act = await db.scalar(
            select(func.max(Activity.occurred_at))
            .where(Activity.customer_id == q.customer_id)
        )
        idle_since = last_act or q.created_at
        if idle_since < seven_days_ago:
            days_idle = (now - idle_since).days
            items.append({
                "id": f"deal-risk:{q.id}",
                "kind": "at_risk_deal",
                "severity": "high" if days_idle >= 14 else "medium",
                "title": f"At-risk deal: {c.company_name}",
                "body": f"{q.number} idle for {days_idle} days",
                "link": f"/quotations/{q.id}",
                "at": idle_since,
            })

    # 3. Overdue / due-soon invoices
    soon = today + timedelta(days=3)
    inv_stmt = (
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.status.in_(["issued", "partial", "overdue"]),
            Invoice.due_date.is_not(None),
            Invoice.due_date <= soon,
        )
        .order_by(Invoice.due_date.asc())
    )
    if role == Role.SALES:
        inv_stmt = inv_stmt.where(Customer.sales_pic_id == me.id)
    for inv, c in (await db.execute(inv_stmt)).all():
        overdue = inv.due_date < today
        items.append({
            "id": f"invoice:{inv.id}",
            "kind": "payment_due",
            "severity": "high" if overdue else "medium",
            "title": ("Overdue" if overdue else "Due soon") + f": {inv.number}",
            "body": f"{c.company_name} · Rp " + f"{float(inv.total or 0):,.0f}".replace(",", "."),
            "link": "/finance",
            "at": datetime.combine(inv.due_date, datetime.min.time()).replace(tzinfo=UTC),
        })

    # 3b. Overdue / due-soon stage checklist tasks owned by the caller
    soon_dt = now + timedelta(days=2)
    stage_stmt = (
        select(Reminder, Customer)
        .join(Customer, Reminder.customer_id == Customer.id)
        .where(
            Reminder.status == "pending",
            Reminder.kind.like("stage:%"),
            Reminder.due_at <= soon_dt,
        )
        .order_by(Reminder.due_at.asc())
        .limit(50)
    )
    if role == Role.SALES:
        stage_stmt = stage_stmt.where(Reminder.user_id == me.id)
    for rem, cust in (await db.execute(stage_stmt)).all():
        parsed = parse_stage_task_kind(rem.kind)
        if not parsed:
            continue
        stg, task_key = parsed
        playbook_item = next(
            (t for t in playbook_for(stg) if t["key"] == task_key), None
        )
        title = playbook_item["title"] if playbook_item else rem.message or task_key
        overdue = rem.due_at <= now
        items.append({
            "id": f"stage-task:{rem.id}",
            "kind": "stage_task",
            "severity": "high" if overdue else "medium",
            "title": ("Overdue" if overdue else "Due soon")
                     + f": {title} ({stg.replace('_', ' ')})",
            "body": f"{cust.company_name}",
            "link": f"/customers/{cust.id}",
            "at": rem.due_at,
        })

    # 4. Drawings awaiting customer approval
    d_stmt = (
        select(Drawing)
        .where(Drawing.status == "submitted")
        .order_by(Drawing.created_at.desc())
        .limit(20)
    )
    for d in (await db.scalars(d_stmt)).all():
        items.append({
            "id": f"drawing:{d.id}",
            "kind": "drawing_pending",
            "severity": "low",
            "title": f"Drawing awaiting customer (rev {d.revision})",
            "body": "Submitted, waiting on customer approval",
            "link": "/projects",
            "at": d.created_at,
        })

    # 5. Chat unread (single roll-up row if any)
    members = (await db.scalars(
        select(ChatChannelMember).where(ChatChannelMember.user_id == me.id)
    )).all()
    total_unread = 0
    for mem in members:
        stmt = (
            select(func.count(ChatMessage.id))
            .where(
                ChatMessage.channel_id == mem.channel_id,
                ChatMessage.user_id != me.id,
                ChatMessage.deleted_at.is_(None),
            )
        )
        if mem.last_read_at:
            stmt = stmt.where(ChatMessage.created_at > mem.last_read_at)
        total_unread += await db.scalar(stmt) or 0
    if total_unread:
        items.append({
            "id": "chat-unread",
            "kind": "chat",
            "severity": "low",
            "title": f"{total_unread} unread message" + ("" if total_unread == 1 else "s"),
            "body": "Click to open chat",
            "link": "/chat",
            "at": now,
        })

    # Order: high → medium → low; within tier, newest first
    SEVERITY = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (SEVERITY.get(x["severity"], 9), -(x["at"].timestamp() if x.get("at") else 0)))
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "high": sum(1 for i in items if i["severity"] == "high"),
            "medium": sum(1 for i in items if i["severity"] == "medium"),
            "low": sum(1 for i in items if i["severity"] == "low"),
        },
    }
