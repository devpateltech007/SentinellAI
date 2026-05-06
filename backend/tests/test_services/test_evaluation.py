"""Integration tests for the rule-based evaluation engine.

Tests each evaluation rule with controlled evidence inputs, and
tests the engine's aggregation + AI-fallback logic.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.evaluator.engine import evaluate_control
from app.services.evaluator.rules.access_control import check_access_control
from app.services.evaluator.rules.audit_logging import check_audit_logging
from app.services.evaluator.rules.encryption_at_rest import check_encryption_at_rest
from app.services.evaluator.rules.incident_response import check_incident_response
from app.services.evaluator.rules.logging_enabled import check_logging_enabled
from app.services.evaluator.rules.transmission_security import check_transmission_security

# ---------------------------------------------------------------------------
# Access Control Rule
# ---------------------------------------------------------------------------

class TestAccessControlRule:
    def test_pass_when_rbac_present(self):
        evidence = [{"content_json": {"access_control": "rbac_enabled", "iam": True},
                      "source_ref": "test.tf"}]
        result = check_access_control("HIPAA-AC-001", evidence)
        assert result is not None
        assert result["passed"] is True

    def test_pass_with_policy_keyword(self):
        evidence = [{"content_json": {"policy": "allow-list"}, "source_ref": "iam.tf"}]
        result = check_access_control("HIPAA-164.312(a)-001", evidence)
        assert result["passed"] is True

    def test_fail_when_no_access_control(self):
        evidence = [{"content_json": {"database": "postgres"}, "source_ref": "db.tf"}]
        result = check_access_control("HIPAA-AC-001", evidence)
        assert result is not None
        assert result["passed"] is False
        assert "Remediation" in result["reason"]


# ---------------------------------------------------------------------------
# Encryption at Rest Rule
# ---------------------------------------------------------------------------

class TestEncryptionRule:
    def test_pass_when_aes_enabled(self):
        evidence = [{"content_json": {"encryption": "AES256", "enabled": True},
                      "source_ref": "s3.tf"}]
        result = check_encryption_at_rest("HIPAA-SC-002-encrypt", evidence)
        assert result["passed"] is True

    def test_pass_when_kms_enabled(self):
        evidence = [{"content_json": {"kms": "aws/key", "encrypt": True},
                      "source_ref": "rds.tf"}]
        result = check_encryption_at_rest("HIPAA-164.312(a)-encrypt", evidence)
        assert result["passed"] is True

    def test_fail_when_no_encryption(self):
        evidence = [{"content_json": {"storage": "s3"}, "source_ref": "s3.tf"}]
        result = check_encryption_at_rest("HIPAA-SC-002-encrypt", evidence)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Logging Enabled Rule
# ---------------------------------------------------------------------------

class TestLoggingRule:
    def test_pass_when_logging_enabled(self):
        evidence = [{"content_json": {"logging": True, "enabled": True},
                      "source_ref": "main.tf"}]
        result = check_logging_enabled("HIPAA-AU-001-log", evidence)
        assert result["passed"] is True

    def test_fail_when_logging_disabled(self):
        evidence = [{"content_json": {"logging": "disabled", "status": "off"},
                      "source_ref": "main.tf"}]
        result = check_logging_enabled("HIPAA-AU-001-log", evidence)
        assert result["passed"] is False

    def test_fail_when_no_logging_config(self):
        evidence = [{"content_json": {"compute": "ec2"}, "source_ref": "main.tf"}]
        result = check_logging_enabled("HIPAA-AU-001-log", evidence)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Audit Logging Rule
# ---------------------------------------------------------------------------

class TestAuditLoggingRule:
    def test_pass_with_cloudtrail_and_retention(self):
        evidence = [{"content_json": {"cloudtrail": "enabled", "retention_in_days": 365},
                      "source_type": "iac_config", "source_ref": "audit.tf"}]
        result = check_audit_logging("HIPAA-164.312(b)-001", evidence)
        assert result["passed"] is True
        assert "CloudTrail" in result["reason"]

    def test_fail_with_only_one_indicator(self):
        evidence = [{"content_json": {"cloudtrail": "enabled"},
                      "source_type": "iac_config", "source_ref": "audit.tf"}]
        result = check_audit_logging("HIPAA-164.312(b)-001", evidence)
        assert result["passed"] is False
        assert "Partial" in result["reason"]

    def test_fail_with_no_indicators(self):
        evidence = [{"content_json": {"storage": "s3"},
                      "source_type": "iac_config", "source_ref": "s3.tf"}]
        result = check_audit_logging("HIPAA-164.312(b)-001", evidence)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Transmission Security Rule
# ---------------------------------------------------------------------------

class TestTransmissionSecurityRule:
    def test_pass_with_tls_12(self):
        evidence = [{"content_json": {"ssl_policy": "TLSv1.2"},
                      "source_type": "iac_config", "source_ref": "lb.tf"}]
        result = check_transmission_security("HIPAA-164.312(e)-001", evidence)
        assert result["passed"] is True

    def test_fail_with_outdated_tls(self):
        evidence = [{"content_json": {"ssl_policy": "TLSv1.0"},
                      "source_type": "iac_config", "source_ref": "lb.tf"}]
        result = check_transmission_security("HIPAA-164.312(e)-001", evidence)
        assert result["passed"] is False
        assert "Outdated" in result["reason"]

    def test_fail_with_no_tls_config(self):
        evidence = [{"content_json": {"server": "nginx"},
                      "source_type": "iac_config", "source_ref": "web.tf"}]
        result = check_transmission_security("HIPAA-164.312(e)-001", evidence)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Incident Response Rule
# ---------------------------------------------------------------------------

class TestIncidentResponseRule:
    def test_pass_with_security_md_and_scanner(self):
        evidence = [{"content_json": {"path": "SECURITY.md", "trivy": "enabled"},
                      "source_type": "github_code", "source_ref": "repo"}]
        result = check_incident_response("HIPAA-Incident-001", evidence)
        assert result["passed"] is True

    def test_fail_with_only_security_md(self):
        evidence = [{"content_json": {"path": "SECURITY.md"},
                      "source_type": "github_code", "source_ref": "repo"}]
        result = check_incident_response("HIPAA-Incident-001", evidence)
        assert result["passed"] is False
        assert "Partial" in result["reason"]


# ---------------------------------------------------------------------------
# Evaluation Engine (aggregation + AI fallback)
# ---------------------------------------------------------------------------

class TestEvaluationEngine:
    @pytest.mark.asyncio
    async def test_no_evidence_returns_needs_review(self):
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-AC-001",
            evidence_items=[],
        )
        assert result.status == "NeedsReview"
        assert "No evidence" in result.rationale

    @pytest.mark.asyncio
    async def test_passing_evidence_returns_pass(self):
        evidence = [{"id": str(uuid.uuid4()), "source_type": "iac_config",
                      "content_json": {"access_control": "rbac", "iam": "enabled"}}]
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-access-001",
            evidence_items=evidence,
        )
        assert result.status == "Pass"

    @pytest.mark.asyncio
    async def test_failing_evidence_returns_fail(self):
        evidence = [{"id": str(uuid.uuid4()), "source_type": "iac_config",
                      "content_json": {"storage": "s3"}}]
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-SC-encrypt-001",
            evidence_items=evidence,
        )
        assert result.status == "Fail"
        assert "Remediation" in result.rationale

    @pytest.mark.asyncio
    async def test_unmatched_control_returns_needs_review(self):
        evidence = [{"id": str(uuid.uuid4()), "source_type": "iac_config",
                      "content_json": {"something": "unrelated"}}]
        with patch("app.services.evaluator.ai_rule_suggest.settings.OPENAI_API_KEY", new=None):
            result = await evaluate_control(
                control_id=uuid.uuid4(), control_id_code="HIPAA-UNKNOWN-999",
                evidence_items=evidence,
            )
        assert result.status == "NeedsReview"

    @pytest.mark.asyncio
    async def test_evidence_ids_captured(self):
        eid = str(uuid.uuid4())
        evidence = [{"id": eid, "source_type": "iac_config",
                      "content_json": {"access_control": "rbac"}}]
        result = await evaluate_control(
            control_id=uuid.uuid4(), control_id_code="HIPAA-AC-001",
            evidence_items=evidence,
        )
        assert uuid.UUID(eid) in result.evidence_ids
