"""Purchasing module — PR → RFQ → PO → GR → QC → Payment.

Stubs scaffolded; full implementation follows the same pattern as quotations.
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/pr")
async def list_pr(_user: User = Depends(get_current_user)):
    return []


@router.post("/pr")
async def create_pr(_user: User = Depends(get_current_user)):
    return {"status": "todo"}


@router.post("/pr/{pr_id}/rfq")
async def spawn_rfq(pr_id: str, _user: User = Depends(get_current_user)):
    return {"pr_id": pr_id, "rfqs": []}


@router.post("/rfq/{rfq_id}/po")
async def rfq_to_po(rfq_id: str, _user: User = Depends(get_current_user)):
    return {"rfq_id": rfq_id, "po_id": "todo"}


@router.post("/po/{po_id}/gr")
async def goods_receipt(po_id: str, _user: User = Depends(get_current_user)):
    return {"po_id": po_id, "gr_id": "todo"}


@router.post("/po/{po_id}/qc")
async def qc(po_id: str, _user: User = Depends(get_current_user)):
    return {"po_id": po_id, "qc_id": "todo"}
