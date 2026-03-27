"""RAG query pipeline for the Compliance Brain.

Retrieves top-K relevant document chunks via pgvector similarity search,
applies optional reranking, and returns context ready for the LLM prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass
class RetrievedChunk:
    text: str
    source_section: str
    similarity_score: float


async def retrieve_context(
    query: str,
    framework_name: str,
    db: AsyncSession,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    """Retrieve the most relevant document chunks for a RAG query."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.embeddings.create(input=[query], model=EMBEDDING_MODEL)
    query_embedding = resp.data[0].embedding

    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    result = await db.execute(
        text(
            "SELECT chunk_text, source_section, "
            "1 - (embedding <=> CAST(:emb AS vector)) AS score "
            "FROM regulatory_chunks "
            "WHERE framework_name = :name "
            "ORDER BY embedding <=> CAST(:emb AS vector) "
            "LIMIT :top_k"
        ),
        {"emb": embedding_str, "name": framework_name, "top_k": top_k},
    )

    chunks = []
    for row in result:
        chunks.append(
            RetrievedChunk(
                text=row.chunk_text,
                source_section=row.source_section,
                similarity_score=float(row.score),
            )
        )

    logger.info("Retrieved %d chunks for query (framework=%s)", len(chunks), framework_name)
    return chunks


async def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Rerank retrieved chunks by relevance. Currently returns top-N by score."""
    sorted_chunks = sorted(chunks, key=lambda c: c.similarity_score, reverse=True)
    return sorted_chunks[:top_n]
