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
    # other target_types: no automatic propagation (yet)
    return applied
