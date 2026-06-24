from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounts,
    ai,
    approvals,
    attachments,
    attendance,
    audit,
    auth,
    portal,
    calendar,
    chat,
    comments,
    custom_roles,
    customer_pos,
    customers,
    dashboards,
    finance,
    financial_reports,
    inventory,
    kpi,
    ledger,
    notifications,
    operation,
    payments,
    purchasing,
    quotations,
    reports,
    salaries,
    sales_targets,
    search,
    tags,
    users,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(customers.router, prefix="/customers", tags=["crm"])
api_router.include_router(customer_pos.router, prefix="/customer-pos", tags=["customer-pos"])
api_router.include_router(quotations.router, prefix="/quotations", tags=["quotation"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approval"])
api_router.include_router(purchasing.router, prefix="/purchasing", tags=["purchasing"])
api_router.include_router(operation.router, prefix="/operation", tags=["operation"])
api_router.include_router(finance.router, prefix="/finance", tags=["finance"])
api_router.include_router(financial_reports.router, prefix="/finance/reports", tags=["finance-reports"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(salaries.router, prefix="/salaries", tags=["salaries"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
api_router.include_router(sales_targets.router, prefix="/sales-targets", tags=["sales-targets"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
api_router.include_router(portal.router, prefix="/portal", tags=["portal"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(kpi.router, prefix="/kpi", tags=["kpi"])
api_router.include_router(dashboards.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
api_router.include_router(custom_roles.router, prefix="/custom-roles", tags=["custom-roles"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
