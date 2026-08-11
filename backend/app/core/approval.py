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
                ("pending_finance", "pending_sales_confirm")
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
                        po.status = "pending_sales_confirm"
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
                        project = await _spawn_project(db, po, actor)
                        po.project_id = project.id
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
                changes = (req.payload or {}).get("changes") or {}
                for k, v in changes.items():
                    if k == "po_date":
                        po.po_date = None if v in (None, "") else date_t.fromisoformat(v)
                    elif hasattr(po, k):
                        setattr(po, k, v)
                applied["applied_changes"] = list(changes.keys())
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
        # Sales-initiated follow-ups are deferred: on approval we materialise
        # the activity (and a reminder, for the quotation flow) using the
        # original requester as the author. Rejection leaves nothing behind.
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
