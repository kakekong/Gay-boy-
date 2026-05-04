"""AI endpoints — orchestrate the modules under app.ai."""

from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import (
    assistant,
    deal_risk,
    doc_parser,
    kb,
    lead_score,
    loss_analysis,
    profit_engine,
    quotation_auto,
    sales_coach,
    supply_risk,
    upsell,
)
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.post("/lead-score/{customer_id}")
async def recompute_lead_score(customer_id: UUID, db: AsyncSession = Depends(get_db),
                               _user: User = Depends(get_current_user)):
    return await lead_score.compute(db, customer_id)


@router.get("/lead-score/{customer_id}")
async def get_lead_score(customer_id: UUID, db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    return await lead_score.get_latest(db, customer_id)


@router.post("/deal-risk/scan")
async def scan_risk(db: AsyncSession = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    return await deal_risk.scan_all(db)


@router.get("/deal-risk")
async def list_risk(db: AsyncSession = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    return await deal_risk.list_at_risk(db)


@router.post("/assistant/suggest")
async def assistant_suggest(payload: dict,
                            db: AsyncSession = Depends(get_db),
                            _user: User = Depends(get_current_user)):
    return await assistant.suggest(db, payload)


@router.post("/quotation/auto")
async def quote_auto(payload: dict,
                     db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return await quotation_auto.auto(db, payload, user)


@router.post("/document/parse")
async def parse_document(file: UploadFile,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    blob = await file.read()
    return await doc_parser.parse(db, blob, filename=file.filename, content_type=file.content_type)


@router.post("/upsell/{customer_id}")
async def upsell_for(customer_id: UUID, db: AsyncSession = Depends(get_db),
                     _user: User = Depends(get_current_user)):
    return await upsell.for_customer(db, customer_id)


@router.get("/loss-analysis/patterns")
async def loss_patterns(db: AsyncSession = Depends(get_db),
                        _user: User = Depends(get_current_user)):
    return await loss_analysis.patterns(db)


@router.get("/coach/{user_id}")
async def coach(user_id: UUID, db: AsyncSession = Depends(get_db),
                _user: User = Depends(get_current_user)):
    return await sales_coach.advise(db, user_id)


@router.post("/kb/search")
async def kb_search(payload: dict, db: AsyncSession = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    return await kb.search(db, payload.get("query", ""), top_k=payload.get("top_k", 5))


@router.post("/kb/index")
async def kb_index(payload: dict, db: AsyncSession = Depends(get_db),
                   _user: User = Depends(get_current_user)):
    return await kb.index(db, payload)


@router.get("/profit/{project_id}")
async def project_profit(project_id: UUID, db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    return await profit_engine.for_project(db, project_id)


@router.get("/supply-risk")
async def supply_risk_dash(db: AsyncSession = Depends(get_db),
                           _user: User = Depends(get_current_user)):
    return await supply_risk.dashboard(db)
