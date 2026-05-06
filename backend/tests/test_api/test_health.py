import pytest
from httpx import AsyncClient
from unittest.mock import patch

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    # Mock celery ping to return true so the health check passes without a real worker
    with patch("app.workers.celery_app.celery_app.control.inspect") as mock_inspect:
        mock_inspect.return_value.ping.return_value = {"celery@worker": {"ok": "pong"}}
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "sentinellai"
