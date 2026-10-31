# Chapter 1: Project Overview

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text. Numbers in square brackets, such as [1], refer to the References
> list at the end of the report; the full entries, ready to paste, are in
> `report/References.md`.

## 1.1 Introduction

This chapter introduces the problem that ComplianceLens addresses, the goals and limits of
the project, its academic contribution, and how it compares with existing tools.

### 1.1.1 Problem and motivation

Modern organizations must show that they follow security standards such as the CIS
Benchmarks [1], SOC 2 [2] and ISO/IEC 27001 [3]. These standards contain many concrete
requirements, for example "every user who can sign in to the cloud console uses
multi-factor authentication (MFA)" or "code must be reviewed before it is merged". Meeting
them is not a one-time task. A company must check its systems repeatedly and keep proof of
every check for its auditors.

In practice, much of this work is still done by hand. Staff open each settings page, take a
screenshot, rename and file it, and repeat the process for dozens of pages every quarter.
This is slow, costly and prone to error. Existing tools automate parts of the work, but a
gap remains. Some tools check cloud settings through APIs but cannot judge a screenshot or
a written policy. Others automate the collection of screenshots but do not judge what the
screenshots show, so a picture of a disabled protection can still be filed as compliant.
**Collecting evidence is not the same as judging it.**

ComplianceLens was built to automate both halves: to collect evidence from the systems a
company uses and to decide, for each rule, whether the evidence shows the rule is met. The
running example used throughout this report, rule AWS-02, illustrates the need. A single
AWS user without MFA is easy to miss when checking a long user list by hand, yet it is
exactly the kind of gap an auditor must find.

### 1.1.2 Goals, scope, and non-goals

The goal of the project was a working tool that checks a company's security rules across
AWS, GitHub, an HR employee list and written policy documents; saves tamper-evident proof
for every rule; and decides PASS, FAIL or NEEDS REVIEW with a reason, while sending only
the unclear cases to a person. A second goal was to measure how far AI judgment of
evidence can be trusted. Table 1.1 lists the required features and the items deliberately
left out of scope. The project was carried out over a 15-week semester in seven versions,
each ending with a working tool.

> **Table 1.1 goes here. Caption:** "Table 1.1: Goals and non-goals." Paste this table:

| Goals (required features) | Non-goals (out of scope) |
| --- | --- |
| Rules written as data files (rule cards), not code | Fixing problems automatically; the tool reports and people fix |
| Connectors for AWS and GitHub, plus an HR list and policy documents | Replacing an auditor or giving a legal compliance sign-off |
| Exact code checks of API data | Scanning application source code for vulnerabilities |
| Screenshots of settings pages as supporting evidence | Serving many companies (multi-tenant use), billing, or user accounts beyond one administrator |
| AI judgment of screenshots and documents, with a reason and confidence | Production-grade hardening; this is an educational project |
| Evidence saved with timestamps and SHA-256 hashes; history in a database | |
| PASS, FAIL or NEEDS REVIEW verdicts that never default to PASS | |
| A web dashboard with human review | |
| An exportable HTML and PDF audit report | |
| An experiment measuring AI accuracy against code | |

## 1.2 Areas of Study and Academic Contribution

The project contributes in three areas: a way of writing rules, a way of combining
different judges, and a measurement of how reliable AI judgment is.

### 1.2.1 Rules as data: the rule card

In ComplianceLens, every rule is a short data file called a rule card rather than a piece
of program code. A rule card answers four questions: what the rule is, where the proof is
found, how the proof is collected, and how it is judged. Writing rules as data has two
benefits. First, the rulebook can grow without new programming: adding a rule usually
means writing a few lines of text. Second, the rules can be read and checked by people who
are not programmers, such as compliance staff and auditors. The project shows that this
model can describe very different kinds of rules, from a numeric password setting to a
requirement stated in a policy document, within one consistent format.

### 1.2.2 Layered evaluation: code, AI, human

The second contribution is a layered approach to judging evidence. Each rule is decided by
the most reliable method available. An exact code check on API data comes first, because
it is precise, free and always gives the same answer. An AI model is used only for evidence
that code cannot read, such as a screenshot or a policy document, and its answer is
accepted only when it is clear, consistent and supported by a quote. Anything else goes to
a human reviewer. Throughout, no error or uncertain answer is ever allowed to become a
PASS. This approach combines the strengths of each judge while limiting the weaknesses of
AI, which can be confident and still wrong.

### 1.2.3 Measuring when AI judgment can be trusted

