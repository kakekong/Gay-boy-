from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerPOItem(BaseModel):
    """A single line on the customer PO. Free-form so it can be filled
    from a subset of a quotation's items, or typed in fresh."""
    description: str
    qty: float = 1
    unit_price: float = 0
    uom: str | None = None


class CustomerPOCreate(BaseModel):
    customer_id: UUID
    # Linkage to the originating quotation is now required — every
    # customer PO has to reference the won quote it's against. The
    # endpoint also verifies the quote belongs to the same customer.
    quotation_id: UUID
    number: str
    po_date: date | None = None
    items: list[CustomerPOItem] = Field(default_factory=list)
    notes: str | None = None


class CustomerPOPatch(BaseModel):
    number: str | None = None
    po_date: date | None = None
    items: list[CustomerPOItem] | None = None
    notes: str | None = None


class CustomerPOOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None = None
    quotation_id: UUID | None = None
    quotation_number: str | None = None
    number: str
    po_date: date | None = None
    items: list[dict]
    total: float
    notes: str | None = None
    status: str
    project_id: UUID | None = None
    project_code: str | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
