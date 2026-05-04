"""Celery tasks. Wrap async logic with anyio.from_thread or run sync helpers."""

import asyncio

from loguru import logger

from app.workers.celery_app import celery


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@celery.task(name="app.workers.tasks.deal_risk_scan")
def deal_risk_scan():
    from app.ai import deal_risk
    from app.core.db import SessionLocal

    async def _go():
        async with SessionLocal() as db:
            result = await deal_risk.scan_all(db)
            logger.info(f"deal_risk scan: {result['scanned']} deals")
    _run(_go())


@celery.task(name="app.workers.tasks.kpi_rollup")
def kpi_rollup():
    logger.info("KPI rollup placeholder — write snapshots into kpi_snapshots.")


@celery.task(name="app.workers.tasks.supplier_risk_scan")
def supplier_risk_scan():
    from app.ai import supply_risk
    from app.core.db import SessionLocal

    async def _go():
        async with SessionLocal() as db:
            data = await supply_risk.dashboard(db)
            logger.info(f"supply risk: {len(data['suppliers'])} suppliers scanned")
    _run(_go())


@celery.task(name="app.workers.tasks.smart_reminder_rerank")
def smart_reminder_rerank():
    logger.info("smart reminder rerank — recompute ai_optimal_at across pending reminders")


@celery.task(name="app.workers.tasks.payment_reminder_run")
def payment_reminder_run():
    logger.info("payment reminder run — n8n picks the list and dispatches WA")
