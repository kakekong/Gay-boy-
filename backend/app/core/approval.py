"""Generic approval engine.

Used by:
- Quotation discount approvals
- Admin data-edit approvals
- Any future approvable workflow.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import Role
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.user import User as _User


@dataclass(slots=True)
class ApprovalRule:
    target_type: str
    required_role: Role | None  # None = auto-approve
    reason: str


# Requests addressed to finance that are finance's alone — they do not also
# sit in the director's inbox. The director can settle anything, so every
# finance request used to show there too, and a Mark-won read as one more
# thing queued behind the director when the point of sending it to finance
# was that it isn't. The director still wins a deal directly from the
# quotation page, and `decide()` still accepts their answer if one is given.
FINANCE_ONLY_TARGETS = ("quotation_won", "delivery_order")

# ...and of those, the ones nobody else may decide at all — not even the
# director, who can otherwise settle anything. Releasing a delivery order is
# finance's signature on the sheet the customer signs for, so it is theirs
# alone; the direct Approve DO button has always been finance-only, and the
# inbox must not be a way round it.
FINANCE_EXCLUSIVE_TARGETS = ("delivery_order",)


def scope_to_inbox(stmt, role: Role):
    """Narrow a pending-ApprovalRequest query to what `role` should be shown.

    One filter for the approvals page, its sidebar badge (which counts that
    page) and the bell, so all three agree about what is waiting on you.
    """
    if role == Role.MANAGER:
        return stmt.where(ApprovalRequest.required_role == Role.MANAGER.value)
    if role == Role.FINANCE:
        return stmt.where(ApprovalRequest.required_role == Role.FINANCE.value)
    if role == Role.DIRECTOR:
        return stmt.where(~(
            (ApprovalRequest.required_role == Role.FINANCE.value)
            & ApprovalRequest.target_type.in_(FINANCE_ONLY_TARGETS)
        ))
    return stmt


def evaluate_discount(discount_pct: float) -> ApprovalRule:
    """Return required approver based on configured thresholds."""
    if discount_pct <= settings.DISCOUNT_AUTO_MAX:
        return ApprovalRule("discount", None, "auto-approved (≤5%)")
    if discount_pct <= settings.DISCOUNT_MANAGER_MAX:
        return ApprovalRule("discount", Role.MANAGER,
                            f"manager approval (>{settings.DISCOUNT_AUTO_MAX}%)")
    return ApprovalRule("discount", Role.DIRECTOR,
                        f"director approval (>{settings.DISCOUNT_MANAGER_MAX}%)")


def evaluate_data_change(actor_role: Role) -> ApprovalRule:
    if actor_role == Role.ADMIN:
        return ApprovalRule("data_change", Role.MANAGER, "admin edit requires manager approval")
    return ApprovalRule("data_change", None, "no approval required")


async def file_or_revise(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: UUID,
    requested_by: UUID,
    required_role: Role,
    reason: str,
    changes: dict[str, Any],
) -> ApprovalRequest:
    """File a proposed edit — or revise the one already waiting on this document.

    A person testing a change does not get it right first time. They edit,
    look at it, edit again. Filing a fresh request each time gave the director
    a stack of near-identical rows against one document, with no way to tell
    which was current, and — worse than confusing — approving an older one
    applied a stale intent while the newer one sat there still waiting.

    So there is only ever **one live proposal per document**. A second edit
    revises the first in place: same row, new values, the clock reset to the
    latest change. The count of revisions rides along in the payload so the
    screen can say the row has moved rather than pretending it is new.

    Each request is a complete statement of the fields its form governs,
    computed against a document that does not move while the request is
    pending — so replacing the changes wholesale is what "this is what I now
    propose" means. This is the behaviour quotation edits already had; it is
    here so every document gets it rather than the one that was noticed first.
    """
    existing = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == target_type,
            ApprovalRequest.target_id == target_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        ).order_by(ApprovalRequest.created_at.asc())
    )
    if existing is None:
        return await request_approval(
            db, target_type=target_type, target_id=target_id,
            requested_by=requested_by, required_role=required_role,
            reason=reason,
            payload={"action": "update", "changes": changes, "revision": 1},
        )

    prior = (existing.payload or {}).get("revision") or 1
    existing.payload = {
        "action": "update",
        "changes": changes,
        "revision": int(prior) + 1,
        # When somebody first raised this, kept so the queue can show how long
        # a document has been waiting rather than how long the latest keystroke
        # has.
        "first_requested_at": ((existing.payload or {}).get("first_requested_at")
                               or (existing.created_at.isoformat()
                                   if existing.created_at else None)),
    }
    existing.requested_by = requested_by
    existing.reason = reason
    # The row is the latest proposal, so it sorts as the latest proposal.
    existing.created_at = datetime.now(UTC)
    await db.flush()
    return existing


async def request_approval(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: UUID,
    requested_by: UUID,
    required_role: Role,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> ApprovalRequest:
    req = ApprovalRequest(
        target_type=target_type,
        target_id=target_id,
        requested_by=requested_by,
        required_role=required_role.value,
        reason=reason,
        payload=payload or {},
        status=ApprovalStatus.PENDING.value,
    )
    db.add(req)
    await db.flush()
    return req


async def require_pr_approval(db: AsyncSession, *, pr, requester) -> bool:
    """Gate a freshly-created PurchaseRequest on director approval.

    A director's own PR opens immediately; everyone else's parks at
    'pending_approval' with a director ApprovalRequest filed. The PR must
    already be flushed (have an id). Returns True when an approval was filed.
    """
    if Role(requester.role) == Role.DIRECTOR:
        pr.status = "open"
        return False
    pr.status = "pending_approval"
    n = len(pr.items or [])
    await request_approval(
        db,
        target_type="purchase_request",
        target_id=pr.id,
        requested_by=requester.id,
        required_role=Role.DIRECTOR,
        reason=f"Purchase request {pr.number}" + (f" ({n} item(s))" if n else ""),
        payload={"action": "create"},
    )
    return True


async def decide(
    db: AsyncSession,
    *,
    request_id: UUID,
    decider_id: UUID,
    decider_role: Role,
    approve: bool,
    notes: str | None = None,
) -> ApprovalRequest:
    req = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == request_id))
    if not req:
        raise ValueError("approval request not found")
    if req.status != ApprovalStatus.PENDING.value:
        raise ValueError("approval already decided")
    if req.target_type in FINANCE_EXCLUSIVE_TARGETS and decider_role != Role.FINANCE:
        raise PermissionError("only finance can approve this")
    if Role(req.required_role) == Role.DIRECTOR and decider_role != Role.DIRECTOR:
        raise PermissionError("director approval required")
    if Role(req.required_role) == Role.MANAGER and decider_role not in (Role.MANAGER, Role.DIRECTOR):
        raise PermissionError("manager or director approval required")
    if Role(req.required_role) == Role.FINANCE and decider_role not in (Role.FINANCE, Role.DIRECTOR):
        # DP customer-PO approvals target finance — a manager must not be
        # able to decide them through the generic approvals API.
        raise PermissionError("finance or director approval required")
    req.status = (ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED).value
    req.decided_by = decider_id
    req.decided_at = datetime.now(UTC)
    req.decision_notes = notes
    return req


async def apply_to_target(
    db: AsyncSession, req: ApprovalRequest, approve: bool
) -> dict:
    """When an approval is decided, propagate the outcome to its target entity.

    - quotation:    on approve → status becomes 'approved'; on reject → 'rejected'
    - customer:     on approve → apply the saved 'changes' from payload
    - discount/etc: legacy alias — discount approvals were sometimes filed under
                    target_type='quotation' but older code used 'discount';
                    we handle both.
    Returns a small dict describing what was applied (for the API response).
    """
    applied: dict = {"target_type": req.target_type, "target_id": str(req.target_id)}
    if req.target_type == "cross_dept_chat":
        # Approving opens the DM between the two people; rejecting opens
        # nothing. Either way the requester can see the outcome on their own
        # request list.
        from app.services.chat_policy import existing_dm_id
        from app.models.chat import ChatChannel, ChatChannelMember
        if approve:
            already = await existing_dm_id(db, req.requested_by, req.target_id)
            if already:
                applied["channel_id"] = str(already)
            else:
                ch = ChatChannel(kind="dm", created_by=req.requested_by)
                db.add(ch)
                await db.flush()
                db.add_all([
                    ChatChannelMember(channel_id=ch.id, user_id=req.requested_by),
                    ChatChannelMember(channel_id=ch.id, user_id=req.target_id),
                ])
                await db.flush()
                applied["channel_id"] = str(ch.id)
        applied["opened"] = approve
        return applied

    if req.target_type == "price_request_revision":
        # A negotiation revision on a price request. Approving applies the
        # proposed lines; rejecting leaves the request exactly as it was and
        # does NOT spend one of the rep's three revisions — nothing changed.
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, req.target_id)
        n = (req.payload or {}).get("revision_n")
        if pr:
            revs = list(pr.revisions or [])
            for i, r in enumerate(revs):
                if r.get("n") != n or r.get("status") != "pending":
                    continue
                r = dict(r)
                r["status"] = "approved" if approve else "rejected"
                r["decided_at"] = datetime.now(UTC).isoformat()
                r["decision_notes"] = req.decision_notes
                decider = await db.get(_User, req.decided_by) if req.decided_by else None
                r["decided_by"] = str(req.decided_by) if req.decided_by else None
                r["decided_by_name"] = decider.full_name if decider else None
                revs[i] = r
                if approve:
                    pr.items = r.get("proposed_items") or pr.items
                    if r.get("proposed_notes") is not None:
                        pr.notes = r["proposed_notes"]
                applied["revision"] = n
                applied["revision_status"] = r["status"]
                break
            pr.revisions = revs
        return applied

    if req.target_type in ("quotation", "discount"):
        from app.models.quotation import Quotation
        q = await db.get(Quotation, req.target_id)
        if q:
            q.status = "approved" if approve else "rejected"
            applied["new_status"] = q.status
            # Fused pipeline: quotation approval advances the deal to the
            # 'quotation' stage in the same decision — no separate
            # stage-move request from sales.
            if approve and q.customer_id:
                from app.core.stage_playbook import bump_customer_stage
                from app.core.stage_tasks import ensure_stage_tasks
                from app.models.crm import Customer as _Cust
                cust = await db.get(_Cust, q.customer_id)
                if cust and bump_customer_stage(cust, "quotation"):
                    await ensure_stage_tasks(db, cust, "quotation")
                    applied["customer_stage"] = "quotation"
            # An approved revision replaces its parent — the old version
            # flips to 'superseded' so only one offer is ever live.
            if approve and q.parent_id:
                parent = await db.get(Quotation, q.parent_id)
                if parent and parent.status not in ("won", "cancelled", "superseded"):
                    parent.status = "superseded"
                    applied["superseded"] = str(parent.id)
    elif req.target_type == "quotation_edit":
        # Pricing edit to an already-approved quotation: the stashed
        # changes apply only when the director approves. Rejection leaves
        # the quotation exactly as it was.
        from sqlalchemy import select as _select
        from sqlalchemy.orm import selectinload as _sel
        from app.models.quotation import Quotation
        q = await db.scalar(
            _select(Quotation).options(_sel(Quotation.items))
            .where(Quotation.id == req.target_id)
        )
        if q and approve and (req.payload or {}).get("action") == "update":
            from app.api.v1.endpoints.quotations import _apply_quotation_changes
            changes = (req.payload or {}).get("changes") or {}
            await _apply_quotation_changes(db, q, changes)
            applied["applied_changes"] = sorted(changes)
    elif req.target_type == "customer":
        from app.models.crm import Customer
        c = await db.get(Customer, req.target_id)
        if c and approve and req.payload and "changes" in req.payload:
            changes = req.payload["changes"]
            prev_stage = c.stage
            for k, v in changes.items():
                if hasattr(c, k):
                    setattr(c, k, v)
            applied["applied_changes"] = list(changes.keys())
            # If the approval included a stage move, kick off that stage's
            # checklist now — same behaviour as a direct director edit.
            if "stage" in changes and changes["stage"] != prev_stage:
                from app.core.stage_tasks import ensure_stage_tasks
                await ensure_stage_tasks(db, c, changes["stage"])
    elif req.target_type == "customer_po":
        # Approving a customer PO spawns a Project; rejecting it parks
        # the PO at status='rejected' so the sales team can file a new
        # one if the paperwork changes.
        # NOTE: use the module-level `UTC`/`datetime` (imported at top). A
        # local `from datetime import UTC` here would make UTC a function-
        # local for the WHOLE function, so other branches (e.g. follow-up)
        # that reference UTC before this line would raise UnboundLocalError.
        from app.api.v1.endpoints.customer_pos import _spawn_project
        from app.models.customer_po import CustomerPO
        po = await db.get(CustomerPO, req.target_id)
        if po:
            is_dp_request = bool(
                po.is_downpayment
                or (req.payload or {}).get("action") == "dp_finance_approve"
            )
            # Stale-request guard: if the PO has already moved past its
            # pending state (the DP endpoints or the PO-page buttons acted
            # on it directly), do NOT re-apply — re-approving used to
            # spawn a duplicate project.
            pending_states = (
                ("pending_finance", "pending_payment_confirm")
                if is_dp_request else ("pending_approval",)
            )
            if po.status not in pending_states:
                applied["skipped"] = (
                    f"customer PO already '{po.status}' — decision recorded "
                    "but not re-applied"
                )
                return applied

            decider = await db.get(__import__("app.models.user", fromlist=["User"]).User, req.decided_by) if req.decided_by else None
            po.decided_by = req.decided_by
            po.decided_at = req.decided_at or datetime.now(UTC)
            po.decision_notes = req.decision_notes
            if approve:
                if is_dp_request:
                    # DP chain: approval here is FINANCE approval only.
                    # Never spawn the project — that stays gated behind
                    # sales confirming the deposit landed.
                    if po.status == "pending_finance":
                        po.status = "pending_payment_confirm"
                        po.dp_finance_approved_by = req.decided_by
                        po.dp_finance_approved_at = req.decided_at or datetime.now(UTC)
                    applied["dp"] = "finance approval applied; awaiting sales deposit confirmation"
                else:
                    po.status = "approved"
                    # Use the decider as the project's creator so authorship
                    # reflects who signed off — falling back to the requester
                    # if for any reason the decider record is missing.
                    actor = decider
                    if actor is None:
                        from app.models.user import User as _UserModel
                        actor = await db.get(_UserModel, req.requested_by)
                    if actor is not None:
                        # Attaches to the job Won already started, or mints it
                        # here when Won has not happened yet — an approved
                        # order is reason enough to have somewhere to work.
                        # Down-payment orders still wait for the deposit.
                        project = await _spawn_project(db, po, actor)
                        if project is not None:
                            applied["project_id"] = str(project.id)
                            applied["project_code"] = project.code
            else:
                po.status = "rejected"
            applied["new_status"] = po.status
    elif req.target_type == "supplier_po":
        # Every PO step needs director approval. The original request
        # carries an "action" tag in its payload telling us how to apply
        # the decision: a freshly-created PO sits at pending_approval
        # until the director flips it open; an update request stashes the
        # proposed field changes and we apply them now.
        from datetime import date as date_t

        from app.models.purchasing import SupplierPO
        po = await db.get(SupplierPO, req.target_id)
        if po:
            action = (req.payload or {}).get("action")
            if action == "create" and po.status != "pending_approval":
                # Already decided elsewhere (or goods received against it) —
                # don't overwrite the live status with open/cancelled.
                applied["skipped"] = (
                    f"supplier PO already '{po.status}' — decision recorded "
                    "but not re-applied"
                )
                return applied
            if action == "create":
                po.status = "open" if approve else "cancelled"
                applied["new_status"] = po.status
                # Releasing the PO is what puts its goods on the shelf — the
                # same act that told the supplier to send them.
                if approve:
                    from app.services.stock_sync import receive_purchase_order
                    # No actor here — apply_to_target takes the request, not
                    # the person; the movement's own reference names the PO,
                    # and the approval row records who decided it.
                    applied["stock_in"] = await receive_purchase_order(db, po)
                # An approved supplier PO is the trigger that moves the project
                # to the purchasing stage (matches the direct-director path in
                # purchasing.create_po). Forward-only.
                if approve and po.project_id:
                    from app.models.operation import (
                        Project, advance_project_status,
                    )
                    project = await db.get(Project, po.project_id)
                    if project:
                        advance_project_status(project, "purchasing")
            elif action == "update" and approve:
                changes = dict((req.payload or {}).get("changes") or {})
                was_currency = (po.currency or "IDR").upper()
                # A project is not a field to copy across: it moves the lines
                # and the job with it, so it goes through the same helper the
                # director's own edit uses — after the lines, so any new lines
                # in the same change are stamped with it.
                has_project = "project_id" in changes
                new_project_id = changes.pop("project_id", None)
                for k, v in changes.items():
                    if k == "po_date":
                        po.po_date = None if v in (None, "") else date_t.fromisoformat(v)
                    elif hasattr(po, k):
                        setattr(po, k, v)
                # Same rule the direct path applies: a rate belongs to the
                # currency it was quoted against, so switching the currency
                # drops a rate that came from the old one. A change that
                # carries its own rate keeps it — purchasing said what the new
                # currency is worth when they asked for the switch, and this
                # is the moment that answer takes effect.
                if ("currency" in changes
                        and "fx_rate" not in changes
                        and (po.currency or "IDR").upper() != was_currency):
                    po.fx_rate = 1 if (po.currency or "IDR").upper() == "IDR" else None
                if has_project:
                    from app.models.operation import Project
                    from app.services.po_project import assign_po_project
                    target = None
                    if new_project_id:
                        target = await db.get(Project, UUID(str(new_project_id)))
                    # A job deleted while the request sat in the queue is not
                    # one to attach to; leave the PO as it is and say so.
                    if new_project_id and target is None:
                        applied["project_skipped"] = "that project no longer exists"
                    else:
                        applied["project"] = await assign_po_project(db, po, target)
                    changes["project_id"] = new_project_id
                applied["applied_changes"] = list(changes.keys())
    elif req.target_type == "delivery_order":
        # The director's release of a delivery order, taken from the inbox
        # instead of the project page. Approving it is the same act as the
        # Approve DO button: the sheet the driver carries is generated from
        # this row at this moment, so the signature is stamped on the row.
        #
        # Rejecting deliberately changes nothing on the delivery order. It is
        # still unapproved, still editable, still deletable — which is exactly
        # what the desk needs in order to fix whatever the director sent it
        # back for. The reason lives on this request, and the project page
        # reads it off there.
        from app.models.operation import DeliveryOrder
        d = await db.get(DeliveryOrder, req.target_id)
        if d:
            applied["number"] = d.number
            if d.approved_at:
                applied["skipped"] = (
                    f"{d.number} was already released — decision recorded "
                    "but not re-applied"
                )
                return applied
            if approve:
                d.approved_by = req.decided_by
                d.approved_at = req.decided_at or datetime.now(UTC)
                applied["new_status"] = "approved"
                applied["approved_at"] = d.approved_at.isoformat()
            else:
                applied["new_status"] = "sent back for correction"
    elif req.target_type == "purchase_request":
        # A PR sits at pending_approval until the director opens it; rejecting
        # cancels it so purchasing knows not to source against it.
        from app.models.purchasing import PurchaseRequest
        pr = await db.get(PurchaseRequest, req.target_id)
        if pr and pr.status != "pending_approval":
            applied["skipped"] = (
                f"purchase request already '{pr.status}' — decision recorded "
                "but not re-applied"
            )
            return applied
        if pr:
            pr.status = "open" if approve else "cancelled"
            applied["new_status"] = pr.status
    elif req.target_type == "project":
        # Director-gated shipping/date edits: apply the stashed patch on
        # approval (skipping nulls that would only clear a protected date).
        from app.api.v1.endpoints.operation import (
            DATE_FIELDS_PROTECTED,
            _apply_project_changes,
        )
        from app.models.operation import Project
        p = await db.get(Project, req.target_id)
        if p and approve and (req.payload or {}).get("action") == "update":
            changes = (req.payload or {}).get("changes") or {}
            _apply_project_changes(p, changes)
            applied["applied_changes"] = [
                k for k in changes
                if not (changes[k] is None and k in DATE_FIELDS_PROTECTED)
            ]
    elif req.target_type == "inventory_item":
        # New inventory items don't exist until the director signs off — the
        # whole batch rides in the payload and is materialised on approval.
        from app.models.inventory import InventoryItem
        if approve and (req.payload or {}).get("action") == "create_bulk":
            created: list[str] = []
            skipped: list[str] = []
            for data in (req.payload.get("items") or []):
                sku = (data.get("sku") or "").strip()
                if not sku:
                    continue
                clash = await db.scalar(
                    select(InventoryItem).where(InventoryItem.sku == sku)
                )
                if clash:
                    skipped.append(sku)
                    continue
                db.add(InventoryItem(**data))
                created.append(sku)
            await db.flush()
            applied["created_skus"] = created
            applied["skipped_skus"] = skipped
    elif req.target_type == "followup":
        # **Nothing files these any more.** Logging a follow-up no longer needs
        # the director — the call already happened and the note is the record
        # of it, so it is written when it is logged.
        #
        # This stays for the backlog: requests filed before that change are
        # still sitting in the queue, and deleting the branch would leave them
        # undecidable — approving one would close the request and silently
        # write nothing, losing the note somebody typed. Approving materialises
        # the activity (and the reminder, for the quotation flow) with the
        # original requester as the author; rejection leaves nothing behind.
        # Once the queue is clear this can go.
        if approve:
            from app.models.crm import Activity, Reminder
            p = req.payload or {}
            customer_id = req.target_id
            user_id = req.requested_by
            if p.get("source") == "quotation":
                act = Activity(
                    customer_id=customer_id, user_id=user_id, type="follow_up",
                    direction="outbound", occurred_at=datetime.now(UTC),
                    notes=p.get("notes"),
                    meta={
                        "quotation_id": p.get("quotation_id"),
                        "quotation_number": p.get("quotation_number"),
                    },
                )
                db.add(act)
                await db.flush()
                applied["activity_id"] = str(act.id)
                if p.get("next_at"):
                    rem = Reminder(
                        customer_id=customer_id, user_id=user_id,
                        kind="follow_up",
                        due_at=datetime.fromisoformat(p["next_at"]),
                        channel=p.get("next_channel") or "dashboard",
                        message=f"Follow up on quotation {p.get('quotation_number')}",
                        status="pending",
                    )
                    db.add(rem)
                    await db.flush()
                    applied["reminder_id"] = str(rem.id)
            else:
                act = Activity(
                    customer_id=customer_id, user_id=user_id,
                    type=p.get("type", "follow_up"),
                    direction=p.get("direction", "internal"),
                    occurred_at=datetime.now(UTC),
                    notes=p.get("notes"),
                    meta=p.get("meta") or {},
                )
                db.add(act)
                await db.flush()
                applied["activity_id"] = str(act.id)
    elif req.target_type == "project_skip_drawing":
        # Purchasing or ops asked to declare a job as having no drawing to
        # wait for. The decision is the director's, so it lands here; applying
        # it goes through the same helper the director's direct path uses, so
        # a skip signed off in this queue is indistinguishable from one done
        # on the project page.
        from app.api.v1.endpoints.operation import apply_drawing_skip
        from app.models.operation import Project as _Project
        proj = await db.get(_Project, req.target_id)
        if proj is None:
            applied["skipped"] = "the project is gone — decision recorded only"
        elif proj.drawing_skipped_at is not None:
            applied["skipped"] = "the drawing was already skipped on this job"
        elif approve:
            apply_drawing_skip(
                proj, actor_id=req.decided_by or req.requested_by,
                reason=(req.payload or {}).get("reason"),
            )
            applied["drawing_skipped"] = True
            applied["new_status"] = proj.status
        else:
            applied["drawing_skipped"] = False
    elif req.target_type == "quotation_won":
        # Marking a deal Won is director-gated. On approval the quotation flips
        # to 'won' and posts to the ledger (idempotent, best-effort).
        from app.models.quotation import Quotation
        q = await db.get(Quotation, req.target_id)
        if q and q.status in ("won", "lost", "cancelled", "superseded"):
            # Stale request: the quote already settled (e.g. the director
            # marked it Won directly, or a revision superseded it). Record
            # the decision but don't re-apply — re-winning a superseded quote
            # would post its revenue a second time alongside the live one.
            applied["skipped"] = (
                f"quotation already '{q.status}' — decision recorded "
                "but not re-applied"
            )
            return applied
        if q and approve:
            # Re-check the customer's PO at decision time, not only when the
            # request was filed. A PO rejected in between would otherwise let
            # an approval signed off yesterday win a deal whose evidence is
            # gone — and this is the signature that posts the revenue.
            from sqlalchemy import func as _func

            from app.models.customer_po import CustomerPO as _CPO
            still = await db.scalar(
                select(_func.count(_CPO.id)).where(
                    _CPO.quotation_id == q.id,
                    _CPO.status.notin_(("rejected", "cancelled")),
                )
            )
            if not still:
                applied["skipped"] = (
                    "the customer PO behind this request is gone — decision "
                    "recorded, but the quotation was not marked Won"
                )
                return applied
            q.status = "won"
            # Won is where the job starts — same rule as the director's direct
            # path in quotations.mark_won. The requester is the one who won
            # the deal, but the decider is who signed it off, so authorship
            # follows the signature.
            # `_User` is imported at module scope; re-importing it under the
            # same name here would make it local to this whole function and
            # break the branches above that already use it.
            from app.services.project_factory import ensure_project_for_quotation
            actor = (await db.get(_User, req.decided_by)) if req.decided_by else None
            if actor is None:
                actor = await db.get(_User, req.requested_by)
            if actor is not None:
                project = await ensure_project_for_quotation(db, q, actor)
                if project is not None:
                    applied["project_id"] = str(project.id)
                    applied["project_code"] = project.code
            # Fused pipeline: the Won approval is also the sign-off that the
            # deal reached negotiation — bump the stage in the same stroke.
            if q.customer_id:
                from app.core.stage_playbook import bump_customer_stage
                from app.core.stage_tasks import ensure_stage_tasks
                from app.models.crm import Customer as _Cust
                cust = await db.get(_Cust, q.customer_id)
                if cust and bump_customer_stage(cust, "negotiation"):
                    await ensure_stage_tasks(db, cust, "negotiation")
                    applied["customer_stage"] = "negotiation"
            from app.services import ledger
            try:
                await ledger.post_quotation(db, q)
            except Exception:
                pass
            applied["new_status"] = "won"
        elif q:
            # Rejected: the quote stays where it was (approved/sent).
            applied["new_status"] = q.status
    # other target_types: no automatic propagation (yet)
    return applied
