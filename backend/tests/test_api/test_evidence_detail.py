"""API Contract Tests for evidence endpoints."""

import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timezone

from app.models import EvidenceItem
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def seeded_evidence(db_session: AsyncSession) -> EvidenceItem:
    evidence = EvidenceItem(
        id=uuid.uuid4(),
        source_type="github_code",
        source_ref="https://github.com/test",
        collected_at=datetime.now(timezone.utc),
        sha256_hash="abc123hash",
        content_json={"key": "value"},
        redacted=False,
    )
    db_session.add(evidence)
    await db_session.commit()
    await db_session.refresh(evidence)
    return evidence


@pytest.mark.asyncio
class TestEvidenceEndpoints:
    async def test_get_evidence_unauthorized(self, client: AsyncClient):
        """No token -> 401."""
        resp = await client.get("/api/v1/evidence")
        assert resp.status_code == 401

    async def test_get_evidence_list_success(self, client: AsyncClient, admin_token: str, seeded_evidence: EvidenceItem):
        """Valid token -> 200 with evidence list."""
        resp = await client.get(
            "/api/v1/evidence",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1
        assert data["items"][0]["source_type"] == "github_code"

    async def test_get_evidence_detail_success(self, client: AsyncClient, auditor_token: str, seeded_evidence: EvidenceItem):
        """Auditor token -> 200 with single evidence detail."""
        resp = await client.get(
            f"/api/v1/evidence/{seeded_evidence.id}",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(seeded_evidence.id)
        assert data["sha256_hash"] == "abc123hash"

    async def test_get_evidence_not_found(self, client: AsyncClient, auditor_token: str):
        """Missing evidence -> 404."""
        resp = await client.get(
            f"/api/v1/evidence/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert resp.status_code == 404
