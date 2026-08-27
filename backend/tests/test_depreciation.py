"""The depreciation arithmetic, checked against hand-worked answers.

The API driver proves the register behaves; this proves the numbers are
right, which is a different question and the one an auditor asks. Every
expected figure here was worked out on paper first — a test that computes
its expectation the same way the code does agrees with the bug as readily
as with the fix.

Two things are worth the trouble of checking directly:

- **The declining-balance year.** The rate applies to the book value at the
  *start of the year*, not to the balance each month. Applying it monthly
  compounds twelve times and overstates the year — a mistake that produces
  plausible numbers, which is what makes it dangerous.
- **The end of the life.** Rounding to the rupiah, month after month, does
  not land on the number. The schedule has to stop at salvage value exactly,
  and the last month has to absorb the difference.
"""

from datetime import date

from app.services.depreciation import (
    TAX_GROUPS, annual_rate, monthly_amount, due_for, schedule,
)


def test_straight_line_is_the_same_amount_every_month():
    # 120,000,000 over 4 years, nothing left at the end: 2,500,000 a month.
    amount = monthly_amount(
        method="straight_line", cost=120_000_000, salvage=0, life_months=48,
        accumulated=0, accumulated_start_of_year=0)
    assert amount == 2_500_000

    # Halfway through, it is still the same amount.
    assert monthly_amount(
        method="straight_line", cost=120_000_000, salvage=0, life_months=48,
        accumulated=60_000_000, accumulated_start_of_year=60_000_000
    ) == 2_500_000


def test_salvage_value_is_not_depreciated():
    # 100 million with 20 million expected at the end: only 80 comes off.
    rows = schedule(acquired_on=date(2024, 1, 1), cost=100_000_000,
                    salvage=20_000_000, life_months=40,
                    method="straight_line")
    assert sum(r["amount"] for r in rows) == 80_000_000
    assert rows[-1]["book_value"] == 20_000_000


def test_the_life_ends_exactly_even_when_the_division_does_not():
    # 10,000,000 over 7 months is 1,428,571.43 a month — which times seven
    # is 10,000,000.01. The last month has to take the difference.
    rows = schedule(acquired_on=date(2025, 1, 1), cost=10_000_000, salvage=0,
                    life_months=7, method="straight_line")
    assert len(rows) == 7
    assert sum(r["amount"] for r in rows) == 10_000_000
    assert rows[-1]["book_value"] == 0
    assert rows[-1]["amount"] < rows[0]["amount"]


def test_declining_balance_applies_the_rate_to_the_years_opening_value():
    # Kelompok 2: 25% declining. 800,000,000 acquired in January.
    # Year one:  800,000,000 × 25%  = 200,000,000 → 16,666,666.67 a month.
    # Year two:  600,000,000 × 25%  = 150,000,000 → 12,500,000.00 a month.
    rows = schedule(acquired_on=date(2024, 1, 1), cost=800_000_000, salvage=0,
                    life_months=96, method="declining_balance",
                    tax_group="kelompok_2")
    year_one = [r for r in rows if r["period_year"] == 2024]
    year_two = [r for r in rows if r["period_year"] == 2025]
    assert len(year_one) == 12
    assert round(sum(r["amount"] for r in year_one), 2) == 200_000_000.04
    assert year_one[0]["amount"] == 16_666_666.67
    assert year_two[0]["amount"] == 12_500_000.00

    # And the mistake this guards against: compounding monthly would make
    # the first year 800m × (1 − (1 − 0.25/12)^12) ≈ 178.6m, not 200m.
    assert round(sum(r["amount"] for r in year_one), 2) > 190_000_000


def test_declining_falls_back_to_double_declining_without_a_tax_group():
    # No statutory group, four-year life: 2 ÷ 4 = 50% a year.
    assert annual_rate(method="declining_balance", life_months=48) == 0.5
    # With one, the law's rate wins.
    assert annual_rate(method="declining_balance", life_months=48,
                       tax_group="kelompok_3") == 0.125


def test_buildings_have_no_declining_rate():
    for group in ("bangunan_permanen", "bangunan_tidak_permanen"):
        assert TAX_GROUPS[group]["declining_pct"] is None


def test_the_month_of_acquisition_is_charged_in_full():
    rows = schedule(acquired_on=date(2025, 6, 20), cost=48_000_000, salvage=0,
                    life_months=48, method="straight_line")
    assert (rows[0]["period_year"], rows[0]["period_month"]) == (2025, 6)
    assert rows[0]["amount"] == 1_000_000


def test_an_asset_is_not_depreciated_before_it_is_bought():
    bought = date(2025, 6, 1)
    assert due_for(acquired_on=bought, year=2025, month=5) is False
    assert due_for(acquired_on=bought, year=2025, month=6) is True


def test_a_disposed_asset_is_charged_for_the_month_it_left_and_no_later():
    bought, gone = date(2024, 1, 1), date(2025, 3, 14)
    assert due_for(acquired_on=bought, year=2025, month=3,
                   status="disposed", disposed_on=gone) is True
    assert due_for(acquired_on=bought, year=2025, month=4,
                   status="disposed", disposed_on=gone) is False


def test_a_part_worn_asset_says_which_months_predate_the_system():
    # Bought in 2023, entered with two years already written off.
    rows = schedule(acquired_on=date(2023, 1, 1), cost=60_000_000, salvage=0,
                    life_months=60, method="straight_line",
                    opening_accum=24_000_000)
    old = [r for r in rows if r["already_written_off"]]
    assert len(old) == 24
    assert old[-1]["accumulated"] == 24_000_000
    assert rows[24]["already_written_off"] is False


def test_nothing_comes_off_an_asset_already_written_down_to_salvage():
    assert monthly_amount(
        method="straight_line", cost=50_000_000, salvage=5_000_000,
        life_months=36, accumulated=45_000_000,
        accumulated_start_of_year=45_000_000) == 0
