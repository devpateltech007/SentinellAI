import asyncio
import uuid
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.models.control_status import ControlStatus
from app.services.evidence_engine.normalizer import compute_sha256
from app.workers.evaluation_tasks import _evaluate_control_async


async def seed_data(db: AsyncSession):
    control_id = uuid.uuid4()
    control = Control(
        id=control_id,
        framework_id=uuid.uuid4(),  # Mock framework ID, foreign key constraint might fail if we don't have it.
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
        source_ref="https://github.com/acme/repo/run/1",
        content_json=content,
        sha256_hash=compute_sha256(content_str),
        collected_at=datetime.now(timezone.utc),
    )

    # We need a project to create framework. Wait, framework isn't necessary for control if we bypass FK or if we mock it?
    # Actually, let's insert raw using text() to bypass FKs if needed, or just create Project + Framework.
    project_id = uuid.uuid4()
    await db.execute(text(f"INSERT INTO projects (id, name, created_at, updated_at) VALUES ('{project_id}', 'Test Project', NOW(), NOW())"))
    
    framework_id = uuid.uuid4()
    await db.execute(text(f"INSERT INTO frameworks (id, project_id, name, version, status, is_custom, created_at, updated_at) VALUES ('{framework_id}', '{project_id}', 'SOC2', '1.0', 'active', false, NOW(), NOW())"))
    
    control.framework_id = framework_id

    db.add(control)
    db.add(evidence)
    await db.flush()

    ce = ControlEvidence(
        control_id=control_id,
        evidence_id=evidence_id,
    )
    db.add(ce)
    await db.commit()
    
    return str(control_id), str(evidence_id)


async def run():
    async with async_session() as db:
        print("Seeding DB...")
        control_id, evidence_id = await seed_data(db)
        
        print("1. Running evaluation on intact evidence...")
        res = await _evaluate_control_async(control_id)
        print("Result:", res)
        
        # Verify status is not NeedsReview (probably Fail/Pass based on LLM mock or error if LLM isn't mocked)
        
        print("2. Tampering evidence...")
        await db.execute(text(f"UPDATE evidence_items SET content_json = '{{\"message\": \"Hacked\"}}' WHERE id = '{evidence_id}'"))
        await db.commit()
        
        print("3. Re-evaluating control...")
        res = await _evaluate_control_async(control_id)
        print("Result:", res)
        assert res["status"] == "tamper_detected"
        assert res["tampered_evidence"] == [evidence_id]
        
        # Verify DB status
        result = await db.execute(select(Control).where(Control.id == uuid.UUID(control_id)))
        control = result.scalar_one()
        print("Control status:", control.status)
        assert control.status == ControlStatusEnum.NEEDS_REVIEW
        
        result = await db.execute(select(ControlStatus).where(ControlStatus.control_id == uuid.UUID(control_id)).order_by(ControlStatus.evaluated_at.desc()))
        status_log = result.scalars().first()
        print("Rationale:", status_log.rationale)
        assert "INTEGRITY ALERT" in status_log.rationale
        
        print("4. Fixing evidence...")
        content = {"message": "Original Evidence"}
        content_str = json.dumps(content, sort_keys=True, default=str)
        orig_hash = compute_sha256(content_str)
        await db.execute(text(f"UPDATE evidence_items SET content_json = '{{\"message\": \"Original Evidence\"}}', sha256_hash = '{orig_hash}' WHERE id = '{evidence_id}'"))
        await db.commit()
        
        print("5. Re-evaluating fixed control...")
        res = await _evaluate_control_async(control_id)
        print("Result:", res)
        
        result = await db.execute(select(ControlStatus).where(ControlStatus.control_id == uuid.UUID(control_id)).order_by(ControlStatus.evaluated_at.desc()))
        statuses = result.scalars().all()
        # Verify tamper history is preserved
        tamper_events = [s for s in statuses if "INTEGRITY ALERT" in s.rationale]
        assert len(tamper_events) > 0
        print("Tamper event preserved in history:", bool(tamper_events))

        print("Done!")

if __name__ == "__main__":
    asyncio.run(run())
