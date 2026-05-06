import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_export_json_report(client: AsyncClient, admin_token: str):
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Report Test"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = project.json()["id"]

    response = await client.post(
        "/api/v1/reports/export",
        json={"project_id": project_id, "format": "json"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["project"]["name"] == "Report Test"
    assert "frameworks" in data

    reports_response = await client.get(
        "/api/v1/reports",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reports_response.status_code == 200
    reports = reports_response.json()
    assert len(reports) >= 1
    assert reports[0]["format"] == "json"


@pytest.mark.asyncio
async def test_export_report_project_not_found(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/reports/export",
        json={
            "project_id": "00000000-0000-0000-0000-000000000000",
            "format": "json",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_oscal_report(client: AsyncClient, admin_token: str):
    project = await client.post(
        "/api/v1/projects",
        json={"name": "OSCAL Report Test"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    project_id = project.json()["id"]

    response = await client.post(
        "/api/v1/reports/export/oscal",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "uuid" in data
    assert "metadata" in data
    assert "results" in data
