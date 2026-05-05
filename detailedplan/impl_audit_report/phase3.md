# Phase 3 — Implementation Audit Report

**Date**: 2026-05-05  
**Scope**: Phase 3 Connector Framework Hardening, commit `b0674470a63465ff66a1203d338e9e527c90ea0d`  
**Verification**: 13 focused service tests passed; connector API tests could not run because local PostgreSQL was unavailable; `ruff` and `mypy` both fail

> Note: The requested commit `b0674470a63465ff66a1203d338e9e527c90ea0d` is the latest commit in this checkout, with Phase 2 immediately before it. I audited that exact commit as the Phase 3 implementation.

---

## Plan vs. Implementation Checklist

| Task | Plan Requirement | Status | Notes |
|---|---|---|---|
| 3.1 | Add `GitHubCodeConnector` | ✅ Done | Connector exists and scans matching repo files |
| 3.1 | Tree discovery via GitHub tree API | ✅ Done | Also improves plan by fetching default branch dynamically |
| 3.1 | Rate-limit warning and skip when remaining < 100 | ✅ Done | Implemented after tree call |
| 3.1 | Validate rejects missing `content` or `sha`, and files > 1MB | ✅ Done | Covered by tests |
| 3.1 | Normalize stores truncated content and full-content SHA-256 | ✅ Mostly done | Connector `normalize()` does this, but evidence task does not use it |
| 3.2 | Add Terraform security parser | ✅ Mostly done | Core flags exist, but modern S3 versioning syntax is missed |
| 3.2 | Add Kubernetes security parser | ✅ Done | Required flags implemented and covered |
| 3.2 | Add at least 5 variations of each file type | ⚠️ Partial | There are 3 Terraform tests and 3 Kubernetes tests, not 5 each |
| 3.3 | Add `github_code` enum value and migration | ✅ Done | Model and migration present |
| 3.3 | Wire `github_code` branch into evidence collection | ✅ Done | Branch persists redacted normalized evidence |
| 3.3 | Preserve PII redaction path | ✅ Done | Uses `normalize_evidence(..., DEFAULT_REDACTION_CONFIG)` |
| 3.4 | Add connector health response schema | ✅ Done | Schema exists |
| 3.4 | Add health endpoint | ✅ Mostly done | Endpoint exists, but GitHub health tests are missing |
| 3.5 | Add `is_active` migration/model field | ✅ Done | Migration `008` and model field exist |
| 3.5 | Add PUT endpoint for partial update | ✅ Done | Endpoint exists |
| 3.5 | Add DELETE endpoint as soft delete | ✅ Done | Sets `is_active = False` |
| 3.5 | Audit logs for update and delete | ⚠️ Mostly done | Logs are written, but after committing the mutation |
| 3.6 | Add cron validation with `croniter` | ✅ Done | Create/update validators exist |
| 3.6 | Default schedule to `0 */6 * * *` | ❌ Missing | `ConnectorCreate.schedule` defaults to `None` |
| 3.6 | Scheduled collection respects per-connector schedules | ✅ Mostly done | It filters active connectors and evaluates cron schedules |

---

## Definition of Done Verification

| Area | Result |
|---|---|
| GitHub code connector service tests | ✅ 7/7 passed |
| IaC parser service tests | ✅ 6/6 passed |
| Connector API tests | ⚠️ Could not run locally; PostgreSQL was not listening on `localhost:5432` |
| Linting | ❌ `ruff` failed with 27 errors in Phase 3 files/tests |
| Type checking | ❌ `mypy app` failed with 4 errors |
| Real GitHub/public repo connector run | ⚠️ Not run during this audit |
| Manual scheduled Celery verification | ⚠️ Not run during this audit |

Commands run:

```bash
venv/bin/python -m pytest tests/test_services/test_github_code.py tests/test_services/test_iac_parser.py tests/test_api/test_connectors.py
venv/bin/python -m pytest tests/test_api/test_connectors.py
venv/bin/ruff check app tests/test_services/test_github_code.py tests/test_services/test_iac_parser.py tests/test_api/test_connectors.py
venv/bin/mypy app
```

The service-only portion passed:

```text
tests/test_services/test_github_code.py .......
tests/test_services/test_iac_parser.py ......
13 passed
```

