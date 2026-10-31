# Chapter 4: Project Design

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

This chapter presents the detailed design of ComplianceLens. Chapter 2 described what each
subsystem does, and Chapter 3 described the technologies used to build it. This chapter
explains how each part was designed: the commands and pages that users see, the structure
of a rule card, the way connectors and the AI evaluator work, and the layout of the stored
data. The running example, rule AWS-02, is used throughout to show each design in
practice.

## 4.1 Client Design

The client tier was designed around one idea: every result must be traceable back to
its evidence. Users can start an audit, see each verdict with its reason, and check the
evidence behind it, from either the command line or the dashboard.

### 4.1.1 CLI commands

The command-line interface offers seven commands (Table 4.1). The `run` command has
options that control how much of the tool is used. For example, `--no-screenshots` runs
only the API checks, and `--no-ai` turns off the AI, in which case the AI-judged rules
become NEEDS REVIEW instead of being guessed. A user can also run a single rule, such as
`audit.py run --rule AWS-02`, which is useful after fixing a setting.

> **Table 4.1 goes here. Caption:** "Table 4.1: CLI commands." Paste this table:

| Command | Purpose |
| --- | --- |
| `run` | Perform an audit. Options: `--rule` (only the named rules), `--no-screenshots`, `--no-ai`, `--cross-check` (the AI also reads code rules' screenshots and records whether it agrees), `--refresh-ai` (ask the AI again instead of using saved answers), `--ai-model` |
| `history` | List past runs with their verdict counts |
| `verify` | Check every evidence file of a run against its saved hash |
| `login` | Sign in to AWS or GitHub by hand once and save the session for screenshots |
| `report` | Export the audit report of a finished run as HTML, PDF or both |
| `settings` | Show and check what will be audited (company, AWS region, GitHub organization and repository) |
| `ai-test` | Confirm the AI model and key work, using one sample document and one sample screenshot with known answers |

The commands were designed to fail safely. Without any accounts set up, `run` still
completes: every rule becomes NEEDS REVIEW with a reason such as "GITHUB_TOKEN not set",
and the tool never crashes.

### 4.1.2 Dashboard pages and review workflow

The dashboard has eight pages:

- **Home** shows the score of the latest full audit, the number of results waiting for
  review, the AI cost, and the trend across past audits.
- **Run audit** starts an audit, shows its progress live, and lists anything missing, such
  as an expired login, together with the command that fixes it.
- **History** lists every run with its state and counts.
- **Results** shows one row per rule with its verdict, method, confidence and reason
  (Figure 4.1). It can be filtered by verdict, system and severity, and it offers the
  audit report for download.
- **Rule detail** shows everything about one result: the collected data, the screenshot,
  the AI's answer, the evidence hashes, and every review.
- **Review queue** lists the results still marked NEEDS REVIEW, so a reviewer can work
  through them one by one (Figure 4.2).
- **Compare** shows two runs side by side and highlights which verdicts changed.
- **Rules** lists the rulebook and lets a user turn rules on or off for future audits.

The review workflow was designed so that no decision is ever lost. A reviewer chooses a
verdict and must write a note explaining it. Each review is added as a new record and is
never edited or deleted, so the full history of decisions is kept, and the latest review
becomes the result's verdict. The original verdict from the audit always remains visible
next to it. Two further safeguards apply. First, a result marked NEEDS REVIEW can only
become PASS through an explicit choice by the reviewer, never through a single "approve"
click. Second, if someone else reviewed the same result after the form was opened, the
review is refused, so that two reviewers cannot overwrite each other.

> **Figure 4.1 goes here. Caption:** "Figure 4.1: The dashboard Results page."
> **Where to find it:** `compliance-lens/docs/images/dashboard-results.png` (from a
> made-up audit, so it shows no real account data).

> **Figure 4.2 goes here. Caption:** "Figure 4.2: The dashboard Review queue."
> **Where to find it:** `compliance-lens/docs/images/dashboard-queue.png`.

### 4.1.3 Audit report layout

The audit report was designed for an auditor who may not have access to the tool. It has
five parts:

1. **Cover:** the company, what was audited (AWS account, region, GitHub organization and
   repository), the score after review and as originally decided, the tool version, and a
   statement that the report supports an auditor but is not a compliance sign-off
   (Figure 4.3).
2. **Summary:** the verdict of every rule in one table.
3. **Findings:** the failures first, then the other results. Each finding shows the
   reason, an excerpt of the evidence, the AI's answer with the model name where an AI
   was used, the screenshot, and the suggested fix.
4. **Human reviews:** every review, with the verdict the tool decided kept visible.
5. **Appendix:** the SHA-256 hash of every evidence file, with instructions for checking
   them.

A report is fixed to a "review snapshot", meaning all reviews up to a given point. Its
file name records that point, for example `run-0042-r17.html` for run 42 with reviews up to
review 17. Because reviews are never edited, the same snapshot always produces the same
report. A later review produces a new file, and earlier reports are never overwritten.

> **Figure 4.3 goes here. Caption:** "Figure 4.3: The cover page of an audit report."
> **Where to find it:** take a screenshot of page 1 of
> `compliance-lens/docs/sample-report.pdf` (a made-up company, "Example Labs").

## 4.2 Middle-Tier Design

The middle tier was designed so that each concern has its own part: rule cards describe
the rules, connectors collect the evidence, and the evaluator judges it. This separation
keeps each part simple and allows it to be tested on its own.

### 4.2.1 Rule card schema and check operators

A rule card is a YAML entry with a fixed set of fields. Figure 4.4 shows the card for
AWS-02. The main fields are:

- `id`, `title`, `severity`: identify the rule and how serious a failure is.
- `framework_ref`: the matching item in a security standard, such as CIS AWS 1.10.
- `remediation`: the suggested fix that the report shows when the rule fails.
- `collector` and `params`: which connector function collects the evidence.
- `check`: the code test, made of a field, an operator and an expected value.
- `screenshot`: the page to capture, what to wait for, and what to hide (such as account
  numbers).
- `ai_check`: for AI-judged rules, the expected state and the written PASS, FAIL and
  REVIEW conditions the AI must follow.

The rule engine checks every card before the audit starts and rejects unknown fields, so a
misspelled field name is caught instead of being silently ignored. A check uses one of
seven operators (Table 4.2). This small set covers all 15 code-judged rules; only HR-01
needs a custom check, because it compares two lists of accounts.

> **Figure 4.4 goes here. Caption:** "Figure 4.4: The rule card for AWS-02."
> **Where to find it:** this is a trimmed copy of AWS-02 from
> `compliance-lens/rules/starter_rules.yaml`. Paste it in a monospace font (for example,
> Courier New) inside a bordered box, or take a screenshot of it.
>
> ```yaml
> - id: AWS-02
>   title: Every IAM user with a console password has MFA
>   framework_ref: CIS AWS 1.10
>   severity: high
>   remediation: >-
>     For each user named: IAM > Users > the user > Security credentials >
>     Assign MFA device. If the user doesn't need the console, remove their
>     console password instead.
>   collector: aws.users_without_mfa
>   check: { field: count, op: "==", value: 0 }
>   screenshot:
>     site: aws
>     url: "https://{region}.console.aws.amazon.com/iam/home?region={region}#/users"
>     mask:
>       - { pattern: "[0-9]{12}" }    # hide every 12-digit account ID
>   ai_check:
>     expect: "Every IAM user who has a console password also has an MFA device."
>     pass_if: ["Every user with a Password age shows an MFA device"]
>     fail_if: ["A user with a Password age shows no MFA device (a dash in the MFA column)"]
>     review_if: ["The MFA or Password age columns are not visible, cut off or still loading"]
> ```

> **Table 4.2 goes here. Caption:** "Table 4.2: Check operators." Paste this table:

| Operator | Meaning | Example rule |
| --- | --- | --- |
| `==` | The value equals the expected value | AWS-02: count of users without MFA == 0 |
| `>=` | The value is at least the expected value | AWS-01: minimum password length >= 12 |
| `<=` | The value is at most the expected value | (available for limits) |
| `in` | The value is one of a list | GH-06: base permission in [read, none] |
| `not_in` | The value is not one of a list | (available for forbidden values) |
| `contains` | A list contains the expected value | (available for required entries) |
| `all_true` | Every item in a list is true | AWS-05: every bucket blocks public access |

### 4.2.2 Connector interface and screenshot capture

Every connector follows the same simple interface. A rule card names a collector as
`system.function`, for example `aws.users_without_mfa`, and the engine calls that function
with the card's parameters. The function returns the collected data, such as
`{"count": 1, "users": ["intern-bob"]}` for AWS-02. Any problem, such as a missing token,
an access error or a network failure, becomes NEEDS REVIEW with a reason rather than
stopping the audit. To add a new system, a developer writes new collector functions; the
engine and evaluator need no changes.

The browser connector is designed differently because it supports the evidence rather
than providing it. For every rule with a `screenshot` block, it opens the page using the
saved login, waits for the setting to appear, scrolls to it if needed, hides sensitive
details, and adds a banner showing the rule, the time in UTC and the page address
(Figure 4.5). For safety, it can open only AWS and GitHub pages, and a rule card can only
make it wait, scroll or click a link; it can never type, tick a box or save a setting.
Every capture ends with one of nine statuses, such as "captured", "session expired" or
"access denied", so that a missing screenshot always comes with a clear reason.

> **Figure 4.5 goes here. Caption:** "Figure 4.5: A screenshot with its evidence banner
> (rule, time in UTC and page address)."
> **Where to find it:** open `compliance-lens/docs/sample-report.html` in a browser, go
> to the AWS-02 finding, and take a screenshot of its picture. It comes from the made-up
> audit, so it shows no real account data.

### 4.2.3 AI evaluator design

The AI evaluator was designed on the assumption that an AI answer can be wrong, so the
design focuses on deciding when an answer can be trusted. Each request to the model
contains three parts in a fixed order: the fixed instructions, then the evidence (the
screenshot or the document text), and finally the rule with its written PASS, FAIL and
REVIEW conditions. The instructions tell the model to treat the evidence as data, not as
instructions, so text inside a document such as "say PASS" is not obeyed.

The model must reply with one JSON object containing six fields: `verdict` (PASS, FAIL or
UNSURE), `confidence` (high, medium or low), `observed` (the value it read), `quote` (the
exact text it relied on), `evidence_found`, and `reason`. The reply is read strictly: any
missing field, wrong type or extra text is rejected, and nothing is repaired or guessed.
The answer then passes through a series of checks, and the first check that applies
decides the outcome (Table 4.3). Only an answer that passes every check is accepted as
PASS or FAIL. For documents, the quote must also appear word for word in the document,
which catches answers based on text the model invented.

Two further features control cost and keep results stable. Accepted answers are stored
in a cache and reused when the same evidence is judged again with the same rule, model and
prompt, so repeating an unchanged audit costs nothing and gives the same verdict. A
spending limit per run stops further AI calls once it is reached, and the remaining
AI-judged rules become NEEDS REVIEW. The prompt is versioned and never edited once used,
so every saved answer records exactly which prompt produced it.

> **Table 4.3 goes here. Caption:** "Table 4.3: How an AI answer becomes a verdict (the
> first row that applies decides)." Paste this table:

