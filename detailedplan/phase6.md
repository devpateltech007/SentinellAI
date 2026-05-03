# Phase 6 — OSCAL & Reporting

> **Estimated Total**: 16 engineering hours
> **Dependencies**: Phase 1 Tasks 1.2-1.3 (integrity verification) for evidence hash inclusion in reports. Core backend models must be stable.
> **Rationale**: Compliance reports are the primary deliverable of an auditing platform. Currently the system can export basic PDF and JSON reports, but they lack evidence traceability and don't conform to any industry standard. OSCAL (Open Security Controls Assessment Language) is NIST's standard for machine-readable compliance data — supporting it makes SentinellAI's output interoperable with GRC tools like AWS Audit Manager, Tanium, and Trestle.

---

## Current State

| Component | File | Status |
|---|---|---|
| Report Export API | `api/reports.py` | 🟡 Works for PDF + JSON, but no evidence references |
| PDF Template | `services/report_generator.py` | 🟡 HTML→PDF via WeasyPrint, basic styling |
| JSON Report | `services/report_generator.py:72` | 🟡 Raw data dump, no structure |
| Report Schema | `schemas/report.py` | 🟡 Only `pdf` and `json` formats |
| Report Storage | — | 🔴 Not implemented — reports are generated on-the-fly, never saved |
| OSCAL Support | — | 🔴 Not implemented |

---

## Task 6.1: Define OSCAL Assessment Result Schema

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/schemas/oscal.py`

**Files to Reference**:
- OSCAL Assessment Results model spec: https://pages.nist.gov/OSCAL/concepts/layer/assessment/assessment-results/
- `backend/app/models/control.py` — `Control` + `ControlStatusEnum`
- `backend/app/models/evidence.py` — `EvidenceItem`

**Detailed Logic Brief**:

OSCAL defines a specific JSON structure for assessment results. Our Pydantic v2 models must mirror this structure so the output validates against the official OSCAL 1.1.2 JSON schema. The key mapping is:

| SentinellAI Concept | OSCAL Concept |
|---|---|
| Project | `assessment-results.metadata` |
| Framework | `assessment-results.result` |
| Control (Pass) | `finding` with `state: "satisfied"` |
| Control (Fail) | `finding` with `state: "not-satisfied"` |
| Control (NeedsReview) | `finding` with `state: "not-satisfied"` + `risk` entry |
| EvidenceItem | `observation` with `collected` timestamp |
| Control → Evidence link | `finding.related-observations` referencing observation UUIDs |

```python
"""OSCAL 1.1.2 Assessment Results Pydantic v2 models."""

from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict

# --- OSCAL Building Blocks ---

class OSCALMetadata(BaseModel):
    title: str
    last_modified: datetime
    version: str = "1.0.0"
    oscal_version: str = "1.1.2"

class OSCALProp(BaseModel):
    """OSCAL property — key/value metadata attached to any element."""
    name: str
    value: str
    ns: str = "https://sentinellai.dev/ns/oscal"

class OSCALSubjectReference(BaseModel):
    subject_uuid: UUID
    type: str  # "component", "inventory-item", etc.
    title: str | None = None

# --- Observations (Evidence) ---

class OSCALObservation(BaseModel):
    """Maps to an EvidenceItem in SentinellAI."""
    uuid: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    collected: datetime
    methods: list[str] = Field(default_factory=lambda: ["AUTOMATED"])
    types: list[str] = Field(default_factory=lambda: ["finding"])
    props: list[OSCALProp] = Field(default_factory=list)

    # SentinellAI-specific extensions
    # OSCAL allows custom properties via the `props` field
    # We store source_type, source_ref, sha256_hash as props

class OSCALRelatedObservation(BaseModel):
    observation_uuid: UUID

# --- Findings (Controls) ---

class OSCALFinding(BaseModel):
    """Maps to a Control evaluation result in SentinellAI."""
    uuid: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    target: OSCALFindingTarget
    related_observations: list[OSCALRelatedObservation] = Field(default_factory=list)
    related_risks: list[OSCALRelatedRisk] = Field(default_factory=list)

class OSCALFindingTarget(BaseModel):
    type: str = "objective-id"
    target_id: str            # Our control_id_code (e.g., "HIPAA-AC-001")
    status: OSCALTargetStatus

