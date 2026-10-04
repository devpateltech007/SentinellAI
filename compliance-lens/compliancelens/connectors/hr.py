"""HR connector: compares the employee list with the real AWS and GitHub accounts.

The employee list is a local CSV file (data/employees.csv, gitignored). Each row
maps one employee to their AWS user name and GitHub login:

    employee_id,name,email,status,aws_username,github_login

Only rows with status "active" count. The evidence holds account names only,
never employee names or emails.
"""

import csv
from pathlib import Path

from compliancelens.connectors import aws, github

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EMPLOYEES_FILE = "data/employees.csv"
REQUIRED_COLUMNS = {"employee_id", "status", "aws_username", "github_login"}


def load_employees(path) -> list[dict]:
    """Rows of the employee CSV. A missing, empty or malformed file is an error."""
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        raise FileNotFoundError(
            f"employee list not found: {path.name} (copy data/employees.example.csv)"
        )
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"employee list is missing columns: {sorted(missing)}")
    if not rows:
        raise ValueError("employee list is empty")
    return rows


def _column(rows: list[dict], name: str) -> set[str]:
    return {(row.get(name) or "").strip() for row in rows} - {""}


def unmatched_accounts(params: dict) -> dict:
    """HR-01: AWS users and GitHub members that don't belong to an active employee.

    `allow_aws` / `allow_github` list service accounts that have no employee, such
    as the tool's own `compliancelens-audit` user. GitHub logins are compared
    without case, as GitHub does. If either system can't be read, this raises:
    half the data is not enough to judge.
    """
    employees = load_employees(params.get("employees_file", DEFAULT_EMPLOYEES_FILE))
    active = [row for row in employees if (row.get("status") or "").strip().lower() == "active"]
    known_aws = _column(active, "aws_username") | set(params.get("allow_aws") or [])
    known_github = {login.lower() for login in _column(active, "github_login")} | {
        login.lower() for login in params.get("allow_github") or []
    }

    aws_users = aws.iam_users({})["users"]
    github_members = github.org_members(params)["members"]
    return {
        "unmatched_aws": sorted(user for user in aws_users if user not in known_aws),
        "unmatched_github": sorted(m for m in github_members if m.lower() not in known_github),
        "aws_accounts_checked": len(aws_users),
        "github_accounts_checked": len(github_members),
        "active_employees": len(active),
    }
