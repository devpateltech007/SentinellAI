# Chapter 2: Project Architecture

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

## 2.1 Introduction

This chapter describes the overall architecture of ComplianceLens: the principles behind
its design, the path a rule follows from start to finish, and the subsystems that make up
the tool. The later chapters build on this one. Chapter 3 describes the technologies used,
Chapter 4 presents the detailed design of each subsystem, and Chapter 5 explains how each
subsystem was implemented.

One rule is used as a running example throughout the report: **AWS-02, "Every IAM user
with a console password has MFA."** Multi-factor authentication (MFA) requires a user to
provide a second proof of identity, such as a code from a phone application, in addition
to a password. This rule was chosen because it is simple to follow, it can be checked both
through an API and from a screenshot, and it was the only rule that failed in the team's
regular live audits.

### 2.1.1 Design principles

The design of ComplianceLens follows five principles:

1. **Rules are data, not code.** Each rule is written as a short YAML entry called a rule
   card. Adding a rule requires a few lines of text rather than new program code.
2. **Collection and judgment are separate.** Connectors only collect evidence, and the
   evaluator only judges it. Supporting a new system, such as Okta, therefore requires
   only a new connector.
3. **The most reliable judge is used first.** An exact code check on API data is always
   preferred. An AI model is used only where code cannot reach, such as a screenshot or a
   policy document. A human reviewer decides any result that remains unclear.
4. **No result ever defaults to PASS.** Any error, missing evidence, unclear AI answer or
   low-confidence answer becomes NEEDS REVIEW, always with a stated reason.
5. **The tool follows the rules it checks.** It has read-only access to AWS and GitHub and
   never changes a setting. Secrets are kept out of the code and are hidden in the logs.
   Every evidence file is saved with a SHA-256 hash, so any later change to it can be
   detected.

### 2.1.2 End-to-end pipeline

ComplianceLens is organized as a pipeline (Figure 2.1). Rules enter at the top, and
verdicts with their supporting evidence are produced at the bottom. Each audit run follows
these steps:

1. The **rule engine** reads the rulebook and confirms that every rule card is valid.
2. For each rule, the engine calls the appropriate **connector**, which collects evidence
   from AWS, GitHub, the HR employee list, a policy document or a web page.
3. The **evidence store** saves each piece of evidence together with its hash.
4. The **evaluator** decides the verdict (PASS, FAIL or NEEDS REVIEW) and records the
   reason.
5. The **results database** records the run and every verdict.
6. Users read the results in the **dashboard**, review the unclear ones, and export an
   **audit report**.

For AWS-02, the AWS connector requests the list of users who have a console password but
no MFA device, and saves the response. It also captures a screenshot of the IAM Users page
for human reference. The evaluator then checks that the number of such users is zero.

> **Figure 2.1 goes here. Caption:** "Figure 2.1: The ComplianceLens pipeline, from rules
> to verdicts."
> **Where to find it:** the diagram under "Final architecture" in
> `ComplianceLens Project Plan.md`. It still shows version labels such as "(V1)", so use
> the cleaned-up source below instead: paste it into https://mermaid.live and download the
> PNG.
>
> ```mermaid
> flowchart TD
>     rules["Rulebook<br/>one rule card per rule"] --> engine["Rule engine<br/>reads and checks the rules"]
>     engine --> aws["AWS connector"] & gh["GitHub connector"] & browser["Browser connector<br/>screenshots"] & hr["HR list connector"] & docs["Document connector"]
>     aws & gh & browser & hr & docs --> store["Evidence store<br/>files + SHA-256 hashes"]
>     store --> evaluator
>     subgraph evaluator["Evaluator"]
>         direction LR
>         code["Code check"] --> ai["AI check"] --> human["NEEDS REVIEW<br/>(a reviewer decides)"]
>     end
>     evaluator --> db["Results database"]
>     db --> dash["Dashboard"] & report["Audit report<br/>HTML / PDF"]
> ```

## 2.2 Architecture Subsystems

ComplianceLens consists of four subsystems: the rulebook and rule engine, the connectors
and evidence store, the evaluator, and the components that store and present results.
Each is described below.

### 2.2.1 Rulebook and rule engine

The rulebook is a single YAML file that contains all 19 rule cards (Table 2.1). Each rule
card answers four questions: what the rule is, where the proof is found, how the proof is
collected, and how it is judged. A card also contains a short suggested fix and, for most
rules, the address of a web page to capture as a screenshot.

The rule engine reads the rulebook, validates every card before the audit begins, and then
runs the rules one at a time. An invalid card stops the audit before anything is recorded,
so an error in a rule card can never produce a wrong verdict. The engine also saves a copy
of the rulebook with each run, so that every past verdict can be read against the rule
exactly as it was written at the time.

