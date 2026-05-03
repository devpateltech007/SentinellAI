# Phase 4 — The Logic Bridge

> **Estimated Total**: 24 engineering hours
> **Dependencies**: Phase 3 Task 3.2 (IaC parsers) should be done so new rules can use structured flags instead of raw string matching.
> **Rationale**: The "Logic Bridge" is the critical translation layer that maps an AI-generated compliance control (e.g., "HIPAA-SC-001: Transmission Security") to a specific Python function that can evaluate whether that control passes or fails based on real evidence. Currently, only 3 hard-coded rules exist and they use crude keyword matching. This phase builds a dynamic, extensible rule system with AI-assisted fallback for unmatched controls.

---

## Current State

| Component | File | Status |
|---|---|---|
| Rule Registry | `evaluator/rules/__init__.py` | 🔴 Flat list, manually maintained |
| `check_access_control` | `evaluator/rules/access_control.py` | 🟡 Works but crude keyword matching |
| `check_encryption_at_rest` | `evaluator/rules/encryption_at_rest.py` | 🟡 Same — `"encrypt" in raw` |
| `check_logging_enabled` | `evaluator/rules/logging_enabled.py` | 🟡 Same pattern |
| Evaluation Engine | `evaluator/engine.py` | ✅ Solid loop + result aggregation |
| Status Persistence | `evaluator/status.py` | ✅ Append-only write + denormalized update |

**The core problem**: When the Compliance Brain generates 25+ controls for HIPAA, only 3 of them can be automatically evaluated. The other 22 fall through to "NeedsReview — No applicable rules matched." This phase closes that gap.

---

## Task 4.1: Define RuleSpec Dataclass and Refactor Registry

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/services/evaluator/rules/__init__.py` — refactor registry
- `backend/app/services/evaluator/engine.py` — update loop to use RuleSpec

**Files to Edit (minor)**:
- `backend/app/services/evaluator/rules/access_control.py` — export RuleSpec
- `backend/app/services/evaluator/rules/encryption_at_rest.py` — export RuleSpec
- `backend/app/services/evaluator/rules/logging_enabled.py` — export RuleSpec

**Detailed Logic Brief**:

Currently each rule function does its own applicability check internally (e.g., `access_control.py` line 17: `if not any(p in code_lower for p in APPLICABLE_PATTERNS): return None`). This mixes two concerns: "Does this rule apply to this control?" and "Does the evidence pass?". Separating them into a `RuleSpec` makes the system declarative and inspectable.

**Define RuleSpec** in `rules/__init__.py`:

```python
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class RuleSpec:
    """Declaration of a single evaluation rule."""
    name: str
    description: str
    fn: Callable[[str, list[dict]], dict | None]
    applicable_control_patterns: list[str]
    applicable_source_types: list[str] = field(default_factory=lambda: ["*"])
    # If source_types is ["*"], rule runs against all evidence types.
    # Otherwise, only runs when evidence of that type is linked.
```

**Refactor each existing rule** to export a `RULE_SPEC`. Example for `access_control.py`:

```python
# At the bottom of access_control.py, after the function definition:
RULE_SPEC = RuleSpec(
    name="check_access_control",
    description="Verify RBAC or access control is configured in evidence",
    fn=check_access_control,
    applicable_control_patterns=["access", "rbac", "role", "164.312(a)", "164.308(a)(4)", "article 25"],
    applicable_source_types=["github_actions", "iac_config", "github_code"],
)
```

Remove the internal applicability check from the function body (lines 16-18). The engine will handle that externally now.

**Update the registry**:
```python
from app.services.evaluator.rules.access_control import RULE_SPEC as access_control_spec
from app.services.evaluator.rules.encryption_at_rest import RULE_SPEC as encryption_spec
from app.services.evaluator.rules.logging_enabled import RULE_SPEC as logging_spec

RULE_REGISTRY: list[RuleSpec] = [
    access_control_spec,
    encryption_spec,
    logging_spec,
]
```

**Update `engine.py`** to use the new structure:

```python
async def evaluate_control(
    control_id: UUID,
    control_id_code: str,
    evidence_items: list[dict],
) -> EvaluationResult:
    if not evidence_items:
        return EvaluationResult(
            control_id=control_id, status="NeedsReview",
            evidence_ids=[], rationale="No evidence collected.",
        )

    evidence_ids = [e.get("id") for e in evidence_items if e.get("id")]
    failures, passes = [], []
    code_lower = control_id_code.lower()

    for spec in RULE_REGISTRY:
        # Check applicability via RuleSpec patterns (moved OUT of rule functions)
        if not any(p in code_lower for p in spec.applicable_control_patterns):
            continue

        # Check source type applicability
        if "*" not in spec.applicable_source_types:
            evidence_types = {e.get("source_type") for e in evidence_items}
            if not evidence_types.intersection(spec.applicable_source_types):
                continue

        result = spec.fn(control_id_code, evidence_items)
        if result is None:
            continue
        if result["passed"]:
            passes.append(result["reason"])
        else:
            failures.append(result["reason"])

    # ... rest unchanged
