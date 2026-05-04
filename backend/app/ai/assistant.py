"""Sales AI Assistant — WA follow-ups, closing strategy, stalled detection."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import chat
from app.models.crm import Activity, Customer


_SYSTEM_PROMPTS = {
    "wa_followup": (
        "You are a senior B2B industrial sales coach. Write WhatsApp follow-up messages "
        "in Bahasa Indonesia. Tone: respectful, concise, professional. Always include one "
        "concrete ask. Reference the last activity. Do NOT invent prices."
    ),
    "closing_strategy": (
        "You are a senior B2B sales strategist for industrial engineering. "
        "Suggest 3 concrete closing tactics, an objection-handling line, and a concession ladder."
    ),
    "stalled_detection": (
        "You analyze deal activity to detect stalls. Output JSON "
        "{\"stalled\": bool, \"reason\": str, \"recommendation\": str}."
    ),
}


async def suggest(db: AsyncSession, payload: dict) -> dict:
    intent = payload.get("intent", "wa_followup")
    if intent not in _SYSTEM_PROMPTS:
        return {"error": "unknown_intent"}

    customer_id = payload.get("customer_id")
    context = await _gather_context(db, customer_id) if customer_id else {}
    user_msg = payload.get("prompt") or _default_user_prompt(intent, context)

    text = chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPTS[intent]},
            {"role": "user", "content": user_msg},
        ],
        json_mode=(intent == "stalled_detection"),
    )
    return {"intent": intent, "output": text, "context_used": context}


async def _gather_context(db: AsyncSession, customer_id: str) -> dict:
    customer = await db.get(Customer, customer_id)
    if not customer:
        return {}
    last = (await db.scalars(
        select(Activity).where(Activity.customer_id == customer_id)
        .order_by(Activity.occurred_at.desc()).limit(5)
    )).all()
    return {
        "company": customer.company_name,
        "industry": customer.industry,
        "stage": customer.stage,
        "last_activities": [
            {"type": a.type, "direction": a.direction, "at": a.occurred_at.isoformat(),
             "notes": (a.notes or "")[:200]} for a in last
        ],
    }


def _default_user_prompt(intent: str, ctx: dict) -> str:
    if intent == "wa_followup":
        return (f"Customer: {ctx.get('company')} ({ctx.get('industry')}). "
                f"Stage: {ctx.get('stage')}. Last activities: {ctx.get('last_activities')}. "
                "Write 2 short WhatsApp follow-ups in Bahasa Indonesia.")
    if intent == "closing_strategy":
        return f"Deal context: {ctx}. Suggest closing strategy."
    return f"Activity history: {ctx.get('last_activities')}. Detect stalled deal."
