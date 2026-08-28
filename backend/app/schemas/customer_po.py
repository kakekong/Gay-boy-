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
    # Sales flags this on submission when the customer's PO is for a
    # deposit / DP. A DP PO routes through finance approval first, then
    # sales confirms once the money is in, and only then the project
    # spawns. Regular POs keep the director-approves path.
    is_downpayment: bool = False


class CustomerPOPatch(BaseModel):
    number: str | None = None
    po_date: date | None = None
    items: list[CustomerPOItem] | None = None
    notes: str | None = None


class CustomerPOOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None = None
    sales_pic_id: UUID | None = None
    sales_pic_name: str | None = None
    quotation_id: UUID | None = None
    quotation_number: str | None = None
    number: str
    po_date: date | None = None
    items: list[dict]
    total: float
    notes: str | None = None
    status: str
    is_downpayment: bool = False
    dp_finance_approved_at: datetime | None = None
    dp_payment_confirmed_at: datetime | None = None
    # DP invoices issued against this PO (before the project exists).
    # Populated on the detail endpoint only — lists skip it to stay cheap.
    dp_invoices: list[dict] = []
    project_id: UUID | None = None
    project_code: str | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
