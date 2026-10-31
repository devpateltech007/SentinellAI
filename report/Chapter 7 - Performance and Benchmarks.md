# Chapter 7: Performance and Benchmarks

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text. The four figures for this chapter are ready as PNG files in
> `report/figures/`.

This chapter measures ComplianceLens in two ways. Section 7.1 reports how long an audit
takes and how much it costs to run. Section 7.2 presents the project's research
experiment, which measured how accurately an AI model judges a compliance setting from a
screenshot compared with code reading the same setting through the API.

## 7.1 Runtime and Cost

A compliance tool is only practical if audits are quick enough to run often and cheap
enough to run on every change. The project set a target of under two minutes for a full
audit and a spending limit well within a student budget.

### 7.1.1 Audit run time

The full audit whose run time was recorded, `run-0042`, completed all 19 rules in
**1 minute 29 seconds**
(Table 7.1). This run was started from the dashboard with every option turned on: it took
screenshots, asked the AI for new answers instead of reusing saved ones, and also asked the
AI to cross-check the screenshots of code-judged rules. It therefore represents the slowest
normal case, and it met the two-minute target.

Most of an audit's time is spent on screenshots and AI calls rather than on API checks.
Capturing the 15 screenshots of the version 3 audit took 31 seconds, and an AI answer took
3.9 seconds on average in the research experiment. With eight AI calls in `run-0042`,
screenshots and AI together account for roughly two thirds of its run time. An audit with
screenshots turned off, or one that reuses saved AI answers, is correspondingly faster.
Since version 6, the tool logs how long each rule takes to collect, capture and judge, and
prints the three slowest rules after each audit, so any slow rule can be identified
directly.

> **Table 7.1 goes here. Caption:** "Table 7.1: Run time and AI cost of real audits and
> the experiment." Paste this table:

| Run | What ran | Time | AI calls | AI cost |
| --- | --- | --- | --- | --- |
| run-0010 (V4) | 19 rules, screenshots, AI | not measured | 5 | $0.0010 |
| run-0011 (V4) | Same audit repeated | not measured | 5, all from the cache | $0.0000 |
| run-0042 (V5) | 19 rules, screenshots, AI with new answers and cross-check | 1 min 29 s | 8 | $0.0018 |
| Experiment main run | 55 pictures, 3 answers each | 3.9 s per answer | 165 | $0.0542 |

*The version 4 runs did not record their run time; per-rule timing was added to the log in
version 6.*

### 7.1.2 AI cost and caching

The AI cost of an audit is very small. A normal audit in version 4 (`run-0010`) made five
AI calls, one for each AI-judged rule at the time (GH-06, GH-07 and the three policy
documents), and cost $0.0010. Since GH-06 moved to a code check in version 6, a normal
audit makes four. The audit with cross-checking made eight calls for $0.0018. Even the
research experiment, which made 165 AI calls on large screenshots, cost $0.0542 in total,
or about $0.0003 per answer. These low costs are the result of choosing an inexpensive
model after testing (Section 3.2.3). All the AWS services the tool reads are covered by the
AWS free tier, and GitHub is free, so the AI is the only running cost.

Two features keep this cost predictable. First, the AI cache stores every accepted answer
and reuses it when the same evidence is judged again with the same rule, model and prompt.
When the audit was repeated without changes (`run-0011`), all five answers came from the
cache, the cost was zero, and the verdicts were identical. Second, a spending limit per
run (by default $2) stops further AI calls once it is reached. In a live test with a limit
of $0.0045, the fourth AI call was refused, that rule became NEEDS REVIEW with the reason,
and the run was still saved and verified.

## 7.2 Research Experiment: AI versus Code Accuracy

The research experiment is the project's main academic contribution. It measures, on real
accounts, how far an AI judgment of a screenshot can be trusted when compared with an
exact code check.

### 7.2.1 Research question and hypothesis

The research question was: **for rules that can be checked both ways, how accurately does
an AI judge a setting from a screenshot, compared with code reading the same setting from
the API? And when the AI cannot tell, does it say so rather than guess?**

Before the experiment, the team wrote down a four-part hypothesis to be confirmed or
rejected:

1. Code checks match the human labels in nearly every case.
2. AI judgments of screenshots are less accurate than code.
3. Most AI errors occur on long pages and ambiguous pages.
4. Sending low-confidence AI answers to review reduces false PASS results.

### 7.2.2 Experiment design

The experiment used five rules that have both an API value and a settings page: AWS-01
(password length), AWS-02 (MFA for console users), AWS-05 (S3 public access), GH-01
(branch review) and GH-06 (base repository permission). For these rules, the team created
**55 cases**, each a screenshot of a known account state (Table 7.2). Forty were plain
cases, with eight per rule split evenly between compliant and non-compliant. Fifteen were
hard cases designed to challenge the AI, such as a dark theme, small text, a setting below
the visible area, a pop-up covering the setting, and pages containing a hidden instruction
to "say PASS" (prompt injection).

