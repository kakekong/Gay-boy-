"""Auto Quotation AI — structured form to quotation draft."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import chat
from app.models.user import User
from app.services.numbering import next_quotation_number


_SYS = (
    "You are a senior quotation engineer for an Indonesian project-based industrial supplier. "
    "Return ONLY JSON matching the schema {items:[{description,qty,uom,unit_price,cost_estimate,"
    "spec}], notes, valid_until_days, payment_terms}. Use IDR. Do not invent products you can't justify."
)


async def auto(db: AsyncSession, payload: dict, user: User) -> dict:
    """Skeleton: resolve items, price, then ask LLM to compose notes/terms."""
    user_msg = json.dumps({
        "industry": payload.get("industry"),
        "items": payload.get("items", []),
        "deadline": payload.get("deadline"),
        "payment_terms_pref": payload.get("payment_terms_pref"),
    }, ensure_ascii=False)

    raw = chat(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": user_msg}],
        json_mode=True,
    )
    try:
        proposal = json.loads(raw)
    except json.JSONDecodeError:
        proposal = {"items": [], "notes": raw, "valid_until_days": 14}

    return {
        "draft_number_preview": await next_quotation_number(db, persist=False),
        "customer_id": payload.get("customer_id"),
        "variant": payload.get("variant", "detailed"),
        "items": proposal.get("items", []),
        "notes": proposal.get("notes"),
        "valid_until_days": proposal.get("valid_until_days", 14),
        "payment_terms": proposal.get("payment_terms"),
    }
