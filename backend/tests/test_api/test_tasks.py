from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stream_task_status_unauthorized(client: AsyncClient):
    # Missing token entirely
    response = await client.get("/api/v1/tasks/some-task-id/stream")
    assert response.status_code == 401

    # Invalid token
    response = await client.get("/api/v1/tasks/some-task-id/stream?token=invalid_token")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_stream_task_status_authorized_query_token(client: AsyncClient, devops_token: str):
    token = devops_token

    # Mock celery task to return a terminal state immediately to prevent infinite stream
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.result = {"items_collected": 5}

    with patch("app.api.tasks.celery_app.AsyncResult", return_value=mock_result):
        # Make request with token as query param
        async with client.stream("GET", f"/api/v1/tasks/test-task-id/stream?token={token}") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # Read the first event
            content = await response.aread()
            text = content.decode("utf-8")
            assert "data:" in text
            assert "SUCCESS" in text
            assert "items_collected" in text

@pytest.mark.asyncio
async def test_stream_task_status_authorized_header(client: AsyncClient, devops_token: str):
    token = devops_token

    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.result = {"items_collected": 5}

    with patch("app.api.tasks.celery_app.AsyncResult", return_value=mock_result):
        # Make request with token as Authorization header
        async with client.stream("GET", "/api/v1/tasks/test-task-id/stream", headers={"Authorization": f"Bearer {token}"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # Read the first event
            content = await response.aread()
            text = content.decode("utf-8")
            assert "data:" in text
            assert "SUCCESS" in text
            assert "items_collected" in text
