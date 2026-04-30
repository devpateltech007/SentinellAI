# Phase 2 — RAG Pipeline Optimization

> **Estimated Total**: 28 engineering hours
> **Dependencies**: None from Phase 1 (can start in parallel)
> **Rationale**: The current RAG pipeline uses naive vector-only search and a simple sort-by-score reranker. For a compliance platform, retrieval precision is critical — a missed regulatory clause means a missed control, which means audit failure. This phase upgrades to hybrid search, cross-encoder reranking, and prompt grounding to eliminate hallucinated citations.

---

## Current State of the RAG Pipeline

| Component | File | Status |
|---|---|---|
| Document Ingestion | `services/compliance_brain/ingestion.py` | ✅ Working — chunks docs, embeds via OpenAI, stores in pgvector |
| Vector Search | `services/compliance_brain/rag.py` | 🟡 Semantic-only, no keyword fallback |
| Reranking | `services/compliance_brain/rag.py:69-76` | 🔴 Naive `sorted()` by similarity score — not a real reranker |
| Control Generator | `services/compliance_brain/generator.py` | 🟡 Works but no grounding validation |
| Citation Enforcement | `services/compliance_brain/citation.py` | 🟡 Checks citation exists but not that it's real |
| Deduplication | `services/compliance_brain/ingestion.py:49-57` | 🟡 Doc-level only, not chunk-level |

---

## Task 2.1: Add Keyword Search via `ts_vector`

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/alembic/versions/005_tsvector_search.py`

**Files to Edit**:
- `backend/app/services/compliance_brain/rag.py` — add `keyword_search()` function

**Detailed Logic Brief**:

Vector/semantic search excels at understanding meaning ("data protection" matches "information security") but misses exact regulatory clause references. When an auditor searches for "§ 164.312(a)(2)(iv)", semantic search may return tangentially related chunks because the embedding model doesn't treat clause numbers as high-signal tokens. Keyword search (BM25-style via PostgreSQL `tsvector`) solves this by matching exact terms.

**Step 1 — Alembic Migration** `005_tsvector_search.py`:

```python
def upgrade():
    # Add tsvector column
    op.execute(
        "ALTER TABLE regulatory_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED"
    )
    # Add GIN index for fast full-text search
    op.execute(
        "CREATE INDEX idx_regulatory_chunks_tsv "
        "ON regulatory_chunks USING GIN (tsv)"
    )

def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_regulatory_chunks_tsv")
    op.execute("ALTER TABLE regulatory_chunks DROP COLUMN IF EXISTS tsv")
