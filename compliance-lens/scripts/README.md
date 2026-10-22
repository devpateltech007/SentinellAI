# scripts/ — break-and-fix routines

**Version:** V1 (3 rules), V2 (14 rules), V3 (16 rules + screenshot checks), V4 (19 rules: AI-judged screenshots and policy documents), V6 (GH-06 judged by code). Grows with every new rule.

**Purpose:** for every rule, a short routine that makes the real test account
**non-compliant** and then **compliant** again, so you can prove the verdict flips.
Run it before every demo.

The tool itself is read-only. These steps are done by **you**, with your own admin
login (AWS console / GitHub website), never with the tool's SecurityAudit user.

To check one rule quickly: `python audit.py run --rule AWS-05` (recorded as a partial run).

**What goes here:** these notes, and small helper scripts:

| Script | Job |
| --- | --- |
| `make_sample_pdfs.py` | V4: writes `policies/examples/*/password-policy.pdf` from the text inside it (`--check`: compare with the committed PDFs) |
| `export_experiment_json.py` | V6: writes the experiment's main run as `docs/experiment-results.json` (numbers only, no paths), from the private data (`--check`: compare with the committed file) |
| `plot_experiment.py` | V6: draws `docs/figures/*.svg` from that JSON alone; same JSON, same bytes (`--check`: compare with the committed SVGs) |
| `crop_examples.py` | V6: cuts the example pictures `docs/figures/example-*.png` from the private pictures, user names covered. Look at them before committing |

**Never commit:** passwords, access keys or tokens inside a script.

---

## Which rules are flipped live, and which only with fake data

Some rules can't be broken safely or quickly. Their FAIL state is proven by the
automated tests (`make test`) with fake AWS/GitHub data instead.

| Rule | Live break-and-fix | Why not, if not |
| --- | --- | --- |
| AWS-01, AWS-02 | ✅ | |
| AWS-03 root MFA | ❌ PASS only | Turning off root MFA is dangerous |
| AWS-04 old access keys | ❌ PASS only | A key has to be 90 days old |
| AWS-05, AWS-06, AWS-07 | ✅ | |
| AWS-08 inactive users | ❌ PASS only (quick check below) | A user has to be idle 90 days |
| GH-01 to GH-04 | ✅ | |
| GH-05 org 2FA | ❌ PASS only | GitHub requires 2FA for most accounts, so a member without it is hard to create |
| GH-06 | ✅ (V6: code reads the API) | |
| GH-07 | ✅ (V4: the AI reads the screenshot, so the verdict flips) | |
| DOC-01 to DOC-03 | ✅ by switching the policy folder (no account change) | |
| HR-01 | ✅ (edit the local CSV) | |

---

## AWS-01: Password policy requires 12+ characters

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | IAM → Account settings → Password policy → set minimum length to **8** (or delete the policy) | FAIL |
| Fix | Set minimum length to **14** | PASS |

CLI alternative (admin profile): `aws iam update-account-password-policy --minimum-password-length 8`, then `... 14`.

## AWS-02: Every IAM user with a console password has MFA

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | User `intern-bob` has a console password and **no MFA** (the default setup) | FAIL, `users: ['intern-bob']` |
| Fix | IAM → Users → intern-bob → Security credentials → Assign MFA device (authenticator app) | PASS |
| Break again | Remove the MFA device from intern-bob | FAIL |

This is the live fix in the final demo.

## AWS-03: Root account has MFA

**Do not break this.** Live: PASS (root MFA on; AWS now requires it for root users).
FAIL and NEEDS REVIEW are tested with fake data in `tests/test_aws.py`.

## AWS-04: No active access key older than 90 days

Live: PASS (`compliancelens-audit` signs in with `aws login` and has no keys).
A key can't be made 90 days old on purpose, so FAIL is tested with a fake clock in
`tests/test_aws.py`. Inactive keys are ignored.

## AWS-05: Every S3 bucket blocks public access

Use the **empty test bucket with no bucket policy**. Turning off the block on it exposes
nothing; it only removes the guardrail. Never do this on a bucket with files or a policy.

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | S3 → test bucket → Permissions → Block public access → Edit → untick **Block all public access** → Save | FAIL, names the bucket |
| Fix | Tick **Block all public access** again → Save | PASS |

