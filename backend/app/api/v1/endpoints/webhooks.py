"""Inbound webhooks (n8n forwards external events)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import settings
from app.core.db import get_db
from app.models.crm import Activity, Customer

router = APIRouter()


def _verify(secret: str | None) -> None:
    if not secret or secret != settings.N8N_WEBHOOK_SECRET:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad webhook secret")


@router.post("/whatsapp/inbound")
async def wa_inbound(
    payload: dict,
    x_webhook_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _verify(x_webhook_secret)
    phone = (payload.get("from") or "").lstrip("+")
    text = payload.get("text", "")
    customer = await db.scalar(
        select(Customer).where(Customer.whatsapp.like(f"%{phone[-9:]}%"))
    )
    if customer:
        db.add(Activity(
            customer_id=customer.id,
            type="whatsapp_in",
            direction="inbound",
            occurred_at=datetime.now(UTC),
            notes=text[:1000],
            meta={"raw": payload},
        ))
        await db.flush()
        return {"matched_customer_id": str(customer.id)}
    return {"matched_customer_id": None, "stashed": True}


@router.post("/whatsapp/status")
async def wa_status(payload: dict,
                    x_webhook_secret: str | None = Header(default=None)):
    _verify(x_webhook_secret)
    return {"ok": True}


@router.post("/payment/inbound")
async def payment_inbound(payload: dict,
                          x_webhook_secret: str | None = Header(default=None)):
    _verify(x_webhook_secret)
    return {"ok": True}