class OSCALTargetStatus(BaseModel):
    state: str                # "satisfied" or "not-satisfied"
    reason: str | None = None # "pass", "fail", "other"

class OSCALRelatedRisk(BaseModel):
    risk_uuid: UUID

# --- Risk (for NeedsReview / Failed controls) ---

class OSCALRisk(BaseModel):
    uuid: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    status: str = "open"     # "open", "closed", "deviation-approved"
    characterizations: list[OSCALProp] = Field(default_factory=list)

# --- Top-Level Result ---

class OSCALResult(BaseModel):
    """One result per framework evaluation run."""
    uuid: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    start: datetime
    end: datetime | None = None
    findings: list[OSCALFinding] = Field(default_factory=list)
    observations: list[OSCALObservation] = Field(default_factory=list)
    risks: list[OSCALRisk] = Field(default_factory=list)
    props: list[OSCALProp] = Field(default_factory=list)

# --- Top-Level Document ---

class OSCALAssessmentResults(BaseModel):
    """OSCAL Assessment Results document — the root object."""
    uuid: UUID = Field(default_factory=uuid4)
    metadata: OSCALMetadata
    results: list[OSCALResult]

    model_config = ConfigDict(
        json_schema_extra={
            "description": "OSCAL 1.1.2 Assessment Results generated by SentinellAI"
        }
    )
```

**Key design decisions**:

1. **SentinellAI extensions go in `props`**: OSCAL has a flexible `props` mechanism for vendor-specific metadata. We store `source_type`, `source_ref`, `sha256_hash`, and `redacted` as props on observations rather than inventing custom fields. This keeps the output OSCAL-compliant.

2. **Control status mapping**: OSCAL only has `satisfied` / `not-satisfied` for finding states. Our `NeedsReview` maps to `not-satisfied` with a linked `risk` entry that has `status: "open"` — signaling that this finding requires human attention.

3. **`methods: ["AUTOMATED"]`**: OSCAL tracks whether observations were collected manually or automatically. Since all our evidence comes from connectors, we default to `AUTOMATED`.

**Definition of Done**:
1. Instantiate `OSCALAssessmentResults` with mock data — validates without Pydantic errors.
2. `model.model_dump(mode="json")` produces valid JSON.
3. The output structure can be visually compared against the OSCAL spec example at the NIST OSCAL website.
4. Add `jsonschema>=4.20.0` to `requirements.txt` for validation in Task 6.2.

---

## Task 6.2: Implement OSCAL JSON Export Service

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/services/oscal_export.py`

**Files to Reference**:
- `backend/app/schemas/oscal.py` — the models from Task 6.1
- `backend/app/api/reports.py` — existing report data assembly logic (lines 30-77)

**Detailed Logic Brief**:

This service transforms SentinellAI's internal data model into the OSCAL structure defined in Task 6.1.

