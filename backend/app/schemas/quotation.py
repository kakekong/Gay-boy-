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
    # Quotation number is auto-generated from the fixed company token, but the
    # user may type a custom full number here when needed (blank = auto). A
    # number_token overrides just the <TOK> segment of the auto number.
    number: str | None = None
    number_token: str | None = None


class QuotationOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    contact_id: UUID | None = None
    price_request_id: UUID | None = None
    # Injected by _load (not columns): the PR's human number for the
    # click-through chip, the revision lineage, and any newer revisions.
    price_request_number: str | None = None
    parent_id: UUID | None = None
    parent_number: str | None = None
    revisions: list[dict] = Field(default_factory=list)
    won_pending: bool = False
    edit_pending: bool = False
    version: int
    variant: str
    status: str
    sales_pic_id: UUID | None
    sales_pic_name: str | None = None
    currency: str
    subtotal: float
    discount_pct: float
    discount_amount: float
    tax_pct: float
    total: float
    valid_until: date | None
    notes: str | None
    # Why it was sent back, when it was. Survives a resubmission so the
    # director can see what they asked for last time.
    decision_notes: str | None = None
    items: list[QuotationItemOut] = []
    # CoA linkage
    account_revenue_no:    str | None = None
    account_receivable_no: str | None = None
    account_discount_no:   str | None = None
    account_tax_no:        str | None = None
    is_posted: bool = False
    posted_at: datetime | None = None
    posted_snapshot: dict = Field(default_factory=dict)
    # Timestamps: the detail page renders `created_at` as the "Issued"
    # date and `updated_at` for last-edit context, so the row's own
    # dates need to travel over the wire.
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class QuotationAccountLinks(BaseModel):
    account_revenue_no:    str | None = None
    account_receivable_no: str | None = None
    account_discount_no:   str | None = None
    account_tax_no:        str | None = None


class QuotationDecide(BaseModel):
    notes: str | None = None


class QuotationUpdate(BaseModel):
    """Edit a draft/rejected quotation. All fields optional; when `items` is
    provided it replaces the existing line items wholesale."""
    contact_id: UUID | None = None
    variant: str | None = Field(default=None, pattern="^(short|detailed)$")
    items: list[QuotationItemIn] | None = None
    discount_pct: float | None = None
    tax_pct: float | None = None
    valid_until: date | None = None
    notes: str | None = None
    number: str | None = None
