# data/ — local input data (not committed)

**Version:** V2 (HR-01).

**Purpose:** the employee list that rule HR-01 compares with the real AWS users and
GitHub organization members. Any account that doesn't belong to an **active**
employee (and isn't an allowed service account) makes HR-01 FAIL.

**Set it up:**

```bash
cp data/employees.example.csv data/employees.csv
```

Then edit `data/employees.csv` to match your test accounts. Columns:

| Column | Meaning |
| --- | --- |
| `employee_id` | Any unique ID |
| `name`, `email` | For people only; never copied into evidence |
| `status` | `active` counts; anything else (`terminated`, `on_leave`) does not |
| `aws_username` | Their IAM user name (blank if none) |
| `github_login` | Their GitHub login (blank if none) |

Service accounts with no employee, like the tool's own `compliancelens-audit`, are
listed in HR-01's `allow_aws` / `allow_github` params in `rules/starter_rules.yaml`.
Put your own GitHub login in the CSV (or in `allow_github`) so the org owner matches.

**Break and fix:** set `intern-bob`'s status to `terminated` → HR-01 FAIL; back to
`active` → PASS.

**Never commit:** `employees.csv` or any real names or emails. Only this README and
`employees.example.csv` (fake people) are tracked.
