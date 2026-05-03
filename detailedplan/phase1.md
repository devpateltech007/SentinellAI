# Phase 1 — Data Integrity & Evidence Sealing

> **Estimated Total**: 20 engineering hours
> **Dependency**: None — this phase has zero dependencies on other phases and can start immediately.
> **Rationale**: A compliance platform is only as trustworthy as its audit trail. If evidence can be silently modified or deleted after collection, the entire system's credibility collapses during a real audit. This phase establishes cryptographic and database-level guarantees that evidence is immutable and verifiable.

---

## Task 1.1: Add Append-Only Constraints via PostgreSQL Triggers

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/alembic/versions/003_append_only_audit.py`

**Files to Reference (read-only)**:
- `backend/app/models/control_status.py` — to confirm table name is `control_statuses`
- `backend/app/models/audit_log.py` — to confirm table name is `audit_logs`
- `backend/alembic/versions/001_initial_schema.py` — to confirm the existing migration chain

**Detailed Logic Brief**:

The goal is to make `control_statuses` and `audit_logs` truly append-only at the database level — not just at the application level. Even if someone gains direct DB access, they should not be able to silently alter or delete historical records.

Create a new Alembic migration file `003_append_only_audit.py`. Inside the `upgrade()` function:

1. First, create a shared PostgreSQL trigger function using raw SQL via `op.execute()`:

```sql
CREATE OR REPLACE FUNCTION prevent_update_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Append-only table: UPDATE and DELETE operations are prohibited on %', TG_TABLE_NAME;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
```

2. Then bind this function to both tables as a `BEFORE UPDATE OR DELETE` trigger:

```sql
CREATE TRIGGER enforce_append_only_control_statuses
    BEFORE UPDATE OR DELETE ON control_statuses
    FOR EACH ROW
    EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER enforce_append_only_audit_logs
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_update_delete();
```

3. In the `downgrade()` function, drop both triggers and then the function:

```sql
DROP TRIGGER IF EXISTS enforce_append_only_control_statuses ON control_statuses;
DROP TRIGGER IF EXISTS enforce_append_only_audit_logs ON audit_logs;
DROP FUNCTION IF EXISTS prevent_update_delete();
```

**Why a trigger and not an ORM-level check?** Application-level protections can always be bypassed by direct SQL access, migration scripts, or a compromised admin. PostgreSQL triggers enforce the constraint at the storage engine level, which is the correct layer for tamper-proofing in a compliance context.

**Important edge case**: The `persist_evaluation()` function in `backend/app/services/evaluator/status.py` currently does an `UPDATE` on the `Control` table (to update the denormalized `status` field on line 48), but it only **inserts** into `control_statuses`. Verify this doesn't conflict. The `Control` table is NOT append-only — only `control_statuses` (the history/audit trail) is.

**Definition of Done**:
1. Run `docker compose exec backend alembic upgrade head` — migration applies without errors.
2. Connect to psql: `docker compose exec postgres psql -U sentinell -d sentinell`
3. Attempt: `UPDATE control_statuses SET status = 'pass' WHERE id = (SELECT id FROM control_statuses LIMIT 1);` — must raise exception with message "Append-only table: UPDATE and DELETE operations are prohibited on control_statuses".
4. Attempt: `DELETE FROM audit_logs WHERE id = (SELECT id FROM audit_logs LIMIT 1);` — must raise exception.
5. Attempt: `INSERT INTO control_statuses (id, control_id, status, rationale, determined_at) VALUES (gen_random_uuid(), (SELECT id FROM controls LIMIT 1), 'pass', 'test', NOW());` — must succeed.
6. Run `alembic downgrade -1` — triggers and function are removed cleanly.

---

## Task 1.2: Implement Evidence SHA-256 Seal Verification Service

**Estimated Time**: 2 hours

**Files to Create**:
- `backend/app/services/evidence_engine/integrity.py`

**Files to Reference (read-only)**:
- `backend/app/services/evidence_engine/normalizer.py` — the `compute_sha256()` function on line 19 that we'll reuse
- `backend/app/models/evidence.py` — the `EvidenceItem` model to understand the schema
- `backend/app/database.py` — the `async_session` factory for DB access

**Detailed Logic Brief**:

This service provides runtime verification that stored evidence has not been tampered with after collection. During ingestion (in `normalizer.py`), we already compute `SHA-256` over the serialized `content_json` and store it alongside the evidence. This task creates the inverse operation: reload the evidence, recompute the hash, and compare.

Create `integrity.py` with the following function:

```python
async def verify_evidence_integrity(
    evidence_id: UUID,
    db: AsyncSession,
) -> EvidenceIntegrityResult:
```

The `EvidenceIntegrityResult` is a dataclass with fields: `evidence_id: UUID`, `integrity_valid: bool`, `stored_hash: str`, `computed_hash: str`.

**Implementation steps inside the function**:

1. Query the `EvidenceItem` by `evidence_id` using `select(EvidenceItem).where(EvidenceItem.id == evidence_id)`.
2. If not found, raise an `EvidenceNotFoundError` (custom exception, define it in the same file).
3. Serialize the stored `content_json` using `json.dumps(evidence.content_json, sort_keys=True, default=str)` — the `sort_keys=True` is critical because JSON key ordering is non-deterministic; this must match exactly what `normalizer.py` does on line 39.
4. Compute `computed_hash = compute_sha256(content_str)` by importing from `normalizer.py`.
5. Compare `computed_hash == evidence.sha256_hash`.
6. Return the result dataclass.

**Critical detail about `sort_keys` and `default`**: The `normalizer.py` on line 39 uses `json.dumps(content, sort_keys=True, default=str)`. The integrity checker MUST use the exact same serialization parameters. If there's a mismatch (e.g., one uses `default=str` and the other doesn't), datetime objects inside `content_json` will serialize differently, causing false-positive tamper alerts. This is the #1 source of bugs in hash-based integrity systems.

Also create a batch verification function for efficiency:

```python
async def verify_batch_integrity(
    evidence_ids: list[UUID],
    db: AsyncSession,
) -> list[EvidenceIntegrityResult]:
```

This loads all evidence items in a single query using `EvidenceItem.id.in_(evidence_ids)` and verifies each. This will be used by the evaluation pipeline in Task 1.6 where we need to check multiple evidence items per control.

**Definition of Done**:
1. Write a test in `backend/tests/test_services/test_integrity.py`:
   - Insert an `EvidenceItem` with known `content_json` and pre-computed `sha256_hash`.
   - Call `verify_evidence_integrity()` — assert `integrity_valid == True` and hashes match.
   - Directly update `content_json` in the DB via raw SQL (bypassing ORM): `UPDATE evidence_items SET content_json = '{"tampered": true}' WHERE id = :id`.
   - Call `verify_evidence_integrity()` again — assert `integrity_valid == False` and hashes differ.
2. Test the batch function with 3 items (2 valid, 1 tampered) — returns correct results for all.

---

## Task 1.3: Add Integrity Check API Endpoint

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/api/evidence.py` — add new endpoint
- `backend/app/schemas/evidence.py` — add response schema

