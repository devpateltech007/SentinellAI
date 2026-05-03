# SentinellAI — Development Roadmap (Part 1 of 2)

> **Scope**: Phases 1–3 | **Baseline**: Current skeleton state as of April 2026
> **Rule**: Every task ≤ 4 hours. Pydantic v2 enforced. PII redaction before DB writes.

---

## Current State Summary

| Layer | Status |
|---|---|
| DB Models (12 tables) | ✅ Complete |
| Auth (JWT + RBAC matrix) | ✅ Complete |
| Evidence Engine (GitHub Actions + IaC) | 🟡 Functional but no redaction middleware |
| Evaluator (3 rules) | 🟡 Hard-coded, no Logic Bridge |
| Compliance Brain (Ingest + RAG + Generator) | 🟡 Works but naive rerank, no hybrid search |
| Celery Workers (evidence + evaluation) | 🟡 Wired but untested end-to-end |
| Frontend (Dashboard, Projects, Evidence, Connectors, Reports) | 🟡 UI shells, no real-time updates |
| Tests | 🔴 Skeleton only (8 test files, minimal coverage) |

---

## PHASE 1 — Data Integrity & Evidence Sealing (Est. 20 hrs)

### Task 1.1: Add Append-Only Constraint to `control_statuses` and `audit_logs`

**Files**: `backend/alembic/versions/003_append_only_audit.py`
**Logic**: Create Alembic migration adding a PostgreSQL trigger function `prevent_update_delete()` that raises an exception on UPDATE or DELETE. Bind it to both `control_statuses` and `audit_logs` tables using `BEFORE UPDATE OR DELETE` triggers.
**DoD**: `UPDATE control_statuses SET status='pass'` via psql fails. INSERT still works. Same for `audit_logs`.

---

### Task 1.2: Implement Evidence SHA-256 Seal Verification Service

**Files**: `backend/app/services/evidence_engine/integrity.py` (new)
**Logic**: Create `verify_evidence_integrity(evidence_id, db) -> bool`. Loads `EvidenceItem`, recomputes SHA-256 over `json.dumps(content_json, sort_keys=True)`, compares against stored `sha256_hash`.
**DoD**: Unit test — verify returns `True` for untampered evidence, `False` after manual DB mutation.

---

### Task 1.3: Add Integrity Check Endpoint

**Files**: `backend/app/api/evidence.py`, `backend/app/schemas/evidence.py`
**Logic**: Add `GET /evidence/{evidence_id}/verify`. Returns `EvidenceIntegrityResponse` (Pydantic v2) with `integrity_valid`, `computed_hash`, `stored_hash`. Restrict to ADMIN/AUDITOR roles.
**DoD**: Curl endpoint — returns `integrity_valid: true`. Tamper DB, re-curl — returns `false`.

---

### Task 1.4: Wire Redaction as Middleware in Evidence Ingestion

**Files**: `backend/app/services/evidence_engine/normalizer.py`, `backend/app/workers/evidence_tasks.py`
**Logic**: Define `DEFAULT_REDACTION_CONFIG = {"pattern_scan": True}` in normalizer. Update `evidence_tasks.py` `_collect_evidence_async()` to call `normalize_evidence(raw, DEFAULT_REDACTION_CONFIG)` instead of `gh.normalize(raw)`.
**DoD**: Trigger connector collection. Evidence with emails/SSNs shows `[REDACTED]` in stored `content_json`.

---

### Task 1.5: Add `redacted` Column to `evidence_items`

**Files**: `backend/alembic/versions/004_evidence_redacted_flag.py`, `backend/app/models/evidence.py`
**Logic**: Migration adds `redacted = Column(Boolean, default=False)`. Update model. Set `evidence.redacted = normalized.redacted` in evidence tasks.
**DoD**: New evidence items have correct `redacted` flag after collection.

---

### Task 1.6: Add Tamper Detection to Scheduled Evaluation

**Files**: `backend/app/workers/evaluation_tasks.py`
**Logic**: Before running rules, call `verify_evidence_integrity()` for each linked evidence. If any fails, set control to `NeedsReview` with tamper warning, skip evaluation.
**DoD**: Tamper evidence row. Run evaluation task. Control transitions to `NeedsReview` with tamper message.

---

## PHASE 2 — RAG Pipeline Optimization (Est. 28 hrs)

### Task 2.1: Add Keyword Search via `ts_vector`

**Files**: `backend/alembic/versions/005_tsvector_search.py`, `backend/app/services/compliance_brain/rag.py`
**Logic**: Migration adds `tsv` tsvector column + GIN index to `regulatory_chunks`. Populate via `to_tsvector('english', chunk_text)`. Add `keyword_search()` function using `ts_query` + `ts_rank`.
**DoD**: `keyword_search("encryption ePHI", "HIPAA", db)` returns chunks with those terms ranked by score.

---

### Task 2.2: Implement Hybrid Search (Semantic + Keyword Fusion)

**Files**: `backend/app/services/compliance_brain/rag.py`
**Logic**: Create `hybrid_retrieve(query, framework_name, db, top_k, alpha=0.7)`. Calls `retrieve_context()` and `keyword_search()` via `asyncio.gather()`. Fuses via Reciprocal Rank Fusion: `score = alpha * (1/(k+sem_rank)) + (1-alpha) * (1/(k+kw_rank))` with `k=60`.
**DoD**: Query "access control RBAC" returns chunks with higher combined scores than either method alone.