```

**Definition of Done**:
1. All 3 existing rules work identically to before (no behavioral regression).
2. `RULE_REGISTRY` is a list of `RuleSpec` objects, not raw functions.
3. Each rule function no longer has internal applicability checks — those live in `RULE_SPEC.applicable_control_patterns`.
4. Adding `print([s.name for s in RULE_REGISTRY])` shows all 3 rule names.

---

## Task 4.2: Create Dynamic Rule Loader

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/services/evaluator/loader.py`

**Files to Edit**:
- `backend/app/services/evaluator/rules/__init__.py` — use loader instead of manual imports

**Detailed Logic Brief**:

Hard-coding every rule import in `__init__.py` doesn't scale. When the team has 15+ rules, someone will forget to add an import. A dynamic loader scans the `rules/` directory and auto-discovers any module exporting a `RULE_SPEC`.

```python
"""Dynamic rule loader — auto-discovers evaluation rules from the rules/ directory."""

import importlib
import logging
from pathlib import Path

from app.services.evaluator.rules import RuleSpec

logger = logging.getLogger(__name__)

def load_rules_from_directory(rules_dir: Path | None = None) -> list[RuleSpec]:
    """Scan the rules directory and load all modules that export RULE_SPEC."""
    if rules_dir is None:
        rules_dir = Path(__file__).parent / "rules"

    specs: list[RuleSpec] = []

    for py_file in sorted(rules_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue  # skip __init__.py, __pycache__, etc.

        module_name = f"app.services.evaluator.rules.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "RULE_SPEC"):
                spec = module.RULE_SPEC
                if isinstance(spec, RuleSpec):
                    specs.append(spec)
                    logger.info("Loaded rule: %s from %s", spec.name, py_file.name)
                else:
                    logger.warning(
                        "RULE_SPEC in %s is not a RuleSpec instance, skipping", py_file.name
                    )
            else:
                logger.debug("No RULE_SPEC in %s, skipping", py_file.name)
        except Exception:
            logger.exception("Failed to load rule from %s", py_file.name)

    logger.info("Loaded %d evaluation rules total", len(specs))
    return specs
```

**Update `rules/__init__.py`** to use the loader:

```python
from app.services.evaluator.loader import load_rules_from_directory

# Auto-discover all rules at import time
RULE_REGISTRY: list[RuleSpec] = load_rules_from_directory()
```

**Why `sorted()`?** Ensures deterministic rule execution order regardless of filesystem ordering. Rules are applied in alphabetical filename order, which makes debugging predictable.

**Why catch exceptions per-module?** One broken rule file should not prevent all other rules from loading. The system logs the error and continues. This is critical for production resilience.

**Convention established**: To add a new evaluation rule, a developer:
1. Creates `backend/app/services/evaluator/rules/my_new_check.py`
2. Defines `check_my_thing(control_id_code, evidence_items) -> dict | None`
3. Exports `RULE_SPEC = RuleSpec(name="...", fn=check_my_thing, ...)`
4. Done. No other file needs editing. The loader discovers it automatically.

**Definition of Done**:
1. Remove manual imports from `__init__.py`. Replace with `load_rules_from_directory()`.
2. All 3 existing rules still load and execute correctly.
3. Create a dummy `rules/test_dummy.py` with a `RULE_SPEC` that matches pattern `"dummy"`. Verify `load_rules_from_directory()` returns 4 specs. Remove the dummy file.
4. Create a `rules/broken.py` with a syntax error. Verify the loader logs an exception but the other 3 rules still load.
5. Container startup logs show "Loaded 3 evaluation rules total".

---

