# Phase 2 — Implementation Audit Report

**Date**: 2026-05-05  
**Scope**: Phase 2 RAG Pipeline Optimization, commit `81777ef5b56ab27a2564518a54e6effcfbff66ef`  
**Verification**: 22 focused Phase 2 tests passed; `mypy app` clean; `ruff` fails on Phase 2 test files

---

## Plan vs. Implementation Checklist

| Task | Plan Requirement | Status | Notes |
|---|---|---|---|
| 2.1 | Add `005_tsvector_search.py` with generated `tsv` column and GIN index | ✅ Done | Migration matches the plan closely |
| 2.1 | Add `keyword_search()` using `plainto_tsquery` and `ts_rank_cd` | ✅ Done | Implemented in `rag.py` with parameterized SQL |
| 2.2 | Add `hybrid_retrieve()` using semantic + keyword search with RRF | ✅ Done | Uses `asyncio.gather`, `alpha=0.7`, `k=60`, and over-fetches |
| 2.3 | Replace naive reranker with LLM cross-encoder reranker | ✅ Mostly done | `rerank_with_llm()` implemented; fallback retained as `rerank_by_score()` |
| 2.3 | Error handling falls back to score 5 and does not crash | ✅ Done | Covered by tests |
| 2.3 | Log score distribution for debugging | ⚠️ Missing | Only failure warnings are logged; no distribution logging exists |
| 2.4 | Update control generation task to use hybrid retrieval and rerank | ✅ Done | `_generate_controls_async()` now calls `hybrid_retrieve(..., top_k=20)` and reranks to 10 |
| 2.4 | Config fallback when OpenAI key is unavailable | ✅ Done | Falls back to `rerank_by_score()` |
| 2.5 | Add grounding guard after citation enforcement | ✅ Done | `_ground_controls()` is called after `enforce_citations()` |
| 2.5 | Ungrounded citations get confidence `0.3` and `[UNGROUNDED]` prefix | ✅ Done | Covered by tests |
| 2.6 | Add `006_chunk_hash_dedup.py` with `chunk_hash` and unique index | ✅ Done | Migration adds and backfills `chunk_hash`, then creates unique index |
| 2.6 | Skip duplicate chunks during ingestion | ✅ Done | Duplicate check uses `(framework_name, chunk_hash)` before insert |
| 2.7 | Add `/api/v1/compliance-brain/query` endpoint | ✅ Mostly done | Endpoint exists, requires auth, runs hybrid retrieval and rerank, writes audit log |
| 2.7 | Invalid framework name returns 422 | ❌ Missing | Schema uses plain `str`; invalid frameworks are accepted |
| 2.7 | Add API tests for auth, validation, response shape, and audit logging | ⚠️ Missing | No endpoint tests were added |

---

## Definition of Done Verification

| Area | Result |
|---|---|
| Focused Phase 2 tests | ✅ `22 passed` for `test_rag.py`, `test_grounding.py`, `test_chunk_dedup.py` |
| Type checking | ✅ `mypy app` passed on the exact Phase 2 commit |
| Linting | ❌ `ruff` failed on Phase 2 test files |
| Real DB migration verification | ⚠️ Not run during this audit |
| Manual HIPAA ingestion/query quality comparison | ⚠️ Not run during this audit |
| RAG query API endpoint behavior | ⚠️ Not covered by tests |

Commands run against a temporary worktree checked out at `81777ef5b56ab27a2564518a54e6effcfbff66ef`:

```bash
/Users/vatsal/Documents/CMPE\ 295/SentinellAI/backend/venv/bin/python -m pytest tests/test_services/test_rag.py tests/test_services/test_grounding.py tests/test_services/test_chunk_dedup.py
/Users/vatsal/Documents/CMPE\ 295/SentinellAI/backend/venv/bin/ruff check app tests/test_services/test_rag.py tests/test_services/test_grounding.py tests/test_services/test_chunk_dedup.py
/Users/vatsal/Documents/CMPE\ 295/SentinellAI/backend/venv/bin/mypy app
```

---

## Issues Found

### Bug 1: Invalid framework names do not return 422

**Severity: Medium**

The Phase 2.7 Definition of Done explicitly says invalid framework names should return `422`. The implementation documents `framework` as "HIPAA or GDPR", but the schema accepts any string:

```python
framework: str = Field(
    ...,
    description="Framework name: HIPAA or GDPR",
)
```

That means a request with `"framework": "SOC2"` passes validation and reaches `hybrid_retrieve()`. Depending on data, it will likely return a normal `200` with empty chunks rather than the planned validation error.

**Recommended fix**: Change the schema to a constrained type, for example `Literal["HIPAA", "GDPR"]`, or add a Pydantic validator. Add an API test that posts an invalid framework and asserts `422`.

