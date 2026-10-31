# Chapter 8: Deployment, Operations, Maintenance

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

This chapter describes how ComplianceLens is installed and configured, how it is used to
run an audit and review the results, and how it can be maintained as rules, systems and web
pages change. ComplianceLens is designed to run on a single computer, such as an auditor's
or administrator's laptop, rather than as a hosted service. This keeps the evidence and the
saved logins on a machine the user controls.

## 8.1 Deployment

Deployment consists of installing the tool, connecting it to the accounts it will audit,
and stating what it should audit. Each step is documented in the project's README files,
and the tool checks the result of each step before an audit begins.

### 8.1.1 Setup and installation

ComplianceLens runs on macOS or Linux and requires Python 3.11 or newer, git, and version 2
of the AWS command-line tool. A single command, `make setup`, creates an isolated Python
environment, installs the exact library versions the project was tested with, installs the
Chromium browser used for screenshots, and installs the pre-commit secret scan. PDF reports
also need the Pango text library, which is installed separately; without it, everything
else works, including the HTML report, and a request for a PDF explains how to install it.
Running `make test` then confirms that the installation works, without needing any
account.

Connecting the tool to real accounts takes a few further steps:

1. **AWS:** create a dedicated IAM user with only the read-only SecurityAudit policy and no
   access keys, and sign in with `aws login`.
2. **GitHub:** create a fine-grained token owned by the organization, limited to the
   audited repository, with read-only permissions.
3. **HR list:** fill in a CSV file that maps each active employee to their AWS user and
   GitHub login.
4. **Screenshots:** sign in once by hand to AWS and GitHub with `make login`, so that the
   browser sessions can be saved.
5. **AI:** choose a model and enter its key, then run `make aitest` to confirm it works.
6. **Dashboard:** set a password.

The tool can be used before all of these steps are complete. Any rule whose account or key
is missing becomes NEEDS REVIEW with a reason, such as "GITHUB_TOKEN not set", so a
partly configured tool never crashes and never reports a false PASS.

### 8.1.2 Configuration and secrets

Configuration is split across a small number of files, each with one purpose (Table 8.1).
Secrets, such as the GitHub token, the AI key and the dashboard password, are kept only in
the `.env` file. The audit targets, such as the company name, the AWS region and the GitHub
organization and repository, are kept in `config/settings.yaml`. Each value has one home,
and conflicts are reported rather than resolved silently: a GitHub organization set
differently in `.env` and in the settings file is an error, and a different AWS region is
a warning, with the settings file taking precedence. The `python audit.py settings` command shows
what will be audited and where each value came from.

Because the tool handles sensitive data, it applies the same controls it checks for in
others:

- **Read-only access.** The AWS user and GitHub token cannot change any setting.
- **Secrets out of the code.** The `.env` file, saved logins, evidence, reports, the HR
  list and the database are all excluded from git. A secret scan runs before every commit
  and blocks any commit that contains a token or key.
- **Secrets out of the logs.** Tokens, keys, passwords and AWS account numbers are replaced
  with `[hidden]` in every log line.
- **Saved logins protected.** A saved browser login works like a password, so the files are
  readable only by the user who created them and are never printed, logged or stored with
  the evidence.
- **Evidence kept local.** Evidence can contain user names and account details, so it stays
  on the user's computer. Screenshots hide account numbers, and the HR evidence holds only
  account names. The only data sent outside is what the AI must read: GH-07's screenshot
  and the policy documents. A local AI model can be used to keep even these on the
  computer.

> **Table 8.1 goes here. Caption:** "Table 8.1: Configuration files." Paste this table:

| File | Contents | Written by | Kept in git? |
| --- | --- | --- | --- |
| `.env` | Secrets: GitHub token, AI model and key, dashboard password, AWS profile name | The user | No |
| `config/settings.yaml` | What to audit: company, AWS region, GitHub organization, repository and branch, HR list location | The user | No (an example copy is) |
| `config/disabled_rules.yaml` | Rules turned off for future audits | The dashboard's Rules page | No |
| `data/employees.csv` | Active employees with their AWS user and GitHub login | The user | No (an example copy is) |
| `sessions/` | Saved browser logins for screenshots | The `login` command | No |
| `rules/starter_rules.yaml` | The rulebook: all 19 rule cards | The project | Yes |

## 8.2 Operations

Day-to-day use consists of running audits, reviewing the results that need a person's
decision, and exporting reports for auditors.

### 8.2.1 Running an audit

