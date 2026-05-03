
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, require_role
from app.middleware.audit_log import log_action
from app.models.control import Control
from app.models.framework import Framework
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.report import ReportExportRequest, ReportFormat, ReportResponse
from app.services.report_generator import generate_pdf_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/export", response_model=ReportResponse)
async def export_report(
    body: ReportExportRequest,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.frameworks)
            .selectinload(Framework.controls)
            .selectinload(Control.requirements)
        )
        .where(Project.id == body.project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    frameworks = project.frameworks
    if body.framework_id:
        frameworks = [fw for fw in frameworks if fw.id == body.framework_id]

    report_data = {
        "project": {"id": str(project.id), "name": project.name},
        "generated_by": current_user.email,
        "frameworks": [],
    }

    for fw in frameworks:
        fw_data = {
            "id": str(fw.id),
            "name": fw.name.value,
            "version": fw.version,
            "controls": [],
        }
        for control in fw.controls:
            ctrl_data = {
                "id": str(control.id),
                "control_id_code": control.control_id_code,
                "title": control.title,
                "description": control.description,
                "source_citation": control.source_citation,
                "status": control.status.value,
                "requirements": [
                    {
                        "description": r.description,
                        "testable_condition": r.testable_condition,
                    }
                    for r in control.requirements
                ],
            }
            fw_data["controls"].append(ctrl_data)
        report_data["frameworks"].append(fw_data)

    await log_action(
        db,
        actor_id=current_user.id,
        action="export_report",
        resource_type="report",
        detail={"project_id": str(body.project_id), "format": body.format.value},
    )

    if body.format == ReportFormat.JSON:
        return JSONResponse(content=report_data)

    pdf_bytes = await generate_pdf_report(report_data)
    filename = f"audit_report_{project.name}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
