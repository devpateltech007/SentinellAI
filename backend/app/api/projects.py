from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_role
from app.middleware.audit_log import log_action
from app.models.control import Control, ControlStatusEnum
from app.models.framework import Framework
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.control import ControlResponse
from app.schemas.framework import FrameworkCreate, FrameworkResponse
from app.schemas.project import (
    FrameworkSummary,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: ProjectCreate,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)),
):
    project = Project(name=body.name, org_id=current_user.org_id)
    db.add(project)
    await db.flush()
    await db.refresh(project)

    await log_action(
        db,
        actor_id=current_user.id,
        action="create",
        resource_type="project",
        resource_id=project.id,
        detail={"name": body.name},
    )

    return ProjectResponse(
        id=project.id,
        name=project.name,
        org_id=project.org_id,
        created_at=project.created_at,
        framework_count=0,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: DbSession,
    current_user: CurrentUser,
):
    query = select(Project).options(selectinload(Project.frameworks))
    if current_user.org_id:
        query = query.where(Project.org_id == current_user.org_id)
    query = query.order_by(Project.created_at.desc())

    result = await db.execute(query)
    projects = result.scalars().all()

    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            org_id=p.org_id,
            created_at=p.created_at,
            framework_count=len(p.frameworks),
        )
        for p in projects
    ]


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.frameworks).selectinload(Framework.controls))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    framework_summaries = []
    for fw in project.frameworks:
        controls = fw.controls
        framework_summaries.append(
            FrameworkSummary(
                id=fw.id,
                name=fw.name.value,
                version=fw.version,
                control_count=len(controls),
                pass_count=sum(1 for c in controls if c.status == ControlStatusEnum.PASS),
                fail_count=sum(1 for c in controls if c.status == ControlStatusEnum.FAIL),
                needs_review_count=sum(1 for c in controls if c.status == ControlStatusEnum.NEEDS_REVIEW),
            )
        )

    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        org_id=project.org_id,
        created_at=project.created_at,
        framework_count=len(project.frameworks),
        frameworks=framework_summaries,
    )


@router.post(
    "/{project_id}/frameworks",
    response_model=FrameworkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_framework(
    project_id: UUID,
    body: FrameworkCreate,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    framework = Framework(
        project_id=project_id,
        name=body.name,
    )
    db.add(framework)
    await db.flush()
    await db.refresh(framework)

    await log_action(
        db,
        actor_id=current_user.id,
        action="add_framework",
        resource_type="framework",
        resource_id=framework.id,
        detail={"project_id": str(project_id), "framework": body.name.value},
    )

    from app.workers.evidence_tasks import generate_controls_for_framework
    generate_controls_for_framework.delay(str(framework.id))

    return FrameworkResponse(
        id=framework.id,
        project_id=framework.project_id,
        name=framework.name,
        version=framework.version,
        doc_hash=framework.doc_hash,
        ingested_at=framework.ingested_at,
        created_at=framework.created_at,
        control_count=0,
        status_summary={},
    )


@router.get(
    "/{project_id}/frameworks/{framework_id}/controls",
    response_model=list[ControlResponse],
)
async def list_controls(
    project_id: UUID,
    framework_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.project_id == project_id,
        )
    )
    framework = result.scalar_one_or_none()
    if not framework:
        raise HTTPException(status_code=404, detail="Framework not found")

    controls_result = await db.execute(
        select(Control)
        .where(Control.framework_id == framework_id)
        .order_by(Control.control_id_code)
    )
    controls = controls_result.scalars().all()
    return [ControlResponse.model_validate(c) for c in controls]