Don't add a bucket policy, ACL or files while it is off. With no buckets at all, AWS-05 is NEEDS REVIEW.

## AWS-06: Every S3 bucket has versioning on

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | S3 → test bucket → Properties → Bucket Versioning → Edit → **Suspend** | FAIL |
| Fix | **Enable** | PASS |

Once enabled, versioning can only be suspended, never fully removed; that's fine.
Remember the CloudTrail log bucket needs versioning on too.

## AWS-07: At least one CloudTrail trail is logging

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | CloudTrail → Trails → your trail → **Stop logging** | FAIL |
| Fix | **Start logging** | PASS |

## AWS-08: No IAM user inactive for more than 90 days

Live: PASS. FAIL is tested with a recorded credential report in `tests/test_aws.py`.

Quick live check that the real report is read (changes nothing in AWS): in
`rules/starter_rules.yaml` set AWS-08's `max_inactive_days: 0`, run
`python audit.py run --rule AWS-08` (FAIL: `intern-bob`, created and never signed in),
then set it back to `90`.

AWS rebuilds the credential report at most **every 4 hours**, so sign-ins can take up to
4 hours to show. The evidence records `report_generated_at`.

**Heads-up for the final demo:** `intern-bob` (created Oct 1, 2026) never signs in, so from
about **Dec 30, 2026** AWS-08 will FAIL for `intern-bob`. That is correct behaviour, but the
demo expects AWS-02 to be the only failure. A few days before the demo, sign in to the
console once as `intern-bob` (the next credential report, up to 4 hours later, shows it),
or present it as a second planned failure.

## GH-01: main branch requires at least 1 review

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Test repo → Settings → Branches → edit the classic rule for `main` → untick "Require a pull request before merging" | FAIL |
| Fix | Tick it again, required approvals **1** | PASS |

## GH-02: Force pushes to main are blocked

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Settings → Branches → edit the `main` rule → tick **Allow force pushes** → Save | FAIL |
| Fix | Untick it → Save | PASS |

Deleting the whole rule also gives FAIL (an unprotected branch allows force pushes).

**Screenshot of GH-01/GH-02:** the rule's own page, `.../settings/branch_protection_rules/<number>`
(`vars.rule` in the rule card). Editing the rule keeps the number. If you **delete and
re-create** the rule, the screenshot says `HTTP 404`: open Settings → Branches, the `main`
rule's menu → Edit, and copy the new number from the address bar into `vars.rule` of GH-01
and GH-02.

## GH-03: Secret scanning is enabled

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Settings → Code security → Secret Protection / Secret scanning → **Disable** | FAIL |
| Fix | **Enable** | PASS |

NEEDS REVIEW with "security_and_analysis not visible" means the token can't see the
setting: give it **Administration: Read-only**.

## GH-04: Dependabot alerts are enabled

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Settings → Code security → Dependabot alerts → **Disable** | FAIL |
| Fix | **Enable** | PASS |

**First time only:** check GitHub's real "disabled" reply matches the one the tool expects.
With alerts disabled:

```bash
set -a; source .env; set +a
curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/$GITHUB_ORG/compliancelens-test/vulnerability-alerts
```

It should print `"message": "Vulnerability alerts are disabled."`. If the text differs,
GH-04 shows NEEDS REVIEW instead of FAIL (safe, but wrong): put the real text in
`DEPENDABOT_DISABLED` in `compliancelens/connectors/github.py` and in
`tests/fixtures/github/dependabot_disabled.json`.

## GH-05: Every organization member has 2FA

Live: PASS (you are the only member and have 2FA). GitHub now requires 2FA for most
accounts, so FAIL is tested with a recorded reply in `tests/test_github.py`. If you do
have a second account without 2FA: invite it to the organization → FAIL; remove it → PASS.

## GH-06: Organization base repository permission is Read or None (code reads the API)

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Organization → Settings → Member privileges → Base permissions → **Write** | FAIL, `default_repository_permission = write (expected in ['read', 'none'])` |
| Fix | Set it back to **Read** | PASS, `default_repository_permission = read ...` |

