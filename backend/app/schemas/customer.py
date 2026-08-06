from uuid import UUID

from pydantic import BaseModel, Field


class CustomerBase(BaseModel):
    company_name: str
    industry: str
    pic_name: str | None = None
    pic_position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    company_address: str | None = None
    delivery_address: str | None = None
    payment_terms: dict = Field(default_factory=dict)
    # Tax info (Indonesian context: NPWP / NPPKP / PKP status)
    tax_id: str | None = None
    tax_name: str | None = None
    tax_address: str | None = None
    is_pkp: bool = False
    nppkp_no: str | None = None
    tax_notes: str | None = None


class ContactCreate(BaseModel):
    name: str
    position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    is_primary: bool = False
    notes: str | None = None


class CustomerCreate(CustomerBase):
    sales_pic_id: UUID | None = None
    stage: str = "lead"
    # Optional extra PICs to create alongside the customer in one round-trip.
    contacts: list[ContactCreate] = Field(default_factory=list)


class CustomerUpdate(BaseModel):
    company_name: str | None = None
    industry: str | None = None
    pic_name: str | None = None
    pic_position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    company_address: str | None = None
    delivery_address: str | None = None
    payment_terms: dict | None = None
    stage: str | None = None
    sales_pic_id: UUID | None = None
    lost_reason: str | None = None
    tax_id: str | None = None
    tax_name: str | None = None
    tax_address: str | None = None
    is_pkp: bool | None = None
    nppkp_no: str | None = None
    tax_notes: str | None = None


class CustomerOut(CustomerBase):
    id: UUID
    sales_pic_id: UUID | None
    sales_pic_name: str | None = None
    stage: str
    lifetime_value: float
    lost_reason: str | None = None
    # Set only on customers brought in from the old accounting system.
    external_code: str | None = None

    model_config = {"from_attributes": True}