## Task 4.3: Implement `check_audit_logging` Rule

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/services/evaluator/rules/audit_logging.py`

**Detailed Logic Brief**:

HIPAA §164.312(b) requires "hardware, software, and/or procedural mechanisms that record and examine activity." This is broader than the existing `check_logging_enabled` which only checks if logging config says `true/false`. This new rule checks for _audit-grade_ logging: CloudTrail, CloudWatch, centralized log aggregation, and log retention policies.

```python
"""Rule: Verify audit-grade logging infrastructure is configured."""

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
```

**Why require ≥2 indicators for pass?** Having CloudTrail enabled but no retention policy means logs could be deleted. Having retention but no CloudTrail means you're only retaining app logs, not infrastructure-level audit trails. A proper audit setup requires multiple layers.

**Definition of Done**:
1. Auto-discovered by `load_rules_from_directory()` — startup logs show 4 rules loaded.
2. Evidence with `{"cloudtrail": "enabled", "retention_in_days": 365}` → passes.
3. Evidence with only `{"cloudtrail": "enabled"}` → fails with partial message.
4. Evidence with no logging keywords → fails with full remediation guidance.

---

## Task 4.4: Implement `check_transmission_security` Rule

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/services/evaluator/rules/transmission_security.py`

**Detailed Logic Brief**:

HIPAA §164.312(e)(1) requires "technical security measures to guard against unauthorized access to ePHI being transmitted over an electronic communications network." This means TLS/SSL must be enforced, with minimum version TLS 1.2.

```python
"""Rule: Verify transmission security (TLS/SSL) is properly configured."""

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
            import re
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
```

**Important design choice**: Concerns (insecure protocols) take priority over findings. Even if TLS 1.2 is configured somewhere, the presence of TLS 1.0 fallback is a fail because attackers can force a downgrade.

**Definition of Done**:
1. Evidence with `{"ssl_policy": "TLSv1.2_2021"}` → passes.
2. Evidence with `{"ssl_policy": "TLSv1.0"}` → fails with "Outdated TLS" message.
3. Evidence with both TLS 1.2 and SSLv3 present → fails (concerns override findings).
4. Evidence with HTTPS redirect + certificate → passes with both findings listed.

---

## Task 4.5: Implement `check_incident_response` Rule

**Estimated Time**: 3 hours

**Files to Create**:
- `backend/app/services/evaluator/rules/incident_response.py`

**Detailed Logic Brief**:

HIPAA §164.308(a)(6)(i) requires "policies and procedures to address security incidents." This is typically verified by checking for: (1) a documented security policy (SECURITY.md), (2) automated vulnerability scanning in CI/CD, (3) alerting/notification infrastructure.

```python
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
```

**Definition of Done**:
1. Evidence with SECURITY.md file path + Trivy in CI/CD → passes.
2. Evidence with only SECURITY.md → fails with "Partial" message.
3. Evidence with nothing → fails with full remediation steps.

---

## Task 4.6: Build AI-Assisted Rule Suggestion Engine

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/services/evaluator/ai_rule_suggest.py`

**Detailed Logic Brief**:

Even with 6+ rules, many AI-generated controls won't match any rule. For example, "HIPAA-AA-001: Business Associate Agreements" has no automated check because it requires reviewing legal contracts, not code. Instead of leaving these as blank "NeedsReview", the AI suggestion engine generates a human-readable analysis of what WOULD need to be checked.

```python
"""AI-assisted evaluation suggestions for controls with no matching rules."""

import logging
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT = """You are a compliance evaluation advisor. A compliance control could not be
automatically evaluated because no automated rule exists for it.

Control: {control_id_code} — {title}
Description: {description}

Available Evidence Summary:
{evidence_summary}

Based on the control description and available evidence, provide:
1. What specific fields or patterns in the evidence should be checked
2. What would constitute a PASS vs FAIL for this control
3. What additional evidence sources might be needed

Keep your response under 200 words. Be specific and actionable."""


async def suggest_evaluation_approach(
    control_id_code: str,
    title: str,
    description: str,
    evidence_items: list[dict],
) -> str:
    """Generate AI-powered evaluation guidance for unmatched controls."""
    if not settings.OPENAI_API_KEY:
        return (
            "No automated evaluation rule exists for this control. "
            "Manual review required by compliance manager."
        )

    # Summarize evidence for the prompt (avoid sending full content)
    evidence_lines = []
    for i, ev in enumerate(evidence_items[:5]):  # limit to 5 items
        src = ev.get("source_type", "unknown")
        ref = ev.get("source_ref", "unknown")[:100]
        keys = list(ev.get("content_json", {}).keys())[:10]
        evidence_lines.append(f"  {i+1}. [{src}] {ref} — keys: {keys}")

    evidence_summary = "\n".join(evidence_lines) if evidence_lines else "  No evidence available."

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": SUGGESTION_PROMPT.format(
                    control_id_code=control_id_code,
                    title=title,
                    description=description,
                    evidence_summary=evidence_summary,
                ),
            }],
            temperature=0.3,
            max_tokens=300,
        )
        suggestion = resp.choices[0].message.content.strip()
        return f"AI Evaluation Guidance: {suggestion}"
    except Exception:
        logger.exception("AI rule suggestion failed for %s", control_id_code)
        return (
            "No automated evaluation rule exists for this control. "
            "AI suggestion unavailable. Manual review required."
        )