```python
"""OSCAL Assessment Results export service."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.evidence import EvidenceItem
from app.models.framework import Framework
from app.models.project import Project
from app.schemas.oscal import (
    OSCALAssessmentResults, OSCALFinding, OSCALFindingTarget,
    OSCALMetadata, OSCALObservation, OSCALProp, OSCALRelatedObservation,
    OSCALRelatedRisk, OSCALResult, OSCALRisk, OSCALTargetStatus,
)

STATUS_TO_OSCAL = {
    ControlStatusEnum.PASS: ("satisfied", "pass"),
    ControlStatusEnum.FAIL: ("not-satisfied", "fail"),
    ControlStatusEnum.NEEDS_REVIEW: ("not-satisfied", "other"),
    ControlStatusEnum.PENDING: ("not-satisfied", "other"),
}


async def generate_oscal_report(
    project_id: UUID,
    db: AsyncSession,
    framework_id: UUID | None = None,
    generated_by: str = "SentinellAI",
) -> OSCALAssessmentResults:
    """Generate a full OSCAL Assessment Results document for a project."""

    # Load project with all nested relationships
    query = (
        select(Project)
        .options(
            selectinload(Project.frameworks)
            .selectinload(Framework.controls)
            .selectinload(Control.evidence_links)
            .selectinload(ControlEvidence.evidence)
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(query)
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError(f"Project {project_id} not found")

    frameworks = project.frameworks
    if framework_id:
        frameworks = [fw for fw in frameworks if fw.id == framework_id]

    now = datetime.now(timezone.utc)
    results: list[OSCALResult] = []

    for fw in frameworks:
        observations: list[OSCALObservation] = []
        findings: list[OSCALFinding] = []
        risks: list[OSCALRisk] = []

        # Track evidence already added to avoid duplicates
        seen_evidence: dict[UUID, OSCALObservation] = {}

        for control in fw.controls:
            # Build observations from linked evidence
            related_obs: list[OSCALRelatedObservation] = []
            for link in control.evidence_links:
                ev = link.evidence
                if ev.id not in seen_evidence:
                    obs = OSCALObservation(
                        uuid=ev.id,
                        title=f"Evidence from {ev.source_type.value}",
                        description=f"Collected from {ev.source_ref}",
                        collected=ev.collected_at,
                        props=[
                            OSCALProp(name="source-type", value=ev.source_type.value),
                            OSCALProp(name="source-ref", value=ev.source_ref),
                            OSCALProp(name="sha256-hash", value=ev.sha256_hash),
                        ],
                    )
                    observations.append(obs)
                    seen_evidence[ev.id] = obs

                related_obs.append(
                    OSCALRelatedObservation(observation_uuid=ev.id)
                )

            # Map control status to OSCAL state
            oscal_state, oscal_reason = STATUS_TO_OSCAL.get(
                control.status, ("not-satisfied", "other")
            )

            # Create risk entry for non-passing controls
            related_risks: list[OSCALRelatedRisk] = []
            if control.status in (ControlStatusEnum.FAIL, ControlStatusEnum.NEEDS_REVIEW):
                risk = OSCALRisk(
                    title=f"Risk: {control.title}",
                    description=f"Control {control.control_id_code} is {control.status.value}.",
                    status="open",
                    characterizations=[
                        OSCALProp(name="severity", value="high" if control.status == ControlStatusEnum.FAIL else "medium"),
                    ],
                )
                risks.append(risk)
                related_risks.append(OSCALRelatedRisk(risk_uuid=risk.uuid))

            # Build finding
            finding = OSCALFinding(
                title=f"{control.control_id_code}: {control.title}",
                description=control.description,
                target=OSCALFindingTarget(
                    target_id=control.control_id_code,
                    status=OSCALTargetStatus(
                        state=oscal_state,
                        reason=oscal_reason,
                    ),
                ),
                related_observations=related_obs,
                related_risks=related_risks,
            )
            findings.append(finding)

        # Assemble result for this framework
        oscal_result = OSCALResult(
            title=f"{fw.name.value} Assessment — {project.name}",
            description=f"Automated compliance assessment for {fw.name.value} v{fw.version}",
            start=fw.ingested_at or now,
            end=now,
            findings=findings,
            observations=observations,
            risks=risks,
            props=[
                OSCALProp(name="framework-name", value=fw.name.value),
                OSCALProp(name="framework-version", value=fw.version),
                OSCALProp(name="total-controls", value=str(len(findings))),
                OSCALProp(name="pass-count", value=str(sum(
                    1 for c in fw.controls if c.status == ControlStatusEnum.PASS
                ))),
            ],
        )
        results.append(oscal_result)

    return OSCALAssessmentResults(
        metadata=OSCALMetadata(
            title=f"SentinellAI Assessment Results — {project.name}",
            last_modified=now,
        ),
        results=results,
    )
```

**Evidence deduplication**: Multiple controls may link to the same evidence item. The `seen_evidence` dict ensures each `OSCALObservation` appears once in the `observations` list, while multiple findings can reference it via `related_observations`. This matches OSCAL's intended data model where observations are shared resources.

**Definition of Done**:
1. Call `generate_oscal_report(project_id, db)` with the seeded "Healthcare App Compliance" project.
2. Output contains 1 result (HIPAA framework), 8 findings (one per control), and 4 observations (one per unique evidence item).
3. Findings for passing controls have `state: "satisfied"`. Failing controls have `state: "not-satisfied"` with linked risks.
4. `json.dumps(result.model_dump(mode="json"), indent=2)` produces well-structured JSON.
5. (Optional) Validate output against OSCAL 1.1.2 JSON schema using `jsonschema.validate()`.