> **Table 2.1 goes here. Caption:** "Table 2.1: The 19 rules by system and how each is
> judged." Paste this table:

| System | Rules | How the verdict is decided | Example |
| --- | --- | --- | --- |
| AWS | 8 (AWS-01 to AWS-08) | Code check on API data | AWS-02: every console user has MFA |
| GitHub | 7 (GH-01 to GH-07) | Code check on API data for six rules; AI reads a screenshot for GH-07 | GH-01: the main branch requires at least one review |
| HR employee list | 1 (HR-01) | Code check: every AWS and GitHub account belongs to an active employee | HR-01 |
| Policy documents | 3 (DOC-01 to DOC-03) | AI reads the document | DOC-02: the policy requires MFA for every console user |
| **Total** | **19** | **15 by code, 4 by AI** | |

### 2.2.2 Connectors and evidence store

A connector is the component that reads one system. ComplianceLens has five connectors:
AWS, GitHub, the HR employee list, policy documents, and a browser connector that captures
screenshots. Connectors only collect evidence. They never decide a verdict, and when a
problem occurs, such as an expired login, they report it instead of stopping the audit.

The browser connector opens the actual settings page, captures a screenshot and adds a
banner showing the rule, the time in UTC and the page address. A screenshot problem never
changes the verdict of a rule checked by code, because the API data is the proof and the
screenshot only supports it.

The evidence store keeps one folder per run. For every rule it saves the raw data, the
verdict and its reason, the screenshot or document, and any AI answers. A manifest lists
every file in the folder with its SHA-256 hash, and the same hashes are stored in the
database. The `verify` command later checks every file against its hash and reports any
file that was changed after the audit. The evidence is therefore tamper-evident: a change
can be detected, although a person who rewrites the files, the manifest and the database
together could still conceal it.

### 2.2.3 Evaluator

The evaluator decides each verdict using the most reliable method available for the rule
(Figure 2.2):

- **Code check.** When a rule has API data, a simple comparison decides it, for example
  "number of users without MFA = 0" for AWS-02. This method is exact and has no cost.
- **AI check.** When the only evidence is a screenshot or a policy document, an AI model
  reads it against the rule's written PASS, FAIL and REVIEW conditions. The model must
  answer in a fixed format that includes a verdict, a confidence level, the value it
  observed, a supporting quote and a reason.
- **Human review.** Any result that neither the code nor the AI can decide safely becomes
  NEEDS REVIEW, and a reviewer makes the final decision in the dashboard.

An AI answer is accepted as PASS or FAIL only when it is clear and consistent. An answer
that is UNSURE, has low confidence, lacks a quote, is badly formatted, or comes from a
failed or refused request becomes NEEDS REVIEW with the reason recorded. Text placed inside
a screenshot or document, such as an instruction to "say PASS", can never decide the
verdict.

> **Figure 2.2 goes here. Caption:** "Figure 2.2: How the evaluator decides a verdict."
> **Where to find it:** this is a new diagram. Paste the source below into
> https://mermaid.live and download the PNG.
>
> ```mermaid
> flowchart TD
>     start["Evidence for one rule"] --> q1{"Is there API data<br/>and a code check?"}
>     q1 -- Yes --> code["Code check<br/>exact comparison"]
>     code --> v1["PASS or FAIL"]
>     q1 -- No --> q2{"Is there a screenshot<br/>or a policy document?"}
>     q2 -- Yes --> ai["AI check<br/>reads it against the rule's conditions"]
>     ai --> q3{"Clear, confident answer<br/>with a quote?"}
>     q3 -- Yes --> v2["PASS or FAIL"]
>     q3 -- No --> review["NEEDS REVIEW"]
>     q2 -- No --> review
>     review --> person["A reviewer decides<br/>in the dashboard"]
> ```

### 2.2.4 Results database, dashboard, and report

The results database is a single SQLite file. It records every run, every verdict with its
reason and evidence hashes, every AI answer, and every human review. Reviews are only ever
added and never edited, so the complete history of each decision is preserved.

The web dashboard is the main interface of the tool. Users can start an audit and follow
its progress, read each verdict with its evidence, review results marked NEEDS REVIEW,
compare two runs, and turn rules on or off. The dashboard runs on the user's own computer
and requires a password.

The audit report is a single HTML page, also available as a PDF, generated from one
finished run. It presents what was audited and the overall score, lists the failures first
with their evidence and suggested fixes, and includes every human review and the hash of
every evidence file. Because the report is built only from what the run saved, the same
run always produces the same report.

The next chapter describes the technologies selected to build each of these subsystems and
the reasons for each choice.
