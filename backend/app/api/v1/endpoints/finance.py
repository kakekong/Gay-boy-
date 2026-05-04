"""Finance: invoice, payment, AR/AP, tax."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.finance import Invoice, Payment
from app.models.user import User

router = APIRouter()


@router.get("/ar/aging")
async def ar_aging(db: AsyncSession = Depends(get_db),
                   _user: User = Depends(get_current_user)):
    """AR aging buckets: 0-30, 31-60, 61-90, 90+ days past due."""
    today = date.today()
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0, "current": 0.0}
    rows = (await db.scalars(
        select(Invoice).where(Invoice.status.in_(["issued", "partial", "overdue"]))
    )).all()
    for inv in rows:
        if not inv.due_date:
            continue
        delta = (today - inv.due_date).days
        amount = float(inv.total)
        if delta < 0:
            buckets["current"] += amount
        elif delta <= 30:
            buckets["0-30"] += amount
        elif delta <= 60:
            buckets["31-60"] += amount
        elif delta <= 90:
            buckets["61-90"] += amount
        else:
            buckets["90+"] += amount
    return buckets


@router.post("/reminders/run")
async def run_payment_reminders(db: AsyncSession = Depends(get_db),
                                _user: User = Depends(get_current_user)):
    """Identify invoices needing reminders. The actual WA send is done by n8n."""
    today = date.today()
    upcoming = today + timedelta(days=3)
    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status.in_(["issued", "partial"]),
            Invoice.due_date <= upcoming,
        )
    )).all()
    return {"to_remind": [
        {"invoice_id": str(r.id), "number": r.number,
         "customer_id": str(r.customer_id), "due_date": r.due_date,
         "total": float(r.total)} for r in rows
    ]}


@router.get("/tax/report")
async def tax_report(period: str = "current_month",
                     db: AsyncSession = Depends(get_db),
                     _user: User = Depends(get_current_user)):
    total_tax = await db.scalar(select(func.coalesce(func.sum(Invoice.tax_amount), 0)))
    return {"period": period, "tax_collected": float(total_tax or 0)}


@router.post("/payments")
async def record_payment(invoice_id: str, amount: float, method: str | None = None,
                         reference: str | None = None,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    p = Payment(invoice_id=invoice_id, amount=amount, method=method, reference=reference)
    db.add(p)
    await db.flush()
    return {"id": str(p.id), "ok": True}
