"""Tests for the redaction middleware in the evidence normalization pipeline.

Verifies that PII/PHI patterns (emails, SSNs, phone numbers, IP addresses)
are correctly redacted before hashing, and that non-PII content passes
through unchanged.
"""

import json

import pytest

from app.services.evidence_engine.base import RawEvidence
from app.services.evidence_engine.normalizer import (
    DEFAULT_REDACTION_CONFIG,
    compute_sha256,
    normalize_evidence,
)
from app.services.evidence_engine.redaction import REDACTION_PLACEHOLDER


@pytest.mark.asyncio
async def test_email_redacted_in_normalized_evidence():
    """Email addresses in raw evidence must be replaced with [REDACTED]."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="https://github.com/acme/app/actions/runs/123",
        raw_data={
            "run_id": 123,
            "status": "completed",
            "commit_author_email": "alice@example.com",
            "commit_author_name": "Alice",
        },
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert result.content_json["commit_author_email"] == REDACTION_PLACEHOLDER
    assert result.content_json["commit_author_name"] == "Alice"
    assert result.content_json["run_id"] == 123
    assert result.content_json["status"] == "completed"
    assert result.redacted is True


@pytest.mark.asyncio
async def test_ssn_redacted():
    """SSN patterns (XXX-XX-XXXX) must be redacted."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"note": "Employee SSN is 123-45-6789"},
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert "123-45-6789" not in result.content_json["note"]
    assert REDACTION_PLACEHOLDER in result.content_json["note"]
    assert result.redacted is True


@pytest.mark.asyncio
async def test_phone_redacted():
    """Phone number patterns must be redacted."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"contact": "Call 555-123-4567 for support"},
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert "555-123-4567" not in result.content_json["contact"]
    assert REDACTION_PLACEHOLDER in result.content_json["contact"]
    assert result.redacted is True


@pytest.mark.asyncio
async def test_ip_address_redacted():
    """IP address patterns must be redacted."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"server": "Deployed to 192.168.1.100"},
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert "192.168.1.100" not in result.content_json["server"]
    assert REDACTION_PLACEHOLDER in result.content_json["server"]
    assert result.redacted is True


@pytest.mark.asyncio
async def test_no_pii_passes_through_unchanged():
    """Content without PII should pass through with redacted=False."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"run_id": 456, "status": "completed", "conclusion": "success"},
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert result.content_json == {"run_id": 456, "status": "completed", "conclusion": "success"}
    assert result.redacted is False


@pytest.mark.asyncio
async def test_hash_seals_redacted_content():
    """The SHA-256 hash must be computed on the REDACTED content, not the original."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"email": "bob@corp.com", "status": "ok"},
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    # Manually compute expected hash from the redacted content
    expected_content = {"email": REDACTION_PLACEHOLDER, "status": "ok"}
    expected_str = json.dumps(expected_content, sort_keys=True, default=str)
    expected_hash = compute_sha256(expected_str)

    assert result.sha256_hash == expected_hash
    assert result.content_json["email"] == REDACTION_PLACEHOLDER


@pytest.mark.asyncio
async def test_multiple_pii_types_redacted():
    """Multiple PII types in a single evidence item must all be redacted."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={
            "author_email": "dev@company.io",
            "note": "SSN: 111-22-3333, Phone: 800.555.1234",
            "server_ip": "10.0.0.1",
            "clean_field": "no PII here",
        },
    )

    result = normalize_evidence(raw, redaction_config=DEFAULT_REDACTION_CONFIG)

    assert result.content_json["author_email"] == REDACTION_PLACEHOLDER
    assert "111-22-3333" not in result.content_json["note"]
    assert "800.555.1234" not in result.content_json["note"]
    assert "10.0.0.1" not in result.content_json["server_ip"]
    assert result.content_json["clean_field"] == "no PII here"
    assert result.redacted is True


@pytest.mark.asyncio
async def test_no_redaction_without_config():
    """When no redaction config is passed, PII should remain untouched."""
    raw = RawEvidence(
        source_type="github_actions",
        source_ref="ref",
        raw_data={"email": "alice@example.com"},
    )

    result = normalize_evidence(raw, redaction_config=None)

    assert result.content_json["email"] == "alice@example.com"
    assert result.redacted is False
