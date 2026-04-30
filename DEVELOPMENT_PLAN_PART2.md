# SentinellAI — Development Roadmap (Part 2 of 2)

> **Scope**: Phases 4–7 | Continues from DEVELOPMENT_PLAN_PART1.md

---

## PHASE 4 — The Logic Bridge (Est. 24 hrs)

*The "Logic Bridge" is the code that maps an AI-generated control to a specific Python evaluation function.*

### Task 4.1: Define Rule Registry with Control-Pattern Matching

**Files**: `backend/app/services/evaluator/rules/__init__.py`
**Logic**: Refactor `RULE_REGISTRY` from a flat list into a list of `RuleSpec` dataclasses: `RuleSpec(name, fn, applicable_patterns, applicable_source_types)`. Each rule declares which control code patterns it handles (e.g., `["encrypt", "aes", "164.312(a)"]`) and which evidence source types it can evaluate. The engine matches rules to controls using these declarations instead of each rule doing its own matching internally.
**DoD**: `RULE_REGISTRY` contains 3 `RuleSpec` entries. `engine.py` iterates specs and skips non-applicable rules before calling `fn()`.

---

### Task 4.2: Create Dynamic Rule Loader

**Files**: `backend/app/services/evaluator/loader.py` (new)
**Logic**: Create `load_rules_from_directory(rules_dir: Path) -> list[RuleSpec]`. Scans `rules/` directory for `.py` files. Each module must export a `RULE_SPEC` variable of type `RuleSpec`. Uses `importlib` to dynamically load modules. This allows new rules to be added as simple files without editing `__init__.py`.
**DoD**: Add a dummy `rules/test_rule.py` with a `RULE_SPEC`. `load_rules_from_directory()` discovers and loads it. Remove dummy after test.

---

### Task 4.3: Implement `check_audit_logging` Rule

**Files**: `backend/app/services/evaluator/rules/audit_logging.py` (new)
**Logic**: Handles controls matching `["audit", "164.312(b)", "logging"]`. Checks evidence for: (1) CI/CD pipeline has logging step, (2) IaC config has CloudWatch/CloudTrail enabled, (3) Application config has audit log rotation. Returns pass if ≥1 logging indicator found.
**DoD**: Mock evidence with `{"cloudtrail": "enabled"}` passes. Evidence without any logging keywords fails.

---

### Task 4.4: Implement `check_transmission_security` Rule

**Files**: `backend/app/services/evaluator/rules/transmission_security.py` (new)
**Logic**: Handles `["transmission", "164.312(e)", "tls", "ssl", "https"]`. Checks evidence for TLS/SSL configuration: certificate presence, HTTPS enforcement, TLS version ≥ 1.2. Checks IaC for `ssl_policy`, `certificate_arn`, `redirect_http_to_https`.
**DoD**: Evidence with `{"ssl_policy": "TLSv1.2"}` passes. Evidence with `{"ssl_policy": "TLSv1.0"}` fails with remediation.

---

### Task 4.5: Implement `check_incident_response` Rule

**Files**: `backend/app/services/evaluator/rules/incident_response.py` (new)
**Logic**: Handles `["incident", "164.308(a)(6)", "response"]`. Checks for: GitHub has `.github/SECURITY.md`, CI/CD has security scanning step (Snyk/Trivy/Dependabot), alerting webhook is configured. Returns pass if ≥2 indicators found.
**DoD**: Evidence with both SECURITY.md and Trivy scan passes. Evidence with neither fails.

---

### Task 4.6: Build AI-Assisted Rule Suggestion Engine

**Files**: `backend/app/services/evaluator/ai_rule_suggest.py` (new)
**Logic**: `suggest_evaluation_approach(control, evidence_items) -> str`. When no rule in the registry matches a control, call OpenAI with the control description and evidence summary. Ask it to suggest which evidence fields to check and what conditions indicate pass/fail. Return the suggestion as a human-readable string stored in the `rationale` field with status `NeedsReview`.
**DoD**: An unmatched control (e.g., "Business Associate Agreements") gets a rationale like "Suggested check: Look for BAA documents in legal/ directory..."

---

### Task 4.7: Wire AI Rule Suggestions into Evaluation Engine

**Files**: `backend/app/services/evaluator/engine.py`
**Logic**: In `evaluate_control()`, after the rule loop, if no rules matched (both `passes` and `failures` are empty), call `suggest_evaluation_approach()`. Set status to `NeedsReview` and include the AI suggestion in the rationale. This provides guidance for manual reviewers on controls the system can't auto-evaluate yet.
**DoD**: Evaluate a control with no matching rules. Result is `NeedsReview` with AI-generated suggestion in rationale.

---

## PHASE 5 — Frontend Real-Time Updates (Est. 20 hrs)

### Task 5.1: Add SSE (Server-Sent Events) Endpoint for Task Status

