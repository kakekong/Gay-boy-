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
    if req.target_type in ("quotation", "discount"):
        from app.models.quotation import Quotation
        q = await db.get(Quotation, req.target_id)
        if q:
            q.status = "approved" if approve else "rejected"
            applied["new_status"] = q.status
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
        from datetime import UTC, datetime as _dt
        from app.api.v1.endpoints.customer_pos import _spawn_project
        from app.models.customer_po import CustomerPO
        po = await db.get(CustomerPO, req.target_id)
        if po:
            decider = await db.get(__import__("app.models.user", fromlist=["User"]).User, req.decided_by) if req.decided_by else None
            po.decided_by = req.decided_by
            po.decided_at = req.decided_at or _dt.now(UTC)
            po.decision_notes = req.decision_notes
            if approve:
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
            if action == "create":
                po.status = "open" if approve else "cancelled"
                applied["new_status"] = po.status
            elif action == "update" and approve:
                changes = (req.payload or {}).get("changes") or {}
                for k, v in changes.items():
                    if k == "po_date":
                        po.po_date = None if v in (None, "") else date_t.fromisoformat(v)
                    elif hasattr(po, k):
                        setattr(po, k, v)
                applied["applied_changes"] = list(changes.keys())
    # other target_types: no automatic propagation (yet)
    return applied
