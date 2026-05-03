import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.control_status import ControlStatus
from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.services.evidence_engine.normalizer import compute_sha256
from app.workers.evaluation_tasks import _evaluate_control_async


@pytest.mark.asyncio
async def test_tamper_detection_in_evaluation(db_session: AsyncSession):
    # 1. Setup Models
    control_id = uuid.uuid4()

    # We need a project and framework to satisfy foreign keys
    from app.models.framework import Framework, FrameworkName
    from app.models.project import Project

    project = Project(name="Test Project")
    db_session.add(project)
    await db_session.flush()

    framework = Framework(
        project_id=project.id,
        name=FrameworkName.HIPAA,
        version="1.0"
    )
    db_session.add(framework)
    await db_session.flush()

    control = Control(
        id=control_id,
        framework_id=framework.id,
        control_id_code="TAMPER-TEST-1",
        title="Tamper Test Control",
        description="Testing tamper detection",
        source_citation="N/A",
        source_text="N/A",
        status=ControlStatusEnum.PENDING,
        generated_at=datetime.now(timezone.utc),
    )

    evidence_id = uuid.uuid4()
    content = {"message": "Original Evidence"}
    content_str = json.dumps(content, sort_keys=True, default=str)

    evidence = EvidenceItem(
        id=evidence_id,
        source_type=EvidenceSourceType.GITHUB_ACTIONS,
        source_ref="ref",
        content_json=content,
        sha256_hash=compute_sha256(content_str),
    )

    db_session.add(control)
    db_session.add(evidence)
    await db_session.flush()

    ce = ControlEvidence(
        control_id=control_id,
        evidence_id=evidence_id,
    )
    db_session.add(ce)
    await db_session.commit()

    # 2. Run evaluation on intact evidence
    res = await _evaluate_control_async(str(control_id))
    assert res["status"] == "evaluated"

    # 3. Tamper evidence directly in DB
    await db_session.execute(
        text(f"UPDATE evidence_items SET content_json = '{{\"message\": \"Hacked\"}}' WHERE id = '{evidence_id}'")
    )
    await db_session.commit()

    # 4. Re-evaluate - should detect tamper
    res_tamper = await _evaluate_control_async(str(control_id))
    assert res_tamper["status"] == "tamper_detected"
    assert res_tamper["tampered_evidence"] == [str(evidence_id)]

    # 5. Check Control Status
    db_session.expire_all()
    result = await db_session.execute(select(Control).where(Control.id == control_id))
    control_updated = result.scalar_one()
    assert control_updated.status == ControlStatusEnum.NEEDS_REVIEW

    # 6. Check Audit Rationale
    status_result = await db_session.execute(
        select(ControlStatus).where(ControlStatus.control_id == control_id).order_by(ControlStatus.determined_at.desc())
    )
    status_log = status_result.scalars().first()
    assert status_log is not None
    assert status_log.rationale is not None
    assert "INTEGRITY ALERT" in status_log.rationale

    # 7. Fix evidence
    await db_session.execute(
        text(f"UPDATE evidence_items SET content_json = '{{\"message\": \"Original Evidence\"}}' WHERE id = '{evidence_id}'")
    )
    await db_session.commit()

    # 8. Re-evaluate - should pass normally
    res_fixed = await _evaluate_control_async(str(control_id))
    assert res_fixed["status"] == "evaluated"
