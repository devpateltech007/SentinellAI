import pytest
import asyncio
from uuid import uuid4
from unittest.mock import patch

from app.services.evaluator.loader import load_rules_from_directory
from app.services.evaluator.engine import evaluate_control

@pytest.mark.asyncio
async def test_loader_discovers_all_rules():
    rules = load_rules_from_directory()
    rule_names = {r.name for r in rules}
    assert "check_access_control" in rule_names
    assert "check_audit_logging" in rule_names
    assert "check_encryption_at_rest" in rule_names
    assert "check_incident_response" in rule_names
    assert "check_logging_enabled" in rule_names
    assert "check_transmission_security" in rule_names
    assert len(rule_names) == 6

@pytest.mark.asyncio
async def test_loader_handles_exceptions(tmp_path):
    # Create a dummy rule directory
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    
    # Create a valid rule (using one of our actual rules by content or just a dummy file is tricky,
    # let's just mock importlib to raise an exception for a specific module name).
    # Since load_rules_from_directory catches exceptions, we can just test it directly 
    # without creating a full dummy directory by mocking `importlib.import_module`.
    with patch("app.services.evaluator.loader.importlib.import_module") as mock_import:
        mock_import.side_effect = Exception("Mocked error")
        # Should not raise exception
        rules = load_rules_from_directory()
        # It shouldn't crash, and will return whatever it successfully loaded
        # Since we mocked importlib, it won't load anything if we don't handle side_effect
        # appropriately, but the key is that it doesn't crash.
        assert isinstance(rules, list)

@pytest.mark.asyncio
async def test_transmission_security_overlap():
    control_id = uuid4()
    control_id_code = "HIPAA-164.312(e)"
    evidence_items = [
        {
            "id": str(uuid4()),
            "source_type": "iac_config",
            "content_json": {"ssl_policy": "TLSv1.2"}
        }
    ]
    # Evaluate with the engine to ensure encryption_at_rest doesn't falsely fail this
    result = await evaluate_control(control_id, control_id_code, evidence_items)
    # Transmission rule passes. Encryption at rest shouldn't match.
    assert result.status == "Pass"
    assert "TLS 1.2 policy configured" in result.rationale

@pytest.mark.asyncio
async def test_audit_logging_overlap():
    control_id = uuid4()
    control_id_code = "HIPAA-164.312(b)"
    evidence_items = [
        {
            "id": str(uuid4()),
            "source_type": "iac_config",
            "content_json": {"cloudtrail": "enabled", "retention_in_days": 365}
        }
    ]
    # Audit logging rule passes. Legacy logging shouldn't falsely fail this.
    result = await evaluate_control(control_id, control_id_code, evidence_items)
    assert result.status == "Pass"
    assert "CloudTrail" in result.rationale

@pytest.mark.asyncio
async def test_incident_response_evaluation():
    control_id = uuid4()
    control_id_code = "HIPAA-Incident-001"
    evidence_items = [
        {
            "id": str(uuid4()),
            "source_type": "github_code",
            "content_json": {"path": "SECURITY.md", "trivy": "enabled"}
        }
    ]
    result = await evaluate_control(control_id, control_id_code, evidence_items)
    assert result.status == "Pass"

@pytest.mark.asyncio
async def test_ai_fallback_no_api_key():
    control_id = uuid4()
    control_id_code = "HIPAA-BA-001"
    evidence_items = [
        {
            "id": str(uuid4()),
            "source_type": "github_actions",
            "content_json": {"steps": ["checkout"]}
        }
    ]
    with patch("app.services.evaluator.ai_rule_suggest.settings.OPENAI_API_KEY", new=None):
        result = await evaluate_control(control_id, control_id_code, evidence_items)
        assert result.status == "NeedsReview"
        assert "No automated evaluation rule exists" in result.rationale

@pytest.mark.asyncio
async def test_ai_fallback_empty_content():
    control_id = uuid4()
    control_id_code = "HIPAA-BA-001"
    evidence_items = [
        {
            "id": str(uuid4()),
            "source_type": "github_actions",
            "content_json": {"steps": ["checkout"]}
        }
    ]
    
    # Mock AsyncOpenAI
    class MockChoice:
        class MockMessage:
            content = None
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    class MockCompletions:
        async def create(self, **kwargs):
            return MockResponse()

    class MockChat:
        completions = MockCompletions()

    class MockClient:
        chat = MockChat()

    with patch("app.services.evaluator.ai_rule_suggest.settings.OPENAI_API_KEY", new="dummy"), \
         patch("app.services.evaluator.ai_rule_suggest.AsyncOpenAI", return_value=MockClient()):
        
        result = await evaluate_control(control_id, control_id_code, evidence_items)
        assert result.status == "NeedsReview"
        # Since it raised ValueError due to empty content, it gets caught and returns the fallback message
        assert "Manual review required" in result.rationale
