"""Generic approval engine.

Used by:
- Quotation discount approvals
- Admin data-edit approvals
- Any future approvable workflow.
"""

from dataclasses import dataclass
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
    req.decision_notes = notes
    return req