**Files**: `backend/app/api/tasks.py` (new), `backend/app/main.py`
**Logic**: Create `GET /api/v1/tasks/{task_id}/stream` using FastAPI's `StreamingResponse` with `text/event-stream` content type. Poll Redis for Celery task state (`celery_app.AsyncResult(task_id)`) every 2 seconds. Emit SSE events: `{"state": "PENDING|STARTED|SUCCESS|FAILURE", "progress": ..., "result": ...}`. Close stream on terminal state. Register router.
**DoD**: Trigger a connector, capture `task_id`. Open SSE stream in browser/curl — see state transitions from PENDING → STARTED → SUCCESS.

---

### Task 5.2: Create React Hook for SSE Consumption

**Files**: `frontend/src/lib/useTaskStream.ts` (new)
**Logic**: Custom React hook `useTaskStream(taskId)` that opens an `EventSource` connection to the SSE endpoint. Returns `{state, progress, result, error}`. Handles reconnection on failure. Cleans up EventSource on unmount. Uses `useState` for reactive updates.
**DoD**: Call hook with a task ID in a test component. UI updates reactively as task progresses.

---

### Task 5.3: Add Connector Trigger with Progress Indicator

**Files**: `frontend/src/app/(authenticated)/connectors/page.tsx`
**Logic**: When user clicks "Trigger" on a connector, call `POST /connectors/{id}/trigger` (which returns a `task_id`). Pass `task_id` to `useTaskStream()`. Show a progress badge next to the connector row: spinner during STARTED, checkmark on SUCCESS, X on FAILURE. Animate transitions.
**DoD**: Click trigger → spinner appears → transitions to checkmark. Failure case shows red X with error tooltip.

---

### Task 5.4: Add Real-Time Dashboard Auto-Refresh

**Files**: `frontend/src/app/(authenticated)/dashboard/page.tsx`, `frontend/src/lib/api.ts`
**Logic**: Add a `useEffect` with `setInterval` (30s) that re-fetches `GET /dashboard/summary`. When control counts change, animate the stat cards (e.g., count-up animation via CSS transition on the number). Add a "Last updated: X seconds ago" indicator in the header.
**DoD**: Leave dashboard open. Trigger an evaluation in another tab. Dashboard stats update within 30s with smooth animation.

---

### Task 5.5: Add Control Detail Drawer with Status Timeline

**Files**: `frontend/src/components/controls/ControlDrawer.tsx` (new)
**Logic**: Slide-in drawer component. On click of a control row (in Projects or Dashboard), fetch `GET /controls/{id}`. Display: title, description, citation, current status badge, evidence list (with source_ref links), and a vertical timeline of `status_history` entries (date + rationale). Use CSS transitions for drawer slide-in.
**DoD**: Click a control → drawer slides in from right showing full detail with timeline. Click outside → closes.

---

### Task 5.6: Add Evidence Detail Modal with Integrity Badge

**Files**: `frontend/src/components/evidence/EvidenceModal.tsx` (new)
**Logic**: Modal component for evidence items. Shows `source_type`, `source_ref` (as clickable link), `collected_at`, `sha256_hash` (truncated with copy button), and `content_json` in a syntax-highlighted JSON viewer. Add an "Integrity" badge that calls `GET /evidence/{id}/verify` — green if valid, red if tampered.
**DoD**: Click evidence item → modal shows JSON content and integrity badge. Badge turns green on valid, red on tampered.

---

## PHASE 6 — OSCAL & Reporting (Est. 16 hrs)

### Task 6.1: Define OSCAL Assessment Result Schema

**Files**: `backend/app/schemas/oscal.py` (new)
**Logic**: Create Pydantic v2 models mirroring OSCAL Assessment Results format: `OSCALAssessmentResult`, `OSCALFinding`, `OSCALObservation`, `OSCALControlSelection`. Map SentinellAI's `Control` + `ControlStatus` + `EvidenceItem` to OSCAL findings. Each finding includes `control-id`, `state` (satisfied/not-satisfied), `observations` (evidence references).
**DoD**: Instantiate `OSCALAssessmentResult` from a mock project — validates without errors. JSON output matches OSCAL spec structure.

---

### Task 6.2: Implement OSCAL JSON Export Service

**Files**: `backend/app/services/oscal_export.py` (new)
**Logic**: `generate_oscal_report(project_id, db) -> dict`. Queries all frameworks, controls, evidence for the project. Maps to OSCAL schema. Uses `model_dump(mode="json")` for serialization. Includes metadata: `last-modified`, `oscal-version: 1.1.2`, `uuid`.
**DoD**: Call with test project ID. Output valid JSON. Validate against OSCAL 1.1.2 JSON schema (use `jsonschema` library).

---

### Task 6.3: Add OSCAL Export API Endpoint

**Files**: `backend/app/api/reports.py`, `backend/app/schemas/report.py`
**Logic**: Add `POST /api/v1/reports/export/oscal` accepting `{project_id, framework_id?}`. Calls `generate_oscal_report()`. Returns JSON response with `Content-Disposition: attachment` header. Restrict to AUDITOR/ADMIN/COMPLIANCE_MANAGER.
**DoD**: POST returns downloadable OSCAL JSON. Open in OSCAL viewer tool — renders correctly.

---

### Task 6.4: Enhance PDF Report with Evidence Links

