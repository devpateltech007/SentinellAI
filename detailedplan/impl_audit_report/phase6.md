# Phase 6 — Implementation Audit Report

**Date**: 2026-05-06  
**Scope**: Phase 6 OSCAL & Reporting, commit `a2f9ec607cd7c60f1fc181495ec6f3a8693e9334`  
**Verification**: Phase 6-specific `mypy` passed; Phase 6-specific `ruff` has 1 newline issue; report API tests could not run because local PostgreSQL was unavailable

> Note: The requested commit `a2f9ec607cd7c60f1fc181495ec6f3a8693e9334` is the latest commit in this checkout. I audited that exact commit as the Phase 6 implementation.

---

## Plan vs. Implementation Checklist

| Task | Plan Requirement | Status | Notes |
|---|---|---|---|
| 6.1 | Define OSCAL Assessment Results schema | ✅ Mostly done | Pydantic models exist with aliases for several hyphenated fields |
| 6.1 | Add `jsonschema>=4.20.0` | ✅ Done | Added to `requirements.txt` |
| 6.1 | Output should validate against official OSCAL 1.1.2 schema | ❌ Not proven / likely fails | No schema validation test; output lacks official `assessment-results` root wrapper |
| 6.2 | Implement OSCAL export service | ✅ Mostly done | Maps projects/frameworks/controls/evidence into OSCAL-ish results |
| 6.2 | Deduplicate evidence observations | ✅ Done | Uses `seen_evidence` set |
| 6.2 | Passing controls map to `satisfied`, failing controls to `not-satisfied` | ✅ Done | `STATUS_TO_OSCAL` present |
| 6.2 | Failed/NeedsReview controls link risks | ✅ Done | Creates `OSCALRisk` for Fail and NeedsReview |
| 6.3 | Add OSCAL export API endpoint | ✅ Done | `POST /api/v1/reports/export/oscal` added |
| 6.3 | Add OSCAL enum option | ✅ Done | `ReportFormat.OSCAL` added |
| 6.3 | Audit log export action | ✅ Done | Logs `export_oscal_report` with `report_id` |
| 6.4 | PDF report includes summary counts | ✅ Done | Summary cards added |
| 6.4 | PDF report includes linked evidence | ✅ Done | Evidence type/ref/date/hash included under controls |
| 6.5 | Add report model and migration | ✅ Done | `Report` model and `009_report_history.py` present |
| 6.5 | Save exported reports to disk | ✅ Done | `_save_report_file()` writes PDF/JSON/OSCAL files |
| 6.5 | Add report list endpoint | ✅ Done | `GET /api/v1/reports` added |
| 6.5 | Add report download endpoint | ✅ Done | `GET /api/v1/reports/{id}/download` added |

---

## Definition of Done Verification

| Area | Result |
|---|---|
| Report API tests | ⚠️ Could not run locally; PostgreSQL was not listening on `localhost:5432` |
| Phase 6-specific `ruff` | ❌ Failed: no newline at end of `app/api/reports.py` |
| Phase 6-specific `mypy` | ✅ Passed for changed Phase 6 source files |
| Full `mypy app` | ⚠️ Fails on pre-existing Phase 3 issues, not Phase 6-specific files |
| OSCAL model smoke serialization | ✅ Pydantic model dumps to JSON |
| Official OSCAL schema validation | ❌ Not implemented/run |

Commands run:

```bash
venv/bin/python -m pytest tests/test_api/test_reports.py
venv/bin/ruff check app/schemas/oscal.py app/services/oscal_export.py app/api/reports.py app/services/report_generator.py app/models/report.py app/schemas/report.py tests/test_api/test_reports.py
venv/bin/mypy app/schemas/oscal.py app/services/oscal_export.py app/api/reports.py app/services/report_generator.py app/models/report.py app/schemas/report.py
venv/bin/mypy app
```

Report API tests errored before exercising behavior:

```text
OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432),
[Errno 61] Connect call failed ('127.0.0.1', 5432)
```

---

## Issues Found

### Bug 1: OSCAL export is likely not official OSCAL 1.1.2 JSON

**Severity: High**

The Phase 6 rationale and Task 6.1 say the OSCAL output should validate against the official OSCAL 1.1.2 JSON schema. The implementation returns this shape from the API:

```json
{
  "uuid": "...",
  "metadata": { ... },
  "results": [ ... ]
}
```

The official NIST OSCAL 1.1.2 Assessment Results reference says the root of the JSON format is `assessment-results`, so a schema-shaped document should be wrapped more like:

```json
{
  "assessment-results": {
    "uuid": "...",
    "metadata": { ... },
    "results": [ ... ]
  }
}
```

Also, NIST's JSON reference lists `result.status` as required, but `OSCALResult` has no `status` field. That means the current payload may be useful as an internal "OSCAL-like" export, but it is not proven interoperable with OSCAL tools.

**Recommended fix**: Add a top-level wrapper model, include required fields such as result `status`, and validate generated output against the official OSCAL 1.1.2 assessment-results JSON schema in tests.

