# Phase 7 — Testing & Production Polish

> **Estimated Total**: 20 engineering hours
> **Dependencies**: All prior phases should be substantially complete.
> **Rationale**: The platform has zero integration tests and lacks production-grade observability. No compliance platform can ship without verified correctness and operational readiness.

---

## Current Test State

| File | Coverage |
|---|---|
| `tests/conftest.py` | ✅ Solid — DB setup/teardown, role-based token fixtures, ASGI test client |
| `tests/test_api/test_auth.py` | 🟡 Basic register/login |
| `tests/test_api/test_projects.py` | 🟡 CRUD happy path |
| `tests/test_api/test_connectors.py` | 🟡 Create + list |
| `tests/test_api/test_dashboard.py` | 🟡 Summary endpoint |
| `tests/test_api/test_evidence.py` | 🟡 List endpoint |
| `tests/test_api/test_rbac.py` | 🟡 Role enforcement |
| `tests/test_api/test_reports.py` | 🟡 Export endpoint |
| `tests/test_api/test_health.py` | ✅ Basic health check |
| Service-level tests | 🔴 None exist |

---

## Task 7.1: Add Integration Tests for Evidence Pipeline

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/tests/test_services/test_evidence_pipeline.py`
- `backend/tests/test_services/__init__.py`

**Detailed Logic Brief**:

Test the full evidence lifecycle: raw collection → validation → redaction → normalization → DB persistence → integrity verification. Mock the GitHub API using `httpx`'s mock transport so no real API calls are made.

```python
"""Integration tests for the evidence collection → storage → verification pipeline."""

import json
import hashlib
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.services.evidence_engine.base import RawEvidence
from app.services.evidence_engine.normalizer import normalize_evidence, DEFAULT_REDACTION_CONFIG
from app.services.evidence_engine.redaction import redact_fields, REDACTION_PLACEHOLDER
from app.services.evidence_engine.github_actions import GitHubActionsConnector


class TestRedaction:
    def test_email_redaction(self):
        content = {"author": "dev@company.com", "message": "fix bug"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert REDACTION_PLACEHOLDER in redacted["author"]
        assert redacted["message"] == "fix bug"  # Non-PII unchanged

    def test_ssn_redaction(self):
        content = {"data": "SSN is 123-45-6789"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert "123-45-6789" not in redacted["data"]

    def test_no_pii_no_redaction(self):
        content = {"status": "success", "count": 42}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is False
        assert redacted == content

    def test_nested_dict_redaction(self):
        content = {"outer": {"inner": {"email": "user@test.com"}}}
        redacted, _ = redact_fields(content, {"pattern_scan": True})
        assert REDACTION_PLACEHOLDER in redacted["outer"]["inner"]["email"]

    def test_field_level_redaction(self):
        content = {"password": "secret123", "name": "test"}
        redacted, was_redacted = redact_fields(content, {"password": True})
        assert redacted["password"] == REDACTION_PLACEHOLDER
        assert redacted["name"] == "test"


class TestNormalization:
    def test_normalize_with_redaction(self):
        raw = RawEvidence(
            source_type="github_actions",
            source_ref="https://github.com/test/repo/actions/runs/1",
            raw_data={"run_id": 1, "author_email": "dev@corp.com"},
            collected_at=datetime.now(timezone.utc),
        )
        result = normalize_evidence(raw, redaction_config={"pattern_scan": True})
        assert result.redacted is True
        assert result.sha256_hash  # Hash exists
        assert REDACTION_PLACEHOLDER in str(result.content_json)

    def test_normalize_hash_deterministic(self):
        raw = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"a": 1, "b": 2},
            collected_at=datetime.now(timezone.utc),
        )
        r1 = normalize_evidence(raw)
        r2 = normalize_evidence(raw)
        assert r1.sha256_hash == r2.sha256_hash

    def test_normalize_hash_changes_on_different_content(self):
        raw1 = RawEvidence(source_type="test", source_ref="test",
                           raw_data={"key": "value1"}, collected_at=datetime.now(timezone.utc))
        raw2 = RawEvidence(source_type="test", source_ref="test",
                           raw_data={"key": "value2"}, collected_at=datetime.now(timezone.utc))
        r1 = normalize_evidence(raw1)
        r2 = normalize_evidence(raw2)
        assert r1.sha256_hash != r2.sha256_hash


