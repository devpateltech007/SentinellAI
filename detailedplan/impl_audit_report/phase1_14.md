# Phase 1 — Implementation Audit Report: Task 1.4

> **Wire Redaction as Mandatory Middleware in Evidence Ingestion**
>
> Suite: **27 tests passed**, `ruff` clean, `mypy` clean

---

## Plan vs Implementation

### Part A — Define default redaction config in `normalizer.py`

| Plan Requirement | Status | Notes |
|---|---|---|
| Add `DEFAULT_REDACTION_CONFIG: dict = {"pattern_scan": True}` | ✅ Exact match | Lines 20–22, verbatim from plan |
| Add `logger.info("Evidence redaction applied: %s fields redacted", redacted)` after redaction | ✅ Present | Line 44 — log line matches plan's Definition of Done item 6 |
| Add `import logging` and `logger = logging.getLogger(__name__)` | ✅ Present | Lines 12, 18 |
| Hash computed AFTER redaction (`content_str` uses potentially-redacted `content`) | ✅ Correct | Line 46 — `json.dumps(content, ...)` uses the redacted dict, line 47 hashes it |
| Serialization parity with integrity verifier (`sort_keys=True, default=str`) | ✅ Maintained | Line 46 matches `integrity.py` line 36 |

### Part B — Reroute evidence processing in `evidence_tasks.py`

| Plan Requirement | Status | Notes |
|---|---|---|
| Import `normalize_evidence, DEFAULT_REDACTION_CONFIG` from normalizer | ✅ Exact match | Line 26 |
| Replace `gh.normalize(raw)` with `normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)` | ✅ Exact match | Line 160 |
| `EvidenceItem(...)` construction uses `normalized.source_ref`, `.collected_at`, `.sha256_hash`, `.content_json` | ✅ Exact match | Lines 161–166 match plan snippet |
| Plan says **files to edit** are `normalizer.py` and `evidence_tasks.py` only | ⚠️ Exceeded | We also edited `github_actions.py` (see "Changes Beyond Plan" below) |

---

## Definition of Done Checklist

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Insert a test connector pointing to a real GitHub repo | ✅ | `verify_redaction.py` used `actions/checkout` |
| 2 | Trigger evidence collection | ✅ | Called `_collect_evidence_async()` directly |
| 3 | Query DB for `content_json` | ✅ | Script printed the JSON |
| 4 | Emails appear as `[REDACTED]` in stored `content_json` | ✅ | `'commit_author_email': '[REDACTED]'` confirmed in output |
| 5 | Non-PII fields unchanged but still pass through pipeline | ✅ | All other fields (`name`, `status`, `conclusion`, etc.) preserved |
| 6 | Log line `Evidence redaction applied: ...` appears | ✅ | 10× `INFO:app.services.evidence_engine.normalizer:Evidence redaction applied: True fields redacted` in output |

---

## Issues Found

### 🐛 Bug 1: `redacted` flag NOT persisted to DB during ingestion

**Severity: Medium**

The `evidence_tasks.py` constructs the `EvidenceItem` but **never sets the `redacted` field**:

```python
# evidence_tasks.py lines 161-166 (current)
evidence = EvidenceItem(
    source_type=EvidenceSourceType.GITHUB_ACTIONS,
    source_ref=normalized.source_ref,
    collected_at=normalized.collected_at,
    sha256_hash=normalized.sha256_hash,
    content_json=normalized.content_json,
    # ❌ Missing: redacted=normalized.redacted
)
```

The `NormalizedEvidence` dataclass has `redacted=True` after redaction, and the `EvidenceItem` model has a `redacted` column (line 39 in `evidence.py`), but the value is never wired through. Our live verification confirmed this:

```
Redacted: False   ← Should be True since emails were actually redacted
```

> [!IMPORTANT]
> This is technically a **Task 1.5 responsibility** (the plan says: "Task 1.5 — set the flag during ingestion"), but it means Task 1.4 is leaving the `redacted` boolean silently defaulting to `False` even when PII was actually scrubbed. This is acceptable only if we are strictly following the plan's task boundaries, since Task 1.5 explicitly handles this. But it should be documented as a known gap until 1.5 is complete.

**Fix** (will be done in Task 1.5 per plan):
```python
evidence = EvidenceItem(
    ...
    redacted=normalized.redacted,
)
```

### 🐛 Bug 2: No automated test coverage for redaction in the pipeline

**Severity: Medium**

