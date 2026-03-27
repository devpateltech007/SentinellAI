"""Configurable rule library for the evaluation engine.

Each rule is a function that takes (control_id_code, evidence_items)
and returns a dict {"passed": bool, "reason": str} or None if the
rule does not apply to that control.
"""

from app.services.evaluator.rules.logging_enabled import check_logging_enabled
from app.services.evaluator.rules.encryption_at_rest import check_encryption_at_rest
from app.services.evaluator.rules.access_control import check_access_control

RULE_REGISTRY = [
    check_logging_enabled,
    check_encryption_at_rest,
    check_access_control,
]
