"""Rule: Verify that encryption at rest is configured."""

from __future__ import annotations

APPLICABLE_PATTERNS = ["encrypt", "aes", "164.312(a)", "164.312(e)", "article 32"]


def check_encryption_at_rest(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check if configuration evidence shows encryption at rest is enabled.

    Applies to controls related to data encryption.
    """
    code_lower = control_id_code.lower()
    if not any(p in code_lower for p in APPLICABLE_PATTERNS):
        return None

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
