from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounts,
    ai,
    assets,
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
    feedback,
    finance,
    financial_reports,
    inventory,
    kpi,
    cash,
    journals,
    ledger,
    maintenance,
    master,
    notifications,
    operation,
    payments,
    price_requests,
    purchasing,
    push,
    quotations,
    reports,
    salaries,
    sales_targets,
    search,
    supplier_price_requests,
    tags,
    users,
    webhooks,
    imports,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(customers.router, prefix="/customers", tags=["crm"])
api_router.include_router(customer_pos.router, prefix="/customer-pos", tags=["customer-pos"])
api_router.include_router(quotations.router, prefix="/quotations", tags=["quotation"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approval"])
api_router.include_router(purchasing.router, prefix="/purchasing", tags=["purchasing"])
# Buy-side price requests. Nested under /purchasing because that is the page
# they live on, but a router of their own: the audience is narrower than
# /purchasing (no sales at all) and the file is its own workflow.
api_router.include_router(supplier_price_requests.router,
                          prefix="/purchasing/price-requests",
                          tags=["supplier-price-requests"])
api_router.include_router(push.router, prefix="/push", tags=["push"])
api_router.include_router(operation.router, prefix="/operation", tags=["operation"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
api_router.include_router(finance.router, prefix="/finance", tags=["finance"])
# Same prefix, wider role gate — see finance.invoice_desk.
api_router.include_router(finance.invoice_desk, prefix="/finance", tags=["finance"])
api_router.include_router(financial_reports.router, prefix="/finance/reports", tags=["finance-reports"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(journals.router, prefix="/journals", tags=["journals"])
api_router.include_router(cash.router, prefix="/cash", tags=["cash-bank"])
api_router.include_router(master.router, prefix="/master", tags=["master-data"])
api_router.include_router(assets.router, prefix="/assets", tags=["fixed-assets"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(salaries.router, prefix="/salaries", tags=["salaries"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(sales_targets.router, prefix="/sales-targets", tags=["sales-targets"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
api_router.include_router(portal.router, prefix="/portal", tags=["portal"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(price_requests.router, prefix="/price-requests", tags=["price-requests"])
api_router.include_router(kpi.router, prefix="/kpi", tags=["kpi"])
api_router.include_router(dashboards.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
api_router.include_router(custom_roles.router, prefix="/custom-roles", tags=["custom-roles"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(maintenance.router, prefix="/maintenance", tags=["maintenance"])
