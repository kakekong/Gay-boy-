"""Knowledge Base AI — semantic search of company memory.

Uses pgvector. Schema and migration are not yet wired here; the API surface
matches the spec so frontend integration can proceed.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import embed


async def index(db: AsyncSession, payload: dict) -> dict:
    text = payload.get("body") or ""
    if not text:
        return {"error": "empty"}
    vec = embed(text[:6000])
    # In a real implementation: insert into kb_documents + embeddings.
    return {"indexed": True, "dim": len(vec)}


async def search(db: AsyncSession, query: str, *, top_k: int = 5) -> dict:
    if not query:
        return {"results": []}
    vec = embed(query)
    # Real impl: ORDER BY embedding <=> :vec LIMIT :k
    return {"query": query, "dim": len(vec), "results": []}
