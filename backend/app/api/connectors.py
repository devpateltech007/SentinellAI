import os
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.config import settings
from app.middleware.audit_log import log_action
from app.models.connector import Connector
from app.models.user import User, UserRole
from app.schemas.connector import (
    ConnectorCreate,
    ConnectorHealthResponse,
    ConnectorResponse,
    ConnectorStatusResponse,
    ConnectorUpdate,
)

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
    task = collect_evidence.delay(str(connector.id))

    return ConnectorStatusResponse(
        id=connector.id,
        source_type=connector.source_type,
        task_id=str(task.id),
        last_run_at=connector.last_run_at,
        last_status="triggered",
        last_error=connector.last_error,
    )

@router.get("/{connector_id}/health", response_model=ConnectorHealthResponse)
async def check_connector_health(
    connector_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_role(
        UserRole.ADMIN, UserRole.DEVOPS_ENGINEER, UserRole.COMPLIANCE_MANAGER
    )),
):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if connector.source_type in ("github_actions", "github_code"):
        config = connector.config_json
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{config['owner']}/{config['repo']}",
                    headers={"Authorization": f"Bearer {settings.GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"},
                    timeout=10.0,
                )
                return ConnectorHealthResponse(
                    connector_id=connector.id,
                    source_type=connector.source_type,
                    reachable=resp.status_code == 200,
                    rate_limit_remaining=int(resp.headers.get("X-RateLimit-Remaining", 0)),
                    error=None if resp.status_code == 200 else f"HTTP {resp.status_code}: {resp.text[:200]}",
                    checked_at=datetime.now(timezone.utc),
                )
            except httpx.HTTPError as e:
                return ConnectorHealthResponse(
                    connector_id=connector.id,
                    source_type=connector.source_type,
                    reachable=False,
                    error=str(e),
                    checked_at=datetime.now(timezone.utc),
                )
    elif connector.source_type == "iac_config":
        config = connector.config_json
        path = config.get("config_path", "")
        reachable = os.path.exists(path)
        return ConnectorHealthResponse(
            connector_id=connector.id,
            source_type=connector.source_type,
            reachable=reachable,
            error=None if reachable else f"Path '{path}' not found",
            checked_at=datetime.now(timezone.utc),
        )

    return ConnectorHealthResponse(
        connector_id=connector.id,
        source_type=connector.source_type,
        reachable=True,
        checked_at=datetime.now(timezone.utc),
    )


@router.put("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: UUID,
    body: ConnectorUpdate,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DEVOPS_ENGINEER)),
):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if body.config_json is not None:
        connector.config_json = body.config_json
    if body.schedule is not None:
        connector.schedule = body.schedule
    if body.is_active is not None:
        connector.is_active = body.is_active

    await db.commit()
    await db.refresh(connector)

    await log_action(
        db,
        actor_id=current_user.id,
        action="update_connector",
        resource_type="connector",
        resource_id=connector.id,
        detail={"updated_fields": body.model_dump(exclude_unset=True)},
    )
    return ConnectorResponse.model_validate(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DEVOPS_ENGINEER)),
):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    connector.is_active = False
    await db.commit()

    await log_action(
        db,
        actor_id=current_user.id,
        action="delete_connector",
        resource_type="connector",
        resource_id=connector.id,
        detail={"soft_delete": True},
    )
    return None
