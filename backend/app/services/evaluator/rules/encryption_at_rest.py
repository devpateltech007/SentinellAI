"""Rule: Verify that encryption at rest is configured."""

from __future__ import annotations

from app.services.evaluator.rules.rule_spec import RuleSpec

APPLICABLE_PATTERNS = ["encrypt", "aes", "164.312(a)", "article 32"]


def check_encryption_at_rest(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check if configuration evidence shows encryption at rest is enabled.

    Applies to controls related to data encryption.
    """
    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        raw = str(content).lower()

        if any(kw in raw for kw in ["encrypt", "aes-256", "kms", "sse-s3", "sse-kms"]):
            if any(val in raw for val in ["true", "enabled", "aes"]):
                return {
                    "passed": True,
                    "reason": f"Encryption at rest is enabled per evidence from {evidence.get('source_ref', 'unknown')}",
                }

    return {
        "passed": False,
        "reason": "No encryption-at-rest configuration found in collected evidence. "
        "Remediation: Enable AES-256 encryption for data at rest in your storage configuration.",
    }


RULE_SPEC = RuleSpec(
    name="check_encryption_at_rest",
    description="Verify encryption at rest is enabled in evidence",
    fn=check_encryption_at_rest,
    applicable_control_patterns=APPLICABLE_PATTERNS,
    applicable_source_types=["github_actions", "iac_config", "github_code"],
)