### Bug 2: RAG API returns stale retrieval scores after LLM reranking

**Severity: Medium**

`rerank_with_llm()` scores chunks with the LLM and sorts by those scores, but it never writes the LLM score back to `chunk.similarity_score`. The endpoint then returns:

```python
relevance_score=round(c.similarity_score, 4)
```

So when LLM reranking is enabled, the returned order is based on LLM scores, but the displayed `relevance_score` is still the previous hybrid/RRF retrieval score. That is misleading for API consumers and future UI work because the score no longer explains the ranking.

**Recommended fix**: Either update `chunk.similarity_score` to the normalized LLM score during reranking, or add a separate response field that clearly distinguishes retrieval score from rerank score.

### Bug 3: Phase 2 lint is not clean

**Severity: Low**

On the exact Phase 2 commit, the focused tests pass, but `ruff` fails:

```text
tests/test_services/test_chunk_dedup.py:18 F841 doc_hash assigned but unused
tests/test_services/test_chunk_dedup.py:19 F841 chunk_hash assigned but unused
tests/test_services/test_rag.py:6 I001 import block is un-sorted or un-formatted
```

The unused hash variables are especially relevant because they look like the test intended to assert the exact hash behavior but never did. This does not make the runtime implementation wrong, but it means the test file itself was not clean and contains dead assertions-in-waiting.

**Recommended fix**: Remove unused variables or assert that the generated insert `chunk_hash` equals the expected digest. Sort imports in `test_rag.py`.

### Gap 4: No API endpoint tests were added for Task 2.7

**Severity: Medium**

The endpoint is a new user-facing surface, but Phase 2 only added service-level tests. There are no tests covering:

- Unauthorized request returns `401`
- Invalid framework returns `422`
- `top_k` bounds are enforced
- Response shape contains ranked chunks
- `rag_query` audit log is persisted
- Fallback reranking is used when `OPENAI_API_KEY` is absent

This is where tests could pass while the implementation still misses a Definition of Done item. In fact, the missing invalid-framework validation would have been caught by a small API test.

### Gap 5: Required rerank score-distribution logging is missing

**Severity: Low**

Task 2.3 says to verify log output shows score distribution for debugging, and Task 2.4 says to check task logs for hybrid retrieval + rerank score distribution. The implementation logs rerank failures, ungrounded citations, and ingestion status, but it does not log score distributions after reranking.

**Recommended fix**: Add an info/debug log with min/max/count or histogram of LLM rerank scores and possibly the top section IDs.

---

## Test Quality Assessment

### `test_rag.py`

✅ Good coverage:
- Validates keyword search row mapping
- Validates RRF behavior when a chunk appears in both semantic and keyword results
- Validates LLM reranking sort order, score clamping, and failure fallback

⚠️ Gaps:
- Does not assert LLM rerank score is exposed or stored anywhere
- Does not verify score-distribution logging
- Uses mocks only, so PostgreSQL `tsvector` SQL is not integration-tested

### `test_grounding.py`

✅ Good coverage:
- Tests grounded and ungrounded citations
- Tests `§` and `Article` normalization
- Tests case-insensitive matching and multiple chunks

✅ Not a fake pass:
- The confidence and title assertions would fail if `_ground_controls()` were not mutating ungrounded controls correctly.

### `test_chunk_dedup.py`

✅ Good coverage:
- Exercises duplicate-skip branch and new-insert branch
- Verifies inserted chunks include a 64-character hash

⚠️ Gaps:
- Test has unused expected hash values, so it does not verify the actual digest equals SHA-256 of chunk text
- Does not assert how many inserts occurred directly
- Does not cover the "modified one line, only changed chunks inserted" Definition of Done with multiple chunks

---

## Changes Beyond Plan Scope

None concerning. The implementation stayed within the expected Phase 2 surface area:

- RAG service
- generator grounding
- ingestion deduplication
- regulatory chunk model/migrations
- evidence generation task wiring
- RAG API router/schemas
- focused service tests

---

## Overall Alignment Verdict

Phase 2 is **substantially aligned** with the implementation plan. The core RAG improvements are present: keyword search, hybrid retrieval, LLM reranking with fallback, grounding guard, chunk-level deduplication, and the query endpoint.

However, Phase 2 should not be considered perfectly complete until these are fixed:

| Item | Priority |
|---|---|
| Enforce valid framework names with `422` for invalid values | High |
| Add API tests for `/api/v1/compliance-brain/query` | High |
| Decide how LLM rerank scores should be represented in API responses | Medium |
| Clean `ruff` failures in Phase 2 tests | Medium |
| Add rerank score-distribution logging | Low |

The biggest test-integrity concern is Task 2.7: the service tests pass, but the missing API tests allow at least one explicit Definition of Done item, invalid framework validation, to remain broken.