```

**Why `gpt-4o-mini`?** This is an advisory function, not a decision-making one. The output is a suggestion for a human reviewer, so accuracy requirements are lower than the control generator. Using the cheaper model keeps costs manageable when evaluating 20+ unmatched controls.

**Why only pass evidence keys, not full content?** The prompt only needs to know what TYPE of data is available, not the actual values. Sending `keys: ["encryption", "run_id", "status"]` is enough for the AI to suggest "Check the 'encryption' field for true/false." This avoids sending potentially sensitive evidence content to the LLM.

**Definition of Done**:
1. Call with a control like "Business Associate Agreements" and GitHub Actions evidence → returns actionable suggestion mentioning what to look for.
2. Call with no OpenAI key → returns graceful fallback message.
3. Call with API failure (mock it) → returns fallback without crashing.

---

## Task 4.7: Wire AI Rule Suggestions into Evaluation Engine

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/services/evaluator/engine.py` — add AI fallback at end of evaluation loop
- `backend/app/workers/evaluation_tasks.py` — pass control metadata to engine

**Detailed Logic Brief**:

Update `evaluate_control()` to accept the control's `title` and `description` (needed for the AI prompt), and call `suggest_evaluation_approach()` when no rules matched:

```python
async def evaluate_control(
    control_id: UUID,
    control_id_code: str,
    evidence_items: list[dict],
    control_title: str = "",         # NEW
    control_description: str = "",   # NEW
) -> EvaluationResult:
    # ... existing rule loop ...

    if not failures and not passes:
        # No rules matched this control — ask AI for guidance
        from app.services.evaluator.ai_rule_suggest import suggest_evaluation_approach
        suggestion = await suggest_evaluation_approach(
            control_id_code=control_id_code,
            title=control_title,
            description=control_description,
            evidence_items=evidence_items,
        )
        return EvaluationResult(
            control_id=control_id,
            status="NeedsReview",
            evidence_ids=evidence_ids,
            rationale=suggestion,
        )
```

Update `_evaluate_control_async()` in `evaluation_tasks.py` to pass the new fields:

```python
eval_result = await evaluate_control(
    control_id=control.id,
    control_id_code=control.control_id_code,
    evidence_items=evidence_items,
    control_title=control.title,               # NEW
    control_description=control.description,   # NEW
)
```

**Definition of Done**:
1. Evaluate a control that matches no rules (e.g., one with control code "HIPAA-BA-001").
2. Result status is `NeedsReview`.
3. Rationale starts with "AI Evaluation Guidance:" followed by specific, actionable suggestions.
4. The suggestion references actual evidence keys available for the control.
5. When OpenAI key is not set, rationale falls back to "Manual review required."

---

## Phase 4 — Dependency Graph

```
Task 4.1 (RuleSpec Refactor)          — No dependencies
Task 4.2 (Dynamic Loader)             — Depends on 4.1
Task 4.3 (Audit Logging Rule)         — Depends on 4.1
Task 4.4 (Transmission Security Rule) — Depends on 4.1
Task 4.5 (Incident Response Rule)     — Depends on 4.1
Task 4.6 (AI Rule Suggestion)         — No dependencies
Task 4.7 (Wire AI into Engine)        — Depends on 4.1 + 4.6
```

**Parallelization**: Task 4.1 is the gatekeeper — do it first. After that, Tasks 4.2-4.5 and 4.6 can ALL run in parallel. Task 4.7 is the final wiring step.

**Recommended assignment**:
- **Person A**: Task 4.1 → 4.2 (infrastructure)
- **Person B**: Tasks 4.3 + 4.4 (two rules)
- **Person C**: Task 4.5 + 4.6 (one rule + AI suggestion)
- **Person D**: Task 4.7 (wiring — can also help with Phase 5)
