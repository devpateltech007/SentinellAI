"""Rule: Verify that system logging / audit logging is enabled."""

from __future__ import annotations

APPLICABLE_PATTERNS = ["audit", "log", "logging", "164.312(b)"]


def check_logging_enabled(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check if logging configuration evidence shows logging is enabled.

    Applies to controls related to audit logging.
    """
    code_lower = control_id_code.lower()
    if not any(p in code_lower for p in APPLICABLE_PATTERNS):
        return None

    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        raw = str(content).lower()

        if "logging" in raw and any(
            val in raw for val in ["true", "enabled", "on", "active"]
        ):
            return {
                "passed": True,
                "reason": f"Logging is enabled per evidence from {evidence.get('source_ref', 'unknown')}",
            }

        if "logging" in raw and any(
            val in raw for val in ["false", "disabled", "off"]
        ):
            return {
                "passed": False,
                "reason": f"Logging is disabled per evidence from {evidence.get('source_ref', 'unknown')}. "
                "Remediation: Enable audit logging in your system configuration.",
            }

    return {
        "passed": False,
        "reason": "No logging configuration found in collected evidence. "
        "Remediation: Ensure audit log configuration is included in your IaC or application config.",
    }
