"""HR connector tests: employee list vs AWS users and GitHub members. No real accounts."""

from pathlib import Path

import pytest

from compliancelens import engine
from compliancelens.connectors import aws, github, hr

EMPLOYEES = Path(__file__).parent / "fixtures" / "hr" / "employees.csv"
HEADER = "employee_id,name,email,status,aws_username,github_login\n"
RULE = {
    "id": "HR-01",
    "title": "accounts belong to active employees",
    "collector": "hr.unmatched_accounts",
    "check": {"custom": "no_unmatched_accounts"},
}


@pytest.fixture
def accounts(monkeypatch):
    """Fake AWS users and GitHub members; tests change the lists as needed."""
    found = {
        "aws": ["alex-admin", "intern-bob", "compliancelens-audit"],
        "github": ["alex-example"],
    }
    monkeypatch.setattr(aws, "iam_users", lambda params: {"users": found["aws"]})
    monkeypatch.setattr(github, "org_members", lambda params: {"members": found["github"]})
    return found


def params(**extra):
    return {"employees_file": str(EMPLOYEES), "allow_aws": ["compliancelens-audit"], **extra}


def test_load_employees():
    rows = hr.load_employees(EMPLOYEES)
    assert [r["employee_id"] for r in rows] == ["E001", "E002", "E003", "E004"]


def test_relative_path_is_from_the_project_folder():
    with pytest.raises(FileNotFoundError, match="employees.csv"):
        hr.load_employees("data/no-such-folder/employees.csv")


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="employees.example.csv"):
        hr.load_employees(tmp_path / "employees.csv")


def test_empty_file_is_an_error(tmp_path):
    path = tmp_path / "employees.csv"
    path.write_text(HEADER)
    with pytest.raises(ValueError, match="empty"):
        hr.load_employees(path)


def test_missing_columns_is_an_error(tmp_path):
    path = tmp_path / "employees.csv"
    path.write_text("name,email\nAlex,alex@example.com\n")
    with pytest.raises(ValueError, match="aws_username"):
        hr.load_employees(path)


def test_everyone_matches(accounts):
    result = hr.unmatched_accounts(params())
    assert result == {
        "unmatched_aws": [],
        "unmatched_github": [],
        "aws_accounts_checked": 3,
        "github_accounts_checked": 1,
        "active_employees": 2,
    }
    assert engine.run_rule({**RULE, "params": params()})["verdict"] == "PASS"


def test_former_employee_accounts_are_unmatched(accounts):
    accounts["aws"].append("casey-old")
    accounts["github"] += ["casey-former", "dana-leave"]
    result = hr.unmatched_accounts(params())
    assert result["unmatched_aws"] == ["casey-old"]
    assert result["unmatched_github"] == ["casey-former", "dana-leave"]
    r = engine.run_rule({**RULE, "params": params()})
    assert r["verdict"] == "FAIL"
    assert "casey-old" in r["reason"]


def test_unknown_account_is_unmatched(accounts):
    accounts["aws"].append("mystery-user")
    assert hr.unmatched_accounts(params())["unmatched_aws"] == ["mystery-user"]


def test_service_account_needs_the_allowlist(accounts):
    result = hr.unmatched_accounts(params(allow_aws=[]))
    assert result["unmatched_aws"] == ["compliancelens-audit"]


def test_github_allowlist_ignores_case(accounts):
    accounts["github"].append("Org-Owner")
    assert hr.unmatched_accounts(params(allow_github=["org-owner"]))["unmatched_github"] == []


def test_github_logins_ignore_case(accounts):
    # The CSV says "Alex-Example"; GitHub reports "alex-example".
    assert hr.unmatched_accounts(params())["unmatched_github"] == []


def test_missing_employee_list_needs_review(accounts, tmp_path):
    r = engine.run_rule({**RULE, "params": {"employees_file": str(tmp_path / "none.csv")}})
    assert r["verdict"] == "NEEDS REVIEW"
    assert "employee list not found" in r["reason"]


def test_github_failure_needs_review(accounts, monkeypatch):
    # Half the data (AWS only) is not enough to judge.
    def down(params):
        raise RuntimeError("GITHUB_TOKEN not set")

    monkeypatch.setattr(github, "org_members", down)
    r = engine.run_rule({**RULE, "params": params()})
    assert r["verdict"] == "NEEDS REVIEW"
    assert "GITHUB_TOKEN" in r["reason"]


def test_evidence_has_no_names_or_emails(accounts):
    text = str(hr.unmatched_accounts(params()))
    assert "@example.com" not in text
    assert "Alex Example" not in text
