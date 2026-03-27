"""Celery tasks for control evaluation after evidence collection.

Runs the rule-based evaluation engine against controls that have
new evidence, and dispatches failure alerts when controls transition to Fail.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.control_status import ControlStatus
from app.models.evidence import EvidenceItem
from app.services.evaluator.engine import evaluate_control
from app.services.evaluator.status import persist_evaluation
from app.services.alerting import send_failure_alert
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.evaluation_tasks.evaluate_control",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
)
def evaluate_control_task(self, control_id: str) -> dict:
    """Evaluate a single control against its evidence."""
    try:
        return asyncio.get_event_loop().run_until_complete(
            _evaluate_control_async(control_id)
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_evaluate_control_async(control_id))
        finally:
            loop.close()


async def _evaluate_control_async(control_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Control)
            .options(
                selectinload(Control.evidence_links).selectinload(
                    ControlEvidence.evidence
                )
            )
            .where(Control.id == UUID(control_id))
        )
        control = result.scalar_one_or_none()
        if not control:
            return {"status": "error", "message": "Control not found"}

        previous_status = control.status

        evidence_items = []
        for link in control.evidence_links:
            ev = link.evidence
            evidence_items.append(
                {
                    "id": str(ev.id),
                    "source_type": ev.source_type.value,
                    "content_json": ev.content_json,
                }
            )

        eval_result = await evaluate_control(
            control_id=control.id,
            control_id_code=control.control_id_code,
            evidence_items=evidence_items,
        )

        await persist_evaluation(db, eval_result)

        if (
            eval_result.status == "Fail"
            and previous_status != ControlStatusEnum.FAIL
        ):
            try:
                await send_failure_alert(
                    control_id=control.id,
                    control_id_code=control.control_id_code,
                    title=control.title,
                    reason=eval_result.rationale,
                )
            except Exception:
                logger.exception("Failed to send failure alert for %s", control_id)

        await db.commit()
        logger.info(
            "Evaluated control %s: %s -> %s",
            control_id,
            previous_status.value,
            eval_result.status,
        )
        return {
            "status": "evaluated",
            "control_id": control_id,
            "result": eval_result.status,
        }


@celery_app.task(name="app.workers.evaluation_tasks.scheduled_evaluation")
def scheduled_evaluation() -> dict:
    """Periodic task: re-evaluate all controls with evidence."""
    try:
        return asyncio.get_event_loop().run_until_complete(
            _scheduled_evaluation_async()
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_scheduled_evaluation_async())
        finally:
            loop.close()


async def _scheduled_evaluation_async() -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Control.id)
            .join(ControlEvidence)
            .distinct()
        )
        control_ids = [str(row[0]) for row in result.all()]

    dispatched = 0
    for cid in control_ids:
        evaluate_control_task.delay(cid)
        dispatched += 1

    return {"status": "scheduled", "controls_dispatched": dispatched}
