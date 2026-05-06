"""Rule: Verify that access control / RBAC is configured."""

from __future__ import annotations

from app.services.evaluator.rules.rule_spec import RuleSpec

APPLICABLE_PATTERNS = ["access", "rbac", "role", "164.312(a)", "164.308(a)(4)", "article 25"]


def check_access_control(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check if configuration evidence shows RBAC or access control is implemented.

    Applies to controls related to access management.
    """
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


RULE_SPEC = RuleSpec(
    name="check_access_control",
    description="Verify RBAC or access control is configured in evidence",
    fn=check_access_control,
    applicable_control_patterns=APPLICABLE_PATTERNS,
    applicable_source_types=["github_actions", "iac_config", "github_code"],
)
