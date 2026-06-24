from datetime import date

from app.services import financials as fin


# ─── Account-type classification ─────────────────────────────────────────────
def test_classify_covers_every_seeded_type():
    from app.scripts.coa_seed import COA_SEED
    seen_types = {row[2] for row in COA_SEED}
    for t in seen_types:
        assert fin.classify(t) in {"asset", "liability", "equity", "revenue", "expense"}, t


def test_classify_buckets():
    assert fin.classify("Cash & Bank") == "asset"
    assert fin.classify("Receivable") == "asset"
    assert fin.classify("Fixed Asset") == "asset"
    assert fin.classify("Payable") == "liability"
    assert fin.classify("Long Term Liability") == "liability"
    assert fin.classify("Equity") == "equity"
    assert fin.classify("Revenue") == "revenue"
    assert fin.classify("Other Income") == "revenue"
    assert fin.classify("Cost Of Good Sold") == "expense"
    assert fin.classify("Other Expense") == "expense"


# ─── Period resolution ───────────────────────────────────────────────────────
TODAY = date(2026, 6, 24)


def test_period_this_month():
    s, e, label = fin.resolve_period("this_month", None, None, TODAY)
    assert s == date(2026, 6, 1) and e == TODAY and "June" in label


def test_period_last_month_is_full_prior_month():
    s, e, _ = fin.resolve_period("last_month", None, None, TODAY)
    assert s == date(2026, 5, 1) and e == date(2026, 5, 31)


def test_period_quarters():
    s, e, label = fin.resolve_period("this_quarter", None, None, TODAY)
    assert s == date(2026, 4, 1) and "Q2" in label
    s, e, label = fin.resolve_period("last_quarter", None, None, TODAY)
    assert s == date(2026, 1, 1) and e == date(2026, 3, 31) and "Q1" in label


def test_period_years():
    s, e, _ = fin.resolve_period("this_year", None, None, TODAY)
    assert s == date(2026, 1, 1)
    s, e, _ = fin.resolve_period("last_year", None, None, TODAY)
    assert s == date(2025, 1, 1) and e == date(2025, 12, 31)


def test_period_custom_overrides_named():
    s, e, _ = fin.resolve_period("this_year", date(2026, 2, 1), date(2026, 2, 28), TODAY)
    assert s == date(2026, 2, 1) and e == date(2026, 2, 28)


def test_period_unknown_falls_back_to_month():
    s, e, _ = fin.resolve_period("nonsense", None, None, TODAY)
    assert s == date(2026, 6, 1)


# ─── P&L math ────────────────────────────────────────────────────────────────
def test_pnl_totals_flow():
    t = fin._pnl_totals({
        "Revenue": 1000.0,
        "Cost Of Good Sold": 400.0,
        "Expense": 200.0,
        "Other Income": 50.0,
        "Other Expense": 30.0,
    })
    assert t["gross_profit"] == 600.0          # 1000 − 400
    assert t["operating_income"] == 400.0      # 600 − 200
    assert t["net_income"] == 420.0            # 400 + 50 − 30


def test_pnl_totals_empty():
    t = fin._pnl_totals({})
    assert t["net_income"] == 0.0