```

Using a `GENERATED ALWAYS AS ... STORED` column means PostgreSQL automatically maintains the tsvector whenever `chunk_text` is inserted or updated — no application-level code needed to keep it in sync.

**Step 2 — Add `keyword_search()` function** in `rag.py`:

```python
async def keyword_search(
    query: str,
    framework_name: str,
    db: AsyncSession,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    """Retrieve chunks using PostgreSQL full-text search (BM25-style ranking)."""
    # Convert natural language query to tsquery
    # Use plainto_tsquery for robustness (handles spaces, ignores operators)
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
```

**Why `plainto_tsquery` instead of `to_tsquery`?** `to_tsquery` requires boolean operator syntax (`&`, `|`). User queries like "encryption at rest HIPAA" would fail. `plainto_tsquery` treats all words as AND-ed terms automatically — much more robust for natural language input.

**Why `ts_rank_cd` instead of `ts_rank`?** `ts_rank_cd` uses cover density ranking, which considers the proximity of matching terms. For regulatory text where related concepts are often in the same paragraph, this produces better results than simple frequency-based ranking.

**Definition of Done**:
1. Run `alembic upgrade head` — migration applies. `\d regulatory_chunks` shows `tsv` column of type `tsvector`.
2. Ingest the HIPAA document (if not already done).
3. Test via psql: `SELECT chunk_text, ts_rank_cd(tsv, plainto_tsquery('english', 'encryption ePHI')) AS score FROM regulatory_chunks WHERE framework_name = 'HIPAA' AND tsv @@ plainto_tsquery('english', 'encryption ePHI') ORDER BY score DESC LIMIT 5;` — returns chunks containing those terms.
4. Call `keyword_search("§ 164.312(a)", "HIPAA", db)` — returns chunks referencing that specific clause (which vector search might miss).

---

## Task 2.2: Implement Hybrid Search (Semantic + Keyword Fusion)

**Estimated Time**: 4 hours

**Files to Edit**:
- `backend/app/services/compliance_brain/rag.py` — add `hybrid_retrieve()` function

**Detailed Logic Brief**:

Neither semantic search nor keyword search alone is sufficient. Semantic search finds conceptually related chunks but may miss exact clause references. Keyword search finds exact matches but misses paraphrased requirements. Hybrid search combines both using **Reciprocal Rank Fusion (RRF)**, a well-established technique from information retrieval.

**Implementation**:

```python
async def hybrid_retrieve(
    query: str,
    framework_name: str,
    db: AsyncSession,
    top_k: int = 10,
    alpha: float = 0.7,
) -> list[RetrievedChunk]:
    """Hybrid retrieval combining semantic and keyword search via RRF."""
    # Run both searches in parallel
    semantic_chunks, keyword_chunks = await asyncio.gather(
        retrieve_context(query, framework_name, db, top_k=top_k * 2),
        keyword_search(query, framework_name, db, top_k=top_k * 2),
    )

    # Build rank maps (chunk text -> rank position)
    k = 60  # RRF constant — standard value from literature
    semantic_ranks: dict[str, int] = {
        c.text: rank for rank, c in enumerate(semantic_chunks)
    }
    keyword_ranks: dict[str, int] = {
        c.text: rank for rank, c in enumerate(keyword_chunks)
    }

    # Collect all unique chunks
    all_chunks: dict[str, RetrievedChunk] = {}
    for c in semantic_chunks + keyword_chunks:
        if c.text not in all_chunks:
            all_chunks[c.text] = c

    # Compute RRF scores
    scored: list[tuple[float, RetrievedChunk]] = []
    for text_key, chunk in all_chunks.items():
        sem_rank = semantic_ranks.get(text_key, top_k * 3)  # penalty if not found
        kw_rank = keyword_ranks.get(text_key, top_k * 3)
        rrf_score = alpha * (1.0 / (k + sem_rank)) + (1 - alpha) * (1.0 / (k + kw_rank))
        chunk.similarity_score = rrf_score
        scored.append((rrf_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
```

**Why `alpha = 0.7`?** We weight semantic search higher (70%) because regulatory language is often paraphrased across documents. But the 30% keyword weight ensures exact clause numbers and technical terms like "AES-256" or "ePHI" aren't missed. This is tunable per use case.

**Why `k = 60`?** This is the standard RRF constant from the original Cormack et al. paper. It dampens the influence of rank position — a chunk ranked #1 vs #2 has a smaller score gap than #1 vs #10. This prevents a single search method from dominating.

**Why fetch `top_k * 2` from each source?** We over-fetch to ensure sufficient overlap for fusion. After RRF scoring and deduplication, we trim to the final `top_k`.

**Definition of Done**:
1. Ingest HIPAA document if needed.
2. Test query: `hybrid_retrieve("minimum necessary access control ePHI", "HIPAA", db, top_k=5)`.
3. Compare results with `retrieve_context()` alone and `keyword_search()` alone.
4. Hybrid results should include: (a) chunks semantically related to "access control" that vector search found, AND (b) chunks containing exact term "ePHI" that keyword search found.
5. Chunks appearing in both methods should rank highest (they get RRF contribution from both sides).

---

## Task 2.3: Implement Cross-Encoder Reranking

**Estimated Time**: 4 hours

**Files to Edit**:
- `backend/app/services/compliance_brain/rag.py` — replace naive `rerank()` with `rerank_with_llm()`

**Detailed Logic Brief**:

The current reranker (lines 69-76) is a simple `sorted()` by the similarity score from vector search. This is a **bi-encoder** approach — the query and document are encoded independently. A **cross-encoder** approach feeds both the query and each candidate document into the same model simultaneously, allowing it to attend to fine-grained interactions between them. This dramatically improves relevance ranking.

We use OpenAI's GPT model as a cross-encoder by prompting it to score each chunk:

```python
async def rerank_with_llm(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Rerank chunks using OpenAI as a cross-encoder."""
    if len(chunks) <= top_n:
        return chunks

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    SCORING_PROMPT = (
        "You are a regulatory compliance relevance scorer. "
        "Rate how relevant the following regulatory text is to the query. "
        "Return ONLY a single integer from 1 to 10.\n\n"
        "Query: {query}\n\n"
        "Regulatory Text: {text}\n\n"
        "Relevance Score (1-10):"
    )

    # Score all chunks concurrently with bounded concurrency
    semaphore = asyncio.Semaphore(5)  # max 5 concurrent API calls

    async def score_chunk(chunk: RetrievedChunk) -> tuple[int, RetrievedChunk]:
        async with semaphore:
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",  # cheaper model sufficient for scoring
                    messages=[{
                        "role": "user",
                        "content": SCORING_PROMPT.format(
                            query=query, text=chunk.text[:1500]
                        ),
                    }],
                    temperature=0,
                    max_tokens=3,
                )
                score_text = resp.choices[0].message.content.strip()
                score = int(score_text)
                return (min(max(score, 1), 10), chunk)
            except (ValueError, Exception):
                logger.warning("Rerank scoring failed for chunk, using default score 5")
                return (5, chunk)

    results = await asyncio.gather(*[score_chunk(c) for c in chunks])
    results.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in results[:top_n]]
```

**Why `gpt-4o-mini` instead of `gpt-4o`?** Relevance scoring is a simple classification task (output is a single integer). Using the full `gpt-4o` would be 10-15x more expensive with marginal accuracy gain. `gpt-4o-mini` is sufficient and keeps latency under ~200ms per chunk.

**Why `max_tokens=3`?** The response should be a single integer (1-10). Setting `max_tokens=3` prevents the model from generating explanations, keeping costs minimal and parsing simple.

**Why a semaphore of 5?** OpenAI rate limits vary by tier. With 10-20 chunks to score, 5 concurrent requests avoids hitting per-minute token limits while still being ~4x faster than sequential calls.

**Why truncate to 1500 chars?** Some regulatory chunks can be large. Truncating to 1500 characters keeps each scoring call fast and cheap while providing enough context for relevance judgment.

**Keep the old `rerank()` function** renamed to `rerank_by_score()` as a fallback for when OpenAI API is unavailable or for testing without API costs.

**Definition of Done**:
1. Call `rerank_with_llm("minimum necessary access", chunks, top_n=5)` where `chunks` includes both highly relevant HIPAA access control chunks and irrelevant preamble chunks.
2. Verify: §164.312(a) related chunks score 8-10, preamble/definitions chunks score 1-3.
3. Final output has the high-score chunks first.
4. Test error handling: mock an API failure — function falls back to score 5 for affected chunks and doesn't crash.
5. Verify log output shows score distribution for debugging.

---

## Task 2.4: Update Evidence Tasks to Use Hybrid Search + Rerank

**Estimated Time**: 2 hours

**Files to Edit**:
- `backend/app/workers/evidence_tasks.py` — lines 76-78

**Detailed Logic Brief**:

The `_generate_controls_async()` function in `evidence_tasks.py` currently calls the old retrieval functions on lines 77-78:

```python
chunks = await retrieve_context(query, framework_name, db, top_k=15)
top_chunks = await rerank(query, chunks, top_n=10)
```

Replace with the upgraded pipeline:

```python
from app.services.compliance_brain.rag import hybrid_retrieve, rerank_with_llm

chunks = await hybrid_retrieve(query, framework_name, db, top_k=20)
top_chunks = await rerank_with_llm(query, chunks, top_n=10)
```

**Why `top_k=20` for hybrid and `top_n=10` for rerank?** Over-fetch at the retrieval stage (20 chunks) to give the reranker a diverse candidate pool. The reranker then selects the 10 most relevant chunks to feed into the LLM control generator. Feeding more than ~10 chunks into the generator risks context overflow and dilutes the signal.

Also add a config-based fallback for environments without an OpenAI key:

```python
if settings.OPENAI_API_KEY:
    top_chunks = await rerank_with_llm(query, chunks, top_n=10)
else:
    top_chunks = rerank_by_score(query, chunks, top_n=10)
```

**Definition of Done**:
1. Trigger `generate_controls_for_framework` for a HIPAA framework.
2. Generated controls must include accurate citations that match actual regulatory sections from the ingested document.
3. Compare control quality with the old pipeline (run both, diff the output) — new pipeline should produce more specific, accurately-cited controls.
4. Check Celery task logs for the hybrid retrieval + rerank score distribution.

---

## Task 2.5: Add Prompt Grounding Guard

**Estimated Time**: 4 hours

**Files to Edit**:
- `backend/app/services/compliance_brain/generator.py` — add grounding check after LLM call

**Detailed Logic Brief**:

Even with perfect retrieval and reranking, LLMs can hallucinate citations. The model might generate a control citing "§ 164.308(a)(7)(ii)(A)" when that clause was never in the provided context. For a compliance platform, a hallucinated citation is worse than no citation — it gives false confidence.

**Add grounding validation after line 163** (after `enforce_citations()` runs):

```python
def _ground_controls(
    controls: list[GeneratedControl],
    context_chunks: list[dict],
) -> list[GeneratedControl]:
    """Verify that each control's citation actually exists in the provided context."""
    # Build a single searchable text from all context chunks
    full_context = " ".join(c["text"] for c in context_chunks).lower()

    for control in controls:
        citation = control.source_citation.strip()
        if not citation:
            continue

        # Extract the core clause reference (e.g., "164.312(a)(1)" from "§ 164.312(a)(1)")
        # Strip common prefixes
        clean_citation = citation.replace("§", "").replace("Article", "").strip()

        # Check if the citation appears in any provided context chunk
        if clean_citation.lower() not in full_context:
            logger.warning(
                "UNGROUNDED citation detected: %s for control %s",
                citation, control.control_id_code,
            )
            control.confidence = 0.3
            control.title = f"[UNGROUNDED] {control.title}"

    return controls
```

Then in `generate_controls()`, insert the call after citation enforcement:

```python
valid, rejected = enforce_citations(controls)
valid = _ground_controls(valid, context_chunks)  # NEW
```

**Why string matching instead of semantic similarity?** Regulatory citation references (like "§ 164.312(a)(1)") are exact identifiers, not natural language concepts. Semantic similarity would be overkill and unreliable for matching structured references. Simple substring matching after normalization is both faster and more accurate.

**What happens to ungrounded controls?** They aren't deleted — they're kept with `confidence = 0.3`, which means they'll be stored with status `NEEDS_REVIEW` (see `evidence_tasks.py` line 97: `ControlStatusEnum.PENDING if gc.confidence >= 0.7 else ControlStatusEnum.NEEDS_REVIEW`). The `[UNGROUNDED]` prefix in the title makes them immediately visible to compliance managers in the UI.

**Definition of Done**:
1. Feed the generator context containing ONLY §164.312 sections.
2. If any generated control cites §164.308 (which was NOT in the context), it must have `confidence = 0.3` and title prefixed with `[UNGROUNDED]`.
3. Controls citing §164.312 subsections that ARE in the context should retain their original confidence scores.
4. Log output shows "UNGROUNDED citation detected" warnings for hallucinated citations.

---

## Task 2.6: Add Chunk-Level Deduplication

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/alembic/versions/006_chunk_hash_dedup.py`

**Files to Edit**:
- `backend/app/services/compliance_brain/ingestion.py` — add per-chunk dedup

**Detailed Logic Brief**:

Current deduplication is document-level only (lines 49-57 in `ingestion.py`). If the same document is re-ingested with a minor edit (e.g., a typo fix in the preamble), the entire document gets a new `doc_hash`, and ALL chunks are re-inserted — including the 95% that didn't change. This wastes storage and creates duplicate embeddings that dilute search quality.

**Step 1 — Migration** `006_chunk_hash_dedup.py`:

```python
def upgrade():
    op.add_column("regulatory_chunks",
        sa.Column("chunk_hash", sa.String(64), nullable=True)
    )
    # Backfill existing rows
    op.execute(
        "UPDATE regulatory_chunks SET chunk_hash = encode(sha256(chunk_text::bytea), 'hex')"
    )
    op.alter_column("regulatory_chunks", "chunk_hash", nullable=False)
    # Add unique constraint per framework
    op.create_index(
        "ix_regulatory_chunks_framework_hash",
        "regulatory_chunks",
        ["framework_name", "chunk_hash"],
        unique=True,
    )

def downgrade():
    op.drop_index("ix_regulatory_chunks_framework_hash")
    op.drop_column("regulatory_chunks", "chunk_hash")
```

**Step 2 — Update ingestion** in `ingestion.py`:

Before inserting each chunk (around line 93), compute the chunk hash and check for existence:

```python
import hashlib

for chunk in chunks:
    chunk_hash = hashlib.sha256(chunk.text.encode()).hexdigest()

    existing_chunk = await db.execute(
        text(
            "SELECT id FROM regulatory_chunks "
            "WHERE framework_name = :name AND chunk_hash = :hash"
        ),
        {"name": framework_name, "hash": chunk_hash},
    )
    if existing_chunk.scalar():
        logger.debug("Skipping duplicate chunk %d (hash=%s)", chunk.chunk_index, chunk_hash[:12])
        continue

    # ... proceed with embedding and insertion, adding chunk_hash to the INSERT
```

**Performance note**: The `ix_regulatory_chunks_framework_hash` index makes the existence check O(log n). For a typical HIPAA document with ~50 chunks, this adds negligible overhead.

**Definition of Done**:
1. Run `alembic upgrade head`. Verify `chunk_hash` column exists and is populated for existing rows.
2. Run `ingest_document("regulatory_docs/hipaa_security_rule.txt", "HIPAA", db)` — first run inserts N chunks.
3. Run the exact same command again — second run inserts 0 new chunks. Logs show "Skipping duplicate chunk" messages.
4. Modify one line in the HIPAA document. Re-run ingestion — only the changed chunk(s) are inserted. Unchanged chunks are skipped.

---

## Task 2.7: Add RAG Query API Endpoint

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/api/compliance_brain.py`
- `backend/app/schemas/compliance_brain.py`

**Files to Edit**:
- `backend/app/main.py` — register new router

**Detailed Logic Brief**:

This endpoint exposes the RAG pipeline as a queryable API so the frontend can build an interactive "Ask the Compliance Brain" feature. Users can type natural language questions about regulatory requirements and get back the most relevant regulatory text chunks.

**Step 1 — Pydantic v2 Schemas** in `schemas/compliance_brain.py`:

```python
from pydantic import BaseModel, Field, ConfigDict

class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500,
                       description="Natural language query about regulatory requirements")
    framework: str = Field(..., description="Framework name: HIPAA or GDPR")
    top_k: int = Field(default=5, ge=1, le=20,
                       description="Number of chunks to return")

class RAGChunkResponse(BaseModel):
    text: str
    source_section: str
    relevance_score: float

class RAGQueryResponse(BaseModel):
    query: str
    framework: str
    chunks: list[RAGChunkResponse]
    total_chunks_searched: int
```

**Step 2 — API Endpoint** in `api/compliance_brain.py`:

```python
router = APIRouter(prefix="/compliance-brain", tags=["compliance-brain"])

@router.post("/query", response_model=RAGQueryResponse)
async def query_compliance_brain(
    body: RAGQueryRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    chunks = await hybrid_retrieve(body.query, body.framework, db, top_k=body.top_k * 3)
    reranked = await rerank_with_llm(body.query, chunks, top_n=body.top_k)

    return RAGQueryResponse(
        query=body.query,
        framework=body.framework,
        chunks=[
            RAGChunkResponse(
                text=c.text, source_section=c.source_section,
                relevance_score=round(c.similarity_score, 4),
            ) for c in reranked
        ],
        total_chunks_searched=len(chunks),
    )
```

**Step 3 — Register Router** in `main.py`:

```python
from app.api import compliance_brain
app.include_router(compliance_brain.router, prefix=PREFIX)
```

**Step 4 — Add audit logging**: Log every query to `audit_logs` with `action="rag_query"` and `detail={"query": body.query, "framework": body.framework}`. This creates a record of what compliance questions users are asking.

**Definition of Done**:
1. `POST /api/v1/compliance-brain/query` with `{"query": "encryption requirements for data at rest", "framework": "HIPAA", "top_k": 5}` returns 5 ranked chunks with relevance scores.
2. Chunks reference actual HIPAA sections about encryption (§164.312(a)(2)(iv) etc.).
3. Unauthorized request (no token) returns 401.
4. Invalid framework name returns 422 (add a validator or handle gracefully).
5. Query is logged in `audit_logs` table.

---

## Phase 2 — Dependency Graph

```
Task 2.1 (Keyword Search)         — No dependencies
Task 2.2 (Hybrid Search)          — Depends on 2.1
Task 2.3 (Cross-Encoder Rerank)   — No dependencies
Task 2.4 (Wire into Evidence)     — Depends on 2.2 + 2.3
Task 2.5 (Grounding Guard)        — No dependencies
Task 2.6 (Chunk Dedup)            — No dependencies
Task 2.7 (RAG Query API)          — Depends on 2.2 + 2.3
```

**Parallelization**: Tasks 2.1, 2.3, 2.5, and 2.6 can all start simultaneously. Task 2.2 follows 2.1. Tasks 2.4 and 2.7 follow after both 2.2 and 2.3 are complete.

**Recommended assignment for a 4-person team**:
- **Person A**: Tasks 2.1 → 2.2 (search infrastructure)
- **Person B**: Task 2.3 → 2.7 (reranking + API)
- **Person C**: Task 2.5 (grounding guard — can also work on Phase 1 tasks)
- **Person D**: Task 2.6 → 2.4 (dedup + final wiring)
