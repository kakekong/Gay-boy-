from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

# The units goods are actually counted in here. A free-text unit box gets
# "pcs", "Pcs", "pc", "EA" and "buah" for the same thing, and then two
# documents about one part disagree about what a quantity means. Sales picks
# from this list; `normalise_uom` maps the spellings that already exist in
# the data onto it rather than refusing them.
#
# `link` is the chain one. A length of conveyor or roller chain is bought,
# quoted and cut in links, and quoting it "per pcs" leaves the reader with
# no idea how much chain is meant — one piece of a hundred links, or one
# link.
UNITS = ("pcs", "meter", "set", "roll", "link")

_UOM_SYNONYMS = {
    "pc": "pcs", "pcs": "pcs", "piece": "pcs", "pieces": "pcs", "pce": "pcs",
    "ea": "pcs", "each": "pcs", "unit": "pcs", "units": "pcs", "buah": "pcs",
    "bh": "pcs", "no": "pcs", "nos": "pcs",
    "m": "meter", "mtr": "meter", "mtrs": "meter", "meter": "meter",
    "meters": "meter", "metre": "meter", "metres": "meter",
    "set": "set", "sets": "set", "st": "set",
    "roll": "roll", "rolls": "roll", "rol": "roll", "gulung": "roll",
    # Chain is counted in links, and chain is most of what this company
    # sells — a conveyor chain quoted "per pcs" says nothing about how much
    # chain that is. Not to be confused with the URL field also called
    # `link` on a price-request line; this one is a unit of measure.
    "link": "link", "links": "link", "lnk": "link", "mata": "link",
    "mata rantai": "link", "pitch": "link", "pitches": "link",
}


def normalise_uom(value: str | None) -> str | None:
    """One of UNITS, or None when there is nothing usable to map.

    Returning None rather than guessing lets the caller decide whether a
    missing unit is a default or a refusal — which differs between a price
    request sales is filling in and a supplier PO typed by somebody else.
    """
    key = (value or "").strip().lower().rstrip(".")
    if not key:
        return None
    return _UOM_SYNONYMS.get(key)


# What the company actually sells. A free-text category box produced
# "sprocket", "Sprockets", "gear sprocket" and "SPROCKET 12T" for one kind of
# thing, so nothing could be counted or filtered by it — which is the only
# reason to record a category at all. Sales picks from this list.
#
# `others` is deliberately part of it rather than an escape hatch bolted on:
# a list without one gets the nearest wrong answer picked instead, and then
# the wrong answer is what you filter on.
CATEGORIES = (
    "conveyor_chain",
    "roller_chain",
    "connecting_link",
    "sprocket",
    "roller_conveyor",
    "others",
)

# How each reads on screen and on a document. Kept beside the values so the
# two cannot drift; the API hands this out so no screen has to hardcode it.
CATEGORY_LABELS = {
    "conveyor_chain":  "Conveyor chain",
    "roller_chain":    "Roller chain",
    "connecting_link": "Connecting link",
    "sprocket":        "Sprocket",
    "roller_conveyor": "Roller conveyor",
    "others":          "Others",
}

_CATEGORY_SYNONYMS = {
    # The canonical values, and the way anybody would actually type them.
    "conveyorchain": "conveyor_chain", "conveyor chain": "conveyor_chain",
    "conveyor-chain": "conveyor_chain", "rantai konveyor": "conveyor_chain",
    "rollerchain": "roller_chain", "roller chain": "roller_chain",
    "roller-chain": "roller_chain", "rantai roller": "roller_chain",
    "connectinglink": "connecting_link", "connecting link": "connecting_link",
    "connecting-link": "connecting_link", "conn link": "connecting_link",
    "sambungan rantai": "connecting_link",
    "sprocket": "sprocket", "sprockets": "sprocket", "gir": "sprocket",
    "rollerconveyor": "roller_conveyor", "roller conveyor": "roller_conveyor",
    "roller-conveyor": "roller_conveyor", "konveyor roller": "roller_conveyor",
    "other": "others", "others": "others", "lainnya": "others",
    "lain-lain": "others", "misc": "others",
}
for _c in CATEGORIES:
    _CATEGORY_SYNONYMS.setdefault(_c, _c)
    _CATEGORY_SYNONYMS.setdefault(_c.replace("_", " "), _c)


def normalise_category(value: str | None) -> str | None:
    """One of CATEGORIES, or None when there is nothing that maps.

    None rather than a guess, for the same reason `normalise_uom` returns it:
    "I could not place this" and "they left it blank" are different answers,
    and only the caller knows which of the two is a refusal.
    """
    key = " ".join((value or "").strip().lower().split())
    if not key:
        return None
    return _CATEGORY_SYNONYMS.get(key)


def category_label(value: str | None) -> str | None:
    """How a stored category reads. Unknown values — legacy free text — are
    handed back as they are rather than hidden behind a guess."""
    if not value:
        return None
    return CATEGORY_LABELS.get(value, value)


class InventoryItem(Base, UUIDPK, TimestampMixin):
    """Stockable item: spare parts, consumables, raw materials, etc."""

    __tablename__ = "inventory_items"

    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    uom: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    # Where the part can be looked up — a supplier's product page, a
    # datasheet, a marketplace listing. Sales has it open while writing the
    # price request; without somewhere to put it, purchasing has to find the
    # same page again.
    link: Mapped[str | None] = mapped_column(String(1000))
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    current_stock: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reorder_point: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reorder_qty: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    supplier_hint: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryMovement(Base, UUIDPK, TimestampMixin):
    """Audit trail for every stock change."""

    __tablename__ = "inventory_movements"

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delta: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # adjust | receive | issue | return | transfer
    reference: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
