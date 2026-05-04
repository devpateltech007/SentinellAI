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


@pytest.mark.asyncio
async def test_verify_evidence(client: AsyncClient, admin_token: str, db_session):
    import json
    import uuid

    from sqlalchemy import text

    from app.models.evidence import EvidenceItem, EvidenceSourceType
    from app.services.evidence_engine.normalizer import compute_sha256

    # 1. Setup evidence
    evidence_id = uuid.uuid4()
    content = {"status": "ok"}
    content_str = json.dumps(content, sort_keys=True, default=str)
    sha256_hash = compute_sha256(content_str)

    item = EvidenceItem(
        id=evidence_id,
        source_type=EvidenceSourceType.GITHUB_ACTIONS,
        source_ref="test_ref",
        content_json=content,
        sha256_hash=sha256_hash,
    )
    db_session.add(item)
    await db_session.commit()

    # 2. Verify via API
    response = await client.get(
        f"/api/v1/evidence/{evidence_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["integrity_valid"] is True
    assert data["computed_hash"] == sha256_hash

    # 3. Tamper via raw SQL
    await db_session.execute(
        text(f"UPDATE evidence_items SET content_json = '{{\"status\": \"hacked\"}}' WHERE id = '{evidence_id}'")
    )
    await db_session.commit()
    db_session.expire_all()

    # 4. Re-verify via API
    response_tampered = await client.get(
        f"/api/v1/evidence/{evidence_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response_tampered.status_code == 200
    data_tampered = response_tampered.json()
    assert data_tampered["integrity_valid"] is False

    # 5. Check audit logs
    from sqlalchemy import select

    from app.models.audit_log import AuditLog
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.resource_id == evidence_id))).scalars().all()
    assert len(logs) == 2
    assert logs[0].action == "verify_evidence"
    assert logs[0].detail_json["integrity_valid"] is True
    assert logs[1].action == "verify_evidence"
    assert logs[1].detail_json["integrity_valid"] is False


@pytest.mark.asyncio
async def test_verify_evidence_forbidden_for_developer(client: AsyncClient, developer_token: str, db_session):
    import uuid
    evidence_id = uuid.uuid4()
    response = await client.get(
        f"/api/v1/evidence/{evidence_id}/verify",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_evidence_list_includes_redacted_flag(client: AsyncClient, admin_token: str, db_session):
    import uuid

    from app.models.evidence import EvidenceItem, EvidenceSourceType

    # 1. Setup evidence with redacted=True
    evidence_id = uuid.uuid4()
    item = EvidenceItem(
        id=evidence_id,
        source_type=EvidenceSourceType.GITHUB_ACTIONS,
        source_ref="test_ref_redacted",
        content_json={"email": "[REDACTED]"},
        sha256_hash="fakehash",
        redacted=True,
    )
    db_session.add(item)
    await db_session.commit()

    # 2. Check list API
    response = await client.get(
        "/api/v1/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Find our item
    found_item = next((i for i in data["items"] if i["id"] == str(evidence_id)), None)
    assert found_item is not None
    assert found_item["redacted"] is True

