"""Live notifications aggregator.

Pulls live signals from across the system:
 - Approvals waiting (manager/director only)
 - At-risk deals owned by the caller
 - Overdue / due-soon invoices
 - Drawings awaiting customer approval
 - Chat unread count

Computed at request time — no separate notifications table.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.core.stage_playbook import playbook_for
from app.core.stage_tasks import parse_stage_task_kind
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.attendance import Attendance
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage
from app.models.crm import Activity, Customer, Reminder
from app.models.finance import Invoice, OUTSTANDING_INVOICE_STATUSES
from app.models.operation import Drawing, Project
from app.models.quotation import Quotation
from app.models.user import User

# Office timezone for "late" attendance — the business runs on WIB (UTC+7).
_WIB = timezone(timedelta(hours=7))
_LATE_CUTOFF = time(9, 15)
# Before this, "nobody has clocked in" is just a description of the morning.
# Raising it at 06:00 trains people to ignore the badge, so the attendance
# alerts stay silent until the office is actually expected to be working.
_ATTENDANCE_ALERT_FROM = time(8, 30)

# Where an approval's *subject* lives. An alert about a quotation belongs in
# Quotations, not on the dashboard — the sidebar badges are derived from these
# links (longest matching nav path wins), so the link is what decides which
# section lights up. `inventory_item` carries a synthetic target id, and
# `cross_dept_chat` a channel, so both point at their list rather than a row.
_TARGET_LINK = {
    "quotation":              "/quotations/{id}",
    "quotation_edit":         "/quotations/{id}",
    "quotation_won":          "/quotations/{id}",
    "price_request_revision": "/price-requests?open={id}",
    "customer_po":            "/customer-pos/{id}",
    "supplier_po":            "/purchase-orders",
    "purchase_request":       "/purchasing",
    "project":                "/projects/{id}",
    "customer":               "/customers/{id}",
    "followup":               "/customers/{id}",
    "inventory_item":         "/inventory",
    "cross_dept_chat":        "/chat",
}


def _target_link(target_type: str, target_id) -> str | None:
    tpl = _TARGET_LINK.get(target_type or "")
    return tpl.format(id=target_id) if tpl else None


_DISCUSSION_LINK = {
    "price_request": "/price-requests?open={id}",
    "quotation": "/quotations/{id}",
    "customer_po": "/customer-pos/{id}",
    "supplier_po": "/purchase-orders",
    "project": "/projects/{id}",
    "invoice": "/finance",
}

# What a pending request is, in the words people use for it. The bell used to
# print the raw target_type — "Approval needed: delivery_order" — which reads
# like a database column rather than a document somebody is waiting on.
_APPROVAL_LABEL = {
    "delivery_order": "delivery order",
    "supplier_po": "purchase order",
    "purchase_request": "purchase request",
    "customer_po": "customer PO",
    "quotation_won": "mark won",
    "quotation_edit": "quotation edit",
    "price_request_revision": "price revision",
    "cross_dept_chat": "cross-department chat",
    "inventory_item": "new inventory items",
}

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


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
                "title": f"Approval needed: {_APPROVAL_LABEL.get(a.target_type, a.target_type.replace('_', ' '))}",
                "body": a.reason or "",
                "link": "/approvals",
                "at": a.created_at,
            })

    # 1a. Down-payment PO handoffs. These live outside the generic
    # approvals queue: finance owns the pending_finance leg, the customer's
    # sales rep owns the deposit confirmation. Without these two sections
    # both DP handoffs were silent.
    from app.models.customer_po import CustomerPO
    if role == Role.FINANCE:
        dp_wait_fin = (await db.execute(
            select(CustomerPO, Customer)
            .join(Customer, CustomerPO.customer_id == Customer.id)
            .where(
                CustomerPO.is_downpayment.is_(True),
                CustomerPO.status == "pending_finance",
            )
            .order_by(CustomerPO.created_at.asc())
            .limit(20)
        )).all()
        for po, c in dp_wait_fin:
            items.append({
                "id": f"dp-finance:{po.id}",
                "kind": "approval",
                "severity": "high",
                "title": f"DP PO awaiting finance: {po.number}",
                "body": f"{c.company_name} · approve, then issue the DP invoice",
                "link": f"/customer-pos/{po.id}",
                "at": po.created_at,
            })
    # Whether the deposit arrived is a fact about the bank account, so this
    # sits with finance rather than with the rep whose job it starts.
    if role in (Role.FINANCE, Role.DIRECTOR):
        dp_wait_pay_stmt = (
            select(CustomerPO, Customer)
            .join(Customer, CustomerPO.customer_id == Customer.id)
            .where(
                CustomerPO.is_downpayment.is_(True),
                CustomerPO.status == "pending_payment_confirm",
            )
            .order_by(CustomerPO.dp_finance_approved_at.asc().nullslast())
            .limit(20)
        )
        for po, c in (await db.execute(dp_wait_pay_stmt)).all():
            items.append({
                "id": f"dp-payment:{po.id}",
                "kind": "approval",
                "severity": "high",
                "title": f"Deposit received? {po.number}",
                "body": f"{c.company_name} · DP invoiced — confirm the money "
                        "landed to start the project, or reject if it never "
                        "came",
                "link": f"/customer-pos/{po.id}",
                "at": po.dp_finance_approved_at or po.created_at,
            })

    # 1b. Decision on YOUR request (any role) — surface the outcome + the
    # reason the approver gave so the requester learns why.
    #
    # The two outcomes do not deserve the same shelf life. A rejection is
    # work — you have to fix the thing and resubmit — so it keeps the full
    # week. An approval is news: it unblocks you, you read it once, and
    # that is the end of it. Left at a week they stacked up, because every
    # edit to a supplier PO needs its own approval: a purchaser who revised
    # a few POs came back to a pile of "approved" notices, none of which
    # asked anything of them. Two days is long enough for anyone to have
    # opened the app since.
    decided_stmt = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.requested_by == me.id,
            ApprovalRequest.decided_at.is_not(None),
            (
                (ApprovalRequest.status == ApprovalStatus.REJECTED.value)
                & (ApprovalRequest.decided_at >= now - timedelta(days=7))
            ) | (
                (ApprovalRequest.status == ApprovalStatus.APPROVED.value)
                & (ApprovalRequest.decided_at >= now - timedelta(days=2))
            ),
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
            # Straight to the document it was about. This used to send
            # everyone below manager to the dashboard, so "your quotation edit
            # was approved" arrived with nothing to click and nothing lit up
            # in the sidebar.
            "link": (_target_link(a.target_type, a.target_id)
                     or ("/approvals" if role in (Role.MANAGER, Role.DIRECTOR) else "/")),
            "at": a.decided_at,
        })

    # 1b2. An account was handed to you (or taken off you). The director
    # makes this change from their own screen, so without a row here the
    # first a rep knows of it is a customer appearing in — or vanishing
    # from — their list.
    handovers = (await db.execute(
        select(Activity, Customer)
        .join(Customer, Activity.customer_id == Customer.id)
        .where(
            Activity.type == "assignment",
            Activity.occurred_at >= now - timedelta(days=14),
            Customer.is_deleted.is_(False),
        )
        .order_by(Activity.occurred_at.desc())
        .limit(40)
    )).all()
    for a, c in handovers:
        meta = a.meta or {}
        took_it = meta.get("to_id") == str(me.id)
        lost_it = meta.get("from_id") == str(me.id)
        if not (took_it or lost_it):
            continue
        carried = meta.get("carried") or {}
        moved_bits = [
            f"{carried.get('price_requests') or 0} price request"
            + ("" if carried.get("price_requests") == 1 else "s"),
            f"{carried.get('quotations') or 0} quotation"
            + ("" if carried.get("quotations") == 1 else "s"),
        ]
        note = (meta.get("note") or "").strip()
        items.append({
            "id": f"handover:{a.id}",
            "kind": "handover",
            "severity": "medium" if took_it else "low",
            "title": (f"You're now in charge of {c.company_name}" if took_it
                      else f"{c.company_name} moved to {meta.get('to_name') or 'nobody'}"),
            "body": ((f"Handed over by {meta.get('by_name') or 'a director'}"
                      + (f" · {note}" if note else "")
                      + " · came with " + " and ".join(moved_bits)) if took_it
                     else (f"Reassigned by {meta.get('by_name') or 'a director'}"
                           + (f" · {note}" if note else ""))),
            "link": f"/customers/{c.id}" if took_it else "/customers",
            "at": a.occurred_at,
        })

    # 1c. Price requests. They run their own pipeline (pending_purchasing →
    # pending_director → approved/rejected) OUTSIDE the approvals queue, so
    # without this section every handoff was silent. Routed to whoever
    # holds the ball: purchasing costs it, the director prices it, and the
    # requesting sales rep hears the outcome.
    from app.models.price_request import PriceRequest
    if role in (Role.PURCHASING, Role.MANAGER):
        pr_cost = (await db.execute(
            select(PriceRequest, Customer)
            .join(Customer, PriceRequest.customer_id == Customer.id)
            .where(
                PriceRequest.is_deleted.is_(False),
                PriceRequest.status == "pending_purchasing",
            )
            .order_by(PriceRequest.updated_at.asc())
            .limit(20)
        )).all()
        for pr, c in pr_cost:
            items.append({
                "id": f"pr-cost:{pr.id}",
                "kind": "price_request",
                "severity": "high" if role == Role.PURCHASING else "medium",
                "title": f"Price request awaiting costing: {pr.number}",
                # Purchasing stays customer-blind — no company name.
                "body": ("Fill the procurement cost per line"
                         if role == Role.PURCHASING else c.company_name),
                "link": f"/price-requests?open={pr.id}",
                "at": pr.updated_at or pr.created_at,
            })
    # 1c2. A new job to source. A project appears the moment a deal is won,
    # and until now nothing told purchasing — they found out when somebody
    # mentioned it, or when they happened to scroll the Projects list. This
    # is the one signal that starts their half of the work.
    #
    # It clears itself: raising a purchase request or a supplier PO against
    # the project is purchasing picking it up, and the row goes. A job that
    # needs nothing bought (stock already on the shelf) ages out after a
    # month rather than nagging forever. And it stays customer-blind — the
    # code and the price request number, never the company.
    if role is Role.PURCHASING:
        from app.models.purchasing import PurchaseRequest as _PR, SupplierPO as _SPO
        from app.models.price_request import PriceRequest as _PriceReq
        untouched = (await db.scalars(
            select(Project).where(
                Project.is_deleted.is_(False),
                Project.status.not_in(("delivered", "paid", "closed")),
                Project.created_at >= now - timedelta(days=30),
                ~select(_SPO.id).where(_SPO.project_id == Project.id).exists(),
                ~select(_PR.id).where(_PR.project_id == Project.id).exists(),
            ).order_by(Project.created_at.desc()).limit(20)
        )).all()
        pr_numbers: dict = {}
        _pr_ids = {p.price_request_id for p in untouched if p.price_request_id}
        if _pr_ids:
            for _pr in (await db.scalars(
                select(_PriceReq).where(_PriceReq.id.in_(_pr_ids))
            )).all():
                pr_numbers[_pr.id] = _pr.number
        for pj in untouched:
            src = pr_numbers.get(pj.price_request_id)
            items.append({
                "id": f"project-new:{pj.id}",
                "kind": "project_new",
                "severity": "high",
                "title": f"New job to source: {pj.code}",
                "body": ("Nothing ordered against it yet"
                         + (f" · from price request {src}" if src else "")),
                "link": f"/projects/{pj.id}",
                "at": pj.created_at,
            })

    if role in (Role.MANAGER, Role.DIRECTOR):
        pr_price = (await db.execute(
            select(PriceRequest, Customer)
            .join(Customer, PriceRequest.customer_id == Customer.id)
            .where(
                PriceRequest.is_deleted.is_(False),
                PriceRequest.status == "pending_director",
            )
            .order_by(PriceRequest.priced_at.asc().nullslast())
            .limit(20)
        )).all()
        for pr, c in pr_price:
            items.append({
                "id": f"pr-price:{pr.id}",
                "kind": "price_request",
                "severity": "high" if role == Role.DIRECTOR else "medium",
                "title": f"Price request awaiting sell price: {pr.number}",
                "body": f"{c.company_name} · costed by purchasing — set the "
                        "sell price and approve",
                "link": f"/price-requests?open={pr.id}",
                "at": pr.priced_at or pr.updated_at or pr.created_at,
            })
    # Outcome goes to the REQUESTER, whatever their role.
    pr_done_stmt = (
        select(PriceRequest, Customer)
        .join(Customer, PriceRequest.customer_id == Customer.id)
        .where(
            PriceRequest.is_deleted.is_(False),
            PriceRequest.status.in_(["approved", "rejected"]),
            PriceRequest.updated_at >= now - timedelta(days=7),
            (PriceRequest.sales_pic_id == me.id)
            | (PriceRequest.created_by == me.id)
            | (Customer.sales_pic_id == me.id),
            # ...but not to the person who made the decision
            (PriceRequest.approved_by.is_(None))
            | (PriceRequest.approved_by != me.id),
        )
        .order_by(PriceRequest.updated_at.desc())
        .limit(20)
    )
    for pr, c in (await db.execute(pr_done_stmt)).all():
        ok = pr.status == "approved"
        reason = (pr.decision_notes or "").strip()
        items.append({
            "id": f"pr-decided:{pr.id}:{pr.status}",
            "kind": "price_request_decided",
            # Both outcomes hand the rep something to do — quote it, or
            # revise and resubmit — so neither is the silent FYI tier.
            "severity": "medium",
            "title": f"Price request {pr.number} "
                     + ("approved — quote it" if ok else "sent back"),
            "body": (f"{c.company_name}"
                     + (f" · {reason}" if reason else
                        ("" if ok else " · revise and resubmit"))),
            "link": f"/price-requests?open={pr.id}",
            "at": pr.approved_at or pr.updated_at,
        })

    # 2. At-risk open quotations — a sales concern. Sales sees their own
    # deals, the manager sees all for day-to-day oversight. The director
    # gets a single roll-up (see 7) instead of one row per stalled deal.
    if role in (Role.SALES, Role.MANAGER):
        seven_days_ago = now - timedelta(days=7)
        q_stmt = (
            select(Quotation, Customer)
            .join(Customer, Quotation.customer_id == Customer.id)
            .where(Quotation.status.in_(["sent", "pending_approval", "approved"]))
            .order_by(Quotation.created_at.desc())
            .limit(50)
        )
        if role == Role.SALES:
            q_stmt = q_stmt.where(
                (Quotation.sales_pic_id == me.id)
                | (Customer.sales_pic_id == me.id))
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

    # 3. Overdue / due-soon invoices — collections is finance's job;
    # sales chases their own customers; the manager oversees. Ops roles
    # (admin/purchasing/hr) can't do anything about an unpaid invoice, so
    # it never reaches them; the director gets the roll-up (see 7).
    if role in (Role.FINANCE, Role.SALES, Role.MANAGER):
        soon = today + timedelta(days=3)
        inv_stmt = (
            select(Invoice, Customer)
            .join(Customer, Invoice.customer_id == Customer.id)
            .where(
                Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES),
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
                # Sales can't open /finance — send them to the customer
                # instead, where the invoice context lives for them.
                "link": f"/customers/{c.id}" if role == Role.SALES else "/finance",
                "at": datetime.combine(inv.due_date, datetime.min.time()).replace(tzinfo=UTC),
            })

    # 3b. Overdue / due-soon stage checklist tasks — routed by who DOES the
    # work, not broadcast to everyone. Each playbook task declares its
    # owning roles ("Issue invoice" → finance, "Raise purchase request" →
    # purchasing, "Schedule delivery" → admin, deal chores → sales).
    # Sales additionally only sees tasks for their own customers; the
    # manager sees everything for oversight. HR never gets these, and the
    # director gets the roll-up (see 7) instead of one row per chore.
    if role in (Role.SALES, Role.FINANCE, Role.PURCHASING, Role.ADMIN,
                Role.MANAGER):
        soon_dt = now + timedelta(days=2)
        stage_stmt = (
            select(Reminder, Customer)
            .join(Customer, Reminder.customer_id == Customer.id)
            .where(
                Reminder.status == "pending",
                Reminder.kind.like("stage:%"),
                # Dateless stage tasks are checklist-only — they never
                # notify until someone explicitly sets a due date.
                Reminder.due_at.is_not(None),
                Reminder.due_at <= soon_dt,
                # A closed deal's leftovers aren't actionable.
                Customer.stage.not_in(("closed_won", "closed_lost")),
                Customer.is_deleted.is_(False),
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
            task_owner_roles = set(
                (playbook_item.get("roles") if playbook_item else None) or ["sales"]
            )
            if role != Role.MANAGER and role.value not in task_owner_roles:
                continue
            title = playbook_item["title"] if playbook_item else rem.message or task_key
            overdue = rem.due_at <= now
            # Land each role on a page it can actually open — and keep
            # purchasing customer-blind (no company name, no customer link).
            if role == Role.PURCHASING:
                body = "Open your purchasing queue"
                link = "/price-requests"
            elif role == Role.FINANCE:
                body = cust.company_name
                link = "/finance"
            elif role == Role.ADMIN:
                body = cust.company_name
                link = "/projects"
            else:
                body = cust.company_name
                link = f"/customers/{cust.id}"
            items.append({
                "id": f"stage-task:{rem.id}",
                "kind": "stage_task",
                "severity": "high" if overdue else "medium",
                "title": ("Overdue" if overdue else "Due soon")
                         + f": {title} ({stg.replace('_', ' ')})",
                "body": body,
                "link": link,
                "at": rem.due_at,
            })

    # 4. Drawings awaiting sign-off — decided internally by manager /
    # director / admin on the project page, so only those roles get the
    # item (sales/purchasing/finance can't act on it), and the link goes
    # straight to the owning project instead of the bare list.
    if role in (Role.MANAGER, Role.DIRECTOR, Role.ADMIN):
        # A drawing on a deleted or already-finished project is historical —
        # without this join it kept notifying forever with nothing to decide.
        d_stmt = (
            select(Drawing)
            .join(Project, Drawing.project_id == Project.id)
            .where(
                Drawing.status == "submitted",
                Project.is_deleted.is_(False),
                Project.status.not_in(("delivered", "paid", "closed")),
            )
            .order_by(Drawing.created_at.desc())
            .limit(20)
        )
        for d in (await db.scalars(d_stmt)).all():
            items.append({
                "id": f"drawing:{d.id}",
                "kind": "drawing_pending",
                "severity": "medium",
                "title": f"Drawing awaiting approval (rev {d.revision})",
                "body": "Submitted — review it on the project page",
                "link": f"/projects/{d.project_id}",
                "at": d.created_at,
            })

    # 6. People oversight (manager/director): attendance + missed deadlines
    if role in (Role.MANAGER, Role.DIRECTOR):
        # 6a. Attendance today — who's missing or late (weekdays, after 08:30 WIB)
        # The clock is read in WIB, not server time: the box runs on UTC, so
        # `now.time()` there is 08:30 WIB minus seven hours and the gate would
        # open mid-afternoon.
        if today.weekday() < 5 and now.astimezone(_WIB).time() >= _ATTENDANCE_ALERT_FROM:
            internal = (await db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.role.notin_(["customer", "supplier"]),
                )
            )).all()
            today_att = {
                a.user_id: a for a in (await db.scalars(
                    select(Attendance).where(Attendance.date == today)
                )).all()
            }
            missing = 0
            late = 0
            for u in internal:
                a = today_att.get(u.id)
                if a is None or a.clock_in is None:
                    # An explicit leave/sick/holiday/wfh status isn't "missing".
                    if a and a.status in ("leave", "sick", "holiday", "wfh"):
                        continue
                    missing += 1
                elif a.clock_in.astimezone(_WIB).time() > _LATE_CUTOFF:
                    late += 1
            if missing:
                items.append({
                    # Day-scoped, NOT count-scoped. Putting the count in the id
                    # meant the alert returned as a brand-new item every time
                    # one more person clocked in — so dismissing it in the
                    # morning was pointless, and the red badge sat there all
                    # day reappearing. One dismissal now covers today.
                    "id": f"attendance-missing:{today.isoformat()}",
                    "kind": "attendance",
                    "severity": "medium",
                    "title": f"{missing} employee(s) not clocked in today",
                    "body": "No attendance recorded yet for today",
                    "link": "/attendance",
                    "at": now,
                })
            if late:
                items.append({
                    "id": f"attendance-late:{today.isoformat()}",
                    "kind": "attendance",
                    "severity": "low",
                    "title": f"{late} employee(s) clocked in late today",
                    "body": f"After {_LATE_CUTOFF.strftime('%H:%M')} WIB",
                    "link": "/attendance",
                    "at": now,
                })

        # 6b. Projects past their promised delivery without an actual delivery
        overdue_proj = (await db.scalars(
            select(Project).where(
                Project.is_deleted.is_(False),
                Project.target_delivery.is_not(None),
                Project.target_delivery < today,
                Project.actual_delivery.is_(None),
                Project.status.notin_(["delivered", "invoiced", "paid", "closed"]),
            ).order_by(Project.target_delivery.asc()).limit(15)
        )).all()
        for p in overdue_proj:
            days_over = (today - p.target_delivery).days
            st = p.status.replace("_", " ")
            items.append({
                "id": f"deadline:{p.id}",
                "kind": "missed_deadline",
                "severity": "high",
                "title": f"Missed deadline: {p.code}",
                "body": f"Target delivery {days_over} day(s) ago, still {st}",
                "link": f"/projects/{p.id}",
                "at": now,
            })

    # 6b2. Director: unread user feedback (any account can write in).
    if role == Role.DIRECTOR:
        from app.models.feedback import Feedback
        fresh_fb = (await db.scalars(
            select(Feedback).where(Feedback.status == "new")
            .order_by(Feedback.created_at.desc()).limit(20)
        )).all()
        if fresh_fb:
            newest = fresh_fb[0]
            items.append({
                # Keyed on the newest message only. The count added nothing —
                # it just made an old dismissal resurface whenever the number
                # moved — while `newest.id` still re-notifies on genuinely new
                # feedback, which is the point.
                "id": f"feedback:{newest.id}",
                "kind": "feedback",
                "severity": "medium",
                "title": f"{len(fresh_fb)} new feedback message"
                         + ("" if len(fresh_fb) == 1 else "s"),
                "body": (newest.message or "")[:120],
                "link": "/feedback",
                "at": newest.created_at,
            })

    # 6c. Director: HR/manager-started cross-department chats (silent oversight).
    if role == Role.DIRECTOR:
        overseers = (await db.execute(
            select(User.id, User.role, User.full_name)
            .where(User.role.in_([Role.HR.value, Role.MANAGER.value]),
                   User.is_active.is_(True))
        )).all()
        if overseers:
            by_id = {u[0]: (u[1], u[2]) for u in overseers}
            recent_chans = (await db.scalars(
                select(ChatChannel).where(
                    ChatChannel.created_by.in_(list(by_id.keys())),
                    ChatChannel.created_at >= now - timedelta(days=7),
                ).order_by(ChatChannel.created_at.desc()).limit(30)
            )).all()
            for ch in recent_chans:
                roles = (await db.execute(
                    select(User.role)
                    .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
                    .where(ChatChannelMember.channel_id == ch.id)
                )).all()
                if len({r[0] for r in roles}) > 1:  # cross-department
                    crole, cname = by_id.get(ch.created_by, (None, None))
                    items.append({
                        "id": f"xdept-chat:{ch.id}",
                        "kind": "chat_oversight",
                        "severity": "low",
                        "title": f"{(crole or 'someone').upper()} started a cross-department chat",
                        "body": (ch.name or "Direct message across teams")
                                + (f" · by {cname}" if cname else ""),
                        "link": "/chat",
                        "at": ch.created_at,
                    })

    # 7. Director team-workload roll-up. The director's bell only carries
    # items the DIRECTOR acts on (approvals, PR pricing, drawings, missed
    # deadlines, attendance, feedback). Everyone else's chores — stage
    # tasks, collections, stalled deals — compress into this single row so
    # the count is visible without 50 rows of other people's work.
    if role == Role.DIRECTOR:
        overdue_tasks = await db.scalar(
            select(func.count(Reminder.id)).where(
                Reminder.status == "pending",
                Reminder.kind.like("stage:%"),
                Reminder.due_at.is_not(None),
                Reminder.due_at <= now,
            )
        ) or 0
        overdue_inv = await db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES),
                Invoice.due_date.is_not(None),
                Invoice.due_date < today,
            )
        ) or 0
        stalled = 0
        seven_days_ago = now - timedelta(days=7)
        open_qs = (await db.scalars(
            select(Quotation)
            .where(Quotation.status.in_(["sent", "pending_approval", "approved"]))
            .limit(50)
        )).all()
        for q in open_qs:
            last_act = await db.scalar(
                select(func.max(Activity.occurred_at))
                .where(Activity.customer_id == q.customer_id)
            )
            if (last_act or q.created_at) < seven_days_ago:
                stalled += 1
        if overdue_tasks or overdue_inv or stalled:
            parts = []
            if overdue_tasks:
                parts.append(f"{overdue_tasks} overdue team task(s)")
            if overdue_inv:
                parts.append(f"{overdue_inv} overdue invoice(s)")
            if stalled:
                parts.append(f"{stalled} stalled deal(s)")
            items.append({
                "id": f"team-rollup:{today.isoformat()}",
                "kind": "team_rollup",
                "severity": "low",
                "title": "Team workload: " + ", ".join(parts),
                "body": "Owned by sales / finance / purchasing / admin — "
                        "the manager tracks the detail",
                "link": "/calendar",
                "at": now,
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
            # Count-scoped id: dismissing hides THIS state; new messages
            # change the id so the row comes back.
            "id": f"chat-unread:{total_unread}",
            "kind": "chat",
            "severity": "low",
            "title": f"{total_unread} unread message" + ("" if total_unread == 1 else "s"),
            "body": "Click to open chat",
            "link": "/chat",
            "at": now,
        })

    # ── Mentions + discussion replies ──────────────────────────────────
    # Discussions used to push to phones and nowhere else, so a reply was
    # invisible to anyone who missed the notification. Both now surface here.
    from app.models.comment import CommentMention, EntityComment

    # Being named is high severity — it is addressed to you personally, and
    # for someone mentioned into a document they cannot open, this row and the
    # push are the only ways they will ever learn about it.
    unread_mentions = (await db.execute(
        select(CommentMention, EntityComment)
        .join(EntityComment, CommentMention.comment_id == EntityComment.id)
        .where(CommentMention.user_id == me.id, CommentMention.read_at.is_(None))
        .order_by(EntityComment.created_at.desc())
        .limit(15)
    )).all()
    for m, c in unread_mentions:
        author = await db.get(User, c.author_id) if c.author_id else None
        who = author.full_name if author else "Someone"
        items.append({
            "id": f"mention:{m.id}",
            "kind": "mention",
            "severity": "high",
            "title": f"{who} mentioned you",
            "body": c.body if len(c.body) <= 120 else c.body[:117] + "…",
            "link": "/mentions",
            "at": c.created_at,
        })

    # Replies on threads you are part of — you commented there, or you were
    # mentioned into it. Deliberately not "every thread you could open": that
    # would make the director's bell useless. Low-ish by design; the mention
    # above is the one that shouts.
    my_threads = set()
    for row in (await db.execute(
        select(EntityComment.owner_type, EntityComment.owner_id)
        .where(EntityComment.author_id == me.id).distinct()
    )).all():
        my_threads.add((row[0], row[1]))
    for row in (await db.execute(
        select(CommentMention.owner_type, CommentMention.owner_id)
        .where(CommentMention.user_id == me.id).distinct()
    )).all():
        my_threads.add((row[0], row[1]))

    for owner_type, owner_id in list(my_threads)[:40]:
        latest = await db.scalar(
            select(EntityComment)
            .where(
                EntityComment.owner_type == owner_type,
                EntityComment.owner_id == owner_id,
                EntityComment.author_id != me.id,
            )
            .order_by(EntityComment.created_at.desc())
            .limit(1)
        )
        if latest is None:
            continue
        # Only what arrived after your own last word in that thread — an old
        # conversation you already answered must not sit in the bell forever.
        mine_last = await db.scalar(
            select(EntityComment.created_at)
            .where(
                EntityComment.owner_type == owner_type,
                EntityComment.owner_id == owner_id,
                EntityComment.author_id == me.id,
            )
            .order_by(EntityComment.created_at.desc())
            .limit(1)
        )
        if mine_last and latest.created_at <= mine_last:
            continue
        if any(i["id"] == f"mention:{latest.id}" for i in items):
            continue  # already shouted about as a mention
        author = await db.get(User, latest.author_id) if latest.author_id else None
        items.append({
            # Scoped to the newest comment, so dismissing hides this reply and
            # the next one brings the row back.
            "id": f"discussion:{owner_type}:{owner_id}:{latest.id}",
            "kind": "discussion",
            "severity": "medium",
            "title": f"{author.full_name if author else 'Someone'} replied",
            "body": latest.body if len(latest.body) <= 120 else latest.body[:117] + "…",
            "link": _DISCUSSION_LINK.get(owner_type, "/mentions").format(id=owner_id),
            "at": latest.created_at,
        })

    # Drop items this user dismissed (X button on the bell). Dismissals are
    # per item-id, so a dismissed item stays gone until it resolves — or,
    # for aggregate rows whose id encodes state (chat count, attendance),
    # until the state changes and mints a new id.
    from app.models.push import NotificationDismissed
    dismissed = {row[0] for row in (await db.execute(
        select(NotificationDismissed.item_id)
        .where(NotificationDismissed.user_id == me.id)
    )).all()}
    if dismissed:
        items = [i for i in items if i["id"] not in dismissed]

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


@router.post("/dismiss")
async def dismiss_notification(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Hide bell items for this user.

    Takes either `item_id` (the X button on one row) or `item_ids` (marking a
    whole section read from its sidebar badge). Batching matters: the sidebar
    number is a count of several alerts, and clearing them one request at a
    time would leave the badge visibly counting down — and a half-failed
    sequence would leave it stuck at some arbitrary number.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.push import NotificationDismissed

    raw = payload.get("item_ids")
    if raw is None:
        raw = [payload.get("item_id")]
    if not isinstance(raw, list):
        raw = [raw]
    # Deduplicate but keep it bounded — this is a user action, not an import.
    seen: list[str] = []
    for x in raw[:200]:
        s = str(x or "")[:120]
        if s and s not in seen:
            seen.append(s)
    if not seen:
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "item_id or item_ids required")
    for item_id in seen:
        await db.execute(
            pg_insert(NotificationDismissed)
            .values(user_id=me.id, item_id=item_id)
            .on_conflict_do_nothing(constraint="uq_notif_dismissed")
        )
    return {"ok": True, "dismissed": len(seen)}


@router.post("/dismiss-all")
async def dismiss_all_notifications(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Hide everything currently in this user's bell (Clear all)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.push import NotificationDismissed

    data = await list_notifications(db=db, me=me)
    ids = [i["id"] for i in data.get("items", [])]
    for item_id in ids:
        await db.execute(
            pg_insert(NotificationDismissed)
            .values(user_id=me.id, item_id=item_id)
            .on_conflict_do_nothing(constraint="uq_notif_dismissed")
        )
    return {"ok": True, "dismissed": len(ids)}