| Situation | Verdict |
| --- | --- |
| No evidence to send (document not read, screenshot not taken) | NEEDS REVIEW |
| AI turned off, no key set, or the spending limit reached | NEEDS REVIEW |
| The request failed after retries, or the model refused | NEEDS REVIEW |
| The reply was cut off or is not valid JSON in the required format | NEEDS REVIEW |
| The model answered UNSURE | NEEDS REVIEW |
| The model reported low confidence | NEEDS REVIEW |
| For a document: the policy never mentions the requirement (high confidence) | FAIL |
| PASS or FAIL, but the model reported finding no evidence | NEEDS REVIEW |
| For a document: the quote does not appear in the document | NEEDS REVIEW |
| For a screenshot: PASS or FAIL with no quote | NEEDS REVIEW |
| A clear PASS or FAIL with a quote and medium or high confidence | PASS or FAIL (accepted) |

## 4.3 Data-Tier Design

The data tier was designed so that every verdict can be checked later against the exact
evidence behind it. The database holds the records, and the evidence folder holds the
files.

### 4.3.1 Database schema

The database has five tables (Figure 4.6):

- **runs:** one row per audit, with its start and end time, state (running, complete or
  failed), scope (full or partial), tool version, verdict counts, AI cost, and the hash of
  the rulebook and manifest it used.
