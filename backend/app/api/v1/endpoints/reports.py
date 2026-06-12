"""Reports — P&L, AR Aging detail, Sales by salesperson, Pipeline by stage,
Lost-deal analysis. Everyone authenticated can view; downstream UI gates
finer access if needed.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.quotation import Quotation
from app.models.user import User

# Reports are a director-only management surface. Gate the whole router.
router = APIRouter(dependencies=[Depends(require(Role.DIRECTOR))])


# ─── P&L (uses current CoA balances) ────────────────────────────────────────

@router.get("/pnl")
async def pnl(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Simple Profit & Loss derived from CoA balances by category."""
    rows = (await db.scalars(select(Account))).all()
    totals: dict[str, float] = defaultdict(float)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for a in rows:
        bal = float(a.balance or 0)
        if a.is_parent or not bal:
            continue
        totals[a.account_type] += bal
        by_type[a.account_type].append({
            "account_no": a.account_no, "name": a.name, "balance": bal,
        })

    revenue = totals.get("Revenue", 0)
    cogs = totals.get("Cost Of Good Sold", 0)
    other_income = totals.get("Other Income", 0)
    expense = totals.get("Expense", 0)
    other_expense = totals.get("Other Expense", 0)

    gross_profit = revenue - cogs
    operating_income = gross_profit - expense
    net_income = operating_income + other_income - other_expense

    return {
        "totals": {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "expense": expense,
            "operating_income": operating_income,
            "other_income": other_income,
            "other_expense": other_expense,
            "net_income": net_income,
        },
        "by_type": by_type,
    }


# ─── AR Aging detail ────────────────────────────────────────────────────────

@router.get("/ar-aging-detail")
async def ar_aging_detail(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    today = date.today()
    rows = (await db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.status.in_(["issued", "partial", "overdue"]))
        .order_by(Invoice.due_date.asc().nullslast())
    )).all()

    def bucket(due: date | None) -> str:
        if not due:
            return "no-due"
        delta = (today - due).days
        if delta < 0:    return "current"
        if delta <= 30:  return "0-30"
        if delta <= 60:  return "31-60"
        if delta <= 90:  return "61-90"
        return "90+"

    items = []
    buckets: dict[str, float] = defaultdict(float)
    for inv, c in rows:
        b = bucket(inv.due_date)
        total = float(inv.total or 0)
        buckets[b] += total
        items.append({
            "invoice_id": str(inv.id),
            "number": inv.number,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
            "due_date": inv.due_date,
            "days_overdue": (today - inv.due_date).days if inv.due_date else None,
            "total": total,
            "status": inv.status,
            "bucket": b,
        })
    return {"items": items, "buckets": buckets}


# ─── Sales by salesperson ───────────────────────────────────────────────────

@router.get("/sales-by-person")
async def sales_by_person(
    range_days: int = Query(90, ge=1, le=730),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=range_days)
    # Per sales user
    users = (await db.scalars(
        select(User).where(User.is_active.is_(True), User.role == "sales")
        .order_by(User.full_name.asc())
    )).all()

    out: list[dict] = []
    for u in users:
        qstmt = select(Quotation).where(Quotation.sales_pic_id == u.id,
                                        Quotation.created_at >= since)
        quotes = (await db.scalars(qstmt)).all()
        won = [q for q in quotes if q.status == "won"]
        lost = [q for q in quotes if q.status == "lost"]
        decided = len(won) + len(lost)
        out.append({
            "user_id": str(u.id),
            "full_name": u.full_name,
            "quotations": len(quotes),
            "won": len(won),
            "lost": len(lost),
            "win_rate": round(len(won) / decided, 3) if decided else 0,
            "pipeline_value": float(sum(float(q.total or 0) for q in quotes
                                        if q.status in ("draft", "pending_approval", "approved", "sent"))),
            "won_revenue": float(sum(float(q.total or 0) for q in won)),
        })
    out.sort(key=lambda x: -x["won_revenue"])
    return {"range_days": range_days, "rows": out}


# ─── Pipeline by stage ──────────────────────────────────────────────────────

