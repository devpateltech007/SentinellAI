"""API Contract Tests for control endpoints.

Ensures proper response structures and RBAC enforcement.
"""

import pytest
from httpx import AsyncClient
import uuid

from app.models import Control, Project, Framework
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def seeded_control(db_session: AsyncSession) -> Control:
    project = Project(
        id=uuid.uuid4(), name="Test Proj"
    )
    db_session.add(project)
    await db_session.flush()
    
    framework = Framework(
        id=uuid.uuid4(), project_id=project.id, name="HIPAA", version="1.0"
    )
    db_session.add(framework)
    await db_session.flush()
    
    control = Control(
        id=uuid.uuid4(), framework_id=framework.id,
        control_id_code="HIPAA-123",
        title="Test Control", description="Test",
        source_citation="test",
        status="NeedsReview"
    )
    db_session.add(control)
    await db_session.commit()
    await db_session.refresh(control)
    return control


@pytest.mark.asyncio
class TestControlEndpoints:
    async def test_get_control_unauthorized(self, client: AsyncClient):
        """No token -> 401."""
        resp = await client.get("/api/v1/controls/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401

    async def test_get_control_not_found(self, client: AsyncClient, admin_token: str):
        """Valid token, missing resource -> 404."""
        resp = await client.get(
            "/api/v1/controls/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_get_control_success(self, client: AsyncClient, admin_token: str, seeded_control: Control):
        """Valid token -> 200 with control details."""
        resp = await client.get(
            f"/api/v1/controls/{seeded_control.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(seeded_control.id)
        assert data["control_id_code"] == "HIPAA-123"
        assert data["status"] == "NeedsReview"

    async def test_review_control_forbidden_for_developer(self, client: AsyncClient, developer_token: str, seeded_control: Control):
        """Developer role -> 403 on review endpoint."""
        resp = await client.post(
            f"/api/v1/controls/{seeded_control.id}/review",
            headers={"Authorization": f"Bearer {developer_token}"},
            json={"decision": "approve", "justification": "test"},
        )
        assert resp.status_code == 403

    async def test_review_control_success_for_compliance_manager(self, client: AsyncClient, compliance_manager_token: str, seeded_control: Control):
        """Compliance manager -> 200 on review."""
        resp = await client.post(
            f"/api/v1/controls/{seeded_control.id}/review",
            headers={"Authorization": f"Bearer {compliance_manager_token}"},
            json={"decision": "override", "override_status": "Pass", "justification": "Approved manually"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "Pass"

    async def test_status_history_allowed_for_auditor(self, client: AsyncClient, auditor_token: str, seeded_control: Control):
        """Auditor role -> allowed on status-history endpoint."""
        resp = await client.get(
            f"/api/v1/controls/{seeded_control.id}/status-history",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
