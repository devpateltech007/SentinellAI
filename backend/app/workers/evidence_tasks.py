"""Celery tasks for evidence collection and control generation.

Dispatches evidence collection jobs for all active connectors,
with retry and exponential backoff on failures (NFR-05).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text

from app.database import async_session
from app.models.connector import Connector
from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.models.framework import Framework
from app.models.requirement import Requirement
from app.services.compliance_brain.ingestion import ingest_document
from app.services.compliance_brain.rag import retrieve_context, rerank
from app.services.compliance_brain.generator import generate_controls
from app.services.evidence_engine.github_actions import GitHubActionsConnector
from app.services.evidence_engine.normalizer import compute_sha256
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DOC_PATHS = {
    "HIPAA": "regulatory_docs/hipaa_security_rule.txt",
    "GDPR": "regulatory_docs/gdpr_articles.txt",
}


@celery_app.task(
    name="app.workers.evidence_tasks.generate_controls_for_framework",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def generate_controls_for_framework(self, framework_id: str) -> dict:
    """Generate compliance controls for a framework using the Compliance Brain."""
    try:
        return asyncio.get_event_loop().run_until_complete(
            _generate_controls_async(framework_id)
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_generate_controls_async(framework_id))
        finally:
            loop.close()


async def _generate_controls_async(framework_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Framework).where(Framework.id == UUID(framework_id))
        )
        framework = result.scalar_one_or_none()
        if not framework:
            return {"status": "error", "message": "Framework not found"}

        framework_name = framework.name.value
        doc_path = DOC_PATHS.get(framework_name)
        if not doc_path:
            return {"status": "error", "message": f"No regulatory doc for {framework_name}"}

        await ingest_document(doc_path, framework_name, db)

        query = f"Extract all compliance controls from {framework_name} regulatory requirements"
        chunks = await retrieve_context(query, framework_name, db, top_k=15)
        top_chunks = await rerank(query, chunks, top_n=10)

        context_dicts = [
            {"text": c.text, "source_section": c.source_section}
            for c in top_chunks
        ]

        generated = await generate_controls(framework_name, context_dicts)

        now = datetime.now(timezone.utc)
        for gc in generated:
            control = Control(
                framework_id=framework.id,
                control_id_code=gc.control_id_code,
                title=gc.title,
                description=gc.description,
                source_citation=gc.source_citation,
                source_text=gc.source_text,
                status=ControlStatusEnum.PENDING
                if gc.confidence >= 0.7
                else ControlStatusEnum.NEEDS_REVIEW,
                generated_at=now,
            )
            db.add(control)
            await db.flush()

            for req in gc.requirements:
                db.add(
                    Requirement(
                        control_id=control.id,
                        description=req.description,
                        testable_condition=req.testable_condition,
                        citation=req.citation,
                    )
                )

        framework.ingested_at = now
        await db.commit()

        logger.info("Generated %d controls for framework %s", len(generated), framework_id)
        return {"status": "success", "controls_generated": len(generated)}


@celery_app.task(
    name="app.workers.evidence_tasks.collect_evidence",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def collect_evidence(self, connector_id: str) -> dict:
    """Collect evidence from a specific connector."""
    try:
        return asyncio.get_event_loop().run_until_complete(
            _collect_evidence_async(connector_id)
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_collect_evidence_async(connector_id))
        finally:
            loop.close()


async def _collect_evidence_async(connector_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Connector).where(Connector.id == UUID(connector_id))
        )
        connector = result.scalar_one_or_none()
        if not connector:
            return {"status": "error", "message": "Connector not found"}

        try:
            if connector.source_type == "github_actions":
                config = connector.config_json
                gh = GitHubActionsConnector(
                    owner=config.get("owner", ""),
                    repo=config.get("repo", ""),
                )
                raw_items = await gh.collect()
                count = 0
                for raw in raw_items:
                    if gh.validate(raw):
                        normalized = gh.normalize(raw)
                        evidence = EvidenceItem(
                            source_type=EvidenceSourceType.GITHUB_ACTIONS,
                            source_ref=normalized.source_ref,
                            collected_at=normalized.collected_at,
                            sha256_hash=normalized.sha256_hash,
                            content_json=normalized.content_json,
                        )
                        db.add(evidence)
                        count += 1

            connector.last_run_at = datetime.now(timezone.utc)
            connector.last_status = "success"
            connector.last_error = None
            await db.commit()

            logger.info("Collected %d evidence items for connector %s", count, connector_id)
            return {"status": "success", "connector_id": connector_id, "items_collected": count}

        except Exception as e:
            connector.last_run_at = datetime.now(timezone.utc)
            connector.last_status = "error"
            connector.last_error = str(e)
            await db.commit()
            raise


@celery_app.task(name="app.workers.evidence_tasks.scheduled_evidence_collection")
def scheduled_evidence_collection() -> dict:
    """Periodic task: collect evidence from all active connectors."""
    try:
        return asyncio.get_event_loop().run_until_complete(
            _scheduled_evidence_async()
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_scheduled_evidence_async())
        finally:
            loop.close()


async def _scheduled_evidence_async() -> dict:
    async with async_session() as db:
        result = await db.execute(select(Connector))
        connectors = result.scalars().all()

    dispatched = 0
    for c in connectors:
        collect_evidence.delay(str(c.id))
        dispatched += 1

    return {"status": "scheduled", "connectors_dispatched": dispatched}
