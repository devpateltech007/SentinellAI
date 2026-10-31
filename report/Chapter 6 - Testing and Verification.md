# Chapter 6: Testing and Verification

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

This chapter describes how the team confirmed that ComplianceLens behaves correctly. A
compliance tool must be trusted not to report a broken setting as compliant, so testing
focused on two questions: does each rule give the correct verdict in both its compliant and
non-compliant states, and does every failure of the tool itself lead to NEEDS REVIEW rather
than PASS? The chapter first presents the overall strategy, then the automated tests, and
finally the live checks carried out on real AWS and GitHub accounts.

## 6.1 Testing Strategy

The testing strategy has two layers. The first layer is a large set of automated tests that
run offline. These tests never touch a real account: AWS is simulated with moto, a library
that imitates AWS services; GitHub replies are loaded from saved response files; screenshots
are taken of a small fake website served on the test computer; and the AI is replaced by a
fake model that returns prepared answers. During tests, all real network access is blocked,
so a test cannot reach a real service by mistake. As a result, the tests are fast, free and
can be run by anyone without accounts or keys.

The second layer is live verification on the team's own AWS free-tier account and GitHub
organization. Live checks confirm what offline tests cannot, such as whether the real AWS
and GitHub pages still match the tool's expectations.

The automated tests run on every change through GitHub Actions, a continuous integration
(CI) service. Each run checks the code style with the ruff linter, runs the full test suite
including real PDF rendering and a real Chromium browser, and confirms that the packaged
tool contains all its files. CI fails if test coverage falls below 70%; in practice, the
team kept coverage at 100% of the code throughout the project. In addition, a pre-commit
check scans every commit for secrets, such as tokens or keys, and blocks the commit if one
is found. At the end of development the suite contained 1,573 tests. Table 6.1 summarizes the
types of test.

> **Table 6.1 goes here. Caption:** "Table 6.1: Types of test." Paste this table:

| Test type | What it checks | Tool |
| --- | --- | --- |
| Unit | Each check operator, each rule's verdict logic, rulebook validation | pytest |
| Connector (AWS) | Every AWS rule in both its compliant and non-compliant state | pytest with moto |
| Connector (GitHub) | Every GitHub rule against saved GitHub replies, including errors | pytest with saved responses |
| Screenshot | Capture, banners, masking, expired login and "no access" pages | Playwright with a fake local website |
| AI safety | Every way an AI answer can be bad becomes NEEDS REVIEW | pytest with a fake AI model |
| Evidence integrity | `verify` catches edited, deleted and added files | pytest |
| Dashboard | Every page, sign-in, form protection, reviews, safe file serving | FastAPI test client and real Chromium |
| Golden report | The same saved run always produces the same report | pytest |
| Live | Real verdicts, break-and-fix, failure modes | Manual runs on the team's accounts |

## 6.2 Automated Testing

The automated tests are grouped into three areas: the rules and connectors that produce
verdicts, the AI evaluator, and the evidence and reports that record them.

### 6.2.1 Unit and connector tests

Unit tests cover the rule engine. Every check operator is tested with normal, empty and
wrong inputs, every path to a verdict is tested, and rulebook validation is tested with
broken rule cards to confirm that each mistake is caught before an audit starts.

Connector tests check every rule in both states. For the running example AWS-02, moto
creates a simulated AWS account with a console user who has MFA, and the test expects PASS;
it then adds a console user without MFA, and the test expects FAIL with that user named. A
user who has no console password is also added, to confirm that such users are correctly
ignored. The GitHub tests use saved replies for each state, as well as for error cases such
as a missing token, an unknown organization, a "not found" reply and GitHub's rate limit.
The screenshot tests start a real Chromium browser against a fake website that imitates a
settings page, an expired login, an MFA prompt and an "access denied" page, and confirm that
each produces the correct status.

### 6.2.2 AI safety tests

The AI safety tests confirm the most important property of the evaluator: a bad or unclear
AI answer never becomes PASS. A fake AI model returns prepared replies, and one test covers
each row of Table 4.3. The cases include a missing key, an exhausted spending limit, a
failed request with retries, a refusal, a reply that was cut off, invalid JSON, an UNSURE
answer, a low-confidence answer, and a quote that does not appear in the document. Each must
produce NEEDS REVIEW with the correct reason.

Further tests check that text inside the evidence cannot control the verdict. Policy
documents are inserted into the prompt in a way that prevents them from imitating the rule
or the instructions, and the prompt itself is frozen: a test fails if the version 1 prompt
is changed, so every saved answer remains linked to the exact prompt that produced it. The
AI provider adapters are tested against fake web replies, and the cache is tested to confirm
that a changed screenshot, rule wording or model always leads to a new AI call.

### 6.2.3 Evidence integrity and report tests

The evidence tests confirm that `verify` detects tampering. Each test creates a run, then
edits, deletes or adds a file, including screenshots, documents and AI answers, and checks
that `verify` reports the problem. Other tests confirm that the database refuses any attempt
to edit or delete a result or a review, and that databases created by earlier versions of
the tool upgrade correctly without losing data.

