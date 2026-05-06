"""Rule: Verify transmission security (TLS/SSL) is properly configured."""

from __future__ import annotations

import re

from app.services.evaluator.rules.rule_spec import RuleSpec

APPLICABLE_PATTERNS = ["transmission", "164.312(e)", "tls", "ssl", "https", "transit"]

def check_transmission_security(
    control_id_code: str,
    evidence_items: list[dict],
) -> dict | None:
    findings: list[str] = []
    concerns: list[str] = []

    for evidence in evidence_items:
        content = evidence.get("content_json", {})
        source_type = evidence.get("source_type", "")
        raw = str(content).lower()

        # Check for TLS configuration in IaC
        if source_type in ("iac_config", "github_code"):
            # SSL/TLS policy version check
            tls_match = re.search(r'ssl_policy.*?tls[v_-]?([\d.]+)', raw)
            if tls_match:
                version = tls_match.group(1)
                if float(version) >= 1.2:
                    findings.append(f"TLS {version} policy configured")
                else:
                    concerns.append(f"Outdated TLS {version} detected — minimum 1.2 required")

            # HTTPS enforcement
            if "redirect_http_to_https" in raw or "force_https" in raw:
                findings.append("HTTPS redirect enforced")
            if "certificate_arn" in raw or "ssl_certificate" in raw:
                findings.append("SSL certificate configured")

            # Check for insecure protocols
            if "sslv3" in raw or "tlsv1_0" in raw or "tls_1_0" in raw:
                concerns.append("Insecure protocol (SSLv3/TLS 1.0) detected in config")

        # Check CI/CD for SSL scanning
        if source_type == "github_actions":
            if any(kw in raw for kw in ["ssl-scan", "testssl", "sslyze", "certificate"]):
                findings.append("SSL/TLS scanning step in CI/CD pipeline")

    if concerns:
        return {
            "passed": False,
            "reason": (
                f"Transmission security issues detected: {'; '.join(concerns)}. "
                f"Remediation: Upgrade to TLS 1.2+, remove SSLv3/TLS 1.0 support, "
                f"and enforce HTTPS redirects on all public endpoints."
            ),
        }
    if findings:
        return {
            "passed": True,
            "reason": f"Transmission security verified: {'; '.join(findings)}",
        }
    return {
        "passed": False,
        "reason": (
            "No TLS/SSL configuration found in evidence. "
            "Remediation: Configure TLS 1.2+ on all load balancers and endpoints, "
            "add SSL certificates, and enforce HTTPS redirects."
        ),
    }

RULE_SPEC = RuleSpec(
    name="check_transmission_security",
    description="Verify TLS 1.2+ is configured with no insecure protocol fallback",
    fn=check_transmission_security,
    applicable_control_patterns=APPLICABLE_PATTERNS,
    applicable_source_types=["iac_config", "github_code", "github_actions"],
)
