"""Auto Workflow Orchestrator — pure-code rules reacting to domain events."""

from typing import Any, Awaitable, Callable

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

EventHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[EventHandler]] = {}


def on(event_name: str):
    def deco(fn: EventHandler) -> EventHandler:
        _handlers.setdefault(event_name, []).append(fn)
        return fn
    return deco


async def emit(db: AsyncSession, event: str, payload: dict) -> None:
    for handler in _handlers.get(event, []):
        try:
            await handler(db, payload)
        except Exception as exc:
            logger.exception(f"orchestrator handler failed: {event}: {exc}")


# Example handler registrations live alongside the services they affect.
@on("quotation.won")
async def _on_quotation_won(db: AsyncSession, payload: dict) -> None:
    logger.info(f"orchestrator: quotation.won {payload}")
    # Project creation is done in services.project_factory


@on("payment.overdue.t7")
async def _on_payment_overdue(db: AsyncSession, payload: dict) -> None:
    logger.info(f"orchestrator: payment overdue {payload}")
    # n8n is the dispatcher; we just record the event.


@on("document.parsed.po")
async def _on_po_parsed(db: AsyncSession, payload: dict) -> None:
    logger.info(f"orchestrator: PO parsed {payload}")