The report is tested with a "golden" file. A made-up audit for a fictional company,
"Example Labs", is created with a fixed clock, and its HTML report is compared with a saved
copy of the expected report. Any change to the report's content or layout makes the test
fail until the expected copy is deliberately updated. The PDF tests render real PDFs with
WeasyPrint and confirm that the PDF cannot load any outside file or web address. The sample
report included with the project is checked in the same way, so it can never fall out of
date.

## 6.3 Live Verification

Offline tests prove that the logic is correct, but only live runs prove that the tool works
against the real services. The team carried out live checks at the end of every version.

### 6.3.1 Break-and-fix routine

The break-and-fix routine proves that the tool actually examines each setting rather than
always returning the same verdict. For a rule, the team changed the real account so that
the rule should fail, ran the audit, confirmed the verdict was FAIL, restored the setting,
and confirmed the verdict returned to PASS. For AWS-02, the team created a test user,
`intern-bob`, with a console password and no MFA. Every live audit correctly reported FAIL
and named this user. The final demonstration is planned to fix it live and show the rule
turning to PASS.

Not every rule could be broken safely on a real account (Table 6.2). Turning off MFA on the
AWS root account is risky, and some rules, such as AWS-04 (access keys older than 90 days),
would take 90 days to fail naturally. For these rules, the FAIL state was proven with
simulated data in the automated tests. The research experiment (Section 7.2) added a
further live check: its setup changed the real accounts 55 times to create known states for
five rules, and the code's verdict matched the state that was set up in all 55 cases.

> **Table 6.2 goes here. Caption:** "Table 6.2: Break-and-fix results by rule." Paste
> this table:

| How FAIL was proven | Rules | Result |
| --- | --- | --- |
| Broken and fixed live on the real accounts | AWS-01, AWS-02, GH-01, GH-06, GH-07 | Verdict flipped as expected each time |
| Live with sample policy documents (compliant, non-compliant, ambiguous, silent, prompt injection) | DOC-01, DOC-02, DOC-03 | PASS, FAIL, NEEDS REVIEW, FAIL and FAIL respectively, as expected |
| Simulated data (unsafe to break, or takes 90 days) | AWS-03, AWS-04, AWS-08, GH-05 | FAIL proven by automated tests; PASS confirmed live |
| Automated tests (live flip judged unnecessary) | AWS-05, AWS-06, AWS-07, GH-02, GH-03, HR-01 | FAIL proven by automated tests; PASS confirmed live |
| Live flip still planned | GH-04 | PASS confirmed live; flip scheduled for final acceptance |

### 6.3.2 Real audit runs and failure modes

The team ran full audits on the real accounts as each version was completed (Table 6.3).
Every audit produced the expected verdicts: AWS-02 failed because of the planned test user,
and every other rule passed, except the two screenshot-only rules in version 3, which went
to review because the AI had not yet been added. Every run's evidence passed
`verify`. The audit in version 5 (`run-0042`) was started from the dashboard as part of an
acceptance test. In the same test, a second audit (`run-0043`) was run with the AI turned
off, which sent the five AI-judged rules to the review queue. The team reviewed them in
the dashboard, setting one to PASS and keeping one open with a note, then turned a rule
off, restarted the dashboard to confirm that nothing was lost, and compared the two runs.
The second run still passed `verify` after the reviews were added.

> **Table 6.3 goes here. Caption:** "Table 6.3: Real audit runs." Paste this table:

| Run | Version (date) | Rules | PASS / FAIL / NEEDS REVIEW | Notes |
| --- | --- | --- | --- | --- |
| run-0001 | V2 (Oct 4) | 14 | 13 / 1 / 0 | First real audit; 28 evidence files verified |
| run-0004 | V3 (Oct 7) | 16 | 13 / 1 / 2 | 15 screenshots; the 2 screenshot-only rules went to review (no AI yet) |
| run-0010 | V4 (Oct 11) | 19 | 18 / 1 / 0 | With the AI: 5 AI calls, $0.0010 |
| run-0011 | V4 (Oct 11) | 19 | 18 / 1 / 0 | Same audit repeated; all AI answers from the cache, $0 |
| run-0042 | V5 (Oct 20) | 19 | 18 / 1 / 0 | Started from the dashboard; 1 min 29 s; 71 files verified |

The team also caused failures on purpose to confirm that each is handled safely:

- **Missing login:** with no saved logins, the code-checked rules kept their verdicts, the
  screenshot-only rule became NEEDS REVIEW, and the fix was printed.
- **Changed web page:** with a deliberately wrong page locator, the screenshot was reported
  as "did not appear within 20 seconds", and the rule's verdict was unchanged.
- **Expired AWS login:** more than 12 hours after signing in, the tool recognized the AWS
  sign-in page, kept the verdict, and saved no misleading screenshot.
- **Tampered evidence:** on a backup copy of a run, editing a screenshot and an AI answer
  each made `verify` fail, naming the file in the manifest, the database and the meta file;
  restoring the file made it pass again.
- **AI problems:** a missing key, an unknown model, an unreachable server and a very low
  spending limit each produced NEEDS REVIEW with the reason, and the run was still saved
  and verified.

These checks confirmed the central design principle in practice: whenever the tool could
not be certain, it said so, and it never reported a PASS it could not support.

The next chapter measures how quickly and cheaply the tool runs, and presents the research
experiment on how accurately the AI judges screenshots compared with code.
