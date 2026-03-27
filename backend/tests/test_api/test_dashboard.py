import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_summary(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/dashboard/summary",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "pass_count" in data
    assert "fail_count" in data
    assert "total_controls" in data
    assert "evidence_coverage" in data
    assert "recent_failures" in data


@pytest.mark.asyncio
async def test_dashboard_summary_with_project_filter(
    client: AsyncClient, admin_token: str
):
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Dashboard Test"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = project.json()["id"]

    response = await client.get(
        f"/api/v1/dashboard/summary?project_id={project_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_controls"] == 0
