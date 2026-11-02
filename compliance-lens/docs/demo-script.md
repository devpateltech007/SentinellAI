# Live demo script (V6)

About 6 minutes, following the Project Plan's final demo: run an audit, open the failure,
read its evidence, review an uncertain result, export the report, fix the failure live,
run again and see it change. Rehearse it twice, and keep the backup video and a saved
report ready in case the network or a login fails on the day.

## The week before

The live checks (V6 Stage 7) run weeks before the presentation, and the accounts, pages and
logins change in between, so check again:

- [ ] A full audit from the dashboard on the real accounts, its HTML and PDF export, and
      `make verify RUN=run-NNNN`. A changed GitHub or AWS page can break a screenshot's
      `wait_for`: harmless for the API rules, but GH-07 is judged only from its picture and
      would be NEEDS REVIEW.
- [ ] **AWS-08 is PASS.** `intern-bob` was created Oct 1, 2026 and never signs in, so from
      about Dec 31, 2026 AWS-08 FAILs for it (more than 90 days, counted from its creation).
      Sign in to the AWS console once as `intern-bob` (an admin can reset its password); the
      next credential report, up to 4 hours later, shows it. Otherwise the demo starts with
      14 PASS / 2 FAIL and the MFA fix leaves AWS-08 failing.
- [ ] Nothing expires before the presentation and the grading: the GitHub tokens (Settings >
      Developer settings > Fine-grained tokens; the organization-owned one the audit uses
      has no recorded end date), the AI key's credit, the AWS account's plan.
- [ ] **The DOC rules still come out NEEDS REVIEW.** The AI has no fixed temperature, and
      once it gives an accepted answer on the ambiguous policies, that answer is cached and
      every later run reuses it. Run
      `COMPLIANCELENS_POLICIES_DIR=policies/examples/ambiguous python audit.py run -r DOC-01 -r DOC-02 -r DOC-03 --refresh-ai`
      five times and count the NEEDS REVIEW; then once without `--refresh-ai`: a PASS or FAIL
      that says "cached from run-NNNN" means an answer was kept, so tick **Ask the AI again**
      on the day (these are partial runs: Home's score is unchanged).
- [ ] Time the PDF export of a real run (a real report carries every full-size screenshot)
      and keep that PDF as the offline fallback.
- [ ] Who presents which part and who drives the laptop; the room's network (bring a phone
      hotspot: picture uploads to the AI often dropped on the home network, V4 D11) and its
      projector.
- [ ] Two timed rehearsals of the whole presentation, logged under "Rehearsals".

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

Run options: **screenshots** and **the AI** ticked. Leave **cross-check** unticked (more
picture uploads, and it never changes a verdict) and **ask the AI again** unticked (GH-07
then comes from the cache), unless the week-before check found a cached DOC answer.

Start the first audit while presenting the architecture, and the second one while
presenting the experiment: each takes about 1.5 minutes.

| # | Do | Say | About |
| --- | --- | --- | --- |
| 1 | **Run audit** with the options above; start it | 19 rules across AWS, GitHub, the HR list and policy documents; code where an API exists, the AI where only a picture or document does | while it runs (about 1.5 min): the rule card and the pipeline |
| 2 | **Results**: the score, then **AWS-02** | The raw API data names `intern-bob`; the screenshot shows the same table; the rule as this run read it; the suggested fix | 1 min |
| 3 | **Review queue**: **DOC-01** | The AI found contradicting lengths and refused to guess; a person decides, with a note; the audit's own result is never edited | 1 min |
| 4 | **Download PDF** on the Results page; open it | Cover with what was audited, failures first, the review with who and when, every file's SHA-256 in the appendix | 1 min |
| 5 | In the AWS console: **Assign MFA device** to intern-bob | The tool only reads; people fix | 1 min |
| 6 | **Run audit** again (a full run: Home scores only full audits) | AWS-02 is now PASS; DOC-01 to DOC-03 are in the queue again (a review belongs to the audit it was made on) | while it runs: the research experiment's result |
| 7 | **History > Compare** the two runs | Exactly what changed, and why a comparison can be weaker (rulebook or settings changed). DOC-01 is listed as changed too: reviewed in the first audit, not yet in the second | 30 s |

Step 5 shows intern-bob's MFA QR code, which is a secret: blur it in the video (the device
is removed after the demo anyway). "Why review again every audit?" is a likely question:
the evidence is new each time, so an old review never decides a new result.

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
| The AI decided a DOC rule (PASS or FAIL), so the queue is empty | Open DOC-01 from **Results**, show the AI's quote and reason, and review it there |
| AWS-08 also FAILs | intern-bob was not signed in (see "The week before"): say it is the inactive-user rule working, and carry on |
| GH-07 is NEEDS REVIEW | Its screenshot failed (login or page change): the API rules are unaffected; review it as the uncertain result |

## Rehearsals

| Date | Took | Problems and fixes |
| --- | --- | --- |
| | | |
| | | |
