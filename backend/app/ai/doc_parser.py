"""Document Intelligence — parse PO PDF / image / text into structured data."""

import io
import json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import chat


_PO_SCHEMA_PROMPT = """\
Extract the following JSON schema from the document text below.
{
  "customer_company": string,
  "po_number": string,
  "po_date": "YYYY-MM-DD",
  "delivery_address": string,
  "items": [{"description": string, "qty": number, "uom": string, "unit_price": number}],
  "payment_terms": string,
  "deadline": "YYYY-MM-DD"
}
Return ONLY the JSON object. If any field is missing, set it to null.
"""


async def parse(db: AsyncSession, blob: bytes, *, filename: str | None = None,
                content_type: str | None = None) -> dict:
    text = _extract_text(blob, content_type)
    if not text.strip():
        return {"error": "no_text_extracted", "filename": filename}
    raw = chat(
        [
            {"role": "system", "content": "You extract structured data from Indonesian/English POs."},
            {"role": "user", "content": _PO_SCHEMA_PROMPT + "\n\nDOCUMENT:\n" + text[:8000]},
        ],
        json_mode=True,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON for PO parse")
        data = {"raw": raw}
    confidence = _heuristic_confidence(data)
    return {
        "filename": filename,
        "extracted": data,
        "confidence": confidence,
        "needs_review": confidence < 0.7,
    }


def _extract_text(blob: bytes, content_type: str | None) -> str:
    if content_type and "pdf" in content_type:
        try:
            from pdfminer.high_level import extract_text
            return extract_text(io.BytesIO(blob)) or ""
        except Exception as exc:
            logger.warning(f"pdfminer failed: {exc}")
            return ""
    if content_type and content_type.startswith("image/"):
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(io.BytesIO(blob))
            return pytesseract.image_to_string(img)
        except Exception as exc:
            logger.warning(f"OCR failed: {exc}")
            return ""
    # fallback: assume text
    try:
        return blob.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _heuristic_confidence(data: dict) -> float:
    if not isinstance(data, dict):
        return 0.0
    fields = ["po_number", "items", "deadline"]
    present = sum(1 for f in fields if data.get(f))
    return round(present / len(fields), 2)
