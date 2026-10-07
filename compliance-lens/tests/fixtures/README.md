# tests/fixtures/ — recorded API replies

Saved copies of real-shaped API responses, so tests run offline and never
touch a real account.

| File | What it is |
| --- | --- |
| `github/branch_protected.json` | Branch protection with 1 required review, force pushes off (GH-01 PASS, GH-02 PASS) |
| `github/protected_no_reviews.json` | Protected branch with no review requirement (GH-01 FAIL) |
| `github/branch_force_push_allowed.json` | Protected branch that allows force pushes (GH-02 FAIL) |
| `github/branch_not_protected.json` | GitHub's 404 "Branch not protected" (GH-01 FAIL, GH-02 FAIL) |
| `github/not_found.json` | GitHub's 404 "Not Found": wrong repo or no access (NEEDS REVIEW) |
| `github/repo_security_enabled.json` | Repo with secret scanning on (GH-03 PASS) |
| `github/repo_security_disabled.json` | Repo with secret scanning off (GH-03 FAIL) |
| `github/repo_no_security_field.json` | Repo seen without admin access: no `security_and_analysis` (GH-03 NEEDS REVIEW) |
| `github/dependabot_disabled.json` | 404 "Vulnerability alerts are disabled." (GH-04 FAIL) |
| `github/org_members_2fa_disabled.json` | One org member without 2FA (GH-05 FAIL) |
| `github/rate_limited.json` | 403 "API rate limit exceeded" body |
| `aws/credential_report.csv` | IAM credential report: root row, recent, never-used, old console and old key users (AWS-08) |
| `hr/employees.csv` | Fake employee list: active, terminated and on-leave people (HR-01) |
| `browser/*.html` | A fake website for the screenshot tests, served on 127.0.0.1 by `test_browser.py`: sign-in page, logged-in pages, a tall page, a slow page, a page that signs out after loading, a sign-in page that logs in by itself (like a person typing while the terminal waits for Enter), "Confirm access", "no permission" and "Access denied" pages |

The Dependabot "disabled" message is GitHub's documented reply; confirm it once with
the real token (see `scripts/README.md`, GH-04) and update the fixture if it differs.

**Never commit:** real tokens, real usernames or emails, or real AWS key IDs
(gitleaks blocks `AKIA...` strings). Replace them with placeholders.
