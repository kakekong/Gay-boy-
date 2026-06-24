"""Financial reporting engine.

One place that knows how the company's Chart-of-Accounts *types* roll up
into financial statements, and how to slice the transaction journal by
period. The report endpoints stay thin — they call these builders and
hand the result to the shared PDF/XLSX exporter.

Two sources of truth, used deliberately:
  • Account.balance — where things stand *right now*. Drives the
    point-in-time statements (Balance Sheet, Assets, Debt) and cash-held.
  • ledger_entries  — every movement *with a date*. Drives the flow
    statements over a chosen window (P&L for a period, cash in/out).
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.finance import LedgerEntry


# ─── Account-type taxonomy → financial-statement classification ──────────────
# These strings are exactly the `account_type` values seeded in coa_seed.py.
CASH_TYPES = {"Cash & Bank"}
ASSET_TYPES = {
    "Cash & Bank", "Receivable", "Inventory",
    "Other Current Asset", "Fixed Asset", "Accumulated Depreciation",
}
LIABILITY_TYPES = {"Payable", "Other Current Liability", "Long Term Liability"}
EQUITY_TYPES = {"Equity"}
REVENUE_TYPES = {"Revenue", "Other Income"}
EXPENSE_TYPES = {"Cost Of Good Sold", "Expense", "Other Expense"}

# Stable display order within each statement.
ASSET_ORDER = [
    "Cash & Bank", "Receivable", "Inventory",
    "Other Current Asset", "Fixed Asset", "Accumulated Depreciation",
]
LIABILITY_ORDER = ["Payable", "Other Current Liability", "Long Term Liability"]


def classify(account_type: str) -> str:
    """Map an account type to its statement bucket."""
    if account_type in ASSET_TYPES:
        return "asset"
    if account_type in LIABILITY_TYPES:
        return "liability"
    if account_type in EQUITY_TYPES:
        return "equity"
    if account_type in REVENUE_TYPES:
        return "revenue"
    if account_type in EXPENSE_TYPES:
        return "expense"
    return "other"


# ─── Period resolution ───────────────────────────────────────────────────────
_PERIODS = {
    "this_month", "last_month", "this_quarter", "last_quarter",
    "this_year", "last_year", "ytd", "all", "custom",
}


def _quarter_start(d: date) -> date:
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def resolve_period(
    period: str | None,
    frm: date | None,
    to: date | None,
    today: date,
) -> tuple[date, date, str]:
    """Return (start, end, human_label) for a report window.

    Precedence: an explicit from/to wins (custom); otherwise the named
    period; otherwise default to the current month.
    """
    if frm or to:
        start = frm or date(1900, 1, 1)
        end = to or today
        return start, end, f"{start.isoformat()} → {end.isoformat()}"

    key = period if period in _PERIODS else "this_month"

    if key == "this_month":
        start = date(today.year, today.month, 1)
        return start, today, start.strftime("%B %Y")
    if key == "last_month":
        start = _add_months(date(today.year, today.month, 1), -1)
        end = date(today.year, today.month, 1)
        end = _add_days(end, -1)
        return start, end, start.strftime("%B %Y")
    if key == "this_quarter":
        start = _quarter_start(today)
        q = (start.month - 1) // 3 + 1
        return start, today, f"Q{q} {start.year}"
    if key == "last_quarter":
        this_q = _quarter_start(today)
        start = _add_months(this_q, -3)
        end = _add_days(this_q, -1)
        q = (start.month - 1) // 3 + 1
        return start, end, f"Q{q} {start.year}"
    if key == "this_year":
        start = date(today.year, 1, 1)
        return start, today, f"FY {today.year}"
    if key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), f"FY {today.year - 1}"
    if key == "ytd":
        return date(today.year, 1, 1), today, f"YTD {today.year}"
    # "all"
    return date(1900, 1, 1), today, "All time"


def _add_days(d: date, days: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=days)


# ─── Profit & Loss ───────────────────────────────────────────────────────────
def _pnl_totals(by_type: dict[str, float]) -> dict[str, float]:
    revenue = by_type.get("Revenue", 0.0)
    other_income = by_type.get("Other Income", 0.0)
    cogs = by_type.get("Cost Of Good Sold", 0.0)
    expense = by_type.get("Expense", 0.0)
    other_expense = by_type.get("Other Expense", 0.0)
    gross_profit = revenue - cogs
    operating_income = gross_profit - expense
    net_income = operating_income + other_income - other_expense
    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "expense": expense,
        "operating_income": operating_income,
        "other_income": other_income,
        "other_expense": other_expense,
        "net_income": net_income,
    }


async def pnl_from_balances(db: AsyncSession) -> dict:
    """All-time P&L from current CoA balances (non-empty on day one)."""
    rows = (await db.scalars(select(Account))).all()
    by_type: dict[str, float] = defaultdict(float)
    by_account: dict[str, list[dict]] = defaultdict(list)
    for a in rows:
        bal = float(a.balance or 0)
        if a.is_parent or not bal or a.account_type not in (REVENUE_TYPES | EXPENSE_TYPES):
            continue
        by_type[a.account_type] += bal
        by_account[a.account_type].append(
            {"account_no": a.account_no, "name": a.name, "amount": bal}
        )
    return {"totals": _pnl_totals(by_type), "by_type": by_account, "source": "balances"}


async def pnl_from_journal(db: AsyncSession, start: date, end: date) -> dict:
    """P&L for [start, end] from the transaction journal."""
    rows = (await db.execute(
        select(
            LedgerEntry.account_type,
            LedgerEntry.account_no,
            LedgerEntry.account_name,
            func.sum(LedgerEntry.amount).label("amount"),
        )
        .where(
            LedgerEntry.entry_date >= start,
            LedgerEntry.entry_date <= end,
            LedgerEntry.account_type.in_(REVENUE_TYPES | EXPENSE_TYPES),
        )
        .group_by(LedgerEntry.account_type, LedgerEntry.account_no, LedgerEntry.account_name)
    )).all()
    by_type: dict[str, float] = defaultdict(float)
    by_account: dict[str, list[dict]] = defaultdict(list)
    for atype, ano, aname, amount in rows:
        amt = float(amount or 0)
        if not amt:
            continue
        by_type[atype] += amt
        by_account[atype].append({"account_no": ano, "name": aname, "amount": amt})
    return {"totals": _pnl_totals(by_type), "by_type": by_account, "source": "journal"}


# ─── Balance Sheet / Assets / Liabilities (point-in-time from balances) ──────
async def _balances_by_type(db: AsyncSession) -> tuple[dict[str, list[dict]], dict[str, float]]:
    rows = (await db.scalars(select(Account))).all()
    accounts: dict[str, list[dict]] = defaultdict(list)
    totals: dict[str, float] = defaultdict(float)
    for a in rows:
        bal = float(a.balance or 0)
        if a.is_parent or not bal:
            continue
        accounts[a.account_type].append(
            {"account_no": a.account_no, "name": a.name, "amount": bal}
        )
        totals[a.account_type] += bal
    return accounts, totals


async def balance_sheet(db: AsyncSession) -> dict:
    """Assets / Liabilities / Equity as they stand right now."""
    accounts, totals = await _balances_by_type(db)
    total_assets = sum(totals.get(t, 0.0) for t in ASSET_TYPES)
    total_liabilities = sum(totals.get(t, 0.0) for t in LIABILITY_TYPES)
    total_equity = sum(totals.get(t, 0.0) for t in EQUITY_TYPES)
    # Profit not yet rolled into equity = revenue − expenses (current earnings).
    pnl = _pnl_totals(totals)
    retained = pnl["net_income"]
    return {
        "assets": {
            "by_type": {t: accounts.get(t, []) for t in ASSET_ORDER if accounts.get(t)},
            "type_totals": {t: totals.get(t, 0.0) for t in ASSET_ORDER if totals.get(t)},
            "total": total_assets,
        },
        "liabilities": {
            "by_type": {t: accounts.get(t, []) for t in LIABILITY_ORDER if accounts.get(t)},
            "type_totals": {t: totals.get(t, 0.0) for t in LIABILITY_ORDER if totals.get(t)},
            "total": total_liabilities,
        },
        "equity": {
            "by_type": {"Equity": accounts.get("Equity", [])},
            "total": total_equity,
            "current_earnings": retained,
            "total_with_earnings": total_equity + retained,
        },
        "balanced": abs(total_assets - (total_liabilities + total_equity + retained)) < 1.0,
    }


# ─── Cash position + cash flow ───────────────────────────────────────────────
async def cash_summary(db: AsyncSession, start: date, end: date) -> dict:
    """Cash held now (per Cash & Bank account) + money in/out for the window."""
    accounts = (await db.scalars(
        select(Account).where(
            Account.account_type.in_(CASH_TYPES), Account.is_parent.is_(False)
        ).order_by(Account.account_no)
    )).all()
    held = [
        {"account_no": a.account_no, "name": a.name, "balance": float(a.balance or 0)}
        for a in accounts if float(a.balance or 0)
    ]
    total_held = sum(h["balance"] for h in held)

    money_in = float(await db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.cash_delta), 0)).where(
            LedgerEntry.entry_date >= start, LedgerEntry.entry_date <= end,
            LedgerEntry.cash_delta > 0,
        )
    ) or 0)
    money_out = float(await db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.cash_delta), 0)).where(
            LedgerEntry.entry_date >= start, LedgerEntry.entry_date <= end,
            LedgerEntry.cash_delta < 0,
        )
    ) or 0)
    return {
        "held": held,
        "total_held": total_held,
        "money_in": money_in,
        "money_out": -money_out,   # report as a positive outflow
        "net_flow": money_in + money_out,
    }
