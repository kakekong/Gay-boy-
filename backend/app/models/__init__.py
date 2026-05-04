"""SQLAlchemy ORM models. Importing the package registers all models with metadata."""

from app.models.approval import ApprovalRequest  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.crm import Activity, Customer, Reminder  # noqa: F401
from app.models.finance import Invoice, Payment  # noqa: F401
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder  # noqa: F401
from app.models.purchasing import (  # noqa: F401
    GoodsReceipt,
    PurchaseRequest,
    QCReport,
    RFQ,
    Supplier,
    SupplierPO,
)
from app.models.quotation import Product, Quotation, QuotationItem  # noqa: F401
from app.models.user import User  # noqa: F401
