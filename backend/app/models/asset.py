"""Aset Tetap — the things the company owns that wear out.

A fixed asset is the one thing on the balance sheet that changes value
without anybody touching it. A truck bought for 400 million is worth less
every month whether or not it is driven, and the books only say so if
somebody posts the depreciation. That is what this module is: the register
of what we own, and the monthly entry that walks each one down.

**Two categories, not one.** An asset is depreciated twice in Indonesia and
the two answers differ. The commercial books use the life the company
actually expects; the tax return uses the statutory groups — Kelompok 1
through 4, Bangunan Permanen, Bangunan Tidak Permanen — whose lives and
rates are set by law and are not ours to choose. Keeping one number and
calling it both is how a fiscal reconciliation stops being possible, so an
asset carries a category of each kind and the schedule is worked out under
both.

**What is stored and what is derived.** Cost, salvage, life and method are
stored because somebody entered them. Accumulated depreciation is stored
because it is the sum of entries actually posted — not a formula re-run on
read, which would silently disagree with the ledger the moment a month is
skipped or an asset is adjusted mid-life. Book value is derived from the
two, and is never stored, because a stored book value is a third number
that can drift from the other two.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

# Straight line walks the same amount off every month; declining balance
# takes a percentage of what is left, so it is heavy early and never quite
# reaches zero. Indonesian tax law allows both for movable assets and only
# straight line for buildings — which is why the method lives on the
# category rather than being assumed.
METHODS = ("straight_line", "declining_balance")

# The statutory groups, with the life and the rates the law fixes. These are
# not defaults anybody may edit — they are the schedule in UU PPh Pasal 11,
# and an asset in Kelompok 2 depreciates over eight years whatever the
# company thinks of its truck.
TAX_GROUPS: dict[str, dict] = {
    "kelompok_1":       {"label": "Kelompok 1", "years": 4,
                         "straight_pct": 25.0, "declining_pct": 50.0},
    "kelompok_2":       {"label": "Kelompok 2", "years": 8,
                         "straight_pct": 12.5, "declining_pct": 25.0},
    "kelompok_3":       {"label": "Kelompok 3", "years": 16,
                         "straight_pct": 6.25, "declining_pct": 12.5},
    "kelompok_4":       {"label": "Kelompok 4", "years": 20,
                         "straight_pct": 5.0, "declining_pct": 10.0},
    # Buildings are straight line only — the law gives no declining rate,
    # so there is none here rather than a plausible-looking guess.
    "bangunan_permanen": {"label": "Bangunan Permanen", "years": 20,
                          "straight_pct": 5.0, "declining_pct": None},
    "bangunan_tidak_permanen": {"label": "Bangunan Tidak Permanen",
                                "years": 10, "straight_pct": 10.0,
                                "declining_pct": None},
}

# What a change to an asset was. Each one is a different thing to explain to
# an auditor, so each one is its own kind rather than a free-text note.
CHANGE_KINDS = ("cost", "life", "move", "revalue")


class AssetCategory(Base, UUIDPK, TimestampMixin):
    """Kategori Aset (commercial) and Kategori Aset Tetap Pajak (fiscal).

    Same shape, two scopes, because the two answers are compared rather than
    merged. The accounts live here: every asset in a category lands in the
    same three places, and putting them on the asset instead would mean a
    hundred chances to put a forklift in the buildings account.
    """

    __tablename__ = "asset_categories"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "commercial" — the company's own view. "tax" — the statutory groups.
    scope: Mapped[str] = mapped_column(String(20), default="commercial",
                                       nullable=False, index=True)
    # Set only on tax categories: which statutory group this is.
    tax_group: Mapped[str | None] = mapped_column(String(40), index=True)
    method: Mapped[str] = mapped_column(String(30), default="straight_line",
                                        nullable=False)
    useful_life_months: Mapped[int] = mapped_column(Integer, default=48,
                                                    nullable=False)
    # Where an asset in this category sits and where its depreciation goes.
    asset_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    accum_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    expense_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True,
                                            nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class FixedAsset(Base, UUIDPK, TimestampMixin):
    __tablename__ = "fixed_assets"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False,
                                        index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("asset_categories.id"), index=True)
    # The fiscal category. Separate on purpose — see the module docstring.
    tax_category_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("asset_categories.id"), index=True)

    acquired_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    # What it is expected to be worth when we are done with it. Depreciation
    # stops here, not at zero.
    salvage_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0,
                                                 nullable=False)
    useful_life_months: Mapped[int] = mapped_column(Integer, default=48,
                                                    nullable=False)
    method: Mapped[str] = mapped_column(String(30), default="straight_line",
                                        nullable=False)

    # An asset bought before the system existed arrives part-worn. This is
    # what had already been written off on the day it was entered, so its
    # schedule picks up where the old books left off instead of starting the
    # whole life again.
    opening_accum: Mapped[float] = mapped_column(Numeric(18, 2), default=0,
                                                 nullable=False)
    # Opening plus everything posted since. Stored, because it is the sum of
    # real entries rather than a formula — see the module docstring.
    accumulated_depreciation: Mapped[float] = mapped_column(
        Numeric(18, 2), default=0, nullable=False)

    location: Mapped[str | None] = mapped_column(String(255), index=True)
    department: Mapped[str | None] = mapped_column(String(120))
    pic_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    serial_no: Mapped[str | None] = mapped_column(String(120))
    supplier: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    # "active" | "disposed". An asset is never deleted once it has been
    # depreciated — the entries that walked it down are still in the ledger,
    # and a register that loses the asset they refer to cannot be audited.
    status: Mapped[str] = mapped_column(String(20), default="active",
                                        nullable=False, index=True)
    disposed_on: Mapped[date | None] = mapped_column(Date)
    disposal_proceeds: Mapped[float] = mapped_column(Numeric(18, 2), default=0,
                                                     nullable=False)
    disposal_reason: Mapped[str | None] = mapped_column(Text)
    disposal_journal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id"))

    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))

    entries: Mapped[list["AssetDepreciation"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan",
        order_by="AssetDepreciation.period_year, AssetDepreciation.period_month")


class AssetDepreciation(Base, UUIDPK, TimestampMixin):
    """One month's write-down of one asset, and the entry that posted it.

    Kept per asset per month rather than as a single run total, because the
    question actually asked is "what has this asset had against it", and a
    run total cannot answer it. It also makes the double-post guard trivial:
    the row either exists for that period or it does not.
    """

    __tablename__ = "asset_depreciations"

    asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fixed_assets.id", ondelete="CASCADE"),
        nullable=False, index=True)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    # The book value after this month came off — so the schedule reads
    # without re-deriving it, and a later adjustment cannot rewrite history.
    book_value_after: Mapped[float] = mapped_column(Numeric(18, 2), default=0,
                                                    nullable=False)
    journal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id"))
    posted_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))

    asset: Mapped["FixedAsset"] = relationship(back_populates="entries")


class AssetChange(Base, UUIDPK, TimestampMixin):
    """Perubahan Aset Tetap and Pindah Aset — what changed, and what it was.

    An asset's cost, life and whereabouts all change over its life, and each
    change makes every figure after it read differently. Storing the before
    and the after means the register can explain itself years later, when
    the only other evidence is a number that does not match anybody's memory.
    """

    __tablename__ = "asset_changes"

    asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fixed_assets.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    changed_on: Mapped[date] = mapped_column(Date, nullable=False)
    before_value: Mapped[str | None] = mapped_column(String(255))
    after_value: Mapped[str | None] = mapped_column(String(255))
    # A cost change moves the balance sheet, so it carries an entry. A move
    # between two of our own warehouses does not, so it carries none.
    journal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id"))
    memo: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))


class DepreciationRun(Base, UUIDPK, TimestampMixin):
    """One month closed across the whole register.

    The run is the thing finance actually does — "depreciate March" — and it
    either happened or it did not. Recording it separately from the per-asset
    rows is what lets the page say "March is done, 42 assets, 18.4 million"
    without adding up the register to find out.
    """

    __tablename__ = "depreciation_runs"

    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    asset_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0,
                                                nullable=False)
    journal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id"))
    run_at: Mapped[date | None] = mapped_column(Date)
    run_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False,
                                              nullable=False)