For each case, a setup script changed the real test account to create the required state.
The tool's read-only API access then confirmed the state twice before the screenshot was
taken, and once more afterwards. If the state had changed in between, the case was
discarded and captured again; this happened once. All settings were restored after each
batch.

Two team members then labelled every screenshot separately, seeing only the picture and
the rule's written conditions, not the setup or the API data. Each label stated what the
picture shows: PASS, FAIL or REVIEW (cannot be decided from the picture). The two labellers
agreed on 54 of the 55 pictures, a Cohen's kappa [12] of 0.97, which indicates almost
perfect agreement on the commonly used scale of Landis and Koch [13]. The one disagreement
was settled together. The final labels were saved before the AI was run and were not
changed afterwards.

Finally, the AI model `openai/gpt-6-luna` judged each picture **three times**, each time as
a fresh request with no cache, giving 165 answers in total. The AI used the same prompt and
the same safety rules as in a normal audit.

> **Table 7.2 goes here. Caption:** "Table 7.2: The 55 experiment cases." Paste this table:

| Kind of case | Cases | Purpose |
| --- | --- | --- |
| Plain | 40 | 8 per rule: 4 compliant and 4 non-compliant |
| Small text | 5 | Setting shown in a small font |
| Dark theme | 2 | Page shown in dark mode |
| Below the fold | 2 | Setting outside the visible part of the page |
| Prompt injection | 2 | A user or bucket name telling the AI to "say PASS" |
| Setting covered | 1 | A pop-up covering the setting |
| Unclear on purpose | 3 | A page still loading, a page without the login, a menu left open |
| **Total** | **55** | Final labels: 21 PASS, 30 FAIL, 4 REVIEW |

### 7.2.3 Metrics

Each AI answer was compared with the case's label. The most important metric is the
**false PASS rate**: the share of non-compliant pictures that the AI called PASS. A false
PASS tells an auditor that a broken setting is fine, which is the most dangerous error a
compliance tool can make. A false FAIL is inconvenient but safe, because a person will look
and find nothing wrong. Table 7.3 defines all the metrics. Because the samples are small,
every rate was reported with a 95% confidence interval calculated with the Wilson score
method [14], which remains reliable for small samples.

> **Table 7.3 goes here. Caption:** "Table 7.3: Metrics." Paste this table:

| Metric | What it counts |
| --- | --- |
| Accuracy | Answers that match the label, out of all answers |
| Decided accuracy | Correct PASS or FAIL answers, out of all PASS or FAIL answers on clear pictures |
| False PASS rate | PASS answers on pictures labelled FAIL |
| False FAIL rate | FAIL answers on pictures labelled PASS |
| Review recall | NEEDS REVIEW answers on pictures labelled REVIEW |
| Consistency | Cases whose three answers all agree |
| Cost and time | US dollars and seconds per answer |

### 7.2.4 Results and analysis

Table 7.4 summarizes the results. The AI's answers are compared both with the labellers'
labels and with the **set-up state**, meaning what the setup actually made true in the
account. Both comparisons are reported because, as explained below, they differ on two
pictures.

> **Table 7.4 goes here. Caption:** "Table 7.4: Overall results of the AI (165 answers)."
> Paste this table:

| Metric | AI compared with the labels | AI compared with the set-up state |
| --- | --- | --- |
| Accuracy | 93% (154 of 165) | 90% (148 of 165) |
| Decided accuracy | 95% (142 of 149) | 99% (148 of 149) |
| False PASS rate | 7% (6 of 90) | 0% (0 of 84) |
| False FAIL rate | 2% (1 of 63) | 1% (1 of 81) |
| Review recall | 100% (12 of 12) | not applicable |
| Consistency | 96% of cases (53 of 55) | 96% of cases (53 of 55) |

*Accuracy against the set-up state is lower because the set-up state is never REVIEW, so
the AI's correct NEEDS REVIEW answers on unclear pictures count as undecided there.*

**Accuracy by rule.** The AI was correct on every answer for AWS-01 and GH-01, and at or
above 92% for AWS-05 and GH-06 (Figure 7.1). GH-01 had the longest pictures, full pages up
to 2,119 pixels tall, and the AI was still correct 33 times out of 33. The weakest rule
was the running example, AWS-02, at 79%.

> **Figure 7.1 goes here. Caption:** "Figure 7.1: AI accuracy by rule, compared with the
> labels."
> **Where to find it:** `report/figures/accuracy-by-rule.png` (made from
> `compliance-lens/docs/figures/accuracy-by-rule.svg`).

