"""OSCAL Assessment Results export service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.framework import Framework
from app.models.project import Project
from app.schemas.oscal import (
    OSCALAssessmentResults,
    OSCALFinding,
    OSCALFindingTarget,
    OSCALMetadata,
    OSCALObservation,
    OSCALProp,
    OSCALRelatedObservation,
    OSCALRelatedRisk,
    OSCALResult,
    OSCALRisk,
    OSCALTargetStatus,
)

STATUS_TO_OSCAL: dict[ControlStatusEnum, tuple[str, str]] = {
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
    """Generate an OSCAL Assessment Results document for a project."""

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
        if not frameworks:
            raise ValueError(f"Framework {framework_id} not found in project {project_id}")

    now = datetime.now(timezone.utc)
    results: list[OSCALResult] = []

    for fw in frameworks:
        observations: list[OSCALObservation] = []
        findings: list[OSCALFinding] = []
        risks: list[OSCALRisk] = []
        seen_evidence: set[UUID] = set()

        for control in fw.controls:
            related_observations: list[OSCALRelatedObservation] = []
            for link in control.evidence_links:
                evidence = link.evidence
                if evidence.id not in seen_evidence:
                    observations.append(
                        OSCALObservation(
                            uuid=evidence.id,
                            title=f"Evidence from {evidence.source_type.value}",
                            description=f"Collected from {evidence.source_ref}",
                            collected=evidence.collected_at,
                            props=[
                                OSCALProp(name="source-type", value=evidence.source_type.value),
                                OSCALProp(name="source-ref", value=evidence.source_ref),
                                OSCALProp(name="sha256-hash", value=evidence.sha256_hash),
                                OSCALProp(name="redacted", value=str(evidence.redacted).lower()),
                            ],
                        )
                    )
                    seen_evidence.add(evidence.id)

                related_observations.append(
                    OSCALRelatedObservation(observation_uuid=evidence.id)
                )

            oscal_state, oscal_reason = STATUS_TO_OSCAL.get(
                control.status, ("not-satisfied", "other")
            )

            related_risks: list[OSCALRelatedRisk] = []
            if control.status in (ControlStatusEnum.FAIL, ControlStatusEnum.NEEDS_REVIEW):
                severity = (
                    "high"
                    if control.status == ControlStatusEnum.FAIL
                    else "medium"
                )
                risk = OSCALRisk(
                    title=f"Risk: {control.title}",
                    description=f"Control {control.control_id_code} is {control.status.value}.",
                    status="open",
                    characterizations=[OSCALProp(name="severity", value=severity)],
                )
                risks.append(risk)
                related_risks.append(OSCALRelatedRisk(risk_uuid=risk.uuid))

            findings.append(
                OSCALFinding(
                    title=f"{control.control_id_code}: {control.title}",
                    description=control.description,
                    target=OSCALFindingTarget(
                        target_id=control.control_id_code,
                        status=OSCALTargetStatus(state=oscal_state, reason=oscal_reason),
                    ),
                    related_observations=related_observations,
                    related_risks=related_risks,
                )
            )

        results.append(
            OSCALResult(
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
                    OSCALProp(name="generated-by", value=generated_by),
                    OSCALProp(name="total-controls", value=str(len(findings))),
                    OSCALProp(
                        name="pass-count",
                        value=str(
                            sum(
                                1
                                for control in fw.controls
                                if control.status == ControlStatusEnum.PASS
                            )
                        ),
                    ),
                ],
            )
        )

    return OSCALAssessmentResults(
        metadata=OSCALMetadata(
            title=f"SentinellAI Assessment Results — {project.name}",
            last_modified=now,
        ),
        results=results,
    )
