"""Evidence normalization and integrity hashing.

Transforms raw evidence artifacts into the platform's internal schema,
computes SHA-256 hashes for integrity verification (NFR-03), and
delegates PII/PHI redaction before storage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from app.services.evidence_engine.base import NormalizedEvidence, RawEvidence
from app.services.evidence_engine.redaction import redact_fields


def compute_sha256(content: str) -> str:
    """Compute SHA-256 hash of content for integrity verification."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_evidence(
    raw: RawEvidence,
    redaction_config: dict | None = None,
) -> NormalizedEvidence:
    """Normalize a raw evidence artifact into the platform schema.

    Applies PII/PHI field-level redaction if a redaction config is provided,
    then computes the SHA-256 hash on the final (potentially redacted) content.
    """
    content = raw.raw_data.copy()

    redacted = False
    if redaction_config:
        content, redacted = redact_fields(content, redaction_config)

    content_str = json.dumps(content, sort_keys=True, default=str)
    sha256 = compute_sha256(content_str)

    return NormalizedEvidence(
        source_type=raw.source_type,
        source_ref=raw.source_ref,
        content_json=content,
        sha256_hash=sha256,
        collected_at=raw.collected_at or datetime.now(timezone.utc),
        redacted=redacted,
    )
