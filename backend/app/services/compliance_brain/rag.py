"""RAG query pipeline for the Compliance Brain.

Retrieves top-K relevant document chunks via pgvector similarity search,
applies optional reranking, and returns context ready for the LLM prompt.
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Task 2.1 — Keyword search via PostgreSQL tsvector
# ---------------------------------------------------------------------------

async def keyword_search(
    query: str,
    framework_name: str,
    db: AsyncSession,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    """Retrieve chunks using PostgreSQL full-text search (BM25-style ranking).

    Uses plainto_tsquery for robustness with natural-language input, and
    ts_rank_cd for cover-density ranking that rewards term proximity.
    """
    result = await db.execute(
        text(
            "SELECT chunk_text, source_section, "
            "ts_rank_cd(tsv, plainto_tsquery('english', :query)) AS score "
            "FROM regulatory_chunks "
            "WHERE framework_name = :name "
            "AND tsv @@ plainto_tsquery('english', :query) "
            "ORDER BY score DESC "
            "LIMIT :top_k"
        ),
        {"query": query, "name": framework_name, "top_k": top_k},
    )
    return [
        RetrievedChunk(
            text=row.chunk_text,
            source_section=row.source_section,
            similarity_score=float(row.score),
        )
        for row in result
    ]


# ---------------------------------------------------------------------------
# Task 2.2 — Hybrid search with Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

async def hybrid_retrieve(
    query: str,
    framework_name: str,
    db: AsyncSession,
    top_k: int = 10,
    alpha: float = 0.7,
) -> list[RetrievedChunk]:
    """Hybrid retrieval combining semantic and keyword search via RRF.

    Parameters:
        alpha: Weight for semantic search (default 0.7 = 70% semantic,
               30% keyword). Higher values favor meaning-based matches;
               lower values favor exact term matches.
    """
    # Run both searches in parallel, over-fetching for fusion diversity
    semantic_chunks, keyword_chunks = await asyncio.gather(
        retrieve_context(query, framework_name, db, top_k=top_k * 2),
        keyword_search(query, framework_name, db, top_k=top_k * 2),
    )

    # RRF constant — standard value from Cormack et al.
    k = 60

    # Build rank maps (chunk text → rank position)
    semantic_ranks: dict[str, int] = {
        c.text: rank for rank, c in enumerate(semantic_chunks)
    }
    keyword_ranks: dict[str, int] = {
        c.text: rank for rank, c in enumerate(keyword_chunks)
    }

    # Collect all unique chunks (first occurrence wins)
    all_chunks: dict[str, RetrievedChunk] = {}
    for c in semantic_chunks + keyword_chunks:
        if c.text not in all_chunks:
            all_chunks[c.text] = c

    # Compute RRF scores — chunks found by both methods get boosted
    penalty = top_k * 3  # rank penalty for chunks not found by a method
    scored: list[tuple[float, RetrievedChunk]] = []
    for text_key, chunk in all_chunks.items():
        sem_rank = semantic_ranks.get(text_key, penalty)
        kw_rank = keyword_ranks.get(text_key, penalty)
        rrf_score = alpha * (1.0 / (k + sem_rank)) + (1 - alpha) * (1.0 / (k + kw_rank))
        chunk.similarity_score = rrf_score
        scored.append((rrf_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


# ---------------------------------------------------------------------------
# Task 2.3 — Cross-encoder reranking
# ---------------------------------------------------------------------------

def rerank_by_score(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Rerank retrieved chunks by similarity score (fallback reranker).

    This is the original naive reranker — kept as a fast fallback for
    environments without an OpenAI key or for testing without API costs.
    """
    sorted_chunks = sorted(chunks, key=lambda c: c.similarity_score, reverse=True)
    return sorted_chunks[:top_n]


RERANK_SCORING_PROMPT = (
    "You are a regulatory compliance relevance scorer. "
    "Rate how relevant the following regulatory text is to the query. "
    "Return ONLY a single integer from 1 to 10.\n\n"
    "Query: {query}\n\n"
    "Regulatory Text: {text}\n\n"
    "Relevance Score (1-10):"
)


async def rerank_with_llm(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Rerank chunks using OpenAI as a cross-encoder.

    Each chunk is scored 1-10 for relevance by gpt-4o-mini. Bounded
    concurrency (semaphore=5) avoids rate-limit issues while staying
    ~4x faster than sequential scoring.
    """
    if len(chunks) <= top_n:
        return chunks

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Bounded concurrency to respect OpenAI rate limits
    semaphore = asyncio.Semaphore(5)

    async def score_chunk(chunk: RetrievedChunk) -> tuple[int, RetrievedChunk]:
        async with semaphore:
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": RERANK_SCORING_PROMPT.format(
                            query=query, text=chunk.text[:1500]
                        ),
                    }],
                    temperature=0,
                    max_tokens=3,
                )
                score_text = resp.choices[0].message.content
                if score_text is None:
                    raise ValueError("OpenAI returned no content for rerank scoring")
                score = int(score_text.strip())
                return (min(max(score, 1), 10), chunk)
            except (ValueError, Exception):
                logger.warning(
                    "Rerank scoring failed for chunk (section=%s), using default score 5",
                    chunk.source_section,
                )
                return (5, chunk)

    results = await asyncio.gather(*[score_chunk(c) for c in chunks])
    results_list = list(results)
    results_list.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in results_list[:top_n]]
