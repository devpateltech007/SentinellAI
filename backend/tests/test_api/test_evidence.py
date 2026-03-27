import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_evidence_empty(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_evidence_with_filter(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/evidence?source_type=github_actions&page=1&size=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


@pytest.mark.asyncio
async def test_get_evidence_not_found(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/evidence/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404