@router.get("/pipeline-by-stage")
async def pipeline_by_stage(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Customer counts and quotation values bucketed by stage."""
    customers = (await db.scalars(
        select(Customer).where(Customer.is_deleted.is_(False))
    )).all()
    by_stage: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "value": 0.0})
    for c in customers:
        by_stage[c.stage]["count"] += 1
        by_stage[c.stage]["value"] += float(c.lifetime_value or 0)

    # Add quotation values by stage of their customer
    rows = (await db.execute(
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.status.in_(["draft", "pending_approval", "approved", "sent"]))
    )).all()
    for q, c in rows:
        by_stage[c.stage]["value"] += float(q.total or 0)

    STAGES = [
        "lead", "presentation", "engineering", "quotation", "negotiation",
        "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
        "closed_won", "closed_lost",
    ]
    return {
        "rows": [
            {"stage": s, "count": by_stage[s]["count"], "value": by_stage[s]["value"]}
            for s in STAGES
        ]
    }


# ─── Lost-deal analysis ─────────────────────────────────────────────────────

@router.get("/lost-deals")
async def lost_deals(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    lost = (await db.execute(
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.status == "lost")
        .order_by(Quotation.updated_at.desc())
    )).all()

    by_industry: dict[str, int] = defaultdict(int)
    by_reason: dict[str, int] = defaultdict(int)
    items = []
    for q, c in lost:
        # Extract last "[lost @ ...] reason" from notes
        reason = "unspecified"
        if q.notes and "[lost @" in q.notes:
            last = q.notes.split("[lost @")[-1]
            if "]" in last:
                reason = last.split("]", 1)[1].strip()[:80] or "unspecified"
        by_industry[c.industry] += 1
        by_reason[reason or "unspecified"] += 1
        items.append({
            "id": str(q.id),
            "number": q.number,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
            "industry": c.industry,
            "discount_pct": float(q.discount_pct or 0),
            "total": float(q.total or 0),
            "reason": reason,
            "lost_at": q.updated_at,
        })
    return {
        "items": items,
        "by_industry": dict(by_industry),
        "by_reason": dict(by_reason),
        "total_lost_value": float(sum(i["total"] for i in items)),
    }


# ─── Export (PDF / Excel) ───────────────────────────────────────────────────

_REPORT_LABELS = {
    "pnl": "Profit & Loss",
    "ar": "AR Aging detail",
    "sales": "Sales by salesperson",
    "pipeline": "Pipeline by stage",
    "lost": "Lost deals",
}


def _idr(n) -> str:
    return "Rp " + f"{float(n or 0):,.0f}".replace(",", ".")


async def _report_sections(report: str, db: AsyncSession, user: User) -> list[dict]:
    """Build export sections for a given report tab."""
    if report == "pnl":
        d = await pnl(db=db, _u=user)
        tot = d["totals"]
        sections = [{
            "name": "P&L summary",
            "headers": ["Metric", "Value"],
            "rows": [
                ["Revenue", _idr(tot["revenue"])],
                ["COGS", _idr(tot["cogs"])],
                ["Gross profit", _idr(tot["gross_profit"])],
                ["Expense", _idr(tot["expense"])],
                ["Operating income", _idr(tot["operating_income"])],
                ["Other income", _idr(tot["other_income"])],
                ["Other expense", _idr(tot["other_expense"])],
                ["Net income", _idr(tot["net_income"])],
            ],
        }]
        for acc_type, accs in d["by_type"].items():
            sections.append({
                "name": acc_type[:31],
                "headers": ["Account no", "Name", "Balance"],
                "rows": [[a["account_no"], a["name"], _idr(a["balance"])] for a in accs],
            })
        return sections

    if report == "ar":
        d = await ar_aging_detail(db=db, _u=user)
        bucket_rows = [[k, _idr(v)] for k, v in d["buckets"].items()]
        return [
            {"name": "AR buckets", "headers": ["Bucket", "Total"], "rows": bucket_rows},
            {
                "name": "AR detail",
                "headers": ["Invoice", "Customer", "Due date", "Days overdue", "Total", "Status"],
                "rows": [[
                    i["number"], i["customer_name"], str(i["due_date"] or ""),
                    i["days_overdue"] if i["days_overdue"] is not None else "",
                    _idr(i["total"]), i["status"],
                ] for i in d["items"]],
            },
        ]

    if report == "sales":
        d = await sales_by_person(range_days=90, db=db, _u=user)
        return [{
            "name": "Sales by salesperson",
            "headers": ["Salesperson", "Quotes", "Won", "Lost", "Win rate", "Pipeline", "Won revenue"],
            "rows": [[
                r["full_name"], r["quotations"], r["won"], r["lost"],
                f"{r['win_rate'] * 100:.1f}%", _idr(r["pipeline_value"]), _idr(r["won_revenue"]),
            ] for r in d["rows"]],
        }]

    if report == "pipeline":
        d = await pipeline_by_stage(db=db, _u=user)
        return [{
            "name": "Pipeline by stage",
            "headers": ["Stage", "Customers", "Value"],
            "rows": [[
                r["stage"].replace("_", " ").title(), r["count"], _idr(r["value"]),
            ] for r in d["rows"]],
        }]

    if report == "lost":
        d = await lost_deals(db=db, _u=user)
        return [
            {
                "name": "Lost deals",
                "headers": ["Quote", "Customer", "Industry", "Discount %", "Total", "Reason"],
                "rows": [[
                    i["number"], i["customer_name"], i["industry"],
                    f"{i['discount_pct']:.1f}", _idr(i["total"]), i["reason"],
                ] for i in d["items"]],
            },
            {
                "name": "By reason",
                "headers": ["Reason", "Count"],
                "rows": [[k, v] for k, v in d["by_reason"].items()],
            },
        ]

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown report '{report}'")


@router.get("/export.{ext}")
async def export_report(
    ext: str,
    report: str = Query(..., description="pnl | ar | sales | pipeline | lost"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if ext not in ("pdf", "xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ext must be pdf or xlsx")
    label = _REPORT_LABELS.get(report)
    if not label:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown report '{report}'")
    sections = await _report_sections(report, db, user)

    from app.services.tabular_export import render_pdf, render_xlsx
    if ext == "pdf":
        data = render_pdf(label, sections)
        media = "application/pdf"
    else:
        data = render_xlsx(label, sections)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    safe = report.replace(" ", "_")
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="report-{safe}.{ext}"'},
    )