**The false PASS results.** All six false PASS answers came from two AWS-02 pictures
(Figure 7.2). In these pictures, one test user had neither a password nor an MFA device,
so both columns showed a dash. The rule's written condition was "FAIL if a user with a
Password age shows no MFA device". Because this user had no password age, the rule's
wording, the setup and the code all give PASS, and the AI answered PASS all six times with
the same reasoning. Both labellers, however, read the dash in the MFA column as a user
without MFA and labelled the pictures FAIL. Against the labels, the AI therefore has a
false PASS rate of 7%; against what was actually true in the account, it has none (Figure
7.3). In this case, the AI followed the rule's written condition more closely than the two
people did. The lesson concerns the rule as much as the AI: a condition that careful
readers interpret differently should be reworded.

> **Figure 7.2 goes here. Caption:** "Figure 7.2: The AWS-02 picture behind the false PASS
> answers. User 1 shows a dash for both MFA and Password age (user names covered)."
> **Where to find it:** `report/figures/example-aws02-no-console.png` (copied from
> `compliance-lens/docs/figures/`).

> **Figure 7.3 goes here. Caption:** "Figure 7.3: False PASS and false FAIL rates,
> compared with the labels and with the set-up state."
> **Where to find it:** `report/figures/false-pass-fail.png`.

**Hard cases and unclear pictures.** The hard cases were not where the AI made mistakes
(Figure 7.4). It read every dark-theme and small-text picture correctly and never obeyed
the prompt injections, answering FAIL as labelled each time. On every picture that could
not be judged, such as a setting below the visible area, a covered setting or a page
without the login, the AI answered NEEDS REVIEW: 12 of 12 answers, and never PASS. The
remaining errors were one misread, in which the AI once reported a missing MFA device that
the picture did show, and four cautious NEEDS REVIEW answers on pictures that the labellers
considered clear.

> **Figure 7.4 goes here. Caption:** "Figure 7.4: What the AI answered, by kind of
> picture."
> **Where to find it:** `report/figures/review-by-kind.png`.

**Confidence and the code.** The model's confidence did not help to catch errors. It never
reported low confidence, and all six false PASS answers had high confidence. The code
check, reading the API data saved with each picture, matched the set-up state in all 55
cases. Table 7.5 summarizes which parts of the hypothesis held.

> **Table 7.5 goes here. Caption:** "Table 7.5: Which parts of the hypothesis held."
> Paste this table:

| Hypothesis | Held? | Evidence |
| --- | --- | --- |
| 1. Code matches the labels in nearly every case | Yes | 49 of 51 clear pictures; 55 of 55 against the set-up state. The 2 differences are the AWS-02 wording disagreement, where the code follows the rule |
| 2. AI is less accurate than code | Partly | Lower, but only slightly: per case, the AI's decided accuracy was 96%, the same as the code's, but it decided fewer clear cases and misread one picture once |
| 3. Most AI errors occur on long and ambiguous pages | Partly | Not long pages (GH-01 was 33 of 33). Ambiguous pages went to NEEDS REVIEW, never to a wrong PASS. Most errors were on one ordinary page, the AWS-02 users table |
| 4. Sending low-confidence answers to review reduces false PASS | No | The model never gave low confidence, and all 6 false PASS answers had high confidence |

The experiment supports the design of ComplianceLens. Where an API exists, code should
decide, because it was correct in every case, costs nothing and always gives the same
answer. Where only a screenshot or a document exists, the AI is useful, because it handled
difficult pictures well and sent every unclear picture to review. However, every AI
decision still needs a human check, because its confidence gave no warning of its errors.
As a direct result of the experiment, rule GH-06 was moved from AI judgment to a code check
in version 6, since its value is available through the API.

### 7.2.5 Limitations

The results should be read with the following limitations in mind:

- **Small sample.** With 55 cases, the confidence intervals are wide. Counting each case
  once, the false PASS rate against the labels could lie anywhere between 2% and 21%, and
  each kind of hard case has only one to five examples.
- **Repeated answers are not independent.** The three answers for a case look at the same
  picture, so the 165 answers are not 165 independent tests.
- **One model, one prompt, one day.** Another model, or the same model at a later date,
  may perform better or worse.
- **One AWS account and one GitHub organization.** Both consoles change their pages over
  time, so future screenshots may be read differently.
- **Two labellers.** On two AWS-02 pictures, their labels differ from the rule's written
  condition. Both readings are reported, and the labels were not changed after the AI
  answered.
- **Simple settings.** Each of the five rules shows one value per page. Harder judgments
  may produce more errors.
- **Rules with an API.** The experiment compared the AI with code on rules where code is
  always available. It does not directly measure the AI on evidence that has no API, which
  is its main use in the tool.

The next chapter describes how ComplianceLens is installed, configured, operated and
maintained.