The third contribution is a controlled experiment that measures how accurately an AI judges
a security setting from a screenshot, compared with code reading the same setting through
the API. Fifty-five screenshots were taken of real AWS and GitHub accounts set to known
states, including deliberately difficult cases such as dark pages, small text, hidden
settings and pages containing instructions aimed at the AI. Two people labelled every
screenshot independently before the AI was run. The experiment focuses on the false PASS
rate, the most dangerous error a compliance tool can make, and its results directly shaped
the tool's design. The method and results are presented in Section 7.2.

## 1.3 Current State of the Art

This section reviews the main kinds of existing compliance automation tools, then examines
in detail the reference project on which ComplianceLens builds.

### 1.3.1 Existing compliance automation tools

Existing tools fall into three broad groups (Table 1.2). **Cloud posture checkers**, such as
AWS Security Hub [4] and the open-source tool Prowler [5], check cloud settings against
benchmarks such as the CIS AWS Foundations Benchmark through APIs. They are precise for the
settings they cover, but they judge only API data: they do not read screenshots or written
policies, and they do not offer a workflow for a person to review unclear results.
**Compliance automation platforms**, such as Vanta [6] and Drata [7], connect to many
systems through integrations, collect evidence continuously, and map it to standards such
as SOC 2. They are broad and widely used, but they are commercial, closed-source products,
so their checking logic cannot be inspected or extended freely, and an independent auditor
is still required for the audit itself. **Evidence collectors**, such as the AWS sample
described in Section 1.3.2, automate the capture of screenshots from web pages, but they do
not reliably judge what the screenshots show.

At the same time, research has begun to use large language models (LLMs) as judges.
Zheng et al. [8] found that a strong LLM can agree with human judgments about as often as
humans agree with each other, but also documented systematic biases. Greshake et al. [9]
showed that text hidden in content an LLM reads can act as an instruction to it, an attack
known as indirect prompt injection. Both findings are directly relevant to a compliance
tool: an AI judge may be useful, but it must be checked, and evidence must never be
allowed to instruct it. ComplianceLens combines these lines of work: it uses API checks
where they exist, adds an AI judge for screenshots and documents with strict safeguards,
and measures how far that judge can be trusted.

> **Table 1.2 goes here. Caption:** "Table 1.2: Existing approaches compared with
> ComplianceLens." Paste this table:

| Approach | Examples | Strength | Gap addressed by ComplianceLens |
| --- | --- | --- | --- |
| Cloud posture checkers | AWS Security Hub [4], Prowler [5] | Precise, automated checks of cloud settings against CIS benchmarks | Judge only API data; no reading of screenshots or policy documents; no human review workflow |
| Compliance automation platforms | Vanta [6], Drata [7] | Many integrations; continuous evidence collection mapped to SOC 2 and other standards | Commercial and closed-source; checking logic cannot be inspected or extended |
| Evidence collectors | AWS sample evidence collector [10], [11] | Automated, timestamped screenshots of web pages | Do not judge what the evidence shows; can report a failure as compliant |
| **ComplianceLens** | This project | Code checks first, AI for screenshots and documents, human review for unclear cases; tamper-evident evidence; open rule cards | |

### 1.3.2 The reference project and its gap

The starting point for ComplianceLens was an AWS sample project, the "AI-Powered Compliance
Evidence Collector" [10], [11]. It is a browser extension for Chrome and Firefox that runs
workflows written in JSON, such as "open this page, click here, take a screenshot". The
screenshots are stored with timestamps in Amazon S3. An AI model, Amazon Nova 2 Lite on
Amazon Bedrock, can generate workflows from uploaded documents, and it writes a report at
the end of each workflow, which is sent by email.

The sample collects evidence well, but its code does not judge the evidence. In the
team's review of the sample's code [11], the report request sent to the AI contains only
the workflow's step names and whether each step succeeded or failed; the screenshots
themselves are not included, although the accompanying blog post [10] describes the model
as analysing them. A step counts as successful if it runs without an error, for example
when a button is found and clicked. The AI then labels the workflow Compliant,
Non-Compliant or Partial Compliance, and if its reply cannot be read, the code fills in
"Compliant" by default. As a result, a screenshot showing "Branch protection: OFF" can
still be reported as compliant, because every step of the workflow completed.

ComplianceLens keeps the useful ideas of the sample: rules and workflows written as data,
timestamped evidence, and a manual login step. It changes the parts that matter for an
audit. Every rule is judged on what its evidence shows. API data is preferred over
screenshots for judging, the AI sees the actual screenshot or document when it is used, and
no result ever defaults to PASS. The next chapter describes the architecture that puts
these ideas into practice.
