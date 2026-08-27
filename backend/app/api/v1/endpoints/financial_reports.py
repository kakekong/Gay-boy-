"""Finance reporting surface — the printable, period-aware financial reports.

Mounted at /finance/reports and gated to the finance line + management
(same audience as the rest of /finance). Everything here is read-only and
derives from the Chart of Accounts and the transaction journal:

  • transactions   — every journal line for the window (the audit trail)
  • cash           — cash held now + money in / out for the window
  • profit-loss    — income statement (all-time from balances, or a period)
  • balance-sheet  — assets vs liabilities + equity, as they stand now
  • assets         — asset breakdown
  • liabilities    — debt breakdown
  • by-salesperson — revenue + cash collected per sales rep
  • salesperson/{id} — one rep's financial report

Each report has matching export.pdf / export.xlsx endpoints that reuse the
shared tabular exporter.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.crm import Customer
from app.models.finance import LedgerEntry
from app.models.quotation import Quotation
from app.models.user import User
from app.services import financials as fin
from app.services.ledger import compute_amounts

router = APIRouter(
    dependencies=[Depends(require(Role.FINANCE, Role.ADMIN, Role.MANAGER, Role.DIRECTOR))]
)


def _today() -> date:
    from datetime import UTC, datetime
    return datetime.now(UTC).date()


def _window(
    period: str | None,
    frm: date | None,
    to: date | None,
) -> tuple[date, date, str]:
    return fin.resolve_period(period, frm, to, _today())


def _idr(n) -> str:
    return "Rp " + f"{int(round(float(n or 0))):,}".replace(",", ".")


# ─── Transactions (the journal) ──────────────────────────────────────────────
async def _r_transactions(
    db: AsyncSession, start: date, end: date,
    account_no: str | None = None, source_type: str | None = None,
    sales_pic_id: UUID | None = None, limit: int = 1000,
) -> dict:
    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.entry_date >= start, LedgerEntry.entry_date <= end)
        .order_by(LedgerEntry.entry_date.desc(), LedgerEntry.created_at.desc())
        .limit(max(1, min(limit, 5000)))
    )
    if account_no:
        stmt = stmt.where(LedgerEntry.account_no == account_no)
    if source_type:
        stmt = stmt.where(LedgerEntry.source_type == source_type)
    if sales_pic_id:
        stmt = stmt.where(LedgerEntry.sales_pic_id == sales_pic_id)
    rows = (await db.scalars(stmt)).all()

    total_in = sum(float(e.cash_delta) for e in rows if float(e.cash_delta) > 0)
    total_out = sum(float(e.cash_delta) for e in rows if float(e.cash_delta) < 0)
    return {
        "entries": [
            {
                "id": str(e.id), "entry_date": e.entry_date,
                "account_no": e.account_no, "account_name": e.account_name,
                "account_type": e.account_type, "amount": float(e.amount),
                "cash_delta": float(e.cash_delta), "source_type": e.source_type,
                "source_ref": e.source_ref, "memo": e.memo,
                "sales_pic_id": str(e.sales_pic_id) if e.sales_pic_id else None,
            } for e in rows
        ],
        "count": len(rows),
        "cash_in": total_in,
        "cash_out": -total_out,
    }


def _sections_transactions(p: dict) -> list[dict]:
    return [{
        "name": "Transactions",
        "headers": ["Date", "Account", "Name", "Type", "Amount", "Cash", "Source", "Ref", "Memo"],
        "rows": [[
            str(e["entry_date"]), e["account_no"], e["account_name"] or "",
            e["account_type"], _idr(e["amount"]),
            _idr(e["cash_delta"]) if e["cash_delta"] else "",
            e["source_type"], e["source_ref"] or "", (e["memo"] or "")[:60],
        ] for e in p["entries"]],
    }]


# ─── Cash ────────────────────────────────────────────────────────────────────
async def _r_cash(db: AsyncSession, start: date, end: date) -> dict:
    return await fin.cash_summary(db, start, end)


def _sections_cash(p: dict) -> list[dict]:
    return [
        {"name": "Cash summary", "headers": ["Metric", "Amount"], "rows": [
            ["Cash held (now)", _idr(p["total_held"])],
            ["Money in (period)", _idr(p["money_in"])],
            ["Money out (period)", _idr(p["money_out"])],
            ["Net cash flow", _idr(p["net_flow"])],
        ]},
        {"name": "Cash accounts", "headers": ["Account", "Name", "Balance"],
         "rows": [[h["account_no"], h["name"], _idr(h["balance"])] for h in p["held"]]},
    ]


# ─── Profit & Loss ───────────────────────────────────────────────────────────
async def _r_pnl(db: AsyncSession, start: date, end: date, period: str | None,
                 *, dated: bool = False) -> dict:
    # A specific period reads the dated journal; the bare default and "all"
    # show the all-time picture from balances so it's never empty on day
    # one, before the journal has accumulated history.
    #
    # `dated` is set when the caller gave an explicit from/to. Without it,
    # an explicit window with no `period` fell through to the all-time
    # figures while the response still carried the requested dates — a
    # report that said "January" and showed every January there had ever
    # been.
    if dated or (period and period != "all"):
        return await fin.pnl_from_journal(db, start, end)
    return await fin.pnl_from_balances(db)


def _sections_pnl(p: dict) -> list[dict]:
    t = p["totals"]
    secs = [{"name": "Profit & Loss", "headers": ["Metric", "Amount"], "rows": [
        ["Revenue", _idr(t["revenue"])],
        ["COGS", _idr(t["cogs"])],
        ["Gross profit", _idr(t["gross_profit"])],
        ["Operating expense", _idr(t["expense"])],
        ["Operating income", _idr(t["operating_income"])],
        ["Other income", _idr(t["other_income"])],
        ["Other expense", _idr(t["other_expense"])],
        ["Net income", _idr(t["net_income"])],
    ]}]
    for atype, accs in p["by_type"].items():
        secs.append({
            "name": atype[:31], "headers": ["Account", "Name", "Amount"],
            "rows": [[a["account_no"], a["name"], _idr(a["amount"])] for a in accs],
        })
    return secs


# ─── Balance sheet / Assets / Liabilities ────────────────────────────────────
async def _r_balance_sheet(db: AsyncSession) -> dict:
    return await fin.balance_sheet(db)


def _sections_balance_sheet(p: dict) -> list[dict]:
    a, lia, eq = p["assets"], p["liabilities"], p["equity"]
    summary = {"name": "Balance sheet", "headers": ["Section", "Amount"], "rows": [
        ["Total assets", _idr(a["total"])],
        ["Total liabilities", _idr(lia["total"])],
        ["Equity", _idr(eq["total"])],
        ["Current earnings", _idr(eq["current_earnings"])],
        ["Liabilities + equity", _idr(lia["total"] + eq["total_with_earnings"])],
    ]}
    secs = [summary]
    for label, blk in (("Assets", a), ("Liabilities", lia)):
        for atype, accs in blk["by_type"].items():
            secs.append({
                "name": f"{label}: {atype}"[:31],
                "headers": ["Account", "Name", "Balance"],
                "rows": [[x["account_no"], x["name"], _idr(x["amount"])] for x in accs],
            })
    if eq["by_type"].get("Equity"):
        secs.append({
            "name": "Equity",
            "headers": ["Account", "Name", "Balance"],
            "rows": [[x["account_no"], x["name"], _idr(x["amount"])]
                     for x in eq["by_type"]["Equity"]],
        })
    return secs


def _sections_assets(p: dict) -> list[dict]:
    a = p["assets"]
    secs = [{"name": "Assets total", "headers": ["Type", "Amount"],
             "rows": [[t, _idr(v)] for t, v in a["type_totals"].items()]
                     + [["TOTAL ASSETS", _idr(a["total"])]]}]
    for atype, accs in a["by_type"].items():
        secs.append({
            "name": atype[:31], "headers": ["Account", "Name", "Balance"],
            "rows": [[x["account_no"], x["name"], _idr(x["amount"])] for x in accs],
        })
    return secs


def _sections_liabilities(p: dict) -> list[dict]:
    lia = p["liabilities"]
    secs = [{"name": "Debt total", "headers": ["Type", "Amount"],
             "rows": [[t, _idr(v)] for t, v in lia["type_totals"].items()]
                     + [["TOTAL LIABILITIES", _idr(lia["total"])]]}]
    for atype, accs in lia["by_type"].items():
        secs.append({
            "name": atype[:31], "headers": ["Account", "Name", "Balance"],
            "rows": [[x["account_no"], x["name"], _idr(x["amount"])] for x in accs],
        })
    return secs


# ─── Per-salesperson ─────────────────────────────────────────────────────────
async def _sales_revenue_rows(
    db: AsyncSession, start: date, end: date, user_id: UUID | None = None,
) -> dict[UUID, dict]:
    """Won-quotation revenue per sales rep within the window (revenue =
    subtotal − discount, matching what posts to the ledger)."""
    stmt = select(Quotation).where(
        Quotation.status == "won",
        Quotation.created_at >= start,
        Quotation.created_at <= _end_of_day(end),
    )
    if user_id:
        stmt = stmt.where(Quotation.sales_pic_id == user_id)
    quotes = (await db.scalars(stmt)).all()
    agg: dict[UUID, dict] = {}
    for q in quotes:
        if not q.sales_pic_id:
            continue
        a = compute_amounts(q)
        d = agg.setdefault(q.sales_pic_id, {"deals_won": 0, "revenue": 0.0, "total": 0.0})
        d["deals_won"] += 1
        d["revenue"] += a["revenue"]
        d["total"] += float(q.total or 0)
    return agg


def _end_of_day(d: date):
    from datetime import datetime, time
    return datetime.combine(d, time.max)


async def _cash_collected_by_sales(
    db: AsyncSession, start: date, end: date, user_id: UUID | None = None,
) -> dict[UUID, float]:
    stmt = (
        select(LedgerEntry.sales_pic_id, func.coalesce(func.sum(LedgerEntry.cash_delta), 0))
        .where(
            LedgerEntry.entry_date >= start, LedgerEntry.entry_date <= end,
            LedgerEntry.cash_delta > 0, LedgerEntry.sales_pic_id.is_not(None),
        )
        .group_by(LedgerEntry.sales_pic_id)
    )
    if user_id:
        stmt = stmt.where(LedgerEntry.sales_pic_id == user_id)
    rows = (await db.execute(stmt)).all()
    return {sid: float(v or 0) for sid, v in rows}


async def _r_by_salesperson(db: AsyncSession, start: date, end: date) -> dict:
    sales = (await db.scalars(
        select(User).where(User.is_active.is_(True), User.role == "sales")
        .order_by(User.full_name)
    )).all()
    revenue = await _sales_revenue_rows(db, start, end)
    cash = await _cash_collected_by_sales(db, start, end)
    rows = []
    for u in sales:
        r = revenue.get(u.id, {"deals_won": 0, "revenue": 0.0, "total": 0.0})
        rows.append({
            "user_id": str(u.id), "full_name": u.full_name,
            "deals_won": r["deals_won"], "revenue": r["revenue"],
            "won_total": r["total"], "cash_collected": cash.get(u.id, 0.0),
        })
    rows.sort(key=lambda x: -x["revenue"])
    return {"rows": rows}


def _sections_by_salesperson(p: dict) -> list[dict]:
    return [{
        "name": "By salesperson",
        "headers": ["Salesperson", "Deals won", "Revenue", "Won total", "Cash collected"],
        "rows": [[
            r["full_name"], r["deals_won"], _idr(r["revenue"]),
            _idr(r["won_total"]), _idr(r["cash_collected"]),
        ] for r in p["rows"]],
    }]


async def _r_salesperson(db: AsyncSession, start: date, end: date, user_id: UUID) -> dict:
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Salesperson not found")
    rev = (await _sales_revenue_rows(db, start, end, user_id)).get(
        user_id, {"deals_won": 0, "revenue": 0.0, "total": 0.0})
    cash = (await _cash_collected_by_sales(db, start, end, user_id)).get(user_id, 0.0)
    # Their journal lines in the window
    tx = await _r_transactions(db, start, end, sales_pic_id=user_id, limit=2000)
    # Their won quotations
    quotes = (await db.scalars(
        select(Quotation).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won",
            Quotation.created_at >= start, Quotation.created_at <= _end_of_day(end),
        ).order_by(Quotation.created_at.desc())
    )).all()
    cust_ids = {q.customer_id for q in quotes if q.customer_id}
    names: dict = {}
    if cust_ids:
        for c in (await db.scalars(select(Customer).where(Customer.id.in_(cust_ids)))).all():
            names[c.id] = c.company_name
    return {
        "user": {"id": str(u.id), "full_name": u.full_name},
        "summary": {
            "deals_won": rev["deals_won"], "revenue": rev["revenue"],
            "won_total": rev["total"], "cash_collected": cash,
        },
        "quotations": [
            {"number": q.number, "customer_name": names.get(q.customer_id),
             "total": float(q.total or 0), "revenue": compute_amounts(q)["revenue"]}
            for q in quotes
        ],
        "transactions": tx["entries"],
    }


def _sections_salesperson(p: dict) -> list[dict]:
    s = p["summary"]
    return [
        {"name": "Summary", "headers": ["Metric", "Amount"], "rows": [
            ["Salesperson", p["user"]["full_name"]],
            ["Deals won", s["deals_won"]],
            ["Revenue", _idr(s["revenue"])],
            ["Won total (incl. tax)", _idr(s["won_total"])],
            ["Cash collected", _idr(s["cash_collected"])],
        ]},
        {"name": "Won quotations",
         "headers": ["Quotation", "Customer", "Revenue", "Total"],
         "rows": [[q["number"], q["customer_name"] or "—", _idr(q["revenue"]),
                   _idr(q["total"])] for q in p["quotations"]]},
        {"name": "Transactions",
         "headers": ["Date", "Account", "Amount", "Cash", "Source", "Ref"],
         "rows": [[str(e["entry_date"]), e["account_name"] or e["account_no"],
                   _idr(e["amount"]), _idr(e["cash_delta"]) if e["cash_delta"] else "",
                   e["source_type"], e["source_ref"] or ""]
                  for e in p["transactions"]]},
    ]


# ─── JSON endpoints ──────────────────────────────────────────────────────────
@router.get("/transactions")
async def transactions(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    account_no: str | None = None, source_type: str | None = None,
    sales_pic_id: UUID | None = None, limit: int = 1000,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    p = await _r_transactions(db, start, end, account_no, source_type, sales_pic_id, limit)
    return {"period": label, "start": start, "end": end, **p}


@router.get("/cash")
async def cash(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    return {"period": label, "start": start, "end": end, **await _r_cash(db, start, end)}


@router.get("/profit-loss")
async def profit_loss(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    d = await _r_pnl(db, start, end, period, dated=bool(frm or to))
    return {"period": label if d["source"] == "journal" else "All time",
            "start": start, "end": end, **d}


@router.get("/balance-sheet")
async def balance_sheet_ep(
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    return {"as_of": _today(), **await _r_balance_sheet(db)}


@router.get("/assets")
async def assets(
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    return {"as_of": _today(), **await _r_balance_sheet(db)}


@router.get("/liabilities")
async def liabilities(
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    return {"as_of": _today(), **await _r_balance_sheet(db)}


@router.get("/by-salesperson")
async def by_salesperson(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    return {"period": label, "start": start, "end": end,
            **await _r_by_salesperson(db, start, end)}


@router.get("/salesperson/{user_id}")
async def salesperson(
    user_id: UUID, period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    return {"period": label, "start": start, "end": end,
            **await _r_salesperson(db, start, end, user_id)}


# ─── Exports ─────────────────────────────────────────────────────────────────
_LABELS = {
    "transactions": "Transactions journal",
    "cash": "Cash report",
    "profit-loss": "Profit & Loss",
    "balance-sheet": "Balance Sheet",
    "assets": "Assets",
    "liabilities": "Debt & Liabilities",
    "by-salesperson": "Financials by salesperson",
}


async def _build_sections(
    report: str, db: AsyncSession, start: date, end: date,
    period: str | None, user_id: UUID | None, dated: bool = False,
) -> tuple[str, list[dict]]:
    if report == "transactions":
        return _LABELS[report], _sections_transactions(await _r_transactions(db, start, end))
    if report == "cash":
        return _LABELS[report], _sections_cash(await _r_cash(db, start, end))
    if report == "profit-loss":
        return _LABELS[report], _sections_pnl(
            await _r_pnl(db, start, end, period, dated=dated))
    if report == "balance-sheet":
        return _LABELS[report], _sections_balance_sheet(await _r_balance_sheet(db))
    if report == "assets":
        return _LABELS[report], _sections_assets(await _r_balance_sheet(db))
    if report == "liabilities":
        return _LABELS[report], _sections_liabilities(await _r_balance_sheet(db))
    if report == "by-salesperson":
        return _LABELS[report], _sections_by_salesperson(await _r_by_salesperson(db, start, end))
    if report == "salesperson" and user_id:
        p = await _r_salesperson(db, start, end, user_id)
        return f"Financials — {p['user']['full_name']}", _sections_salesperson(p)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown report '{report}'")


async def _export(
    ext: str, report: str, db: AsyncSession, start: date, end: date,
    label: str, period: str | None, user_id: UUID | None, dated: bool = False,
) -> Response:
    # `dated` travels with the window so a printed report shows the same
    # figures the screen did — see _r_pnl.
    title, sections = await _build_sections(report, db, start, end, period,
                                            user_id, dated)
    full_title = f"{title} · {label}"
    from app.services.tabular_export import render_pdf, render_xlsx
    if ext == "pdf":
        data, media = render_pdf(full_title, sections), "application/pdf"
    else:
        data = render_xlsx(full_title, sections)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    safe = report.replace("/", "-")
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="finance-{safe}.{ext}"'})


# Exports live under /export/<report>.<ext> so the report name can't be
# mistaken for a {user_id} on the /salesperson/{user_id} route.
@router.get("/export/{report}.pdf")
async def export_pdf(
    report: str, period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    user_id: UUID | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    return await _export("pdf", report, db, start, end, label, period,
                         user_id, bool(frm or to))


@router.get("/export/{report}.xlsx")
async def export_xlsx(
    report: str, period: str | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    user_id: UUID | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    start, end, label = _window(period, frm, to)
    return await _export("xlsx", report, db, start, end, label, period,
                         user_id, bool(frm or to))


# ─── Daftar Laporan ──────────────────────────────────────────────────────────
# The catalogue itself, and the six variants of the profit report that all
# come off one engine. Building them separately would mean six chances for
# the same account to be classified two different ways — and the first time
# the quarterly report disagreed with the monthly one, nobody would know
# which was right.

from app.services import reports_multi as multi  # noqa: E402

CATALOGUE = [
    {"key": "pnl", "group": "Laba Rugi",
     "name": "Laba Rugi (Standar)", "name_en": "Profit & Loss (standard)",
     "path": "/finance/reports/profit-loss", "params": ["period", "from", "to"],
     "about": "One period, account by account."},
    {"key": "pnl-monthly", "group": "Laba Rugi",
     "name": "Laba Rugi Multi Periode", "name_en": "P&L, month by month",
     "path": "/finance/reports/pnl-columns?basis=monthly",
     "params": ["year", "months"],
     "about": "Every month of a year side by side, so a trend is visible "
              "rather than inferred."},
    {"key": "pnl-quarterly", "group": "Laba Rugi",
     "name": "Laba Rugi per Kuartal", "name_en": "P&L by quarter",
     "path": "/finance/reports/pnl-columns?basis=quarterly", "params": ["year"],
     "about": "Four columns, one year."},
    {"key": "pnl-yearly", "group": "Laba Rugi",
     "name": "Laba Rugi Multi Tahun", "name_en": "P&L, year on year",
     "path": "/finance/reports/pnl-columns?basis=yearly",
     "params": ["year", "years"],
     "about": "Several years side by side."},
    {"key": "pnl-compare", "group": "Laba Rugi",
     "name": "Laba Rugi Perbandingan Periode",
     "name_en": "P&L, period against period",
     "path": "/finance/reports/pnl-columns?basis=compare",
     "params": ["year", "month"],
     "about": "This period against the one before it, with the difference."},
    {"key": "pnl-budget", "group": "Laba Rugi",
     "name": "Laba Rugi Perbandingan Anggaran",
     "name_en": "P&L against budget",
     "path": "/finance/reports/pnl-budget", "params": ["year", "month"],
     "about": "Actual against what was planned, on the same basis Monitor "
              "Anggaran uses."},
    {"key": "balance-sheet", "group": "Neraca",
     "name": "Neraca (Standar)", "name_en": "Balance sheet (standard)",
     "path": "/finance/reports/balance-sheet", "params": [],
     "about": "Where we stand right now."},
    {"key": "balance-sheet-at", "group": "Neraca",
     "name": "Neraca per Tanggal", "name_en": "Balance sheet as at a date",
     "path": "/finance/reports/balance-sheet-at", "params": ["on", "compare_to"],
     "about": "As at any date, or two dates side by side — walked from the "
              "journal, because a running balance cannot answer 'as at March'."},
    {"key": "cash-flow", "group": "Arus Kas",
     "name": "Arus Kas (Tidak Langsung)",
     "name_en": "Cash flow (indirect)",
     "path": "/finance/reports/cash-flow-indirect", "params": ["year", "month"],
     "about": "From net income to the change in the bank, and whether the "
              "two agree."},
    {"key": "cash-projection", "group": "Arus Kas",
     "name": "Proyeksi Arus Kas (Komitmen)",
     "name_en": "Cash projection (from commitments)",
     "path": "/finance/reports/cash-projection?basis=commitments",
     "params": ["months"],
     "about": "From invoices already issued and not yet paid. Conservative: "
              "it projects nothing that has not been agreed."},
    {"key": "cash-projection-budget", "group": "Arus Kas",
     "name": "Proyeksi Arus Kas (Anggaran)",
     "name_en": "Cash projection (from budget)",
     "path": "/finance/reports/cash-projection?basis=budget",
     "params": ["months"],
     "about": "From the plan rather than from obligations — it covers months "
              "no invoice exists for yet."},
]


@router.get("/catalogue")
async def catalogue(_u: User = Depends(get_current_user)):
    """Daftar Laporan — what can be run, and what each one is for."""
    return {"reports": CATALOGUE,
            "groups": list(dict.fromkeys(r["group"] for r in CATALOGUE))}


@router.get("/pnl-columns")
async def pnl_columns(
    basis: str = "monthly",
    year: int | None = None,
    month: int | None = None,
    months: int = 12,
    years: int = 3,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    """The profit report over several spans at once.

    Four shapes, one engine: by month, by quarter, by year, and this period
    against the one before it.
    """
    year = year or _today().year
    if basis == "quarterly":
        spans = multi.quarter_spans(year)
    elif basis == "yearly":
        span_years = list(range(year - max(1, min(years, 10)) + 1, year + 1))
        spans = multi.year_spans(span_years)
    elif basis == "compare":
        month = month or _today().month
        prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
        spans = (multi.month_spans(prev_year, [prev_month])
                 + multi.month_spans(year, [month]))
    else:
        basis = "monthly"
        spans = multi.month_spans(year, list(range(1, max(1, min(months, 12)) + 1)))

    data = await multi.pnl_columns(db, spans)
    if basis == "compare" and len(data["columns"]) == 2:
        # The reason to run this rather than two reports: the difference,
        # worked out once rather than by eye.
        for section in data["sections"]:
            for row in section["accounts"]:
                row["change"] = round(row["values"][1] - row["values"][0], 2)
            section["change"] = round(section["totals"][1] - section["totals"][0], 2)
        data["change"] = {
            k: round(data["column_totals"][1][k] - data["column_totals"][0][k], 2)
            for k in data["column_totals"][0]
        }
    return {"basis": basis, "year": year, **data}


@router.get("/pnl-budget")
async def pnl_budget(
    year: int | None = None, month: int | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Laba Rugi Perbandingan Anggaran."""
    return await multi.pnl_vs_budget(db, year=year or _today().year, month=month)


@router.get("/balance-sheet-at")
async def balance_sheet_at(
    on: date | None = None, compare_to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Neraca per Tanggal, optionally beside a second date."""
    return await multi.balance_sheet_at(db, on or _today(), compare_to)


@router.get("/cash-flow-indirect")
async def cash_flow_indirect(
    year: int | None = None, month: int | None = None,
    frm: date | None = Query(None, alias="from"), to: date | None = None,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Arus Kas (tidak langsung), with its own reconciliation."""
    today = _today()
    if frm and to:
        start, end = frm, to
    elif month:
        year = year or today.year
        start, end = date(year, month, 1), multi.month_end(year, month)
    else:
        year = year or today.year
        start, end = date(year, 1, 1), date(year, 12, 31)
    return await multi.cash_flow_indirect(db, start, end)


@router.get("/cash-projection")
async def cash_projection(
    basis: str = "commitments", months: int = 6,
    db: AsyncSession = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Proyeksi Arus Kas, from obligations or from the plan."""
    if basis not in ("commitments", "budget"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "basis is 'commitments' or 'budget'.")
    return await multi.cash_projection(db, months=months, basis=basis)
