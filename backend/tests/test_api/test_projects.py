import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_project(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Test Project"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Project"
    assert "id" in data
    assert data["framework_count"] == 0


@pytest.mark.asyncio
async def test_list_projects(client: AsyncClient, admin_token: str):
    await client.post(
        "/api/v1/projects",
        json={"name": "Project A"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await client.post(
        "/api/v1/projects",
        json={"name": "Project B"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    names = [p["name"] for p in data]
    assert "Project A" in names
    assert "Project B" in names


@pytest.mark.asyncio
async def test_get_project_detail(client: AsyncClient, admin_token: str):
    create = await client.post(
        "/api/v1/projects",
        json={"name": "Detail Project"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Detail Project"
    assert data["frameworks"] == []


@pytest.mark.asyncio
async def test_add_framework(client: AsyncClient, admin_token: str):
    create = await client.post(
        "/api/v1/projects",
        json={"name": "Framework Project"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = create.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project_id}/frameworks",
        json={"name": "HIPAA"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "HIPAA"
    assert data["project_id"] == project_id


@pytest.mark.asyncio
async def test_get_project_not_found(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404
