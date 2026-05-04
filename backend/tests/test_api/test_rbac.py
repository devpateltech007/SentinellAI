import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_developer_cannot_create_project(client: AsyncClient, developer_token: str):
    """FR-26: Developer role should not be able to create projects."""
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Unauthorized Project"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_developer_cannot_register_connector(client: AsyncClient, developer_token: str):
    """FR-26: Developer role should not be able to register connectors."""
    response = await client.post(
        "/api/v1/connectors",
        json={
            "project_id": "00000000-0000-0000-0000-000000000000",
            "source_type": "github_actions",
            "config": {},
        },
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_auditor_cannot_create_project(client: AsyncClient, auditor_token: str):
    """FR-26: Auditor role should not be able to create projects."""
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Unauthorized Project"},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(client: AsyncClient):
    """FR-27: Requests without JWT are rejected."""
    response = await client.get("/api/v1/dashboard/summary")
    assert response.status_code == 401
