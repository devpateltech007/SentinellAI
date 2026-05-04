import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.services.evidence_engine.integrity import (
    EvidenceNotFoundError,
    verify_batch_integrity,
    verify_evidence_integrity,
)
from app.services.evidence_engine.normalizer import compute_sha256


@pytest.mark.asyncio
async def test_evidence_integrity_valid_and_tampered(db_session: AsyncSession):
    evidence_id = uuid.uuid4()
    content = {"original_key": "original_value"}
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
    db_session.expire_all()

    # 1. Verify valid
    result = await verify_evidence_integrity(evidence_id, db_session)
    assert result.integrity_valid is True
    assert result.computed_hash == sha256_hash

    # 2. Tamper directly via raw SQL
    await db_session.execute(
        text("UPDATE evidence_items SET content_json = '{\"tampered\": true}' WHERE id = :id"),
        {"id": evidence_id},
    )
    await db_session.commit()
    db_session.expire_all()

    # 3. Verify invalid
    result_tampered = await verify_evidence_integrity(evidence_id, db_session)
    assert result_tampered.integrity_valid is False
    assert result_tampered.computed_hash != sha256_hash


@pytest.mark.asyncio
async def test_verify_evidence_not_found(db_session: AsyncSession):
    with pytest.raises(EvidenceNotFoundError):
        await verify_evidence_integrity(uuid.uuid4(), db_session)


@pytest.mark.asyncio
async def test_batch_integrity(db_session: AsyncSession):
    items = []
    ids = []
    # Create 2 valid items and 1 tampered item
    for i in range(3):
        e_id = uuid.uuid4()
        content = {f"key_{i}": f"val_{i}"}
        content_str = json.dumps(content, sort_keys=True, default=str)
        items.append(
            EvidenceItem(
                id=e_id,
                source_type=EvidenceSourceType.GITHUB_ACTIONS,
                source_ref=f"ref_{i}",
                content_json=content,
                sha256_hash=compute_sha256(content_str),
            )
        )
        ids.append(e_id)

    db_session.add_all(items)
    await db_session.commit()
    db_session.expire_all()

    # Tamper the 3rd item
    await db_session.execute(
        text("UPDATE evidence_items SET content_json = '{\"tampered\": true}' WHERE id = :id"),
        {"id": ids[2]},
    )
    await db_session.commit()
    db_session.expire_all()

    results = await verify_batch_integrity(ids, db_session)
    assert len(results) == 3

    valid_results = [r for r in results if r.integrity_valid]
    tampered_results = [r for r in results if not r.integrity_valid]

    assert len(valid_results) == 2
    assert len(tampered_results) == 1
    assert tampered_results[0].evidence_id == ids[2]
