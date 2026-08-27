"""The report catalogue's engine: one P&L, many columns.

Six of the reports in Daftar Laporan are the same profit-and-loss shown
over different spans — by month, by quarter, by year, this period against
last, this period against budget. Building them as six reports would mean
six chances for the same account to be classified two different ways, and
the first time the quarterly report disagreed with the monthly one, nobody
would know which was right.

So there is one engine. Give it a list of spans and it returns the P&L over
each, as columns against a single set of account rows. The variants differ
only in how the spans are built and what the last column is drawn from.

Two decisions worth stating:

- **The ledger, not the balances.** Account balances answer "where do we
  stand", which is the wrong question for a report that has a start date.
  Every column here is summed from posted journal lines inside its span.
- **Rows exist wherever any column has activity.** An account that earned
  something in January and nothing in February appears in both, at zero in
  February — otherwise the columns do not line up and the comparison is
  eyeballed rather than read.
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Budget
from app.models.journal import CREDIT_NORMAL, JournalEntry, JournalLine

# The P&L account types, in the order a profit report reads.
PNL_ORDER = ["Revenue", "Cost Of Good Sold", "Expense", "Other Income",
             "Other Expense"]
ASSET_TYPES = {"Cash & Bank", "Receivable", "Inventory", "Other Current Asset",
               "Fixed Asset"}
CONTRA_ASSET = {"Accumulated Depreciation"}
LIABILITY_TYPES = {"Payable", "Other Current Liability", "Long Term Liability"}
EQUITY_TYPES = {"Equity"}


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def month_spans(year: int, months: list[int]) -> list[dict]:
    return [{"label": f"{m:02d}/{year}", "year": year, "month": m,
             "from": date(year, m, 1), "to": month_end(year, m)}
            for m in months]


def quarter_spans(year: int) -> list[dict]:
    out = []
    for q in range(1, 5):
        first = (q - 1) * 3 + 1
        out.append({"label": f"Q{q} {year}", "year": year, "quarter": q,
                    "from": date(year, first, 1),
                    "to": month_end(year, first + 2)})
    return out


def year_spans(years: list[int]) -> list[dict]:
    return [{"label": str(y), "year": y,
             "from": date(y, 1, 1), "to": date(y, 12, 31)} for y in years]


def totals(by_type: dict[str, float]) -> dict[str, float]:
    """The subtotals a profit report is actually read for.

    Kept identical to app.services.financials._pnl_totals on purpose: two
    definitions of gross profit in one system is a disagreement waiting to
    be found by a customer rather than by us.
    """
    revenue = by_type.get("Revenue", 0.0)
    other_income = by_type.get("Other Income", 0.0)
    cogs = by_type.get("Cost Of Good Sold", 0.0)
    expense = by_type.get("Expense", 0.0)
    other_expense = by_type.get("Other Expense", 0.0)
    gross = round(revenue - cogs, 2)
    operating = round(gross - expense, 2)
    return {
        "revenue": round(revenue, 2), "cogs": round(cogs, 2),
        "gross_profit": gross, "expense": round(expense, 2),
        "operating_income": operating,
        "other_income": round(other_income, 2),
        "other_expense": round(other_expense, 2),
        "net_income": round(operating + other_income - other_expense, 2),
    }


async def _pnl_span(db: AsyncSession, start: date, end: date
                    ) -> tuple[dict[str, float], dict[str, tuple[str, str]]]:
    """One span's P&L, per account, signed the way the account is read."""
    rows = (await db.execute(
        select(JournalLine.account_no, JournalLine.account_type,
               JournalLine.account_name,
               func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
        .where(JournalEntry.is_posted.is_(True),
               JournalEntry.entry_date >= start,
               JournalEntry.entry_date <= end,
               JournalLine.account_type.in_(PNL_ORDER))
        .group_by(JournalLine.account_no, JournalLine.account_type,
                  JournalLine.account_name))).all()
    amounts: dict[str, float] = {}
    meta: dict[str, tuple[str, str]] = {}
    for no, kind, name, debit, credit in rows:
        signed = (float(credit) - float(debit)) if kind in CREDIT_NORMAL \
            else (float(debit) - float(credit))
        amounts[no] = round(amounts.get(no, 0.0) + signed, 2)
        meta[no] = (kind, name)
    return amounts, meta


async def pnl_columns(db: AsyncSession, spans: list[dict]) -> dict:
    """The P&L over several spans, as columns against one set of rows."""
    per_span: list[dict[str, float]] = []
    meta: dict[str, tuple[str, str]] = {}
    for span in spans:
        amounts, m = await _pnl_span(db, span["from"], span["to"])
        per_span.append(amounts)
        meta.update(m)

    numbers = sorted(meta)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for no in numbers:
        kind, name = meta[no]
        values = [col.get(no, 0.0) for col in per_span]
        if not any(values):
            continue
        by_type[kind].append({
            "account_no": no, "name": name, "account_type": kind,
            "values": values, "total": round(sum(values), 2),
        })

    column_totals = []
    for col in per_span:
        per_type: dict[str, float] = defaultdict(float)
        for no, amount in col.items():
            per_type[meta[no][0]] += amount
        column_totals.append(totals(per_type))

    return {
        "columns": [{"label": s["label"], "from": s["from"], "to": s["to"]}
                    for s in spans],
        "sections": [{"account_type": kind, "accounts": by_type[kind],
                      "totals": [round(sum(a["values"][i] for a in by_type[kind]), 2)
                                 for i in range(len(spans))]}
                     for kind in PNL_ORDER if by_type.get(kind)],
        "column_totals": column_totals,
    }


async def pnl_vs_budget(db: AsyncSession, *, year: int,
                        month: int | None = None) -> dict:
    """Laba/Rugi Perbandingan Anggaran — actual against what was planned.

    The budget side falls back to a twelfth of the annual figure for a
    month with none of its own, the same rule Monitor Anggaran uses. Two
    rules for the same question would mean the profit report and the budget
    screen disagreeing about whether a department overspent.
    """
    if month:
        start, end = date(year, month, 1), month_end(year, month)
        label = f"{month:02d}/{year}"
    else:
        start, end = date(year, 1, 1), date(year, 12, 31)
        label = str(year)

    actual, meta = await _pnl_span(db, start, end)

    if month:
        rows = (await db.scalars(select(Budget).where(
            Budget.period_year == year, Budget.period_month == month))).all()
        planned = {r.account_no: float(r.amount or 0) for r in rows}
        basis = {no: "monthly" for no in planned}
    else:
        rows = (await db.execute(
            select(Budget.account_no, func.coalesce(func.sum(Budget.amount), 0))
            .where(Budget.period_year == year, Budget.period_month.is_not(None))
            .group_by(Budget.account_no))).all()
        planned = {no: float(v) for no, v in rows}
        basis = {no: "monthly total" for no in planned}

    annual = (await db.scalars(select(Budget).where(
        Budget.period_year == year, Budget.period_month.is_(None)))).all()
    for r in annual:
        if r.account_no in planned:
            continue
        planned[r.account_no] = round(float(r.amount or 0) / 12, 2) if month \
            else float(r.amount or 0)
        basis[r.account_no] = "annual pro-rated" if month else "annual"

    # Budgets can name accounts the ledger has not touched this period; those
    # rows belong in the report at zero actual, because "budgeted and not
    # spent" is exactly what somebody is looking for.
    unseen = {no for no in planned if no not in meta}
    if unseen:
        for a in (await db.scalars(
                select(Account).where(Account.account_no.in_(unseen)))).all():
            meta[a.account_no] = (a.account_type, a.name)

    by_type: dict[str, list[dict]] = defaultdict(list)
    for no in sorted(meta):
        kind, name = meta[no]
        if kind not in PNL_ORDER:
            continue
        got, want = round(actual.get(no, 0.0), 2), round(planned.get(no, 0.0), 2)
        if not got and not want:
            continue
        by_type[kind].append({
            "account_no": no, "name": name, "account_type": kind,
            "actual": got, "budget": want,
            "variance": round(want - got, 2),
            "basis": basis.get(no, "unbudgeted"),
            "used_pct": round(got / want * 100, 1) if want else None,
        })

    actual_by_type: dict[str, float] = defaultdict(float)
    budget_by_type: dict[str, float] = defaultdict(float)
    for kind, accs in by_type.items():
        for a in accs:
            actual_by_type[kind] += a["actual"]
            budget_by_type[kind] += a["budget"]

    return {
        "label": label, "from": start, "to": end,
        "sections": [{"account_type": kind, "accounts": by_type[kind],
                      "actual": round(actual_by_type[kind], 2),
                      "budget": round(budget_by_type[kind], 2),
                      "variance": round(budget_by_type[kind]
                                        - actual_by_type[kind], 2)}
                     for kind in PNL_ORDER if by_type.get(kind)],
        "actual_totals": totals(actual_by_type),
        "budget_totals": totals(budget_by_type),
    }


# ─── Balance sheet as at a date ──────────────────────────────────────────────

async def balances_at(db: AsyncSession, on: date) -> dict[str, dict]:
    """Every account's balance as at the end of a given day, from the journal.

    The chart of accounts carries a running balance, which answers "where do
    we stand now" and cannot answer "where did we stand in March". This
    walks the posted entries up to the date instead, which is the only way
    a comparative balance sheet means anything.
    """
    rows = (await db.execute(
        select(JournalLine.account_no, JournalLine.account_type,
               JournalLine.account_name,
               func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
        .where(JournalEntry.is_posted.is_(True),
               JournalEntry.entry_date <= on)
        .group_by(JournalLine.account_no, JournalLine.account_type,
                  JournalLine.account_name))).all()
    out: dict[str, dict] = {}
    for no, kind, name, debit, credit in rows:
        signed = (float(credit) - float(debit)) if kind in CREDIT_NORMAL \
            else (float(debit) - float(credit))
        if no in out:
            out[no]["amount"] = round(out[no]["amount"] + signed, 2)
        else:
            out[no] = {"account_no": no, "account_type": kind, "name": name,
                       "amount": round(signed, 2)}
    return out


def _classify(kind: str) -> str | None:
    if kind in ASSET_TYPES or kind in CONTRA_ASSET:
        return "assets"
    if kind in LIABILITY_TYPES:
        return "liabilities"
    if kind in EQUITY_TYPES:
        return "equity"
    return None


async def balance_sheet_at(db: AsyncSession, on: date,
                           compare_to: date | None = None) -> dict:
    """Neraca as at a date, optionally beside another date.

    Profit not yet closed into equity is shown as current earnings, the
    same way the standard balance sheet does it — a balance sheet that
    silently leaves it out does not balance, and one that silently folds it
    into Equity cannot be reconciled against the P&L.
    """
    dates = [on] + ([compare_to] if compare_to else [])
    cols = [await balances_at(db, d) for d in dates]
    numbers = sorted({no for col in cols for no in col})

    sections: dict[str, dict[str, list[dict]]] = {
        "assets": defaultdict(list), "liabilities": defaultdict(list),
        "equity": defaultdict(list),
    }
    earnings = []
    for col in cols:
        net = 0.0
        for row in col.values():
            if row["account_type"] in ("Revenue", "Other Income"):
                net += row["amount"]
            elif row["account_type"] in ("Cost Of Good Sold", "Expense",
                                         "Other Expense"):
                net -= row["amount"]
        earnings.append(round(net, 2))

    for no in numbers:
        row = next(c[no] for c in cols if no in c)
        where = _classify(row["account_type"])
        if not where:
            continue
        values = [round(c.get(no, {}).get("amount", 0.0), 2) for c in cols]
        # Accumulated depreciation reduces assets. It is credit-normal, so
        # it comes back positive and has to be carried in negative — added
        # instead, it overstates assets by twice itself and the sheet stops
        # balancing the moment anything is depreciated.
        if row["account_type"] in CONTRA_ASSET:
            values = [-v for v in values]
        if not any(values):
            continue
        sections[where][row["account_type"]].append({
            "account_no": no, "name": row["name"],
            "account_type": row["account_type"], "values": values,
        })

    def _total(where: str) -> list[float]:
        return [round(sum(a["values"][i] for accs in sections[where].values()
                          for a in accs), 2) for i in range(len(cols))]

    assets_total = _total("assets")
    liabilities_total = _total("liabilities")
    equity_total = _total("equity")
    return {
        "columns": [{"label": str(d), "on": d} for d in dates],
        "assets": {"by_type": {k: v for k, v in sections["assets"].items()},
                   "total": assets_total},
        "liabilities": {"by_type": {k: v for k, v in sections["liabilities"].items()},
                        "total": liabilities_total},
        "equity": {"by_type": {k: v for k, v in sections["equity"].items()},
                   "total": equity_total,
                   "current_earnings": earnings,
                   "total_with_earnings": [round(equity_total[i] + earnings[i], 2)
                                           for i in range(len(cols))]},
        "balanced": [abs(assets_total[i] - liabilities_total[i]
                         - equity_total[i] - earnings[i]) < 1.0
                     for i in range(len(cols))],
    }


# ─── Arus Kas (tidak langsung) ───────────────────────────────────────────────

async def cash_flow_indirect(db: AsyncSession, start: date, end: date) -> dict:
    """The indirect cash-flow statement, and the check that it is right.

    Profit is not cash. The indirect method starts from net income and
    walks it to the change in the bank by undoing everything that moved
    profit without moving money: depreciation, and every asset and
    liability that grew or shrank.

    The reason to build it this way rather than just listing the bank
    movements is the last line. The statement *derives* the change in cash;
    the bank accounts *have* a change in cash. If the two disagree,
    something is misclassified — and the statement says so rather than
    presenting a number that happens not to add up.
    """
    from datetime import timedelta

    before = await balances_at(db, start - timedelta(days=1))
    after = await balances_at(db, end)

    def delta(kinds: set[str]) -> float:
        total = 0.0
        for no, row in after.items():
            if row["account_type"] in kinds:
                total += row["amount"] - before.get(no, {}).get("amount", 0.0)
        for no, row in before.items():
            if no not in after and row["account_type"] in kinds:
                total -= row["amount"]
        return round(total, 2)

    pnl_amounts, meta = await _pnl_span(db, start, end)
    per_type: dict[str, float] = defaultdict(float)
    for no, amount in pnl_amounts.items():
        per_type[meta[no][0]] += amount
    net_income = totals(per_type)["net_income"]

    # Accumulated depreciation is credit-normal, so its growth is a positive
    # number — and it is the one expense in the P&L that never moved money.
    depreciation = delta(CONTRA_ASSET)
    d_receivable = delta({"Receivable"})
    d_inventory = delta({"Inventory"})
    d_other_ca = delta({"Other Current Asset"})
    d_payable = delta({"Payable"})
    d_other_cl = delta({"Other Current Liability"})
    d_fixed = delta({"Fixed Asset"})
    d_long = delta({"Long Term Liability"})
    d_equity = delta(EQUITY_TYPES)
    d_cash = delta({"Cash & Bank"})

    operating = round(net_income + depreciation - d_receivable - d_inventory
                      - d_other_ca + d_payable + d_other_cl, 2)
    investing = round(-d_fixed, 2)
    financing = round(d_long + d_equity, 2)
    derived = round(operating + investing + financing, 2)

    return {
        "from": start, "to": end,
        "operating": {
            "net_income": net_income,
            "depreciation": depreciation,
            "receivables": round(-d_receivable, 2),
            "inventory": round(-d_inventory, 2),
            "other_current_assets": round(-d_other_ca, 2),
            "payables": d_payable,
            "other_current_liabilities": d_other_cl,
            "total": operating,
        },
        "investing": {"fixed_assets": round(-d_fixed, 2), "total": investing},
        "financing": {"long_term_debt": d_long, "equity": d_equity,
                      "total": financing},
        "net_change": derived,
        "cash_movement": d_cash,
        # The whole point of the statement. A gap means something is
        # classified in a way the walk does not account for.
        "reconciles": abs(derived - d_cash) < 1.0,
        "difference": round(derived - d_cash, 2),
    }


# ─── Proyeksi Arus Kas ───────────────────────────────────────────────────────

async def cash_projection(db: AsyncSession, *, months: int = 6,
                          basis: str = "commitments") -> dict:
    """What the bank looks like in the months ahead, on one of two bases.

    **commitments** — from what is already owed: invoices issued and not
    paid, by their due date. It projects nothing that has not been agreed,
    which makes it the conservative answer and the one to plan a payment
    run against.

    **budget** — from the plan: budgeted revenue in, budgeted cost out. It
    covers months no invoice exists for yet, and is therefore a statement
    of intent rather than of obligation.

    Both open from the real bank balance, and both label anything already
    past due as due now rather than quietly dropping it into last month.
    """
    from app.models.finance import Invoice, Payment

    today = date.today()
    opening = float(await db.scalar(
        select(func.coalesce(func.sum(Account.balance), 0)).where(
            Account.account_type == "Cash & Bank",
            Account.is_parent.is_(False))) or 0)

    buckets: list[dict] = []
    y, m = today.year, today.month
    for _ in range(max(1, min(months, 24))):
        buckets.append({"label": f"{m:02d}/{y}", "year": y, "month": m,
                        "from": date(y, m, 1), "to": month_end(y, m),
                        "in": 0.0, "out": 0.0})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    index = {(b["year"], b["month"]): b for b in buckets}
    first = buckets[0]

    overdue = 0.0
    if basis == "budget":
        for year in {b["year"] for b in buckets}:
            rows = (await db.scalars(select(Budget).where(
                Budget.period_year == year))).all()
            accounts = await db.scalars(
                select(Account).where(Account.account_no.in_(
                    [r.account_no for r in rows] or [""])))
            kinds = {a.account_no: a.account_type for a in accounts.all()}
            for r in rows:
                kind = kinds.get(r.account_no)
                if kind not in PNL_ORDER:
                    continue
                inflow = kind in ("Revenue", "Other Income")
                target_months = ([r.period_month] if r.period_month
                                 else list(range(1, 13)))
                amount = float(r.amount or 0)
                if not r.period_month:
                    amount = round(amount / 12, 2)
                for month in target_months:
                    b = index.get((year, month))
                    if not b:
                        continue
                    b["in" if inflow else "out"] += amount
    else:
        paid = dict((await db.execute(
            select(Payment.invoice_id,
                   func.coalesce(func.sum(Payment.amount), 0))
            .group_by(Payment.invoice_id))).all())
        invoices = (await db.scalars(select(Invoice).where(
            Invoice.status.notin_(("draft", "cancelled", "void"))))).all()
        for inv in invoices:
            outstanding = round(float(inv.total or 0)
                                - float(paid.get(inv.id, 0) or 0), 2)
            if outstanding <= 0:
                continue
            due = inv.due_date or inv.issue_date or today
            # Already late is money we are still owed, so it belongs in the
            # nearest bucket rather than in a month that has closed.
            if due < first["from"]:
                overdue += outstanding
                first["in"] += outstanding
                continue
            b = index.get((due.year, due.month))
            if b:
                b["in"] += outstanding

    running = opening
    for b in buckets:
        b["in"] = round(b["in"], 2)
        b["out"] = round(b["out"], 2)
        b["net"] = round(b["in"] - b["out"], 2)
        b["opening"] = round(running, 2)
        running = round(running + b["net"], 2)
        b["closing"] = running
        # The line somebody is actually reading this for.
        b["short"] = b["closing"] < 0
    return {
        "basis": basis, "opening_cash": round(opening, 2),
        "overdue_included": round(overdue, 2),
        "closing_cash": running,
        "first_short_month": next((b["label"] for b in buckets if b["short"]),
                                  None),
        "months": buckets,
    }