---

### Task 2.3: Implement Cross-Encoder Reranking

**Files**: `backend/app/services/compliance_brain/rag.py`
**Logic**: Replace naive `sorted()` reranker with OpenAI-based scoring. For each chunk, prompt: `"Rate 1-10 relevance of this text to: {query}..."`. Parse integer score. Sort descending, return `top_n`. Use `temperature=0`.
**DoD**: Reranked output for "minimum necessary access" places §164.312(a) chunks above preamble.

---

### Task 2.4: Update Evidence Tasks to Use Hybrid Search + Rerank

**Files**: `backend/app/workers/evidence_tasks.py`
**Logic**: In `_generate_controls_async()`, replace lines 77-78 with `hybrid_retrieve()` + `rerank_with_llm()`.
**DoD**: Generated controls include citations matching actual regulatory sections.

---

### Task 2.5: Add Prompt Grounding Guard

**Files**: `backend/app/services/compliance_brain/generator.py`
**Logic**: After LLM returns controls, check each `source_citation` against `context_chunks` for substring match. If no match, set `confidence = 0.3` and append `[UNGROUNDED]` to title.
**DoD**: Feed context with only §164.312. Controls citing §164.308 get flagged as `[UNGROUNDED]`.

---

### Task 2.6: Add Chunk-Level Deduplication

**Files**: `backend/app/services/compliance_brain/ingestion.py`, new migration
**Logic**: Add `chunk_hash` column. Before inserting each chunk, compute `sha256(chunk.text)` and skip if exists for same framework.
**DoD**: Run `ingest_document()` twice — second run inserts 0 new chunks.

---

### Task 2.7: Add RAG Query API Endpoint

**Files**: `backend/app/api/compliance_brain.py` (new), `backend/app/schemas/compliance_brain.py` (new), `backend/app/main.py`
**Logic**: `POST /api/v1/compliance-brain/query` accepting `{query, framework, top_k}`. Calls `hybrid_retrieve()` + `rerank_with_llm()`. Returns ranked chunks. Register router in main.
**DoD**: POST with HIPAA encryption query returns ranked chunks. Unauthorized users get 401.

---

## PHASE 3 — Connector Framework Hardening (Est. 24 hrs)

### Task 3.1: Add GitHub Repository Code Scanning Connector

**Files**: `backend/app/services/evidence_engine/github_code.py` (new)
**Logic**: `GitHubCodeConnector(ConnectorInterface)`. Uses GitHub Contents API to scan for `*.tf`, `*.yaml`, `Dockerfile`, `.github/workflows/*.yml`. Decodes Base64 content. Implements retry with backoff.
**DoD**: Point at public repo with Terraform files. `collect()` returns decoded file contents.

---

### Task 3.2: Add IaC Encryption Flag Parser

**Files**: `backend/app/services/evidence_engine/iac_parser.py` (new)
**Logic**: `parse_terraform_encryption(content) -> dict` extracts encryption config via regex. `parse_k8s_security_context(content) -> dict` extracts `runAsNonRoot`, `readOnlyRootFilesystem`.
**DoD**: Sample Terraform with SSE config returns `{"encryption_at_rest": true, "algorithm": "aws:kms"}`.

---

### Task 3.3: Wire GitHub Code Connector into Evidence Tasks

**Files**: `backend/app/workers/evidence_tasks.py`, `backend/app/models/evidence.py`, new migration
**Logic**: Add `elif connector.source_type == "github_code":` branch. Add `GITHUB_CODE` to `EvidenceSourceType` enum.
**DoD**: Create connector, trigger it, evidence items appear in DB.

---

### Task 3.4: Add Connector Health Check Endpoint

**Files**: `backend/app/api/connectors.py`, `backend/app/schemas/connector.py`
**Logic**: `GET /connectors/{id}/health`. For GitHub, calls `GET /repos/{owner}/{repo}` to verify token. Returns `{reachable, rate_limit_remaining, error}`.
**DoD**: Valid connector returns `reachable: true`. Invalid token returns `false` with error.

---

### Task 3.5: Add Connector CRUD (Update + Delete)

**Files**: `backend/app/api/connectors.py`, `backend/app/schemas/connector.py`, new migration
**Logic**: `PUT /connectors/{id}` and `DELETE /connectors/{id}` (soft-delete via `is_active=false`). Update scheduled collection to filter active only.
**DoD**: PUT updates schedule. DELETE soft-deletes. Scheduled job skips inactive.

---

### Task 3.6: Add Cron Validation for Connector Scheduling

**Files**: `backend/app/schemas/connector.py`, `backend/requirements.txt`
**Logic**: Pydantic v2 field validator on `schedule` using `croniter`. In scheduled collection, use `croniter.match()` instead of running all connectors every 5 min.
**DoD**: Invalid cron returns 422. Valid cron only triggers at correct intervals.

---

> **Continued in DEVELOPMENT_PLAN_PART2.md**: Phase 4 (Logic Bridge), Phase 5 (Frontend Real-Time), Phase 6 (OSCAL & Reporting), Phase 7 (Testing & Polish)