The API tests errored before exercising app behavior because the test DB connection failed:

```text
OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432),
[Errno 61] Connect call failed ('127.0.0.1', 5432)
```

---

## Issues Found

### Bug 1: Connectors created without a schedule are never dispatched

**Severity: High**

Task 3.6 says `ConnectorCreate.schedule` should default to `"0 */6 * * *"`. The implementation leaves it optional:

```python
schedule: str | None = None
```

Then the scheduler skips unscheduled connectors:

```python
if not c.schedule:
    continue
```

This means any connector created without explicitly passing `schedule` will never run from scheduled evidence collection. Existing API tests create connectors without schedules, and those connectors would be silently skipped by the scheduler.

**Recommended fix**: Set `ConnectorCreate.schedule = "0 */6 * * *"` or apply the default in `register_connector()`. Add a test that creates a connector without a schedule and asserts it stores the default.

### Bug 2: `iac_config` connectors still cannot collect evidence

**Severity: High**

`_collect_evidence_async()` handles `github_actions` and `github_code`, but there is no `iac_config` branch. If an IaC connector is manually triggered or scheduled, neither branch sets `count`, then the function reaches:

```python
logger.info("Collected %d evidence items for connector %s", count, connector_id)
```

That raises `UnboundLocalError`. Phase 3 adds IaC health checks, CRUD tests, and scheduling around `iac_config` connectors, so this is now a visible lifecycle gap even if the original collection path was already incomplete.

**Recommended fix**: Add an `iac_config` branch using `IaCConfigConnector`, normalize via `normalize_evidence(..., DEFAULT_REDACTION_CONFIG)`, and add a test that triggers an IaC connector without hitting GitHub.

### Bug 3: Terraform versioning test passes by accepting a known parser miss

**Severity: Medium**

The parser only recognizes old inline syntax:

```python
versioning { enabled = true }
```

The test uses modern AWS provider syntax:

```hcl
resource "aws_s3_bucket_versioning" "versioning_example" {
  versioning_configuration {
    status = "Enabled"
  }
}
```

But the test asserts `versioning_enabled is False` and explains that this is due to the regex limitation. That is a false-green test: the parser should identify this as versioning enabled.

**Recommended fix**: Update `parse_terraform_security()` to detect `aws_s3_bucket_versioning` plus `status = "Enabled"`, then change the test to assert `True`.

### Bug 4: `ConnectorResponse` does not expose `is_active`

**Severity: Medium**

Task 3.5 adds soft deletion through `is_active`, but the response schema omits it:

```python
class ConnectorResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_type: str
    schedule: str | None = None
    ...
```

The PUT endpoint accepts `is_active`, DELETE sets it to `False`, and scheduled collection filters by it, but clients cannot see whether a listed connector is active. The API test for update/delete also does not verify the soft-delete state in DB or response.

**Recommended fix**: Add `is_active: bool` to `ConnectorResponse` and test that DELETE leaves the row present with `is_active = false`.

### Bug 5: Phase 3 is not lint-clean or type-clean

**Severity: Medium**

`ruff` fails on Phase 3 files and tests with import ordering, whitespace, duplicate imports, an unused `Any`, a late `croniter` import, and `Connector.is_active == True`.

`mypy app` fails with:

```text
app/schemas/connector.py:5: Library stubs not installed for "croniter"
app/services/evidence_engine/github_code.py:52: Returning Any from function declared to return "str"
app/services/evidence_engine/github_code.py:159: Argument "collected_at" ... has incompatible type "datetime | None"; expected "datetime"
app/workers/evidence_tasks.py:234: Library stubs not installed for "croniter"
```

**Recommended fix**: Clean imports/formatting, remove unused imports, move `croniter` to the top-level import block, use `Connector.is_active.is_(True)` or equivalent, install/configure croniter stubs or ignore the import, cast/default the GitHub default branch, and default `collected_at` when normalizing.

### Bug 6: GitHub Code connector reintroduces empty Authorization header risk

**Severity: Medium**

`GitHubActionsConnector` correctly only adds the Authorization header when a token exists. `GitHubCodeConnector` always sends:

```python
"Authorization": f"Bearer {self.token}",
```

If `GITHUB_TOKEN` is unset or empty, public repo scans can fail due to a malformed/empty authorization header. This exact pattern was fixed earlier for GitHub Actions.