class TestGitHubActionsConnector:
    def test_validate_valid_evidence(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions",
            source_ref="https://github.com/test/repo/actions/runs/123",
            raw_data={"run_id": 123, "status": "completed"},
        )
        assert connector.validate(raw) is True

    def test_validate_rejects_missing_run_id(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions", source_ref="https://example.com",
            raw_data={"status": "completed"},  # No run_id
        )
        assert connector.validate(raw) is False

    def test_validate_rejects_wrong_source_type(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="iac_config",  # Wrong type
            source_ref="https://example.com",
            raw_data={"run_id": 123},
        )
        assert connector.validate(raw) is False
```

**Definition of Done**: `pytest tests/test_services/test_evidence_pipeline.py -v` — all tests pass. Coverage for `redaction.py` and `normalizer.py` exceeds 90%.

---

## Task 7.2: Add Integration Tests for Evaluation Engine

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/tests/test_services/test_evaluation.py`

**Detailed Logic Brief**:

Test each evaluation rule with controlled evidence inputs, and test the engine's aggregation logic.

```python
"""Integration tests for the rule-based evaluation engine."""

import uuid
import pytest
from app.services.evaluator.rules.access_control import check_access_control
from app.services.evaluator.rules.encryption_at_rest import check_encryption_at_rest
from app.services.evaluator.rules.logging_enabled import check_logging_enabled
from app.services.evaluator.engine import evaluate_control


class TestAccessControlRule:
    def test_pass_when_rbac_present(self):
        evidence = [{"content_json": {"access_control": "rbac_enabled", "iam": True},
                      "source_ref": "test.tf"}]
        result = check_access_control("HIPAA-AC-001", evidence)
        assert result is not None
        assert result["passed"] is True

    def test_fail_when_no_access_control(self):
        evidence = [{"content_json": {"database": "postgres"}, "source_ref": "db.tf"}]
        result = check_access_control("HIPAA-AC-001", evidence)
        assert result is not None
        assert result["passed"] is False
        assert "Remediation" in result["reason"]


class TestEncryptionRule:
    def test_pass_when_aes_enabled(self):
        evidence = [{"content_json": {"encryption": "AES256", "enabled": True},
                      "source_ref": "s3.tf"}]
        result = check_encryption_at_rest("HIPAA-SC-002-encrypt", evidence)
        assert result["passed"] is True

    def test_fail_when_no_encryption(self):
        evidence = [{"content_json": {"storage": "s3"}, "source_ref": "s3.tf"}]
        result = check_encryption_at_rest("HIPAA-SC-002-encrypt", evidence)
        assert result["passed"] is False


class TestLoggingRule:
    def test_pass_when_logging_enabled(self):
        evidence = [{"content_json": {"logging": True, "enabled": True},
                      "source_ref": "main.tf"}]
        result = check_logging_enabled("HIPAA-AU-001", evidence)
        assert result["passed"] is True

    def test_fail_when_logging_disabled(self):
        evidence = [{"content_json": {"logging": False, "disabled": True},
                      "source_ref": "main.tf"}]
        result = check_logging_enabled("HIPAA-AU-001", evidence)
        assert result["passed"] is False


class TestEvaluationEngine:
    @pytest.mark.asyncio
    async def test_no_evidence_returns_needs_review(self):
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-AC-001",
            evidence_items=[],
        )
        assert result.status == "NeedsReview"
        assert "No evidence" in result.rationale

    @pytest.mark.asyncio
    async def test_passing_evidence_returns_pass(self):
        evidence = [{"id": str(uuid.uuid4()), "source_type": "iac_config",
                      "content_json": {"access_control": "rbac", "iam": "enabled"}}]
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-AC-001",
            evidence_items=evidence,
        )
        assert result.status == "Pass"

    @pytest.mark.asyncio
    async def test_unmatched_control_returns_needs_review(self):
        evidence = [{"id": str(uuid.uuid4()), "source_type": "iac_config",
                      "content_json": {"something": "unrelated"}}]
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-UNKNOWN-999",
            evidence_items=evidence,
        )
        assert result.status == "NeedsReview"
```