**Files to Reference (read-only)**:
- `backend/app/api/deps.py` — for `require_role()` dependency
- `backend/app/models/user.py` — for `UserRole` enum values

**Detailed Logic Brief**:

Expose the integrity verification as a REST endpoint so auditors and administrators can manually verify evidence seals through the UI (which we'll wire up in Phase 5).

**Step 1 — Add Pydantic v2 Response Schema** in `backend/app/schemas/evidence.py`:

```python
class EvidenceIntegrityResponse(BaseModel):
    evidence_id: UUID
    integrity_valid: bool
    stored_hash: str
    computed_hash: str
    verified_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

Note: We add `verified_at` (set to `datetime.now(timezone.utc)` at response time) so the audit trail records *when* the integrity was checked, not just the result.

**Step 2 — Add API Endpoint** in `backend/app/api/evidence.py`:

```python
@router.get("/{evidence_id}/verify", response_model=EvidenceIntegrityResponse)
async def verify_evidence(
    evidence_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.AUDITOR)),
):
```

Inside the handler:
1. Call `verify_evidence_integrity(evidence_id, db)` from the service.
2. Catch `EvidenceNotFoundError` and raise `HTTPException(404)`.
3. Return `EvidenceIntegrityResponse` populated from the result dataclass plus `verified_at=datetime.now(timezone.utc)`.

**Why restrict to ADMIN and AUDITOR only?** Integrity verification reveals the SHA-256 hashes, which are metadata about evidence content. In a compliance context, only auditors and administrators should be able to run integrity checks — a developer or DevOps engineer viewing tamper status could potentially use that information to cover tracks. The RBAC matrix in `middleware/rbac.py` already defines granular permissions; this endpoint maps to `evidence:verify` (a new permission we should add to the admin and auditor roles).

**Step 3 — Update RBAC Matrix** in `backend/app/middleware/rbac.py`:
- Add `"evidence:verify"` to the `admin` and `auditor` permission lists.

**Step 4 — Write audit log entry** for every verification attempt:
After the verification, call `log_action(db, actor_id=current_user.id, action="verify_evidence", resource_type="evidence", resource_id=evidence_id, detail={"integrity_valid": result.integrity_valid})`. This creates a permanent record of who checked what and when.

**Definition of Done**:
1. Start the application. Login as `admin@sentinellai.dev`.
2. `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/evidence/{known_evidence_id}/verify` — returns JSON with `integrity_valid: true`, both hashes matching, and `verified_at` timestamp.
3. Tamper the evidence in psql: `UPDATE evidence_items SET content_json = jsonb_set(content_json, '{tampered}', '"yes"') WHERE id = '{known_evidence_id}';`
4. Re-curl the same endpoint — returns `integrity_valid: false` with different hashes.
5. Login as `devops@sentinellai.dev`. Curl the same endpoint — returns `403 Forbidden`.
6. Check `audit_logs` table — two entries for `verify_evidence` action logged with the correct actor.

---

## Task 1.4: Wire Redaction as Mandatory Middleware in Evidence Ingestion

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/services/evidence_engine/normalizer.py` — add default config
- `backend/app/workers/evidence_tasks.py` — change evidence processing flow

