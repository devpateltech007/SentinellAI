"""Rule: Verify that access control / RBAC is configured."""

from __future__ import annotations

APPLICABLE_PATTERNS = ["access", "rbac", "role", "164.312(a)", "164.308(a)(4)", "article 25"]


def check_access_control(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check if configuration evidence shows RBAC or access control is implemented.

    Applies to controls related to access management.
    """
    code_lower = control_id_code.lower()
    if not any(p in code_lower for p in APPLICABLE_PATTERNS):
        return None

    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        raw = str(content).lower()

        if any(kw in raw for kw in ["rbac", "role", "access_control", "iam", "policy"]):
            return {
                "passed": True,
                "reason": f"Access control configuration found in evidence from {evidence.get('source_ref', 'unknown')}",
            }

    return {
        "passed": False,
        "reason": "No access control or RBAC configuration found in collected evidence. "
        "Remediation: Implement role-based access control in your application and infrastructure.",
    }