**Definition of Done**: `pytest tests/test_services/test_evaluation.py -v` — all tests pass. Each rule has ≥2 test cases (pass + fail).

---

## Task 7.3: Add Integration Tests for RAG Pipeline

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/tests/test_services/test_rag_pipeline.py`

**Detailed Logic Brief**:

Mock OpenAI embedding API calls to return deterministic vectors. Test ingestion, chunking, keyword search, and deduplication without real API costs.

```python
"""Integration tests for the RAG ingestion and retrieval pipeline."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.compliance_brain.ingestion import _split_by_sections


class TestDocumentSplitter:
    def test_splits_by_markdown_headers(self):
        text = "Preamble text\n## Section One\nContent one\n## Section Two\nContent two"
        sections = _split_by_sections(text)
        assert len(sections) == 3  # Preamble + 2 sections
        assert sections[0][0] == "Preamble"
        assert sections[1][0] == "Section One"
        assert sections[2][0] == "Section Two"

    def test_handles_no_headers(self):
        text = "Just plain text with no headers at all."
        sections = _split_by_sections(text)
        assert len(sections) == 1
        assert sections[0][0] == "Preamble"

    def test_handles_empty_sections(self):
        text = "## Empty Section\n## Another Section\nSome content"
        sections = _split_by_sections(text)
        # Empty section should still be captured (with empty body)
        assert len(sections) >= 2


class TestChunkingLogic:
    def test_chunk_size_respected(self):
        # Create text with exactly 100 words
        words = [f"word{i}" for i in range(100)]
        text = "## Test\n" + " ".join(words)
        sections = _split_by_sections(text)
        assert len(sections) == 1
        # With chunk_size=50 and overlap=10, expect ~3 chunks
        # (0-49, 40-89, 80-99)

    def test_overlap_creates_redundancy(self):
        words = [f"w{i}" for i in range(100)]
        text = " ".join(words)
        sections = _split_by_sections(f"## S\n{text}")
        # Verify overlapping content appears in multiple chunks
        # (tested implicitly via ingestion)
```

Test keyword search by directly inserting rows into `regulatory_chunks` (bypassing the embedding step):

```python
class TestKeywordSearch:
    @pytest_asyncio.fixture
    async def seeded_chunks(self, db_session):
        """Insert test chunks with tsvector for keyword search testing."""
        from sqlalchemy import text as sql_text
        chunks = [
            ("HIPAA", "encryption of ePHI data at rest", "Security Rule"),
            ("HIPAA", "access control and RBAC implementation", "Access Control"),
            ("HIPAA", "audit logging and examination of activity", "Audit Controls"),
        ]
        for fw, content, section in chunks:
            await db_session.execute(sql_text(
                "INSERT INTO regulatory_chunks (id, framework_name, chunk_text, "
                "source_section, chunk_index, doc_hash, created_at) "
                "VALUES (gen_random_uuid(), :fw, :text, :section, 0, 'test', NOW())"
            ), {"fw": fw, "text": content, "section": section})
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_keyword_search_finds_exact_terms(self, db_session, seeded_chunks):
        from app.services.compliance_brain.rag import keyword_search
        results = await keyword_search("encryption ePHI", "HIPAA", db_session)
        assert len(results) >= 1
        assert "encryption" in results[0].text.lower()
```

**Definition of Done**: `pytest tests/test_services/test_rag_pipeline.py -v` passes. Chunking edge cases (empty docs, no headers, single section) all covered.

---

## Task 7.4: Add API Contract Tests for All Endpoints

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/tests/test_api/test_controls.py` (new)
- `backend/tests/test_api/test_evidence_detail.py` (new)

**Detailed Logic Brief**:

Ensure every API endpoint returns the correct response shape and enforces auth/RBAC properly. Use the existing `conftest.py` fixtures (`admin_token`, `devops_token`, `auditor_token`).

**Pattern for each endpoint**:

```python
class TestControlEndpoints:
    @pytest.mark.asyncio
    async def test_get_control_unauthorized(self, client):
        """No token → 401."""
        resp = await client.get("/api/v1/controls/some-uuid")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_control_not_found(self, client, admin_token):
        """Valid token, missing resource → 404."""
        resp = await client.get(
            "/api/v1/controls/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_review_control_forbidden_for_developer(self, client, developer_token):
        """Developer role → 403 on review endpoint."""
        resp = await client.post(
            "/api/v1/controls/00000000-0000-0000-0000-000000000000/review",
            headers={"Authorization": f"Bearer {developer_token}"},
            json={"decision": "approve", "justification": "test"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_status_history_allowed_for_auditor(self, client, auditor_token, db_session):
        """Auditor role → allowed on status-history endpoint."""
        # Create a control first, then query its history
        # ... setup code ...
        resp = await client.get(
            f"/api/v1/controls/{control_id}/status-history",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

**Endpoints to cover** (happy path + error path each):

| Endpoint | Happy Path | Error Paths |
|---|---|---|
| `POST /auth/register` | 201 + user data | 409 duplicate email |
| `POST /auth/login` | 200 + token | 401 wrong password |
| `GET /auth/me` | 200 + user | 401 no token |
| `GET /projects` | 200 + list | 401 |
| `POST /projects` | 201 | 403 for developer |
| `GET /projects/{id}` | 200 + detail | 404 |
| `GET /controls/{id}` | 200 + detail | 404, 401 |
| `POST /controls/{id}/review` | 200 | 403 for devops, 400 bad decision |
| `GET /dashboard/summary` | 200 + counts | 401 |
| `GET /evidence` | 200 + list | 401 |
| `POST /reports/export` | 200 | 404 bad project, 403 for developer |

**Definition of Done**: `pytest tests/test_api/ -v` — all tests pass. Every endpoint has ≥1 happy-path and ≥1 error-path test.

---

## Task 7.5: Add Structured Logging with Correlation IDs

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/middleware/logging.py`

**Files to Edit**:
- `backend/app/main.py` — add middleware
- `backend/requirements.txt` — add `python-json-logger`

**Detailed Logic Brief**:

Add a FastAPI middleware that assigns a UUID `correlation_id` to every request. All log lines during that request include the correlation ID, making it possible to trace a single user action across multiple service calls.

```python
"""Request correlation ID middleware for structured logging."""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        correlation_id_var.set(cid)

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response


class CorrelationIdFilter(logging.Filter):
    """Inject correlation_id into every log record."""
    def filter(self, record):
        record.correlation_id = correlation_id_var.get("")
        return True
```

**Configure structured JSON logging** in `main.py`:

```python
import logging
from pythonjsonlogger import jsonlogger
from app.middleware.logging import CorrelationIdMiddleware, CorrelationIdFilter

# Setup JSON formatter
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(correlation_id)s %(message)s"
)
handler.setFormatter(formatter)

# Apply to root logger
root = logging.getLogger()
root.handlers = [handler]
root.setLevel(logging.INFO)
root.addFilter(CorrelationIdFilter())

# Add middleware
app.add_middleware(CorrelationIdMiddleware)
```

**Definition of Done**:
1. Make an API call. Check container logs — every log line for that request is JSON with a shared `correlation_id`.
2. Response headers include `X-Correlation-ID`.
3. Subsequent API calls get different correlation IDs.
4. Pass `X-Correlation-ID: my-custom-id` in request header — logs and response use that custom ID.

---

## Task 7.6: Add Enhanced Health Check

**Estimated Time**: 2 hours

**Files to Create**:
- `backend/app/api/health.py`

**Files to Edit**:
- `backend/app/main.py` — replace inline health route with router

**Detailed Logic Brief**:

Replace the current minimal `/health` endpoint with a comprehensive check that verifies all dependencies.

```python
from fastapi import APIRouter
from sqlalchemy import text
from app.database import async_session
from app.workers.celery_app import celery_app
import redis.asyncio as aioredis
from app.config import settings

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    checks = {}

    # Database
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Celery (best-effort — ping may timeout)
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        ping_result = inspect.ping()
        checks["celery"] = bool(ping_result)
    except Exception:
        checks["celery"] = False

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "service": "sentinellai",
        },
    )
```

**Definition of Done**:
1. All services running: `GET /api/v1/health` returns `200 {"status": "healthy", "checks": {"database": true, "redis": true, "celery": true}}`.
2. Stop Redis: returns `503 {"status": "degraded", "checks": {"redis": false, ...}}`.
3. Docker health check can use this endpoint for container orchestration.

---

## Task 7.7: Add Rate Limiting Middleware

**Estimated Time**: 2 hours

**Files to Create**:
- `backend/app/middleware/rate_limit.py`

**Files to Edit**:
- `backend/app/main.py` — add middleware

**Detailed Logic Brief**:

Redis-backed sliding window rate limiter to prevent API abuse and protect LLM-heavy endpoints from cost overruns.

```python
"""Redis-backed sliding window rate limiter."""

import time
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import redis.asyncio as aioredis
from app.config import settings

# Endpoint-specific limits (requests per minute)
RATE_LIMITS = {
    "/api/v1/compliance-brain/query": 10,   # LLM-heavy
    "/api/v1/reports/export": 10,           # Resource-heavy
    "default": 100,                         # Standard endpoints
}

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.redis = aioredis.from_url(settings.REDIS_URL)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health checks
        if request.url.path.endswith("/health"):
            return await call_next(request)

        # Identify user (from JWT sub claim or IP)
        user_id = "anon"
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            from jose import jwt as jose_jwt
            try:
                payload = jose_jwt.decode(auth[7:], settings.JWT_SECRET_KEY,
                                          algorithms=[settings.JWT_ALGORITHM])
                user_id = payload.get("sub", "anon")
            except Exception:
                pass

        # Determine limit for this endpoint
        path = request.url.path
        limit = RATE_LIMITS.get(path, RATE_LIMITS["default"])

        # Sliding window check
        key = f"rate_limit:{user_id}:{path}"
        now = time.time()
        window = 60  # 1 minute

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)  # Remove expired
        pipe.zadd(key, {str(now): now})               # Add current
        pipe.zcard(key)                                # Count in window
        pipe.expire(key, window)                       # TTL cleanup
        results = await pipe.execute()
        request_count = results[2]

        if request_count > limit:
            retry_after = int(window - (now - float(await self.redis.zrange(key, 0, 0))[0]))
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        return await call_next(request)
```

**Definition of Done**:
1. Rapid-fire 101 requests to `/api/v1/dashboard/summary`. Request #101 returns `429` with `Retry-After` header.
2. LLM endpoint (`/compliance-brain/query`) returns 429 after 11 requests in a minute.
3. Health check endpoint is exempt from rate limiting.
4. Different users have independent limits (user A's usage doesn't affect user B).

---

## Phase 7 — Dependency Graph

```
Task 7.1 (Evidence Pipeline Tests)   — Depends on Phase 1 code
Task 7.2 (Evaluation Engine Tests)   — Depends on Phase 4 code
Task 7.3 (RAG Pipeline Tests)        — Depends on Phase 2 code
Task 7.4 (API Contract Tests)        — No code dependencies
Task 7.5 (Structured Logging)        — No dependencies
Task 7.6 (Health Check)              — No dependencies
Task 7.7 (Rate Limiting)             — No dependencies
```

**Parallelization**: All 7 tasks can run in parallel since they touch independent files.

**Recommended assignment**:
- **Person A**: Tasks 7.1 + 7.2 (service-level tests)
- **Person B**: Tasks 7.3 + 7.4 (RAG + API tests)
- **Person C**: Task 7.5 (logging — touches main.py, coordinate with Person D)
- **Person D**: Tasks 7.6 + 7.7 (health + rate limiting)

---

## Full Roadmap Summary

| Phase | Tasks | Hours | Key Deliverable |
|---|---|---|---|
| 1 — Data Integrity | 6 | 20 | Append-only audit trail + SHA-256 evidence sealing |
| 2 — RAG Optimization | 7 | 28 | Hybrid search + cross-encoder reranking + grounding |
| 3 — Connector Framework | 6 | 24 | GitHub code scanner + IaC parser + connector CRUD |
| 4 — Logic Bridge | 7 | 24 | Dynamic rule loader + 3 new rules + AI fallback |
| 5 — Frontend Real-Time | 6 | 20 | SSE progress + auto-refresh + drill-down components |
| 6 — OSCAL & Reporting | 5 | 16 | OSCAL export + evidence-linked PDF + report history |
| 7 — Testing & Polish | 7 | 20 | Integration tests + logging + health + rate limiting |
| **TOTAL** | **44** | **152** | **Production-ready MVP** |
