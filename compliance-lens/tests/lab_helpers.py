"""Shared helpers for the research experiment's tests (tests/test_lab_*.py)."""

import io

from PIL import Image, ImageDraw

from compliancelens.connectors import browser
from experiment.lab import capture, cases

SETUPS = {
    "AWS-01": {"password_policy": {"MinimumPasswordLength": 14}},
    "AWS-02": {"users": []},
    "AWS-05": {"bucket": {"name": "ab", "block": True}},
    "GH-01": {"protection": {"approvals": 1}},
    "GH-06": {"org": {"default_repository_permission": "read"}},
}
API = {
    "AWS-01": lambda state: {"MinimumPasswordLength": 14 if state == "PASS" else 8},
    "AWS-02": lambda state: {"count": 0 if state == "PASS" else 1, "users": []},
    "AWS-05": lambda state: {
        "bucket": "b",
        "bucket_flags": {"b": {"BlockPublicAcls": state == "PASS"}},
        "buckets_fully_blocked": {"b": state == "PASS"},
    },
    "GH-01": lambda state: {"required_approving_review_count": 1 if state == "PASS" else 0},
    "GH-06": lambda state: {
        "default_repository_permission": "read" if state == "PASS" else "write"
    },
}


def picture(text: str) -> bytes:
    image = Image.new("RGB", (1440, 900), "white")
    ImageDraw.Draw(image).text((40, 100), text, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def captured(tmp_path, specs, code=None) -> list[dict]:
    """Saved cases as capture.py saves them: (id, rule, state, kind) each, a picture each.
    `code` maps a case ID to the code's verdict when it should differ from the state."""
    rules = cases.experiment_rules()
    root = tmp_path / "cases"
    for case_id, rule_id, state, kind in specs:
        case = cases.Case(
            id=case_id,
            rule=rule_id,
            state=state,
            kind=kind,
            setup=SETUPS[rule_id],
            pilot=case_id.startswith("pilot-"),
        )
        png = picture(f"{case_id}: {state}")
        shot = browser.Capture(
            browser.CAPTURED,
            "captured",
            "github",
            png=png,
            requested_url="https://github.com/x",
            final_url="https://github.com/x",
            captured_at="2026-10-19T10:00:00+00:00",
        )
        verdict = (code or {}).get(case_id, state)
        result = {"verdict": verdict, "reason": f"code says {verdict}"}
        capture.save_case(root, case, rules[rule_id], {}, shot, API[rule_id](state), result)
    return capture.load_captured(root)
