"""Integration tests for the evidence collection → storage → verification pipeline.

Tests the full evidence lifecycle: raw collection → validation → redaction →
normalization → DB persistence → integrity verification.
"""

from datetime import datetime, timezone

from app.services.evidence_engine.base import RawEvidence
from app.services.evidence_engine.github_actions import GitHubActionsConnector
from app.services.evidence_engine.normalizer import normalize_evidence
from app.services.evidence_engine.redaction import REDACTION_PLACEHOLDER, redact_fields

# ---------------------------------------------------------------------------
# Redaction Tests
# ---------------------------------------------------------------------------

class TestRedaction:
    def test_email_redaction(self):
        content = {"author": "dev@company.com", "message": "fix bug"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert REDACTION_PLACEHOLDER in redacted["author"]
        assert redacted["message"] == "fix bug"  # Non-PII unchanged

    def test_ssn_redaction(self):
        content = {"data": "SSN is 123-45-6789"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert "123-45-6789" not in redacted["data"]

    def test_phone_redaction(self):
        content = {"phone": "555-123-4567"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert "555-123-4567" not in redacted["phone"]

    def test_ip_address_redaction(self):
        content = {"server": "192.168.1.100"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert "192.168.1.100" not in redacted["server"]

    def test_no_pii_no_redaction(self):
        content = {"status": "success", "count": 42}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is False
        assert redacted == content

    def test_nested_dict_redaction(self):
        content = {"outer": {"inner": {"email": "user@test.com"}}}
        redacted, _ = redact_fields(content, {"pattern_scan": True})
        assert REDACTION_PLACEHOLDER in redacted["outer"]["inner"]["email"]

    def test_field_level_redaction(self):
        content = {"password": "secret123", "name": "test"}
        redacted, was_redacted = redact_fields(content, {"password": True})
        assert redacted["password"] == REDACTION_PLACEHOLDER
        assert redacted["name"] == "test"
        assert was_redacted is True

    def test_list_with_pii_redacted(self):
        content = {"emails": ["one@test.com", "two@test.com"]}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        for item in redacted["emails"]:
            assert REDACTION_PLACEHOLDER in item

    def test_multiple_pii_types_in_same_value(self):
        content = {"info": "Contact dev@corp.com at 555-111-2222"}
        redacted, was_redacted = redact_fields(content, {"pattern_scan": True})
        assert was_redacted is True
        assert "dev@corp.com" not in redacted["info"]
        assert "555-111-2222" not in redacted["info"]


# ---------------------------------------------------------------------------
# Normalization Tests
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_normalize_with_redaction(self):
        raw = RawEvidence(
            source_type="github_actions",
            source_ref="https://github.com/test/repo/actions/runs/1",
            raw_data={"run_id": 1, "author_email": "dev@corp.com"},
            collected_at=datetime.now(timezone.utc),
        )
        result = normalize_evidence(raw, redaction_config={"pattern_scan": True})
        assert result.redacted is True
        assert result.sha256_hash  # Hash exists
        assert REDACTION_PLACEHOLDER in str(result.content_json)

    def test_normalize_without_redaction(self):
        raw = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"key": "clean_value"},
            collected_at=datetime.now(timezone.utc),
        )
        result = normalize_evidence(raw)
        assert result.redacted is False
        assert result.content_json["key"] == "clean_value"

    def test_normalize_hash_deterministic(self):
        raw = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"a": 1, "b": 2},
            collected_at=datetime.now(timezone.utc),
        )
        r1 = normalize_evidence(raw)
        r2 = normalize_evidence(raw)
        assert r1.sha256_hash == r2.sha256_hash

    def test_normalize_hash_changes_on_different_content(self):
        ts = datetime.now(timezone.utc)
        raw1 = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"key": "value1"}, collected_at=ts,
        )
        raw2 = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"key": "value2"}, collected_at=ts,
        )
        r1 = normalize_evidence(raw1)
        r2 = normalize_evidence(raw2)
        assert r1.sha256_hash != r2.sha256_hash

    def test_normalize_preserves_source_metadata(self):
        ts = datetime.now(timezone.utc)
        raw = RawEvidence(
            source_type="iac_config", source_ref="terraform/main.tf",
            raw_data={"resource": "aws_s3_bucket"}, collected_at=ts,
        )
        result = normalize_evidence(raw)
        assert result.source_type == "iac_config"
        assert result.source_ref == "terraform/main.tf"
        assert result.collected_at == ts

    def test_normalize_auto_assigns_collected_at_when_missing(self):
        raw = RawEvidence(
            source_type="test", source_ref="test",
            raw_data={"x": 1}, collected_at=None,
        )
        result = normalize_evidence(raw)
        assert result.collected_at is not None


# ---------------------------------------------------------------------------
# GitHub Actions Connector Tests (validation only — no network calls)
# ---------------------------------------------------------------------------

class TestGitHubActionsConnector:
    def test_validate_valid_evidence(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions",
            source_ref="https://github.com/test/repo/actions/runs/123",
            raw_data={"run_id": 123, "status": "completed"},
        )
        assert connector.validate(raw) is True

    def test_validate_rejects_missing_run_id(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions", source_ref="https://example.com",
            raw_data={"status": "completed"},  # No run_id
        )
        assert connector.validate(raw) is False

    def test_validate_rejects_wrong_source_type(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="iac_config",  # Wrong type
            source_ref="https://example.com",
            raw_data={"run_id": 123},
        )
        assert connector.validate(raw) is False

    def test_validate_rejects_empty_source_ref(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions", source_ref="",
            raw_data={"run_id": 123},
        )
        assert connector.validate(raw) is False

    def test_normalize_produces_valid_output(self):
        connector = GitHubActionsConnector(owner="test", repo="repo", token="fake")
        raw = RawEvidence(
            source_type="github_actions",
            source_ref="https://github.com/test/repo/actions/runs/123",
            raw_data={"run_id": 123, "status": "completed", "name": "CI"},
            collected_at=datetime.now(timezone.utc),
        )
        result = connector.normalize(raw)
        assert result.sha256_hash
        assert result.source_type == "github_actions"
        assert result.content_json["run_id"] == 123
