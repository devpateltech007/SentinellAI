"""Rule: Verify policies and procedures to address security incidents."""

from __future__ import annotations

from app.services.evaluator.rules.rule_spec import RuleSpec

APPLICABLE_PATTERNS = ["incident", "164.308(a)(6)", "response", "security event"]

def check_incident_response(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    indicators: list[str] = []

    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        raw = str(content).lower()
        source_type = evidence.get("source_type", "")
        path = str(content.get("path", "")).lower()

        # Check for SECURITY.md or security policy
        if "security.md" in path or "security_policy" in path:
            indicators.append("SECURITY.md or security policy document found")

        # Check for vulnerability scanning tools
        vuln_scanners = ["snyk", "trivy", "dependabot", "grype", "clair", "anchore", "semgrep"]
        if source_type in ("github_actions", "github_code"):
            for scanner in vuln_scanners:
                if scanner in raw:
                    indicators.append(f"Vulnerability scanner ({scanner}) configured")
                    break

        # Check for alerting/notification infrastructure
        alert_tools = ["pagerduty", "opsgenie", "slack", "webhook", "alert", "notification"]
        if any(tool in raw for tool in alert_tools):
            indicators.append("Alerting/notification infrastructure detected")

    if len(indicators) >= 2:
        return {
            "passed": True,
            "reason": f"Incident response procedures verified: {'; '.join(indicators)}",
        }
    elif indicators:
        return {
            "passed": False,
            "reason": (
                f"Partial incident response setup ({indicators[0]}). "
                "A complete incident response program requires ≥2 of: "
                "security policy document, vulnerability scanning, alerting infrastructure. "
                "Remediation: Add a SECURITY.md to your repo and configure automated scanning."
            ),
        }
    return {
        "passed": False,
        "reason": (
            "No incident response procedures found in evidence. "
            "Remediation: Create a .github/SECURITY.md with vulnerability disclosure policy, "
            "add Trivy/Snyk scanning to CI/CD, and configure PagerDuty/Slack alerting."
        ),
    }

RULE_SPEC = RuleSpec(
    name="check_incident_response",
    description="Verify incident response policies, vulnerability scanning, and alerting",
    fn=check_incident_response,
    applicable_control_patterns=APPLICABLE_PATTERNS,
    applicable_source_types=["github_code", "github_actions", "iac_config"],
)
