"""SQLAlchemy ORM models. Importing the package registers all models with metadata."""

from app.models.account import Account  # noqa: F401
from app.models.approval import ApprovalRequest  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.attendance import Attendance  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage  # noqa: F401
from app.models.comment import EntityComment  # noqa: F401
from app.models.crm import Activity, Customer, Reminder  # noqa: F401
from app.models.customer_po import CustomerPO  # noqa: F401
from app.models.finance import Invoice, Payment  # noqa: F401
from app.models.inventory import InventoryItem, InventoryMovement  # noqa: F401
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder  # noqa: F401
from app.models.payment_claim import PaymentClaim  # noqa: F401
from app.models.purchasing import (  # noqa: F401
    GoodsReceipt,
    PurchaseRequest,
    QCReport,
    RFQ,
    Supplier,
    SupplierPO,
)
from app.models.quotation import Product, Quotation, QuotationItem  # noqa: F401
from app.models.salary import Salary  # noqa: F401
from app.models.sales_target import SalesTarget  # noqa: F401
from app.models.tag import Tag, UserTagLink  # noqa: F401
from app.models.user import User  # noqa: F401
