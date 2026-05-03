from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.middleware.audit_log import log_action
from app.models.connector import Connector
from app.models.user import User, UserRole
from app.schemas.connector import ConnectorCreate, ConnectorResponse, ConnectorStatusResponse

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_connector(
    body: ConnectorCreate,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.DEVOPS_ENGINEER, UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)),
):
    connector = Connector(
        project_id=body.project_id,
        source_type=body.source_type,
        config_json=body.config,
        schedule=body.schedule,
        created_by=current_user.id,
    )
    db.add(connector)
    await db.flush()
    await db.refresh(connector)

    await log_action(
        db,
        actor_id=current_user.id,
        action="register_connector",
        resource_type="connector",
        resource_id=connector.id,
        detail={"source_type": body.source_type},
    )

    return ConnectorResponse.model_validate(connector)


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.DEVOPS_ENGINEER, UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)
    ),
):
    result = await db.execute(select(Connector).order_by(Connector.created_at.desc()))
    connectors = result.scalars().all()
    return [ConnectorResponse.model_validate(c) for c in connectors]


@router.post("/{connector_id}/trigger", response_model=ConnectorStatusResponse)
async def trigger_connector(
    connector_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.DEVOPS_ENGINEER, UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)),
):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    await log_action(
        db,
        actor_id=current_user.id,
        action="trigger_connector",
        resource_type="connector",
        resource_id=connector.id,
    )

    from app.workers.evidence_tasks import collect_evidence
    collect_evidence.delay(str(connector.id))

    return ConnectorStatusResponse(
        id=connector.id,
        source_type=connector.source_type,
        last_run_at=connector.last_run_at,
        last_status="triggered",
        last_error=connector.last_error,
    )
