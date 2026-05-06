"""Configurable rule library for the evaluation engine.

Each rule is a function that takes (control_id_code, evidence_items)
and returns a dict {"passed": bool, "reason": str} or None if the
rule does not apply to that control.
"""

