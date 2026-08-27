"""The depreciation arithmetic, kept away from the endpoint that posts it.

Two methods, and the difference is not cosmetic.

**Straight line (garis lurus)** takes the same amount off every month:
(cost − salvage) ÷ life. Predictable, and what most of the register uses.

**Declining balance (saldo menurun)** takes a percentage of what is *left*,
so the charge is heavy early and tails off. The percentage is applied to the
book value at the **start of the year**, not to the balance each month —
applying it monthly would compound twelve times and quietly overstate the
year by several percent. That is the one place this file could be wrong in a
way nobody notices, so it is the one place it is spelled out.

Two rules hold for both methods, and both are about the end rather than the
middle:

- Depreciation stops at salvage value, never at zero. An asset expected to
  be worth twenty million at the end is worth twenty million on the books at
  the end.
- The final month takes whatever is left rather than the formula's answer.
  Rounding to the rupiah twelve times a year for eight years does not land
  on the number; letting the last month absorb the difference does.
"""

from datetime import date

from app.models.asset import METHODS, TAX_GROUPS


def _month_index(acquired: date, year: int, month: int) -> int:
    """How many months into its life the asset is in that period.

    1 in the month it was acquired — Indonesian practice charges a full
    month for the month of acquisition rather than prorating by day, and
    half a month's depreciation on a truck bought on the 30th is precision
    nobody asked for.
    """
    return (year - acquired.year) * 12 + (month - acquired.month) + 1


def annual_rate(*, method: str, life_months: int,
                tax_group: str | None = None) -> float:
    """The declining-balance rate, as a fraction of book value per year."""
    if tax_group and tax_group in TAX_GROUPS:
        pct = TAX_GROUPS[tax_group].get("declining_pct")
        if pct:
            return float(pct) / 100.0
    # No statutory group: double declining over the stated life, which is
    # the conventional commercial answer.
    years = max(life_months, 1) / 12.0
    return min(2.0 / years, 1.0)


def monthly_amount(*, method: str, cost: float, salvage: float,
                   life_months: int, accumulated: float,
                   accumulated_start_of_year: float,
                   tax_group: str | None = None) -> float:
    """What comes off in one month, given where the asset already stands.

    `accumulated_start_of_year` is what had been written off before the
    current year began — declining balance needs it, straight line ignores
    it. Passing it in rather than deriving it here keeps this a function of
    its arguments, which is the only way it can be checked.
    """
    depreciable = round(float(cost) - float(salvage), 2)
    if depreciable <= 0:
        return 0.0
    remaining = round(depreciable - float(accumulated), 2)
    if remaining <= 0:
        return 0.0

    if method == "declining_balance":
        rate = annual_rate(method=method, life_months=life_months,
                           tax_group=tax_group)
        book_at_year_start = float(cost) - float(accumulated_start_of_year)
        amount = round(book_at_year_start * rate / 12.0, 2)
    else:
        amount = round(depreciable / max(life_months, 1), 2)

    # Never past salvage, and the last month absorbs the rounding.
    return min(amount, remaining)


def schedule(*, acquired_on: date, cost: float, salvage: float,
             life_months: int, method: str, opening_accum: float = 0.0,
             tax_group: str | None = None,
             max_months: int | None = None) -> list[dict]:
    """The whole life, month by month, without posting anything.

    Used to show what an asset will do and to compare the commercial answer
    against the fiscal one. It projects from acquisition rather than from
    today, so an asset entered part-worn (`opening_accum`) shows the months
    that were written off before the system existed as well as the ones
    ahead.
    """
    if method not in METHODS:
        method = "straight_line"
    rows: list[dict] = []
    accumulated = 0.0
    accumulated_start_of_year = 0.0
    depreciable = round(float(cost) - float(salvage), 2)
    year = acquired_on.year
    month = acquired_on.month
    cap = max_months or (life_months + 24)

    for i in range(cap):
        if month == 1 and i > 0:
            accumulated_start_of_year = accumulated
        if round(depreciable - accumulated, 2) <= 0:
            break
        amount = monthly_amount(
            method=method, cost=cost, salvage=salvage, life_months=life_months,
            accumulated=accumulated,
            accumulated_start_of_year=accumulated_start_of_year,
            tax_group=tax_group)
        if amount <= 0:
            break
        accumulated = round(accumulated + amount, 2)
        rows.append({
            "period_year": year, "period_month": month,
            "month_index": i + 1,
            "amount": amount,
            "accumulated": accumulated,
            "book_value": round(float(cost) - accumulated, 2),
            # Everything up to `opening_accum` was written off in whatever
            # the company used before this system. Marking it keeps the
            # projection honest about which half it is showing.
            "already_written_off": accumulated <= round(float(opening_accum), 2),
        })
        month += 1
        if month > 12:
            month = 1
            year += 1
    return rows


def due_for(*, acquired_on: date, year: int, month: int,
            status: str = "active", disposed_on: date | None = None) -> bool:
    """Is this asset in scope for that month's run at all?

    An asset is not depreciated before it is bought, and not after it is
    gone. The month of disposal is charged — the asset was in use for it —
    which is also why disposal recomputes the gain after the run rather than
    before.
    """
    if _month_index(acquired_on, year, month) < 1:
        return False
    if status == "disposed" and disposed_on:
        if (disposed_on.year, disposed_on.month) < (year, month):
            return False
    return True