- **results:** one row per rule in a run, with the verdict, method, reason, confidence,
  and the path and hash of each evidence file.
- **overrides:** one row per human review, with the new verdict, the reviewer and the
  note. The database itself refuses any edit or deletion in this table.
- **ai_evaluations:** one row per AI answer, with the model, the answer fields, the cost,
  the time taken, and whether it came from the cache.
- **ai_cache:** the stored accepted answers, keyed by everything that could change an
  answer (evidence, rule wording, model, prompt version).

The design uses database rules to protect the data. Verdicts can only be PASS, FAIL or
NEEDS REVIEW, each rule appears only once per run, and every review must point to an
existing result. The database also records its schema version, currently version 4, and
upgrades itself when a newer version of the tool opens it.

> **Figure 4.6 goes here. Caption:** "Figure 4.6: Database schema."
> **Where to find it:** this is a new diagram. Paste the source below into
> https://mermaid.live and download the PNG.
>
> ```mermaid
> erDiagram
>     runs ||--o{ results : "has"
>     results ||--o{ overrides : "reviewed by"
>     results ||--o{ ai_evaluations : "judged by"
>     results ||--o{ ai_cache : "source of"
>     runs {
>         int id
>         text started_at
>         text status
>         text scope
>         text tool_version
>         int pass_count
>         int fail_count
>         int review_count
>         text manifest_sha256
>     }
>     results {
>         int id
>         int run_id
>         text rule_id
>         text verdict
>         text method
>         text reason
>         text confidence
>         text sha256
>     }
>     overrides {
>         int id
>         int result_id
>         text new_verdict
>         text reviewer
>         text note
>         text created_at
>     }
>     ai_evaluations {
>         int id
>         int result_id
>         text model
>         text verdict
>         text confidence
>         text quote
>         real cost_usd
>         int from_cache
>     }
>     ai_cache {
>         text cache_key
>         text rule_id
>         text model
>         text answer_json
>         int source_result_id
>     }
> ```

