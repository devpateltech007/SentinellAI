"""Rule: Verify audit-grade logging infrastructure is configured."""

from __future__ import annotations

from app.services.evaluator.rules.rule_spec import RuleSpec

APPLICABLE_PATTERNS = ["audit", "164.312(b)", "examine activity", "record"]

def check_audit_logging(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    """Check for audit-grade logging beyond basic app-level logging.

    Looks for: CloudTrail/CloudWatch in IaC, audit log steps in CI/CD,
    log retention configuration, and centralized log shipping.
    """
    indicators_found: list[str] = []

    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        source_type = evidence.get("source_type", "")
        raw = str(content).lower()

        # Check IaC for cloud audit logging services
        if source_type in ("iac_config", "github_code"):
            if "cloudtrail" in raw:
                indicators_found.append("AWS CloudTrail configured")
            if "cloudwatch" in raw and "log_group" in raw:
                indicators_found.append("CloudWatch Log Group configured")
            if "stackdriver" in raw or "cloud_logging" in raw:
                indicators_found.append("GCP Cloud Logging configured")
            if "log_analytics_workspace" in raw:
                indicators_found.append("Azure Log Analytics configured")
            if "retention" in raw and any(
                kw in raw for kw in ["days", "retention_in_days", "retention_policy"]
            ):
                indicators_found.append("Log retention policy configured")

        # Check CI/CD for audit logging steps
        if source_type == "github_actions":
            if any(kw in raw for kw in ["audit", "siem", "splunk", "datadog", "elk"]):
                indicators_found.append("Audit/SIEM integration in CI/CD pipeline")

    if len(indicators_found) >= 2:
        return {
            "passed": True,
            "reason": f"Audit logging infrastructure verified: {'; '.join(indicators_found)}",
        }
    elif len(indicators_found) == 1:
        return {
            "passed": False,
            "reason": (
                f"Partial audit logging found ({indicators_found[0]}), but "
                "comprehensive audit logging requires at least 2 indicators "
                "(e.g., CloudTrail + retention policy). "
                "Remediation: Add log retention policies and centralized log aggregation."
            ),
        }
    else:
        return {
            "passed": False,
            "reason": (
                "No audit logging infrastructure found in collected evidence. "
                "Remediation: Configure AWS CloudTrail or equivalent cloud audit logging service, "
                "set log retention to ≥365 days, and ship logs to a centralized SIEM."
            ),
        }


RULE_SPEC = RuleSpec(
    name="check_audit_logging",
    description="Verify audit-grade logging with retention and centralized aggregation",
    fn=check_audit_logging,
    applicable_control_patterns=APPLICABLE_PATTERNS,
    applicable_source_types=["iac_config", "github_code", "github_actions"],
)
