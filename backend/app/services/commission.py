"""What a project has actually collected, and what that is worth to the rep.

The whole commission rule turns on one question — *has the money arrived?* —
and the honest answer is not the project's status or the order value. It is
the sum of the payments recorded against the project's invoices, which is the
same figure the AR screens read and the same one a reversal moves back down.

So this computes it from the payments, and every caller asks here rather than
deciding for itself. A claim gate and a claim button that disagree about
whether a job is paid is the kind of bug nobody reports: the button is simply
greyed out and the rep assumes the system knows something they do not.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission import CommissionClaim, LIVE_STATUSES
from app.models.finance import Invoice, Payment


async def collected_for_projects(
    db: AsyncSession, project_ids: list[UUID],
) -> dict[UUID, dict]:
    """Per project: what has been invoiced, what has been paid, and whether
    the customer has settled it in full.

    "In full" deliberately means *every* invoice on the job, deposit included.
    A deposit paid on a job still being built is money in the bank, but it is
    not the job being paid for, and paying commission on it would have the
    company owing a share of a sale that can still fall over.
    """
    if not project_ids:
        return {}
    rows = (await db.execute(
        select(Invoice.project_id, Invoice.id, Invoice.total, Invoice.status)
        .where(Invoice.project_id.in_(project_ids))
    )).all()
    if not rows:
        return {pid: {"invoiced": 0.0, "collected": 0.0, "outstanding": 0.0,
                      "paid_in_full": False, "invoices": 0} for pid in project_ids}

    # Rejected invoices are not a bill anybody owes, so they count for
    # neither side of the sum — including one would leave a fully-settled
    # job looking permanently short.
    live = [r for r in rows if (r[3] or "") != "rejected"]
    inv_ids = [r[1] for r in live]
    paid_by_inv: dict[UUID, float] = {}
    if inv_ids:
        for row in (await db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(inv_ids))
            .group_by(Payment.invoice_id)
        )).all():
            paid_by_inv[row[0]] = float(row[1] or 0)

    out: dict[UUID, dict] = {
        pid: {"invoiced": 0.0, "collected": 0.0, "outstanding": 0.0,
              "paid_in_full": False, "invoices": 0}
        for pid in project_ids
    }
    for project_id, invoice_id, total, _status in live:
        e = out.setdefault(project_id, {"invoiced": 0.0, "collected": 0.0,
                                        "outstanding": 0.0, "paid_in_full": False,
                                        "invoices": 0})
        e["invoiced"] += float(total or 0)
        e["collected"] += paid_by_inv.get(invoice_id, 0.0)
        e["invoices"] += 1
    for e in out.values():
        e["invoiced"] = round(e["invoiced"], 2)
        e["collected"] = round(e["collected"], 2)
        e["outstanding"] = round(max(0.0, e["invoiced"] - e["collected"]), 2)
        e["paid_in_full"] = e["invoiced"] > 0 and e["collected"] >= e["invoiced"] - 0.01
    return out


async def claims_for_projects(
    db: AsyncSession, project_ids: list[UUID],
) -> dict[UUID, CommissionClaim]:
    """The live claim on each project, if there is one.

    A rejected claim is not live: it was refused, and the rep can put the case
    again. Anything else — pending, approved, paid — blocks a second one,
    because two claims on one job is how the same commission gets paid twice.
    """
    if not project_ids:
        return {}
    rows = (await db.scalars(
        select(CommissionClaim)
        .where(CommissionClaim.project_id.in_(project_ids),
               CommissionClaim.status.in_(LIVE_STATUSES))
        .order_by(CommissionClaim.created_at.asc())
    )).all()
    return {c.project_id: c for c in rows}


def claim_out(c: CommissionClaim | None) -> dict | None:
    if c is None:
        return None
    return {
        "id": str(c.id),
        "status": c.status,
        "rate_pct": float(c.rate_pct or 0),
        "basis_amount": float(c.basis_amount or 0),
        "amount": float(c.amount or 0),
        "notes": c.notes,
        "decision_notes": c.decision_notes,
        "decided_at": c.decided_at,
        "paid_at": c.paid_at,
        "created_at": c.created_at,
    }
