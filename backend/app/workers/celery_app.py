"""Celery app for async jobs."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery(
    "industriacrm",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.TIMEZONE,
    enable_utc=True,
)

celery.conf.beat_schedule = {
    "deal-risk-scan-every-6h": {
        "task": "app.workers.tasks.deal_risk_scan",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "kpi-rollup-nightly": {
        "task": "app.workers.tasks.kpi_rollup",
        "schedule": crontab(minute=30, hour=0),
    },
    "supplier-risk-weekly": {
        "task": "app.workers.tasks.supplier_risk_scan",
        "schedule": crontab(minute=0, hour=2, day_of_week=1),
    },
    "smart-reminder-rerank-daily": {
        "task": "app.workers.tasks.smart_reminder_rerank",
        "schedule": crontab(minute=0, hour=6),
    },
    "payment-reminder-hourly": {
        "task": "app.workers.tasks.payment_reminder_run",
        "schedule": crontab(minute=0),
    },
}

import app.workers.tasks  # noqa: E402,F401
