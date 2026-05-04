from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CustomerBase(BaseModel):
    company_name: str
    industry: str
    pic_name: str | None = None
    pic_position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: EmailStr | None = None
    company_address: str | None = None
    delivery_address: str | None = None
    payment_terms: dict = Field(default_factory=dict)


class CustomerCreate(CustomerBase):
    sales_pic_id: UUID | None = None
    stage: str = "lead"


class CustomerUpdate(BaseModel):
    company_name: str | None = None
    industry: str | None = None
    pic_name: str | None = None
    pic_position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: EmailStr | None = None
    company_address: str | None = None
    delivery_address: str | None = None
    payment_terms: dict | None = None
    stage: str | None = None
    sales_pic_id: UUID | None = None
    lost_reason: str | None = None


class CustomerOut(CustomerBase):
    id: UUID
    sales_pic_id: UUID | None
    stage: str
    lifetime_value: float
    lost_reason: str | None = None

    model_config = {"from_attributes": True}