---

## Task 6.3: Add OSCAL Export API Endpoint

**Estimated Time**: 2 hours

**Files to Edit**:
- `backend/app/api/reports.py` — add OSCAL export endpoint
- `backend/app/schemas/report.py` — add OSCAL format option

**Detailed Logic Brief**:

Add a dedicated endpoint for OSCAL export and update the existing format enum.

**Update `ReportFormat` enum**:
```python
class ReportFormat(str, Enum):
    PDF = "pdf"
    JSON = "json"
    OSCAL = "oscal"  # NEW
```

**Add OSCAL branch to existing `/export` endpoint** (or create a separate `/export/oscal` for cleaner separation):

```python
@router.post("/export/oscal")
async def export_oscal_report(
    body: ReportExportRequest,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    from app.services.oscal_export import generate_oscal_report

    try:
        oscal_doc = await generate_oscal_report(
            project_id=body.project_id,
            db=db,
            framework_id=body.framework_id,
            generated_by=current_user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await log_action(
        db,
        actor_id=current_user.id,
        action="export_oscal_report",
        resource_type="report",
        detail={"project_id": str(body.project_id)},
    )

    content = oscal_doc.model_dump(mode="json")
    filename = f"oscal_assessment_{body.project_id}.json"

    return JSONResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

**Definition of Done**:
1. `POST /api/v1/reports/export/oscal` with `{"project_id": "..."}` returns OSCAL JSON with `Content-Disposition` header.
2. Response has top-level keys: `uuid`, `metadata`, `results`.
3. Unauthorized users get 401. Users without report role get 403.
4. Action is logged in `audit_logs`.

---

## Task 6.4: Enhance PDF Report with Evidence Links and Summary

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/services/report_generator.py` — update HTML template
- `backend/app/api/reports.py` — include evidence data in report_data

**Detailed Logic Brief**:

The current PDF template (in `report_generator.py`) shows controls with their requirements but does NOT include linked evidence items. For a real audit, every control's status must be traceable back to specific evidence.

**Step 1 — Include evidence in report data** in `api/reports.py`:

Update the query to eager-load evidence links:
```python
select(Project)
.options(
    selectinload(Project.frameworks)
    .selectinload(Framework.controls)
    .selectinload(Control.requirements),
    selectinload(Project.frameworks)
    .selectinload(Framework.controls)
    .selectinload(Control.evidence_links)
    .selectinload(ControlEvidence.evidence),
)
```

Add evidence data to each control dict:
```python
ctrl_data = {
    # ... existing fields ...
    "evidence_items": [
        {
            "source_type": link.evidence.source_type.value,
            "source_ref": link.evidence.source_ref,
            "collected_at": link.evidence.collected_at.strftime("%Y-%m-%d %H:%M UTC"),
            "sha256_hash": link.evidence.sha256_hash[:16] + "...",
        }
        for link in control.evidence_links
    ],
}
```

**Step 2 — Add summary table and evidence to PDF template**:

Add a summary section after the header:

```html
<div class="summary">
    <div class="summary-card" style="background: #e8f5e9;">
        <div style="font-size: 24px; font-weight: bold;">{{ pass_count }}</div>
        <div>Passed</div>
    </div>
    <div class="summary-card" style="background: #ffebee;">
        <div style="font-size: 24px; font-weight: bold;">{{ fail_count }}</div>
        <div>Failed</div>
    </div>
    <div class="summary-card" style="background: #fff3e0;">
        <div style="font-size: 24px; font-weight: bold;">{{ review_count }}</div>
        <div>Needs Review</div>
    </div>
    <div class="summary-card" style="background: #f3e5f5;">
        <div style="font-size: 24px; font-weight: bold;">{{ evidence_count }}</div>
        <div>Evidence Items</div>
    </div>
</div>
```

Add evidence list under each control:

```html
{% if control.evidence_items %}
<div style="margin-top: 10px;">
    <strong>Supporting Evidence:</strong>
    {% for ev in control.evidence_items %}
    <div class="evidence">
        <span class="badge">{{ ev.source_type }}</span>
        {{ ev.source_ref }}
        <br><small>Collected: {{ ev.collected_at }} | Hash: {{ ev.sha256_hash }}</small>
    </div>
    {% endfor %}
</div>
{% endif %}
```

Compute the summary counts in `generate_pdf_report()` before rendering:

```python
all_controls = [c for fw in report_data.get("frameworks", []) for c in fw.get("controls", [])]
pass_count = sum(1 for c in all_controls if c["status"] == "Pass")
fail_count = sum(1 for c in all_controls if c["status"] == "Fail")
review_count = sum(1 for c in all_controls if c["status"] == "NeedsReview")
evidence_count = sum(len(c.get("evidence_items", [])) for c in all_controls)
```

**Definition of Done**:
1. Export a PDF for the seeded project.
2. PDF opens and shows: summary table at top (pass/fail/review/evidence counts), each control with evidence list underneath, and the footer.
3. Each evidence entry shows source type, ref, collected date, and truncated hash.
4. Controls with no evidence show nothing (no empty section).

---

## Task 6.5: Add Report History and Download Endpoint

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/models/report.py`
- `backend/alembic/versions/009_report_history.py`

**Files to Edit**:
- `backend/app/models/__init__.py` — register new model
- `backend/app/api/reports.py` — save reports + add list/download endpoints

**Detailed Logic Brief**:

Currently reports are generated and streamed immediately — never persisted. For audit trails, every exported report should be saved and downloadable later.

**Report Model**:

```python
class Report(Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    format: Mapped[str]           # "pdf", "json", "oscal"
    filename: Mapped[str]
    file_size_bytes: Mapped[int]
    generated_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    file_path: Mapped[str]        # Relative path on disk, e.g., "reports/2026/04/report_xxx.pdf"
```

**Storage**: Save reports to `/app/reports/{year}/{month}/` inside the container (mapped to a Docker volume for persistence). Generate filename as `{format}_{project_name}_{timestamp}.{ext}`.

**New endpoints**:

```python
@router.get("", response_model=list[ReportListItem])
async def list_reports(db: DbSession, current_user: CurrentUser):
    """List all previously generated reports."""
    result = await db.execute(
        select(Report).order_by(Report.generated_at.desc()).limit(50)
    )
    return result.scalars().all()

@router.get("/{report_id}/download")
async def download_report(report_id: UUID, db: DbSession, current_user: CurrentUser):
    """Download a previously generated report file."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    file_path = Path(report.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file missing from storage")

    media_types = {"pdf": "application/pdf", "json": "application/json", "oscal": "application/json"}

    return FileResponse(
        path=str(file_path),
        media_type=media_types.get(report.format, "application/octet-stream"),
        filename=report.filename,
    )
```

**Update export endpoints**: After generating a report (PDF, JSON, or OSCAL), save the file to disk and create a `Report` row before returning the response. This way both the download and the inline response work.

**Definition of Done**:
1. Export a PDF report. It now also appears in `GET /api/v1/reports` with correct metadata.
2. `GET /api/v1/reports/{id}/download` streams the file back.
3. Export an OSCAL report. It also appears in the list.
4. File is saved on disk at the correct path under `/app/reports/`.
5. `audit_logs` contains an entry for the export action.

---

## Phase 6 — Dependency Graph

```
Task 6.1 (OSCAL Schema)               — No dependencies
Task 6.2 (OSCAL Export Service)        — Depends on 6.1
Task 6.3 (OSCAL API Endpoint)          — Depends on 6.2
Task 6.4 (PDF Evidence Enhancement)    — No dependencies
Task 6.5 (Report History & Download)   — No dependencies
```

**Parallelization**: Tasks 6.1, 6.4, and 6.5 can all start simultaneously. Tasks 6.2→6.3 are sequential.

**Recommended assignment**:
- **Person A**: Tasks 6.1 → 6.2 → 6.3 (OSCAL pipeline end-to-end)
- **Person B**: Task 6.4 (PDF enhancements — template work)
- **Person C**: Task 6.5 (report persistence + download — model + migration + API)
- **Person D**: Can start Phase 7 testing tasks