Run `python audit.py run --rule GH-06` after each step. The verdict comes from the API
(`GH-06.json`); `GH-06.png` should show the same value. **Admin** also gives FAIL and
**No permission** PASS. With `--cross-check` the AI reads the picture too
(`GH-06.crosscheck.json`); that records whether it agrees but never changes the verdict.
Until V6 the AI judged GH-06 from the picture.

If GH-06 says `default_repository_permission not visible`, the token is missing the
organization's **Administration: Read-only** (see the README's GitHub setup, step 10).

## GH-07: Members cannot delete or transfer repositories (AI reads the screenshot)

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Member privileges → Repository deletion and transfer → tick **Allow members to delete or transfer repositories** → Save | FAIL; the AI reads it ticked |
| Fix | Untick it → Save | PASS; the AI reads it unticked |

Run `python audit.py run --rule GH-07` after each step and open `GH-07.png` and
`GH-07.ai.json` (the AI's answer and quote). A changed page is a new picture, so the AI is
asked again (the cache only reuses answers for identical pixels).

Only the organization's members are affected; owners can always delete and transfer.

## HR-01: Every AWS and GitHub account belongs to an active employee

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | In `data/employees.csv`, set `intern-bob`'s status to `terminated` | FAIL, `aws ['intern-bob']` |
| Fix | Set it back to `active` | PASS |

Also FAIL: an IAM user or org member that isn't in the CSV and isn't in HR-01's
`allow_aws` / `allow_github` lists.

## DOC rules (V4): flip by folder, no account changes

Document rules read their files from `COMPLIANCELENS_POLICIES_DIR`. To flip them, point
it at another folder of `policies/examples/` (see `policies/README.md`), e.g.
`COMPLIANCELENS_POLICIES_DIR=policies/examples/noncompliant python audit.py run --rule DOC-01 --rule DOC-02 --rule DOC-03`:

| Folder | Expected verdict |
| --- | --- |
| `compliant` (default) | PASS |
| `noncompliant` | FAIL, quoting the sentence that fails |
| `ambiguous` | NEEDS REVIEW (each document contradicts itself) |
| `injection` | never PASS |
| `silent` | FAIL (the requirement is never stated) |

Rename one file in the folder: only that rule becomes NEEDS REVIEW ("not found").

## Checks that should give NEEDS REVIEW (never PASS)

| Do this | Expected reason |
| --- | --- |
| Remove `GITHUB_TOKEN` from `.env` | GH-01 to GH-05: `GITHUB_TOKEN not set`; HR-01 too |
| Remove `github.org` from `config/settings.yaml` (and `GITHUB_ORG` from `.env`) | GH-05 and HR-01: `GitHub organization not set` |
| Put a wrong repository name in `config/settings.yaml` | `404 ... Not Found` |
| Set `AWS_PROFILE` to a profile that doesn't exist | `config profile ... could not be found` |
| Run `aws logout --profile compliancelens` | AWS rules: a login/credentials error |
| Rename `data/employees.csv` | HR-01: `employee list not found` |
| Change a rule's `check.field` to a name that doesn't exist | `field ... not in evidence` |

After each step: `make audit` (or `python audit.py run --rule <ID>`) and compare.

## Screenshot checks (V3)

These change nothing in AWS or GitHub. Every one must leave the **API verdicts unchanged**
and say what is wrong with the screenshot.

| Do this | Expected |
| --- | --- |
| Move `sessions/github.json` out of the project, run `make audit` | GitHub rules keep their verdicts; `GitHub: 7 not saved (session missing). Fix: python audit.py login github`; GH-07 (judged from its picture) says why. Move the file back. |
| Wait more than 12 hours after `make login SITE=aws`, run an AWS rule | `session_expired`; the verdict stays; no PNG is saved (a sign-in page is never proof) |
| In a **copy** of the rulebook, change one `wait_for` to text that doesn't exist; run `python audit.py run --rules-file <copy> --rule AWS-01` | `selector_timeout: ... did not appear within 20 s` |
| `python audit.py run --no-screenshots` | No browser; `Screenshots: turned off` |
| Tamper test on a **backup** of a V3 run: draw on `GH-01.png`, run `verify` | FAILED: `GH-01.png was changed` (manifest and database) and `does not match the hash in GH-01.meta.json`; restore → OK |