An audit can be started from the command line with `make audit`, or from the dashboard's
Run audit page. Before starting, the dashboard lists anything missing, such as an expired
AWS login or a missing AI key, together with the exact command that fixes it. The
command line prints each rule's verdict and reason as it runs, then a summary of the
totals, the screenshots saved, the AI calls and their cost, and the command to verify the
evidence later. Only one audit can run at a time; a second one is refused with a message
naming the audit that is already running.

The running example shows a typical cycle. A full audit reports AWS-02 as FAIL, naming the
user `intern-bob`, who has a console password but no MFA device. The administrator assigns
an MFA device to that user, following the suggested fix shown with the result, and then
re-runs only that rule with `python audit.py run --rule AWS-02`. The rule now shows PASS.
Because this run did not include every rule, it is recorded as "partial", and the
dashboard's score continues to come from the latest full audit until the next one is run.

Other options cover common situations. When the browser logins have expired and an audit
is needed immediately, `--no-screenshots` runs only the API checks. When no AI calls should
be made, `--no-ai` sends the AI-judged rules to review instead. The `make history` command
lists past runs, and `make verify` checks that a run's evidence is unchanged.

### 8.2.2 Reviewing results and exporting the report

Results marked NEEDS REVIEW appear in the dashboard's Review queue. For each one, the
reviewer opens the Rule detail page, examines the evidence and the reason, chooses a
verdict, and writes a note explaining the decision. A reviewer can also confirm a PASS or
FAIL decided by the tool. Reviews are added, never edited, and the original verdict stays
visible, so the record shows both what the tool decided and what the person decided. The
Compare page shows how verdicts changed between two runs, for example after a fix.

When the review is complete, the audit report is exported from the Results page with
**Download HTML** or **Download PDF**, or from the command line with `make report
RUN=run-0042`. The report is built only from the saved run, so it can be produced offline
and gives the same result every time. If a reviewer adds a review after a report has been
exported, the next export creates a new file, such as `run-0042-r18.html`, and the earlier
report is kept unchanged. The tool refuses to export a run that is unfinished or whose
evidence fails verification.

## 8.3 Maintenance

ComplianceLens was designed so that the most common maintenance tasks, adding rules and
adapting to changed web pages, require editing data files rather than program code.

### 8.3.1 Adding rules and connectors

A new rule for a system that is already supported needs only a new rule card. The author
writes the card in the rulebook, naming an existing collector and stating the check, and
optionally adds a screenshot block and a suggested fix. The rule engine validates the card
before the next audit and rejects missing, unknown or misspelled fields with a clear
message, so a mistake cannot produce a wrong verdict. Rules judged by AI follow the same
pattern: the author writes the expected state and the PASS, FAIL and REVIEW conditions in
plain words. As the research experiment showed (Section 7.2.4), these conditions must be
written so that they cannot be read in two ways.

A new system, such as Okta or Google Workspace, needs a new connector: a Python module with
one function per piece of data, each returning a simple dictionary. The engine, evaluator,
database, dashboard and report need no changes. Each new collector should come with tests
for both the compliant and the non-compliant state, using simulated or saved responses, in
the same way as the existing AWS and GitHub tests.

### 8.3.2 Handling API and interface changes

The systems that ComplianceLens audits change over time, and the tool is built to report
such changes instead of hiding them. The most frequent change is to web pages. When AWS or
GitHub changes a settings page, the screenshot step can no longer find the expected
content and reports that it "did not appear within 20 seconds". The rule's verdict is not
affected, because it comes from the API. The fix is to update the rule card's `wait_for`
and `steps` fields to match the new page, with no change to the code.

API changes are less frequent. If an API reply no longer contains the expected field, the
rule becomes NEEDS REVIEW with the reason, rather than PASS. Temporary problems, such as
GitHub's rate limit or a dropped connection to the AI provider, are retried automatically.
Changes to AI models are handled through settings: a new model is chosen in `.env`, its
price can be added so that the spending limit stays accurate, and `make aitest` confirms
it works before a real audit. The prompt itself is versioned, so a change to it creates a
new version and every earlier answer stays linked to the prompt that produced it.

When the tool itself is upgraded, the database upgrades its structure automatically the
first time the new version opens it, and earlier runs continue to verify. For diagnosing
problems, every command and the dashboard write to a single log file,
`logs/compliancelens.log`, which records each run's start and end, every verdict with its
timing, report exports, and the full details of any unexpected error. If the tool crashes,
the user sees one short message, and the details are left in the log, with secrets
already hidden.

The next chapter summarizes the project, presents its conclusions and recommends
directions for further work.