**Files**: `backend/app/services/report_generator.py`
**Logic**: Update `PDF_TEMPLATE` to include evidence references under each control. For each control, list linked evidence items with `source_type`, `source_ref`, `collected_at`, and integrity hash. Add a summary table at the top: total controls, pass/fail/review counts, evidence coverage percentage.
**DoD**: Generate PDF. Each control section shows linked evidence. Summary table renders correctly.

---

### Task 6.5: Add Report History and Download Endpoint

**Files**: `backend/app/models/report.py` (new), `backend/app/api/reports.py`, new migration
**Logic**: Create `Report` model with `id, project_id, format (pdf|json|oscal), generated_by, generated_at, file_path, file_size`. Store generated reports on disk under `/app/reports/`. Add `GET /reports` (list) and `GET /reports/{id}/download` (stream file). Add cleanup job for reports older than 90 days.
**DoD**: Export a report. It appears in `GET /reports`. Download endpoint streams the file.

---

## PHASE 7 — Testing & Production Polish (Est. 20 hrs)

### Task 7.1: Add Integration Tests for Evidence Pipeline

**Files**: `backend/tests/test_services/test_evidence_pipeline.py` (new)
**Logic**: End-to-end test: create connector → trigger collection → verify evidence items created → verify SHA-256 hashes → verify redaction applied. Use `pytest-asyncio` with test DB. Mock GitHub API responses with `httpx` mock transport.
**DoD**: `pytest test_services/test_evidence_pipeline.py` passes with all assertions.

---

### Task 7.2: Add Integration Tests for Evaluation Engine

**Files**: `backend/tests/test_services/test_evaluation.py` (new)
**Logic**: Test each rule function with known-good and known-bad evidence dicts. Test `evaluate_control()` with mixed evidence. Test `persist_evaluation()` writes to DB. Verify status transitions and rationale.
**DoD**: All 3 existing rules + new rules tested. `pytest` passes.

---

### Task 7.3: Add Integration Tests for RAG Pipeline

**Files**: `backend/tests/test_services/test_rag_pipeline.py` (new)
**Logic**: Mock OpenAI embedding calls (return fixed vectors). Test `ingest_document()` creates chunks in DB. Test `keyword_search()` returns ranked results. Test `hybrid_retrieve()` fusion logic. Test deduplication.
**DoD**: `pytest` passes. Chunk count matches expected based on doc size and chunk_size params.

---

### Task 7.4: Add API Contract Tests for All Endpoints

**Files**: `backend/tests/test_api/test_controls.py`, `backend/tests/test_api/test_evidence_detail.py` (new)
**Logic**: Test every endpoint returns correct Pydantic v2 response shape. Test 401 for unauthenticated. Test 403 for wrong role. Test 404 for missing resources. Use the existing `conftest.py` fixtures.
**DoD**: Full API surface has at least one happy-path and one error-path test. `pytest tests/test_api/` passes.

---

### Task 7.5: Add Structured Logging with Correlation IDs

**Files**: `backend/app/middleware/logging.py` (new), `backend/app/main.py`
**Logic**: FastAPI middleware that generates a UUID `correlation_id` per request. Injects it into a `contextvars.ContextVar`. Configure Python `logging` to include `correlation_id` in every log line (JSON format via `python-json-logger`). Add `X-Correlation-ID` response header.
**DoD**: Make an API call. All log lines for that request share the same correlation ID. Response header present.

---

### Task 7.6: Add Health Check Enhancements

**Files**: `backend/app/api/health.py` (new), `backend/app/main.py`
**Logic**: Enhance `/health` to check DB connectivity (`SELECT 1`), Redis ping, and Celery worker availability (`celery_app.control.ping()`). Return `{"status": "healthy|degraded", "checks": {"db": bool, "redis": bool, "celery": bool}}`. Return HTTP 503 if any check fails.
**DoD**: Stop Redis container. Health check returns `degraded` with `redis: false` and HTTP 503.

---

### Task 7.7: Add Rate Limiting Middleware

**Files**: `backend/app/middleware/rate_limit.py` (new), `backend/app/main.py`
**Logic**: Use Redis-backed sliding window rate limiter. Key: `rate_limit:{user_id}:{endpoint}`. Limit: 100 requests/minute for standard endpoints, 10/minute for LLM-heavy endpoints (`/compliance-brain/query`, `/reports/export`). Return `429 Too Many Requests` with `Retry-After` header.
**DoD**: Rapid-fire 101 requests to an endpoint. 101st returns 429 with correct header.

---

## Summary Checklist

| Phase | Tasks | Est. Hours |
|---|---|---|
| 1 — Data Integrity | 6 tasks | 20 |
| 2 — RAG Optimization | 7 tasks | 28 |
| 3 — Connector Framework | 6 tasks | 24 |
| 4 — Logic Bridge | 7 tasks | 24 |
| 5 — Frontend Real-Time | 6 tasks | 20 |
| 6 — OSCAL & Reporting | 5 tasks | 16 |
| 7 — Testing & Polish | 7 tasks | 20 |
| **TOTAL** | **44 tasks** | **~152 hrs** |

---

> At ~40 hrs/week of focused development across 4 team members, this roadmap targets a **production-ready MVP in ~4 weeks**.
