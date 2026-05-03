"""Configurable PII/PHI field-level redaction for evidence data.

Applied at ingestion time before storage (FR-10, NFR-02).
Redaction config is toggleable per field. Redacted fields contain
a placeholder value, not the original content.
"""

from __future__ import annotations

import re

REDACTION_PLACEHOLDER = "[REDACTED]"

DEFAULT_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


def redact_fields(
    content: dict,
    config: dict,
) -> tuple[dict, bool]:
    """Apply field-level redaction to evidence content.

    Args:
        content: The raw evidence content dict.
        config: Redaction config. Keys are field paths, values are booleans
                indicating whether to redact. Special key "pattern_scan"
                enables regex-based PII detection across all string values.

    Returns:
        Tuple of (redacted_content, was_any_field_redacted).
    """
    redacted = dict(content)
    any_redacted = False

    # Field-level redaction
    for field_path, should_redact in config.items():
        if field_path == "pattern_scan":
            continue
        if should_redact and field_path in redacted:
            redacted[field_path] = REDACTION_PLACEHOLDER
            any_redacted = True

    # Pattern-based PII/PHI scan across all string values
    if config.get("pattern_scan", False):
        redacted, pattern_hit = _scan_and_redact(redacted)
        any_redacted = any_redacted or pattern_hit

    return redacted, any_redacted


def _scan_and_redact(data: dict) -> tuple[dict, bool]:
    """Recursively scan dict values for PII patterns and redact matches."""
    any_hit = False
    from typing import Any
    result: dict[str, Any] = {}

    for key, value in data.items():
        if isinstance(value, str):
            new_value = value
            for pattern_name, pattern in DEFAULT_PII_PATTERNS.items():
                if pattern.search(new_value):
                    new_value = pattern.sub(REDACTION_PLACEHOLDER, new_value)
                    any_hit = True
            result[key] = new_value
        elif isinstance(value, dict):
            result[key], nested_hit = _scan_and_redact(value)
            any_hit = any_hit or nested_hit
        elif isinstance(value, list):
            new_list: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    redacted_item, nested_hit = _scan_and_redact(item)
                    new_list.append(redacted_item)
                    any_hit = any_hit or nested_hit
                elif isinstance(item, str):
                    new_item = item
                    for pattern in DEFAULT_PII_PATTERNS.values():
                        if pattern.search(new_item):
                            new_item = pattern.sub(REDACTION_PLACEHOLDER, new_item)
                            any_hit = True
                    new_list.append(new_item)
                else:
                    new_list.append(item)
            result[key] = new_list
        else:
            result[key] = value

    return result, any_hit