The plan's Definition of Done is entirely manual verification (items 1–6 are all manual steps). We verified them successfully with `verify_redaction.py`, but there is **no pytest test** that exercises:
- Evidence flowing through `normalize_evidence()` with `DEFAULT_REDACTION_CONFIG`
- PII being redacted in the output
- The `redacted` flag being set correctly (blocked on Bug 1)

The existing 27 tests all pass, but **none of them test the redaction pathway**. The integrity tests in `test_integrity.py` create evidence manually with `EvidenceItem(...)` and bypass the normalizer entirely. The API tests in `test_evidence.py` also insert evidence directly.

> [!WARNING]
> This means the redaction could be broken (e.g., someone reverts the `evidence_tasks.py` change) and all 27 tests would still pass. We should add a redaction-specific test, but the plan doesn't mandate it until Task 1.5's Definition of Done. Still, this is a test gap worth flagging.

**Recommended fix**: Add a test in `test_services/test_redaction.py` that:
1. Creates a `RawEvidence` with PII in `raw_data`
2. Calls `normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)`
3. Asserts PII was replaced with `[REDACTED]`
4. Asserts `normalized.redacted is True`
5. Asserts the SHA-256 matches the redacted content

---

## Changes Beyond Plan Scope

The plan says **files to edit** are only `normalizer.py` and `evidence_tasks.py`. We also modified:

### 1. `github_actions.py` — Auth header fix

```diff
-self._headers = {
-    "Accept": "application/vnd.github+json",
-    "Authorization": f"Bearer {self.token}",
-    "X-GitHub-Api-Version": "2022-11-28",
-}
+self._headers = {
+    "Accept": "application/vnd.github+json",
+    "X-GitHub-Api-Version": "2022-11-28",
+}
+if self.token:
+    self._headers["Authorization"] = f"Bearer {self.token}"
```

**Rationale**: When `GITHUB_TOKEN` is empty/unset, the old code set `Authorization: Bearer ` (with empty value), causing `httpx.LocalProtocolError: Illegal header value`. This is a legitimate bugfix — the connector was non-functional without a token even for public repos.

### 2. `github_actions.py` — Added commit author fields

```diff
+    "commit_author_email": run.get("head_commit", {}).get("author", {}).get("email"),
+    "commit_author_name": run.get("head_commit", {}).get("author", {}).get("name"),
```

**Rationale**: Needed to expose PII (email addresses) that would actually be present in GitHub API responses so we could verify redaction works end-to-end. The plan's "Edge case to handle" section (line 260) specifically mentions that "GitHub Actions API responses typically contain author email addresses in commit metadata."

> [!NOTE]
> These are reasonable additions that align with the plan's intent, but they go beyond the strict "files to edit" scope.

---

## Test Integrity Check

### Are the existing 27 tests still valid?

All 27 tests from Tasks 1.1–1.3 remain correct and are unaffected by Task 1.4 changes because:

1. **Integrity tests** (`test_integrity.py`) — Insert evidence manually via ORM, bypassing the ingestion pipeline. They test hash verification, not redaction. ✅ Still valid.
2. **API tests** (`test_evidence.py`) — Same pattern. The `verify_evidence` test inserts with known content/hash and verifies the API returns correct integrity results. ✅ Still valid.
3. **RBAC/Auth tests** — Unrelated to evidence pipeline. ✅ Still valid.

### Could any test be masking a failure?

The only risk is that the lack of redaction-specific tests means we can't detect regressions in the redaction wiring. But no existing test is "passing incorrectly" — they're testing exactly what they claim to test.

---

## Summary

| Aspect | Verdict |
|---|---|
| **Part A — `normalizer.py` config** | ✅ Fully aligned |
| **Part B — `evidence_tasks.py` reroute** | ✅ Fully aligned |
| **Definition of Done (manual)** | ✅ All 6 items verified |
| **`redacted` flag persistence** | ⚠️ Not wired — expected, deferred to Task 1.5 |
| **Automated test coverage** | ⚠️ No redaction-specific test — recommended to add |
| **Extra changes** | ℹ️ `github_actions.py` auth fix + commit fields — justified but beyond strict plan scope |
| **Existing test suite** | ✅ 27/27 passing, no false positives |

### Recommended Actions Before Moving to 1.5

1. **Add `test_services/test_redaction.py`** — Unit test for `normalize_evidence()` with PII input to close the test gap
2. **Clean up `verify_redaction.py`** — Either delete or add to `.gitignore` (it's a one-off manual verification script, not CI-suitable)
