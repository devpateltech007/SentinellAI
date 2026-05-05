"""API router for the Compliance Brain RAG query endpoint.

Exposes the hybrid-search + cross-encoder reranking pipeline as a
queryable REST API so the frontend can build an interactive
"Ask the Compliance Brain" feature.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.models.audit_log import AuditLog
from app.schemas.compliance_brain import (
    RAGChunkResponse,
    RAGQueryRequest,
    RAGQueryResponse,
)
from app.services.compliance_brain.rag import (
    hybrid_retrieve,
    rerank_by_score,
    rerank_with_llm,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance-brain", tags=["compliance-brain"])


@router.post("/query", response_model=RAGQueryResponse)
async def query_compliance_brain(
    body: RAGQueryRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    """Query the Compliance Brain with a natural-language question.

    Returns the most relevant regulatory text chunks from the specified
    framework, ranked by a hybrid semantic + keyword search pipeline
    with optional LLM-based cross-encoder reranking.
    """
    # Over-fetch at retrieval stage to give the reranker a diverse candidate pool
    chunks = await hybrid_retrieve(body.query, body.framework, db, top_k=body.top_k * 3)
    total_searched = len(chunks)

    if settings.OPENAI_API_KEY:
        reranked = await rerank_with_llm(body.query, chunks, top_n=body.top_k)
    else:
        reranked = rerank_by_score(body.query, chunks, top_n=body.top_k)

    # Audit log — record every RAG query for compliance traceability
    audit_entry = AuditLog(
        actor_id=current_user.id,
        action="rag_query",
        resource_type="compliance_brain",
        resource_id=None,
        detail_json={"query": body.query, "framework": body.framework},
    )
    db.add(audit_entry)

    return RAGQueryResponse(
        query=body.query,
        framework=body.framework,
        chunks=[
            RAGChunkResponse(
                text=c.text,
                source_section=c.source_section,
                relevance_score=round(c.similarity_score, 4),
            )
            for c in reranked
        ],
        total_chunks_searched=total_searched,
    )
