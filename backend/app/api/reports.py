import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, require_role
from app.config import settings
from app.middleware.audit_log import log_action
from app.models.control import Control
from app.models.control_evidence import ControlEvidence
from app.models.framework import Framework
from app.models.project import Project
from app.models.report import Report
from app.models.user import User, UserRole
from app.schemas.report import ReportExportRequest, ReportFormat, ReportListItem
from app.services.oscal_export import generate_oscal_report
from app.services.report_generator import generate_pdf_report

router = APIRouter(prefix="/reports", tags=["reports"])
_PROJECT_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe_project_slug(project_name: str) -> str:
    slug = _PROJECT_SLUG_RE.sub("_", project_name.strip().lower()).strip("_")
    return slug or "project"


def _get_reports_root() -> Path:
    preferred = Path(settings.REPORTS_DIR)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path("reports")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _build_report_data(
    project: Project,
    frameworks: list[Framework],
    generated_by: str,
) -> dict:
    report_data: dict = {
        "project": {"id": str(project.id), "name": project.name},
        "generated_by": generated_by,
        "frameworks": [],
    }

    for framework in frameworks:
        framework_data: dict = {
            "id": str(framework.id),
            "name": framework.name.value,
            "version": framework.version,
            "controls": [],
        }
        for control in framework.controls:
            evidence_items = []
            for link in control.evidence_links:
                evidence = link.evidence
                truncated_hash = (
                    f"{evidence.sha256_hash[:16]}..."
                    if len(evidence.sha256_hash) > 16
                    else evidence.sha256_hash
                )
                evidence_items.append(
                    {
                        "source_type": evidence.source_type.value,
                        "source_ref": evidence.source_ref,
                        "collected_at": evidence.collected_at.strftime(
                            "%Y-%m-%d %H:%M UTC"
                        ),
                        "sha256_hash": truncated_hash,
                    }
                )

            framework_data["controls"].append(
                {
                    "id": str(control.id),
                    "control_id_code": control.control_id_code,
                    "title": control.title,
                    "description": control.description,
                    "source_citation": control.source_citation,
                    "status": control.status.value,
                    "requirements": [
                        {
                            "description": requirement.description,
                            "testable_condition": requirement.testable_condition,
                        }
                        for requirement in control.requirements
                    ],
                    "evidence_items": evidence_items,
                }
            )

        report_data["frameworks"].append(framework_data)

    return report_data


async def _save_report_file(
    db: DbSession,
    project: Project,
    format_name: ReportFormat,
    content: bytes,
    generated_by_user_id: UUID,
) -> Report:
    timestamp = datetime.now(timezone.utc)
    root = _get_reports_root()
    rel_dir = Path(timestamp.strftime("%Y")) / timestamp.strftime("%m")
    abs_dir = root / rel_dir

    try:
        abs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not prepare report storage: {exc}"
        )

    extension = "pdf" if format_name == ReportFormat.PDF else "json"
    timestamp_tag = timestamp.strftime("%Y%m%dT%H%M%SZ")
    filename = (
        f"{format_name.value}_{_safe_project_slug(project.name)}_{timestamp_tag}.{extension}"
    )
    relative_path = rel_dir / filename
    full_path = root / relative_path

    try:
        full_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save report: {exc}")

    report = Report(
        project_id=project.id,
        format=format_name.value,
        filename=filename,
        file_size_bytes=len(content),
        generated_by=generated_by_user_id,
        file_path=str(relative_path),
    )
    db.add(report)
    await db.flush()
    return report


async def _load_project_for_report(project_id: UUID, db: DbSession) -> Project:
    result = await db.execute(
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
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _export_oscal(
    body: ReportExportRequest,
    db: DbSession,
    current_user: User,
) -> JSONResponse:
    project = await _load_project_for_report(body.project_id, db)
    try:
        oscal_doc = await generate_oscal_report(
            project_id=body.project_id,
            db=db,
            framework_id=body.framework_id,
            generated_by=current_user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    content = oscal_doc.model_dump(mode="json", by_alias=True)
    report = await _save_report_file(
        db=db,
        project=project,
        format_name=ReportFormat.OSCAL,
        content=json.dumps(content, default=str).encode("utf-8"),
        generated_by_user_id=current_user.id,
    )

    await log_action(
        db,
        actor_id=current_user.id,
        action="export_oscal_report",
        resource_type="report",
        resource_id=report.id,
        detail={
            "project_id": str(body.project_id),
            "framework_id": str(body.framework_id) if body.framework_id else None,
            "report_id": str(report.id),
            "format": ReportFormat.OSCAL.value,
        },
    )

    return JSONResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{report.filename}"'},
    )


@router.post("/export")
async def export_report(
    body: ReportExportRequest,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    if body.format == ReportFormat.OSCAL:
        return await _export_oscal(body=body, db=db, current_user=current_user)

    project = await _load_project_for_report(body.project_id, db)
    frameworks = project.frameworks
    if body.framework_id:
        frameworks = [fw for fw in frameworks if fw.id == body.framework_id]
        if not frameworks:
            raise HTTPException(status_code=404, detail="Framework not found in project")

    report_data = _build_report_data(
        project=project,
        frameworks=frameworks,
        generated_by=current_user.email,
    )

    if body.format == ReportFormat.JSON:
        report = await _save_report_file(
            db=db,
            project=project,
            format_name=ReportFormat.JSON,
            content=json.dumps(report_data, default=str).encode("utf-8"),
            generated_by_user_id=current_user.id,
        )
        await log_action(
            db,
            actor_id=current_user.id,
            action="export_report",
            resource_type="report",
            resource_id=report.id,
            detail={
                "project_id": str(body.project_id),
                "framework_id": str(body.framework_id) if body.framework_id else None,
                "report_id": str(report.id),
                "format": body.format.value,
            },
        )
        return JSONResponse(
            content=report_data,
            headers={"Content-Disposition": f'attachment; filename="{report.filename}"'},
        )

    pdf_bytes = await generate_pdf_report(report_data)
    report = await _save_report_file(
        db=db,
        project=project,
        format_name=ReportFormat.PDF,
        content=pdf_bytes,
        generated_by_user_id=current_user.id,
    )
    await log_action(
        db,
        actor_id=current_user.id,
        action="export_report",
        resource_type="report",
        resource_id=report.id,
        detail={
            "project_id": str(body.project_id),
            "framework_id": str(body.framework_id) if body.framework_id else None,
            "report_id": str(report.id),
            "format": body.format.value,
        },
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.filename}"'},
    )


@router.post("/export/oscal")
async def export_oscal_report(
    body: ReportExportRequest,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    return await _export_oscal(
        body=body.model_copy(update={"format": ReportFormat.OSCAL}),
        db=db,
        current_user=current_user,
    )


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    _ = current_user
    result = await db.execute(select(Report).order_by(Report.generated_at.desc()).limit(50))
    reports = result.scalars().all()
    return [ReportListItem.model_validate(report) for report in reports]


@router.get("/{report_id}/download")
async def download_report(
    report_id: UUID,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    file_path = _get_reports_root() / report.file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file missing from storage")

    await log_action(
        db,
        actor_id=current_user.id,
        action="download_report",
        resource_type="report",
        resource_id=report.id,
        detail={"project_id": str(report.project_id), "report_id": str(report.id)},
    )

    media_types = {
        ReportFormat.PDF.value: "application/pdf",
        ReportFormat.JSON.value: "application/json",
        ReportFormat.OSCAL.value: "application/json",
    }
    return FileResponse(
        path=str(file_path),
        media_type=media_types.get(report.format, "application/octet-stream"),
        filename=report.filename,
    )
