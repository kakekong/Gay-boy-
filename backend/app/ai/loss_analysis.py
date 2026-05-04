"""Loss Analysis AI — pattern brain over closed_lost deals."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Customer
from app.models.quotation import Quotation


async def patterns(db: AsyncSession) -> dict:
    rows = (await db.scalars(
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.status == "lost")
    )).all()

    by_industry: Counter[str] = Counter()
    discount_avg: dict[str, list[float]] = {}
    for q in rows:
        cust = await db.get(Customer, q.customer_id)
        if not cust:
            continue
        by_industry[cust.industry] += 1
        discount_avg.setdefault(cust.industry, []).append(float(q.discount_pct or 0))

    findings = []
    for ind, n in by_industry.most_common(5):
        avg_disc = sum(discount_avg.get(ind, [])) / max(1, len(discount_avg.get(ind, [])))
        findings.append({
            "industry": ind,
            "lost_count": n,
            "avg_discount_pct_when_lost": round(avg_disc, 2),
            "insight": f"In {ind}, lost deals averaged {avg_disc:.1f}% discount — "
                       f"discount alone is not closing them.",
        })
    return {"patterns": findings}