**Files to Reference (read-only)**:
- `backend/app/services/evidence_engine/redaction.py` — the existing `redact_fields()` function and PII patterns
- `backend/app/services/evidence_engine/github_actions.py` — the current `normalize()` method
- `backend/app/services/evidence_engine/base.py` — the `ConnectorInterface` contract

**Detailed Logic Brief**:

Currently, there is a significant gap in the evidence pipeline. The `redaction.py` module exists with a robust PII/PHI scanner (emails, SSNs, phone numbers, IP addresses), but it is **never actually called** during evidence collection. Looking at `evidence_tasks.py` lines 160-168:

```python
for raw in raw_items:
    if gh.validate(raw):
        normalized = gh.normalize(raw)  # <-- This calls GitHubActionsConnector.normalize()
        evidence = EvidenceItem(...)     #     which does NOT call redact_fields()
```

The `GitHubActionsConnector.normalize()` method (in `github_actions.py` line 86) directly constructs a `NormalizedEvidence` without any redaction step. The `normalizer.py` module has a `normalize_evidence()` function that *does* support redaction, but it's not being used.

**The fix has two parts**:

**Part A — Define default redaction config** in `normalizer.py`:

```python
DEFAULT_REDACTION_CONFIG: dict = {
    "pattern_scan": True,  # Enable regex-based PII/PHI scan on all string values
}
```

This config enables the full regex scan (emails, SSNs, phone numbers, IP addresses) defined in `redaction.py`'s `DEFAULT_PII_PATTERNS`.

**Part B — Reroute evidence processing** in `evidence_tasks.py`:

Replace the current flow where each connector's `.normalize()` is called directly. Instead, after collecting and validating raw evidence, call the centralized `normalize_evidence()` function which includes the redaction step:

```python
from app.services.evidence_engine.normalizer import normalize_evidence, DEFAULT_REDACTION_CONFIG

for raw in raw_items:
    if gh.validate(raw):
        normalized = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)
        evidence = EvidenceItem(
            source_type=EvidenceSourceType.GITHUB_ACTIONS,
            source_ref=normalized.source_ref,
            collected_at=normalized.collected_at,
            sha256_hash=normalized.sha256_hash,
            content_json=normalized.content_json,
        )
        db.add(evidence)
        count += 1
```

**Important**: The SHA-256 hash is computed AFTER redaction (see `normalizer.py` line 40). This means the integrity seal in Task 1.2 verifies the *redacted* content, not the original. This is correct behavior — we never want the original PII stored, so the hash should seal the redacted version.

**Edge case to handle**: GitHub Actions API responses typically contain author email addresses in commit metadata. After this change, those emails will be replaced with `[REDACTED]`. Verify this doesn't break any downstream rule evaluation that might depend on author identity.