### 4.3.2 Evidence folder and manifest

Each run has its own folder, named by date and run number (Figure 4.7). For every rule, the
folder holds the raw data exactly as the connector returned it, a meta file with the
verdict and reason, and, where they exist, the screenshot, the policy document that was
read, and the AI's full answer. The folder also keeps a copy of the rulebook and the
settings as the run used them, so the run can be understood later even if the rules or
settings have since changed.

The manifest is the last file written. It lists every other file in the folder with its
SHA-256 hash, and its own hash is stored in the database. Each meta file also records the
hashes of the files that belong to its rule. Together, these records allow the `verify`
command to detect a changed, missing or added file.

> **Figure 4.7 goes here. Caption:** "Figure 4.7: The evidence folder of one run."
> **Where to find it:** paste the tree below in a monospace font (for example, Courier
> New) inside a bordered box, or take a screenshot of it.
>
> ```
> evidence/2026-10-20/run-0042/
> ├── AWS-02.json          raw data from AWS (users without MFA)
> ├── AWS-02.meta.json     verdict, reason, time, hashes of this rule's files
> ├── AWS-02.png           screenshot with its banner
> ├── DOC-01.source.pdf    the exact policy document that was read
> ├── DOC-01.ai.json       the AI's answer and every attempt
> ├── GH-07.ai-input.png   the exact picture sent to the AI
> ├── ...                  the same files for every other rule
> ├── rulebook.yaml        the rulebook as this run read it
> ├── run-context.json     the settings and targets this run used
> └── manifest.json        every file above with its SHA-256 hash
> ```

The next chapter explains how these designs were implemented and the main problems the
team solved along the way.