**Recommended fix**: Match `GitHubActionsConnector`: build base headers first, then add `Authorization` only if `self.token` is truthy.

### Gap 7: Health endpoint tests do not validate the planned GitHub behavior

**Severity: Medium**

Task 3.4 Definition of Done requires:

- Valid GitHub connector returns `reachable: true`
- Invalid token returns `reachable: false` with `401`
- Nonexistent repo returns `reachable: false` with `404`

The added API test only creates an `iac_config` connector and checks that `"reachable"` exists in the response. No GitHub health behavior is mocked or asserted, so the key planned behavior could regress without test failure.

**Recommended fix**: Add mocked `httpx.AsyncClient.get` tests for GitHub `200`, `401`, `404`, and network error paths.

### Gap 8: Update/delete audit logging is not atomic with the mutation

**Severity: Low**

`update_connector()` and `delete_connector()` call `await db.commit()` before `log_action()`. The dependency will commit again after the request, so audit logs are usually persisted, but the mutation can be committed even if audit logging later fails.

**Recommended fix**: Log before the explicit commit, or avoid explicit commit and let the request-scoped DB dependency commit mutation and audit log together.

---

## Test Quality Assessment

### `test_github_code.py`

✅ Good coverage:
- Collects matching files from mocked tree/content responses
- Verifies rate-limit skip
- Validates required fields and size limit
- Exercises connector-level normalize

⚠️ Gaps:
- Does not verify SHA-256 hash equals the full content hash
- Does not verify content truncation at 5000 chars
- Does not cover missing token/header behavior
- Does not cover default branch API failure
- Has duplicate imports and lint failures

### `test_iac_parser.py`

✅ Good coverage:
- Covers basic Terraform encryption/no-encryption
- Covers Kubernetes non-root, read-only root FS, capabilities drop, resource limits, and automount token

❌ False-green concern:
- `test_terraform_logging_and_versioning()` asserts `versioning_enabled is False` for a modern versioning resource and explains the parser limitation. This test passes while preserving the bug.

⚠️ Coverage gap:
- The plan requested at least 5 variations per file type. Current coverage has 3 Terraform tests and 3 Kubernetes tests.

### `test_connectors.py`

⚠️ Could not execute locally because the PostgreSQL test DB was unavailable.

Static quality concerns:
- Update/delete test does not verify `is_active` in the DB after DELETE
- Health test only covers an IaC path existence response, not GitHub 200/401/404 behavior
- Cron validation test covers invalid cron only, not valid cron creation or default schedule
- No test covers scheduled evidence dispatch decisions
- No test covers `github_code` evidence collection through `_collect_evidence_async()`

---

## Changes Beyond Plan Scope

Mostly acceptable:

- `GitHubCodeConnector` dynamically fetches the default branch instead of assuming `main`. This is a good improvement over the plan.
- Health checks support `iac_config` by checking filesystem existence. This is aligned with the plan.

Potentially problematic:

- The implementation added lifecycle support around `iac_config` connectors without making `iac_config` collection work in `_collect_evidence_async()`, leaving that connector type manageable but not collectable.

---

## Overall Alignment Verdict

Phase 3 is **partially aligned but not production-ready**. The main implementation pieces exist: GitHub code scanning, IaC parsers, GitHub code evidence wiring, health endpoint, update/delete endpoints, soft-delete state, cron validation, and schedule-aware dispatch.

However, there are several correctness and test-integrity gaps:

| Item | Priority |
|---|---|
| Add default connector schedule so unscheduled connectors are not silently skipped | High |
| Add `iac_config` collection branch or prevent unsupported connector triggering | High |
| Fix the Terraform versioning parser and its false-green test | High |
| Expose and verify `is_active` after update/delete | Medium |
| Add real/mocked GitHub health tests for 200/401/404 | Medium |
| Fix `ruff` and `mypy` failures | Medium |
| Fix empty GitHub Authorization header behavior | Medium |
| Add tests for scheduled dispatch behavior | Medium |

The biggest test-integrity issue is the IaC parser test that knowingly asserts the parser's incorrect output. The biggest runtime issue is the missing default schedule, because it causes newly created connectors without an explicit schedule to never run.