**Definition of Done**:
1. Manually insert a test connector pointing to a real GitHub repo (or use the existing `acme/app` mock).
2. Trigger evidence collection: `docker compose exec backend python -c "from app.workers.evidence_tasks import collect_evidence; collect_evidence('CONNECTOR_ID')"`
3. Query the DB: `SELECT content_json FROM evidence_items ORDER BY collected_at DESC LIMIT 1;`
4. If the original GitHub API response contained any email addresses (e.g., committer emails), they must appear as `[REDACTED]` in the stored `content_json`.
5. If there were no PII patterns in the evidence, the `content_json` should be unchanged but the flow should still pass through the redaction pipeline (verify via logging).
6. Add a log line in `normalizer.py` after redaction: `logger.info("Evidence redaction applied: %s fields redacted", redacted)` — verify it appears in container logs.

---

## Task 1.5: Add `redacted` Boolean Column to `evidence_items`

**Estimated Time**: 2 hours

**Files to Create**:
- `backend/alembic/versions/004_evidence_redacted_flag.py`

**Files to Edit**:
- `backend/app/models/evidence.py` — add column to model
- `backend/app/workers/evidence_tasks.py` — set the flag during ingestion
- `backend/app/schemas/evidence.py` — expose in API responses

**Detailed Logic Brief**:

After Task 1.4, we know *whether* redaction occurred (the `normalized.redacted` boolean from `NormalizedEvidence`), but we don't persist that information. Auditors need to know which evidence items had PII removed so they can request the original if needed through a separate secure channel.

**Step 1 — Alembic Migration**:

Create `004_evidence_redacted_flag.py`:
```python
def upgrade():
    op.add_column("evidence_items", sa.Column("redacted", sa.Boolean(), nullable=False, server_default="false"))

def downgrade():
    op.drop_column("evidence_items", "redacted")
```

Using `server_default="false"` ensures existing rows get a sensible default without requiring a data backfill.

**Step 2 — Update SQLAlchemy Model** in `backend/app/models/evidence.py`:

Add to the `EvidenceItem` class:
```python
redacted = Column(Boolean, default=False, server_default=text("false"))
```

**Step 3 — Set During Ingestion** in `evidence_tasks.py`:

After creating the `EvidenceItem` from normalized data, add:
```python
evidence = EvidenceItem(
    source_type=...,
    source_ref=normalized.source_ref,
    collected_at=normalized.collected_at,
    sha256_hash=normalized.sha256_hash,
    content_json=normalized.content_json,
    redacted=normalized.redacted,  # <-- NEW
)
```

**Step 4 — Expose in API Schema** in `backend/app/schemas/evidence.py`:

Add `redacted: bool` to `EvidenceDetailResponse` and `EvidenceListResponse` item schemas so the frontend can display a "Redacted" badge.

**Definition of Done**:
1. `alembic upgrade head` runs without error.
2. `\d evidence_items` in psql shows `redacted | boolean | not null | default false`.
3. Existing evidence items all have `redacted = false`.
4. Trigger new evidence collection that hits PII → new row has `redacted = true`.
5. `GET /api/v1/evidence` response includes `"redacted": true/false` for each item.

---

## Task 1.6: Add Tamper Detection to Scheduled Evaluation Pipeline

**Estimated Time**: 4 hours

**Files to Edit**:
- `backend/app/workers/evaluation_tasks.py` — add integrity checks before evaluation

**Files to Reference (read-only)**:
- `backend/app/services/evidence_engine/integrity.py` — the `verify_batch_integrity()` function from Task 1.2
- `backend/app/services/evaluator/engine.py` — the `evaluate_control()` function
- `backend/app/services/evaluator/status.py` — the `persist_evaluation()` function
- `backend/app/services/alerting.py` — the `send_failure_alert()` function

**Detailed Logic Brief**:

This is the task that ties the integrity verification into the live evaluation pipeline. Every time a control is evaluated (either on-demand or via the 5-minute scheduled job), we first verify that all linked evidence is intact. If any evidence has been tampered with, we abort the normal rule-based evaluation and immediately flag the control as `NeedsReview` with a specific tamper warning.

**Modify `_evaluate_control_async()` in `evaluation_tasks.py`**:

After loading the control and its linked evidence (around line 68), but BEFORE calling `evaluate_control()` (line 79), insert the integrity check:

```python
from app.services.evidence_engine.integrity import verify_batch_integrity

# Collect evidence IDs
evidence_uuids = [UUID(e["id"]) for e in evidence_items if e.get("id")]

# Verify integrity of all linked evidence
integrity_results = await verify_batch_integrity(evidence_uuids, db)
tampered = [r for r in integrity_results if not r.integrity_valid]

if tampered:
    tamper_ids = [str(r.evidence_id) for r in tampered]
    logger.warning(
        "TAMPER DETECTED: Control %s has %d tampered evidence items: %s",
        control_id, len(tampered), tamper_ids,
    )

    # Create a special evaluation result for tampered evidence
    from app.services.evaluator.engine import EvaluationResult
    eval_result = EvaluationResult(
        control_id=control.id,
        status="NeedsReview",
        evidence_ids=evidence_uuids,
        rationale=(
            f"INTEGRITY ALERT: {len(tampered)} evidence item(s) failed SHA-256 "
            f"integrity verification. Evidence IDs: {', '.join(tamper_ids)}. "
            f"This may indicate unauthorized modification of compliance evidence. "
            f"Manual review and re-collection required."
        ),
    )

    await persist_evaluation(db, eval_result)

    # Always alert on tamper detection, regardless of previous status
    await send_failure_alert(
        control_id=control.id,
        control_id_code=control.control_id_code,
        title=f"[TAMPER ALERT] {control.title}",
        reason=eval_result.rationale,
    )

    await db.commit()
    return {
        "status": "tamper_detected",
        "control_id": control_id,
        "tampered_evidence": tamper_ids,
    }

# --- Normal evaluation continues below only if all evidence is intact ---
eval_result = await evaluate_control(...)
```

**Why `NeedsReview` and not `Fail`?** A tampered evidence item doesn't necessarily mean the control itself is failing — it means we can't trust the evidence. The correct response is to flag it for human review, not to auto-fail. The auditor needs to investigate whether the tampering was malicious or an accidental data migration issue.

**Why always send an alert?** Unlike normal failures (where we only alert on status *transitions*), tamper detection should always generate an alert regardless of previous status. Evidence tampering is a security event, not a compliance state change.

**Performance consideration**: The `verify_batch_integrity()` function loads all evidence items in a single DB query and computes hashes in-memory. For a control with 5-10 linked evidence items, this adds ~1-2ms of overhead. For the scheduled job that evaluates all controls, consider adding a config flag `SKIP_INTEGRITY_CHECK` (defaulting to `False`) that can be set for dev/test environments where tamper detection isn't needed.

**Definition of Done**:
1. Seed the database and run the scheduled evaluation — all controls evaluate normally (no tamper warnings).
2. Tamper one evidence item via psql: `UPDATE evidence_items SET content_json = '{"tampered": true}' WHERE id = '{evidence_id}';`
3. Trigger evaluation for the linked control: `evaluate_control_task.delay(control_id)`
4. Check the result:
   - Control status is now `NeedsReview`
   - Latest `control_statuses` entry has rationale containing "INTEGRITY ALERT"
   - Container logs show the WARNING with tampered evidence IDs
   - If Slack webhook is configured, alert was sent with "[TAMPER ALERT]" prefix
5. Fix the evidence (restore original `content_json` and matching hash). Re-evaluate — control goes through normal rule evaluation again.
6. Verify the tamper detection entry in `control_statuses` is preserved (append-only from Task 1.1).

---

## Phase 1 — Dependency Graph

```
Task 1.1 (Append-Only Triggers)     — No dependencies
Task 1.2 (Integrity Service)        — No dependencies
Task 1.3 (Integrity API Endpoint)   — Depends on 1.2
Task 1.4 (Redaction Middleware)      — No dependencies
Task 1.5 (Redacted Column)          — Depends on 1.4
Task 1.6 (Tamper Detection)         — Depends on 1.2
```

**Parallelization**: Tasks 1.1, 1.2, and 1.4 can all be worked on simultaneously by different team members. Task 1.3 follows 1.2, Task 1.5 follows 1.4, and Task 1.6 follows 1.2.

**Recommended assignment for a 4-person team**:
- **Person A**: Tasks 1.1 → 1.3 (database integrity layer)
- **Person B**: Tasks 1.4 → 1.5 (redaction middleware)
- **Person C**: Task 1.2 → 1.6 (verification service + pipeline integration)
- **Person D**: Can start on Phase 2, Task 2.1 (tsvector migration) since it has no Phase 1 dependencies.
