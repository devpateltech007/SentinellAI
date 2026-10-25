# Live demo script (V6)

About 6 minutes, following the Project Plan's final demo: run an audit, open the failure,
read its evidence, review an uncertain result, export the report, fix the failure live,
run again and see it change. Rehearse it twice, and keep the backup video and a saved
report ready in case the network or a login fails on the day.

## The day before

- [ ] `python audit.py settings`: the organization, repository, region and bucket are the
      test accounts', and nothing is "Not set".
- [ ] Rules: none turned off (`config/disabled_rules.yaml` lists none, or doesn't exist).
- [ ] `intern-bob` has **no** MFA device (the planned failure).
- [ ] In `.env`: `COMPLIANCELENS_POLICIES_DIR=policies/examples/ambiguous`, so DOC-01 to
      DOC-03 come out NEEDS REVIEW and there is something to review (decision D13). Remove
      the line after the demo.
- [ ] `make aitest`: "Both checks passed".
- [ ] PDF works on this computer: `brew install pango` once, then
      `make report RUN=run-NNNN FORMAT=pdf` on any finished run.
- [ ] A full rehearsal run, its PDF saved somewhere easy to open (the offline fallback), and
      the backup video downloaded.

## Thirty minutes before

- [ ] Sign in again (the AWS console login lasts 12 hours):
      `aws login --region us-east-1 --profile compliancelens`, `make login SITE=aws`,
      `make login SITE=github`.
- [ ] `make dashboard`, sign in, open **Run audit**: every line under "Before you run" is OK.
- [ ] In another browser profile, the AWS console signed in as an administrator, on
      IAM > Users > intern-bob > Security credentials (for the live fix).
- [ ] Notifications off, other windows closed, browser zoom at 100–125%.

## The demo

Expected first result, with the ambiguous policies: **15 PASS, 1 FAIL (AWS-02), 3 NEEDS
REVIEW (DOC-01 to DOC-03)**.

| # | Do | Say | About |
| --- | --- | --- | --- |
| 1 | **Run audit**, all boxes ticked; start it | 19 rules across AWS, GitHub, the HR list and policy documents; code where an API exists, the AI where only a picture or document does | while it runs (about 1.5 min): the rule card and the pipeline |
| 2 | **Results**: the score, then **AWS-02** | The raw API data names `intern-bob`; the screenshot shows the same table; the rule as this run read it; the suggested fix | 1 min |
| 3 | **Review queue**: **DOC-01** | The AI found contradicting lengths and refused to guess; a person decides, with a note; the audit's own result is never edited | 1 min |
| 4 | **Download PDF** on the Results page; open it | Cover with what was audited, failures first, the review with who and when, every file's SHA-256 in the appendix | 1 min |
| 5 | In the AWS console: **Assign MFA device** to intern-bob | The tool only reads; people fix | 1 min |
| 6 | **Run audit** again (a full run: Home scores only full audits) | AWS-02 is now PASS | while it runs: the research experiment's result |
| 7 | **History > Compare** the two runs | Exactly what changed, and why a comparison can be weaker (rulebook or settings changed) | 30 s |

Optional, if time: `make verify RUN=run-NNNN` in the terminal: every file still matches
its hash, reviews included.

## After the demo

- [ ] Remove intern-bob's MFA device again (the planned failure for next time).
- [ ] Remove the `COMPLIANCELENS_POLICIES_DIR` line from `.env`.

## If something goes wrong

| Problem | Do |
| --- | --- |
| AWS rules say NEEDS REVIEW with a credentials error | `aws login --region us-east-1 --profile compliancelens`, run again |
| Screenshots missing ("login expired") | Verdicts are unaffected: carry on and say so; or `make login SITE=aws` |
| No network, or the audit hangs | Open the saved rehearsal PDF; play the backup video from step 5 |
| "No PDF" | Download HTML instead (it is the same page) |

## Rehearsals

| Date | Took | Problems and fixes |
| --- | --- | --- |
| | | |
| | | |
