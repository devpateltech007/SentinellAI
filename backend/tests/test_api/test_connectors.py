import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_list_connectors(
    client: AsyncClient, admin_token: str, devops_token: str
):
    # Create a project first
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Connector Test Project"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = project.json()["id"]

    # Register connector as devops
    response = await client.post(
        "/api/v1/connectors",
        json={
            "project_id": project_id,
            "source_type": "github_actions",
            "config": {"owner": "acme", "repo": "app"},
            "schedule": "0 */6 * * *",
        },
        headers={"Authorization": f"Bearer {devops_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "github_actions"
    connector_id = data["id"]

    # List connectors
    list_resp = await client.get(
        "/api/v1/connectors",
        headers={"Authorization": f"Bearer {devops_token}"},
    )
    assert list_resp.status_code == 200
    connectors = list_resp.json()
    assert any(c["id"] == connector_id for c in connectors)


@pytest.mark.asyncio
async def test_trigger_connector(
    client: AsyncClient, admin_token: str, devops_token: str
):
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Trigger Test Project"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = project.json()["id"]

    connector = await client.post(
        "/api/v1/connectors",
        json={
            "project_id": project_id,
            "source_type": "github_actions",
            "config": {"owner": "test", "repo": "repo"},
        },
        headers={"Authorization": f"Bearer {devops_token}"},
    )
    connector_id = connector.json()["id"]

    response = await client.post(
        f"/api/v1/connectors/{connector_id}/trigger",
        headers={"Authorization": f"Bearer {devops_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["last_status"] == "triggered"
