from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounts,
    ai,
    approvals,
    auth,
    calendar,
    customers,
    dashboards,
    finance,
    inventory,
    kpi,
    operation,
    purchasing,
    quotations,
    salaries,
    tags,
    users,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(customers.router, prefix="/customers", tags=["crm"])
api_router.include_router(quotations.router, prefix="/quotations", tags=["quotation"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approval"])
api_router.include_router(purchasing.router, prefix="/purchasing", tags=["purchasing"])
api_router.include_router(operation.router, prefix="/operation", tags=["operation"])
api_router.include_router(finance.router, prefix="/finance", tags=["finance"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(salaries.router, prefix="/salaries", tags=["salaries"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(kpi.router, prefix="/kpi", tags=["kpi"])
api_router.include_router(dashboards.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
