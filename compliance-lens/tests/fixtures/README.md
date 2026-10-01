# tests/fixtures/ — recorded API replies

Saved copies of real-shaped API responses, so tests run offline and never
touch a real account.

| File | What it is |
| --- | --- |
| `github/branch_protected.json` | Branch protection with 1 required review (GH-01 PASS) |
| `github/protected_no_reviews.json` | Protected branch with no review requirement (GH-01 FAIL) |
| `github/branch_not_protected.json` | GitHub's 404 "Branch not protected" (GH-01 FAIL) |
| `github/not_found.json` | GitHub's 404 "Not Found": wrong repo or no access (NEEDS REVIEW) |

**Never commit:** real tokens, real usernames or emails. Replace them with placeholders.
