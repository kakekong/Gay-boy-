from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QuotationItemIn(BaseModel):
    line_no: int
    source: str = Field(default="product", pattern="^(product|custom)$")
    product_id: UUID | None = None
    description: str
    spec: dict = Field(default_factory=dict)
    qty: float
    uom: str = "pcs"
    unit_price: float
    cost_estimate: float = 0


class QuotationItemOut(QuotationItemIn):
    id: UUID
    line_total: float

    model_config = {"from_attributes": True}


class QuotationCreate(BaseModel):
    customer_id: UUID
    # Which PIC at the customer this quote is addressed to. Null = use the
    # primary PIC stored on the customer record.
    contact_id: UUID | None = None
    variant: str = Field(default="detailed", pattern="^(short|detailed)$")
    items: list[QuotationItemIn]
    discount_pct: float = 0
    tax_pct: float = 11
    valid_until: date | None = None
    notes: str | None = None


class QuotationOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    contact_id: UUID | None = None
    version: int
    variant: str
    status: str
    sales_pic_id: UUID | None
    currency: str
    subtotal: float
    discount_pct: float
    discount_amount: float
    tax_pct: float
    total: float
    valid_until: date | None
    notes: str | None
    items: list[QuotationItemOut] = []
    # CoA linkage
    account_revenue_no:    str | None = None
    account_receivable_no: str | None = None
    account_discount_no:   str | None = None
    account_tax_no:        str | None = None
    is_posted: bool = False
    posted_at: datetime | None = None
    posted_snapshot: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class QuotationAccountLinks(BaseModel):
    account_revenue_no:    str | None = None
    account_receivable_no: str | None = None
    account_discount_no:   str | None = None
    account_tax_no:        str | None = None


class QuotationDecide(BaseModel):
    notes: str | None = None