Sources checked: [NIST OSCAL 1.1.2 JSON definitions](https://pages.nist.gov/OSCAL-Reference/models/v1.1.2/assessment-results/json-definitions/) and [NIST OSCAL 1.1.2 JSON reference](https://pages.nist.gov/OSCAL-Reference/models/v1.1.2/assessment-results/json-reference/).

### Bug 2: OSCAL tests are too shallow and would pass with broken mappings

**Severity: High**

`test_export_oscal_report()` creates a project and exports OSCAL without adding frameworks, controls, evidence, or control-evidence links. It asserts only:

```python
assert "uuid" in data
assert "metadata" in data
assert "results" in data
```

This does not verify the Phase 6.2 Definition of Done:

- One result per framework
- Findings per control
- Observations per unique evidence item
- Pass/Fail/NeedsReview status mapping
- Risks linked for failing or needs-review controls
- Evidence hash/source metadata in observation props

This is a classic false-green risk: the test can pass while the important OSCAL behavior is absent or schema-invalid.

**Recommended fix**: Add a service-level test that builds Project → Framework → Controls → Evidence → ControlEvidence and asserts exact findings, observations, related observations, risks, status states, and evidence props. Add official jsonschema validation.

### Bug 3: Report history/download tests do not verify file download

**Severity: Medium**

Task 6.5 Definition of Done requires:

- Exported reports appear in `GET /api/v1/reports`
- `GET /api/v1/reports/{id}/download` streams the file back
- PDF and OSCAL both appear in history
- File is saved under the configured reports path

The added test only checks JSON export appears in the report list and only asserts `reports[0]["format"] == "json"`. It does not call the download endpoint, does not verify file contents, does not verify PDF persistence, and does not verify OSCAL persistence in the list.

**Recommended fix**: Add tests for JSON/PDF/OSCAL persistence and `/{report_id}/download`, with `settings.REPORTS_DIR` pointed at a temp directory.

### Bug 4: Phase 6-specific lint is not clean

**Severity: Low**

`ruff` found one Phase 6-specific issue:

```text
W292 No newline at end of file
app/api/reports.py:358
```

**Recommended fix**: Add the trailing newline.

### Gap 5: Report file writes are not atomic with DB/audit persistence

**Severity: Low**

`_save_report_file()` writes the file to disk, creates a `Report` row, and returns before the endpoint logs the audit action. If a later DB commit or audit logging step fails, the file can remain on disk without a committed report row or audit record.

**Recommended fix**: For stronger audit semantics, write to a temporary filename and finalize/rename only after DB flush succeeds, or add cleanup on exceptions.

### Gap 6: OSCAL `model_dump(mode="json")` without aliases is not OSCAL-shaped

**Severity: Low**

The Pydantic models use `serialization_alias`, and the API correctly calls:

```python
oscal_doc.model_dump(mode="json", by_alias=True)
```

But Task 6.1's Definition of Done says `model.model_dump(mode="json")` should produce valid JSON. Without `by_alias=True`, the dump uses snake_case keys like `last_modified`, `oscal_version`, and `target_id`, which are not the OSCAL JSON property names.

**Recommended fix**: Add a helper method such as `to_oscal_json()` or document that all OSCAL serialization must use `by_alias=True`. Tests should assert hyphenated OSCAL keys.

---

## Test Quality Assessment

### `test_reports.py`

✅ Good intent:
- JSON export returns project data
- Missing project returns 404
- OSCAL endpoint returns a JSON object
- Report list endpoint is checked after JSON export

⚠️ Problems:
- Could not execute locally because PostgreSQL was unavailable
- Does not verify report file storage path
- Does not verify download endpoint
- Does not verify PDF export after Phase 6 evidence enhancements
- Does not verify OSCAL report is saved in report history
- Does not check `Content-Disposition`
- Does not check role restrictions (`401`/`403`)
- Does not build any control/evidence graph, so evidence traceability is untested
- Does not validate against official OSCAL schema despite adding `jsonschema`

### Service Tests

No direct service tests were added for:

- `generate_oscal_report()`
- `_build_report_data()`
- `_save_report_file()`
- `generate_pdf_report()` evidence rendering

These functions are where most Phase 6 logic lives, so relying only on API tests leaves large gaps.

---

## Changes Beyond Plan Scope

Mostly acceptable:

- Added `REPORTS_DIR` setting with fallback behavior. This makes local/dev storage more configurable than the plan's fixed `/app/reports`.
- Added support for `format: "oscal"` through the existing `/reports/export` endpoint as well as the dedicated `/reports/export/oscal` endpoint. This is useful and aligns with the plan's "or create a separate endpoint" note.

Potentially problematic:

- The exported "OSCAL" shape is closer to the plan's simplified Pydantic sketch than the official OSCAL JSON schema. Since the phase rationale is interoperability, this needs schema validation before calling it complete.

---

## Overall Alignment Verdict

Phase 6 is **functionally aligned with the project plan at a high level**, but it is **not yet proven OSCAL-compliant**. The implementation adds report persistence, report downloads, PDF evidence sections, and an OSCAL export path. Those are the right features.

The main concern is correctness depth: the current tests are too shallow to catch broken OSCAL mappings, missing evidence traceability, missing downloads, or schema-invalid OSCAL output.

| Item | Priority |
|---|---|
| Validate OSCAL output against official OSCAL 1.1.2 schema | High |
| Add real OSCAL mapping tests with controls, evidence, observations, findings, and risks | High |
| Add report download and file persistence tests for JSON/PDF/OSCAL | Medium |
| Fix Phase 6 `ruff` newline issue | Low |
| Add service tests for PDF evidence rendering and report data assembly | Medium |
| Clarify/standardize OSCAL serialization with `by_alias=True` | Medium |

Phase 6 should be considered feature-present but not audit-grade complete until OSCAL schema validation and deeper report persistence tests are added.
