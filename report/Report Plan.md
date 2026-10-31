# ComplianceLens — Project Report Plan

The working plan for the CMPE 295B final project report: what we are writing, the rules we
write by, the agreed table of contents, and every decision made along the way. Update it
whenever something is decided.

## The assignment

- **Report:** "An AI-Powered Platform for Automated Compliance Auditing", Fall 2026, advisor
  Prof. Andrew Bond.
- **Earlier step (done):** a three-level table of contents (chapter, topic, subtopic).
- **Now:** the draft report, 30 points: "accurately describes team project and is
  substantially complete (well organized, well written, only a few items require
  correction)".
- **Where it lives:** the team's Google Doc. Claude writes the content in chat, one chapter
  at a time; Vatsal pastes it into the doc.

## Writing rules

- **Formal report tone, still plain:** no contractions, no "you", no casual phrases
  ("easy", "the right one"). Refer to the authors as **"the team"**, never "we" or
  "our". Users of the tool are "users"; the person deciding NEEDS REVIEW results is a
  "reviewer".
- **Plain English** for a reader who is decent at English: short sentences, active voice,
  one idea per paragraph, every acronym spelled out on first use, every number with its
  context ("95% of 90 answers").
- **Short sections:** one or two short paragraphs per level-3 heading, sometimes with a
  small table or figure. A level-2 heading with no subtopics (6.1, Chapter 9) gets its
  paragraphs directly.
- **One running example:** rule AWS-02 ("every user has MFA") followed through every
  chapter.
- **Fixed terms:** one word per idea, all defined in the Glossary (list in Step 2).
- **Each chapter** opens with what it covers and why, and ends with one sentence leading
  into the next.
- **Facts only:** describe what the tool does today; plans go in Chapter 9.
- **Every number** comes from the fact sheet (Step 2), so chapters never disagree.

## Steps

| # | Step | Status |
| --- | --- | --- |
| 1 | Agree the table of contents | ✅ Agreed (Oct 30) |
| 2 | Fact sheet (numbers and names) and term list | ✅ Done (Oct 30) |
| 3 | List of figures and tables | ✅ Done (Oct 30) |
| 4 | Chapter 2, Architecture (written first; the rest refer to it) | ✅ Drafted and cross-checked (Oct 30) |
| 5 | Chapters 3, 4, 5 (Technology, Design, Implementation), one at a time | ✅ Drafted and cross-checked (Oct 30); Vatsal expects few changes |
| 6 | Chapters 6, 7 (Testing, Performance and experiment), one at a time | ✅ Ch 6 and Ch 7 drafted (Oct 30) |
| 7 | Chapter 8 (Deployment, operations, maintenance) | ✅ Drafted (Oct 30) |
| 8 | Chapters 1 and 9 (introduction and conclusion) | ✅ Both drafted (Oct 30) |
| 9 | Abstract (past tense, with results), Glossary, References, Appendix | ✅ Drafted (Oct 30): `Abstract.md`, `Glossary.md`, `References.md`, `Appendix.md` |
| 10 | Full read-through: flow, terms, numbers | ✅ Done (Oct 30); 10 small fixes, see decision log |

## Table of contents (agreed)

**Chapter 1: Project Overview**
- 1.1 Introduction
  - 1.1.1 Problem and motivation
  - 1.1.2 Goals, scope, and non-goals
- 1.2 Areas of Study and Academic Contribution
  - 1.2.1 Rules as data: the rule card
  - 1.2.2 Layered evaluation: code, AI, human
  - 1.2.3 Measuring when AI judgment can be trusted
- 1.3 Current State of the Art
  - 1.3.1 Existing compliance automation tools
  - 1.3.2 The reference project and its gap

**Chapter 2: Project Architecture**
- 2.1 Introduction
  - 2.1.1 Design principles
  - 2.1.2 End-to-end pipeline
- 2.2 Architecture Subsystems
  - 2.2.1 Rulebook and rule engine
  - 2.2.2 Connectors and evidence store
  - 2.2.3 Evaluator
  - 2.2.4 Results database, dashboard, and report

**Chapter 3: Technology Description**
- 3.1 Client Technology
  - 3.1.1 Command-line interface
  - 3.1.2 Web dashboard
  - 3.1.3 HTML and PDF reports
- 3.2 Middle-Tier Technology
  - 3.2.1 AWS and GitHub APIs
  - 3.2.2 Browser automation
  - 3.2.3 LLM providers
- 3.3 Data-Tier Technology
  - 3.3.1 SQLite
  - 3.3.2 Evidence store and hashing

**Chapter 4: Project Design**
- 4.1 Client Design
  - 4.1.1 CLI commands
  - 4.1.2 Dashboard pages and review workflow
  - 4.1.3 Audit report layout
- 4.2 Middle-Tier Design
  - 4.2.1 Rule card schema and check operators
  - 4.2.2 Connector interface and screenshot capture
  - 4.2.3 AI evaluator design
- 4.3 Data-Tier Design
  - 4.3.1 Database schema
  - 4.3.2 Evidence folder and manifest

**Chapter 5: Project Implementation**
- 5.1 Client Implementation
  - 5.1.1 Dashboard
  - 5.1.2 Report generation
- 5.2 Middle-Tier Implementation
  - 5.2.1 Engine and runner
  - 5.2.2 Connector implementations
  - 5.2.3 AI evaluator
- 5.3 Data-Tier Implementation
  - 5.3.1 Database and evidence writing
  - 5.3.2 The verify command

**Chapter 6: Testing and Verification**
- 6.1 Testing Strategy
- 6.2 Automated Testing
  - 6.2.1 Unit and connector tests
  - 6.2.2 AI safety tests
  - 6.2.3 Evidence integrity and report tests
- 6.3 Live Verification
  - 6.3.1 Break-and-fix routine
  - 6.3.2 Real audit runs and failure modes

**Chapter 7: Performance and Benchmarks**
- 7.1 Runtime and Cost
  - 7.1.1 Audit run time
  - 7.1.2 AI cost and caching
- 7.2 Research Experiment: AI versus Code Accuracy
  - 7.2.1 Research question and hypothesis
  - 7.2.2 Experiment design
  - 7.2.3 Metrics
  - 7.2.4 Results and analysis
  - 7.2.5 Limitations

**Chapter 8: Deployment, Operations, Maintenance**
- 8.1 Deployment
  - 8.1.1 Setup and installation
  - 8.1.2 Configuration and secrets
- 8.2 Operations
  - 8.2.1 Running an audit
  - 8.2.2 Reviewing results and exporting the report
- 8.3 Maintenance
  - 8.3.1 Adding rules and connectors
  - 8.3.2 Handling API and interface changes

**Chapter 9: Summary, Conclusions, and Recommendations**
- 9.1 Summary
- 9.2 Conclusion
- 9.3 Recommendations for Further Research

Glossary · References · Appendix (sample audit report, full rule list)

## Where content goes (so nothing is written twice)

| Topic | Goes in | Not in |
| --- | --- | --- |
| Security: read-only access, never defaulting to PASS | 2.1.1 Design principles | (no separate 2.3) |
| Secrets (.env, hidden in logs), dashboard password | 8.1.2 Configuration and secrets | |
| AI model research and tools in general | 1.3.1 Existing compliance automation tools | (no separate 1.3.3) |
| What a part is (its job) | Ch 2 | |
| Which tool or library and why | Ch 3 | |
| How a part was planned (schemas, pages, interfaces) | Ch 4 | |
| How it was built, problems solved | Ch 5 | |
| CLI implementation | 4.1.1 (commands) and 8.2.1 (use) | Ch 5 (too thin) |
| CI and test coverage | 6.1 Testing Strategy | |
| Dashboard acceptance on real accounts | 6.3.2 Real audit runs | (no separate 6.3.3) |
| AI cache | 7.1.2 AI cost and caching (design in 4.2.3) | |
| Logging and troubleshooting | 8.3.2 Handling API and interface changes | Ch 5 |
| Report export (use) | 8.2.2 | |

## Fact sheet

Every number and name the report uses. Checked against the code and docs on Oct 30.
Change a fact here first, then in the report.

**The project**

| Fact | Value | Source |
| --- | --- | --- |
| Team | Vatsal Gandhi, Harishita Gupta, Dev Patel, Indraneel Sarode | TOC draft |
| Advisor | Prof. Andrew Bond | TOC draft |
| Length | 15-week semester, built in 7 versions (V1–V7) | Project Plan |
| Status | V1–V5 done (last tag `v5.0`); V6 code done (live checks and release left); V7 (demo) week 15 | Project Progress |
| Tool version | 0.6.0.dev0 | `compliancelens/__init__.py` |
| Code size | about 10,000 lines of Python in `compliancelens/` | line count |
| Baseline it improves on | AWS sample "AI-Powered Compliance Evidence Collector": collects evidence, never judges it; defaults to "Compliant" if the AI reply can't be read | Project Plan |

**Rules**

| Fact | Value | Source |
| --- | --- | --- |
| Rules | 19 | `rules/starter_rules.yaml` |
| By system | AWS 8 (AWS-01..08), GitHub 7 (GH-01..07), HR 1 (HR-01), policy documents 3 (DOC-01..03) | rulebook |
| Judged by code | 15: AWS-01..08, GH-01..06, HR-01 | rulebook |
| Judged by AI | 4: GH-07 (screenshot only) and DOC-01..03 (policy documents) | rulebook |
| Rules with a screenshot | 16 | rulebook |
| Check operators | 7: `>=`, `==`, `<=`, `in`, `not_in`, `contains`, `all_true` | `engine.py` |
| Running example | AWS-02 "Every IAM user with a console password has MFA" (check: count of users without MFA `== 0`) | rulebook |
| Verdicts | PASS, FAIL, NEEDS REVIEW; nothing ever defaults to PASS | code |
| GH-06 history | judged by AI in V4–V5; by code from the API from V6, as the experiment recommended | Project Progress D14 |

**Technology**

| Layer | Choice (version) |
| --- | --- |
| Language | Python 3.11+ |
| Command line | Typer 0.27; commands `run`, `history`, `verify`, `login`, `report`, `settings`, `ai-test` |
| AWS | boto3 1.43, read-only (SecurityAudit policy) |
| GitHub | REST API with `requests`, read-only token |
| Screenshots | Playwright 1.63 (Chromium), saved logins |
| AI | any model set in `.env`: OpenAI, Anthropic, or a local OpenAI-compatible model. In use: `openai/gpt-6-luna` |
| Database | SQLite, schema 4; tables `runs`, `results`, `overrides`, `ai_evaluations`, `ai_cache` |
| Evidence | JSON + PNG files per run, a manifest of SHA-256 hashes |
| Dashboard | FastAPI 0.150 + Jinja2 3.1, served by uvicorn; password sign-in; pages: Home, Run audit, History, Results, Rule detail, Review queue, Compare, Rules |
| Reports | Jinja2 HTML + WeasyPrint 70 for PDF |
| Tests | pytest, moto (fake AWS), recorded GitHub responses; GitHub Actions CI |

**Results**

| Fact | Value | Source |
| --- | --- | --- |
| Tests | 1,573, 100% code coverage | `pytest --collect-only` (Oct 30); Project Progress |
| First real audit (V2) | 13 PASS / 1 FAIL / 0 NEEDS REVIEW, 14 rules | Project Progress |
| Real audit with AI (V4, `run-0010`) | 18 PASS / 1 FAIL (AWS-02) / 0 NEEDS REVIEW; 15 of 15 screenshots; 5 AI calls, $0.0010; re-run from cache $0 | Project Progress |
| Full audit run time (`run-0042`, V5) | **1 min 29 s** for 19 rules with screenshots and AI; 8 AI calls, $0.0018; 71 evidence files verified | Project Progress |
| Screenshots alone | 15 screenshots in 31 s (V3) | Project Progress |
| Run-time target | under 2 minutes | Project Plan |

**Research experiment**

| Fact | Value |
| --- | --- |
| Question | How accurately does an AI judge a setting from a screenshot, compared with code reading the API? Does it say so when it can't tell? |
| Rules tested | 5: AWS-01, AWS-02, AWS-05, GH-01, GH-06 |
| Cases | 55 pictures: 40 plain (8 per rule, 4 PASS + 4 FAIL) and 15 hard (dark theme 2, small text 5, below the fold 2, covered 1, prompt injection 2, unclear on purpose 3) |
| Labels | 2 people, separately; agreed on 54 of 55, Cohen's κ = 0.97; final 21 PASS, 30 FAIL, 4 REVIEW; fixed before the AI ran |
| AI run | `openai/gpt-6-luna`, 3 fresh answers per case = 165 answers; $0.0542 in all; 3.9 s per answer |
| Accuracy vs labels | 93% (154/165); decided accuracy 95% (142/149) |
| False PASS | 7% (6/90) vs the labels; **0% (0/84) vs the set-up state** |
| False FAIL | 2% (1/63) vs the labels |
| Unclear pictures | 12 of 12 answers NEEDS REVIEW, none PASS |
| Prompt injection | never obeyed (6 of 6 right) |
| Consistency | 53 of 55 cases same verdict all 3 times (96%) |
| Confidence | all 6 false PASSes had high confidence; confidence did not help |
| Code | matched the set-up state in 55 of 55 cases |
| Why the false PASSes | all 6 are two AWS-02 pictures: both labellers said FAIL, but the rule's written wording, the setup and the code all say PASS |
| Conclusion | use code where an API exists; use AI plus human review where there is only a picture or a document |
| Hypothesis | 1 held (code), 2 and 3 partly, 4 (confidence) did not |

## Figures and tables

Numbered by chapter (Figure 2.1, Table 7.4). Each one is used in the section shown and
mentioned in the text before it appears. Source: **have** = already in the repo,
**make** = we draw it, **capture** = a screenshot or crop we take. Google Docs can't show
SVG, so the SVG charts are turned into PNG first.

**Figures**

| # | Figure | Section | Source |
| --- | --- | --- | --- |
| 2.1 | End-to-end pipeline: rulebook → engine → connectors → evidence store → evaluator → database → dashboard and report | 2.1.2 | have (Project Plan diagram); redraw without version labels |
| 2.2 | How the evaluator decides: code check, then AI check, then NEEDS REVIEW for a person | 2.2.3 | make |
| 4.1 | Dashboard Results page | 4.1.2 | have (`docs/images/dashboard-results.png`) |
| 4.2 | Dashboard Review queue | 4.1.2 | have (`docs/images/dashboard-queue.png`) |
| 4.3 | Audit report cover page | 4.1.3 | capture page 1 of `docs/sample-report.pdf` |
| 4.4 | The AWS-02 rule card (YAML) | 4.2.1 | capture from `rules/starter_rules.yaml` (trimmed copy in Ch 4) |
| 4.5 | A screenshot with its banner (rule, UTC time, URL) | 4.2.2 | capture the AWS-02 picture in `docs/sample-report.html` (made-up audit) |
| 4.6 | Database schema: the 5 tables and their links | 4.3.1 | make (Mermaid source in Ch 4) |
| 4.7 | Evidence folder of one run, with its manifest | 4.3.2 | make (folder tree in Ch 4) |
| 5.1 | Dashboard Rule detail page (evidence, reason, review) | 5.1.1 | have (`docs/images/dashboard-detail.png`) |
| 5.2 | What happens in one audit run, step by step | 5.2.1 | make (Mermaid source in Ch 5) |
| 7.1 | AI accuracy by rule | 7.2.4 | ready: `report/figures/accuracy-by-rule.png` |
| 7.2 | The AWS-02 picture behind all 6 false PASSes | 7.2.4 | ready: `report/figures/example-aws02-no-console.png` |
| 7.3 | False PASS and false FAIL: against the labels and against the set-up state | 7.2.4 | ready: `report/figures/false-pass-fail.png` |
| 7.4 | What the AI answered by kind of picture | 7.2.4 | ready: `report/figures/review-by-kind.png` |

**Tables**

| # | Table | Section | Source |
| --- | --- | --- | --- |
| 1.1 | Goals (must-haves) and non-goals | 1.1.2 | Project Plan |
| 1.2 | Existing approaches compared with ComplianceLens (approach, examples, strength, gap) | 1.3.1 | done in Ch 1, with references [4]–[11] |
| 2.1 | The 19 rules by system and how each is judged (summary) | 2.2.1 | fact sheet |
| 3.1 | Technology stack: layer, choice, why | Ch 3 intro | fact sheet + Project Plan |
| 4.1 | CLI commands and their options | 4.1.1 | CLI code |
| 4.2 | Check operators, with an example rule each | 4.2.1 | `engine.py` |
| 4.3 | How an AI answer becomes a verdict (first row that applies decides) | 4.2.3 | AI evaluator code |
| 5.1 | Connectors and what each reads | 5.2.2 | connector code |
| 6.1 | Test types: what each checks and with which tool | 6.1 | Project Plan + fact sheet |
| 6.2 | Break-and-fix results, grouped by how FAIL was proven | 6.3.1 | Project Progress |
| 6.3 | Real audit runs and their verdicts (run-0001, 0004, 0010, 0011, 0042) | 6.3.2 | Project Progress |
| 7.1 | Run time and AI cost of real audits, with and without the cache | 7.1.1–7.1.2 | Project Progress |
| 7.2 | The 55 experiment cases by kind | 7.2.2 | experiment write-up |
| 7.3 | Metrics and what each counts | 7.2.3 | experiment write-up |
| 7.4 | Overall results: against the labels and against the set-up state | 7.2.4 | experiment write-up |
| 7.5 | The hypothesis: what held | 7.2.4 | experiment write-up |
| 8.1 | Configuration files: what goes in each | 8.1.2 | READMEs |

**Appendix:** A, the full rule list (all 19 rules with their fixes); B, the sample audit
report (made-up company).

## Terms

One word per idea. Use these and only these; they become the Glossary.

| Term | Meaning | Don't write |
| --- | --- | --- |
| **rule** | One security requirement, for example "every user has MFA" | control, policy, check (for the whole rule) |
| **rule card** | The YAML entry that describes one rule: what to collect, how to judge it, the fix | rule file, rule definition |
| **rulebook** | All 19 rule cards together | rule set, rule library |
| **connector** | The part that reads one system (AWS, GitHub, browser, HR list, documents) and collects evidence | collector (except when naming the code), integration, plugin |
| **evidence** | What a connector saves for a rule: API data, a screenshot or a document | proof, artifacts |
| **evidence store** | The folder of evidence files for each run, with its manifest | |
| **manifest** | The list of every evidence file in a run with its SHA-256 hash | |
| **check** | The code test on API data in a rule card (field, operator, value) | |
| **check operator** | The comparison a check uses, such as `>=` or `all_true` | |
| **AI check** | The conditions an AI uses to judge a screenshot or document | AI evaluation (as a name), LLM check |
| **evaluator** | The part that decides the verdict: code first, then AI, then human | judge |
| **verdict** | PASS, FAIL or NEEDS REVIEW, always with a reason | result, outcome, status |
| **NEEDS REVIEW** | The verdict when the tool cannot decide safely; a person decides | unknown, unsure, error |
| **audit** / **run** | One full pass over the rules; each run has an ID like `run-0042` | scan, job |
| **review** | A person's decision on a result, added in the dashboard and never edited | override (except the database table's name) |
| **false PASS** | A non-compliant setting called PASS: the dangerous error | false negative |
| **set-up state** | What the experiment's setup really made true in the account | ground truth |
| **label** | What the two people said a picture shows | |
| **dashboard** | The web pages for running audits, reading results and reviewing | UI, portal, web app |
| **audit report** | The HTML/PDF made from a finished run | export (as a noun) |
| **verify** | The command that checks every evidence file against its hash | validate |
| **break-and-fix** | Making a rule fail on purpose in a real account, then fixing it, to prove the tool really looks | |

## References

IEEE style, numbered in order of first citation. Chapter 1 uses [1]–[11]; add new ones
at the end with the next number. Web pages accessed Oct 30, 2026.

| # | Reference | First cited |
| --- | --- | --- |
| [1] | Center for Internet Security, "CIS Benchmarks." [Online]. Available: https://www.cisecurity.org/cis-benchmarks | 1.1.1 |
| [2] | AICPA & CIMA, "SOC 2 — SOC for Service Organizations: Trust Services Criteria." [Online]. Available: https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2 | 1.1.1 |
| [3] | ISO/IEC 27001:2022, *Information security, cybersecurity and privacy protection — Information security management systems — Requirements*. Geneva, Switzerland: ISO, 2022. | 1.1.1 |
| [4] | Amazon Web Services, "CIS AWS Foundations Benchmark in Security Hub CSPM," *AWS Security Hub User Guide*. [Online]. Available: https://docs.aws.amazon.com/securityhub/latest/userguide/cis-aws-foundations-benchmark.html | 1.3.1 |
| [5] | Prowler, "Prowler: open cloud security," GitHub repository. [Online]. Available: https://github.com/prowler-cloud/prowler | 1.3.1 |
| [6] | Vanta, "Vanta: automated compliance." [Online]. Available: https://www.vanta.com | 1.3.1 |
| [7] | Drata, "SOC 2 compliance automation." [Online]. Available: https://drata.com/product/soc-2 | 1.3.1 |
| [8] | L. Zheng, W.-L. Chiang, Y. Sheng, *et al.*, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena," in *Advances in Neural Information Processing Systems 36 (NeurIPS 2023), Datasets and Benchmarks Track*, 2023. | 1.3.1 |
| [9] | K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, and M. Fritz, "Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection," in *Proc. 16th ACM Workshop on Artificial Intelligence and Security (AISec '23)*, 2023, pp. 79–90. | 1.3.1 |
| [10] | R. Kumar, S. Ahmed, and S. Barraza, "Building an AI powered system for compliance evidence collection," *AWS Machine Learning Blog*, Mar. 31, 2026. [Online]. Available: https://aws.amazon.com/blogs/machine-learning/building-an-ai-powered-system-for-compliance-evidence-collection | 1.3.1 |
| [11] | Amazon Web Services, "sample-ai-powered-compliance-evidence-collector," GitHub repository, commit 9fe898c, May 12, 2026. [Online]. Available: https://github.com/aws-samples/sample-ai-powered-compliance-evidence-collector | 1.3.1 |

| [12] | J. Cohen, "A coefficient of agreement for nominal scales," *Educational and Psychological Measurement*, vol. 20, no. 1, pp. 37–46, 1960. | 7.2.2 |
| [13] | J. R. Landis and G. G. Koch, "The measurement of observer agreement for categorical data," *Biometrics*, vol. 33, no. 1, pp. 159–174, 1977. | 7.2.2 |
| [14] | E. B. Wilson, "Probable inference, the law of succession, and statistical inference," *J. American Statistical Association*, vol. 22, no. 158, pp. 209–212, 1927. | 7.2.3 |

The final list, ready to paste, is `References.md`.

## Decision log

| Date | Decision | Why |
| --- | --- | --- |
| Oct 30 | Content written in chat chapter by chapter; Vatsal pastes it into the Google Doc | Simplest; the doc stays the team's |
| Oct 30 | Every level-3 heading gets short content; no length target | Draft must be "substantially complete" but readable |
| Oct 30 | Keep a level-3 heading only if it has something distinct to say; renumber freely; old headings can be removed or replaced | No filler sections |
| Oct 30 | Title of Ch 3 fixed (was "Chapter 4: Technology Description"); 3.2.1 is now AWS and GitHub APIs | Numbering error in the TOC draft |
| Oct 30 | Evaluator gets its own section in Ch 2, 4 and 5 (2.2.3, 4.2.3, 5.2.3) | It is what the project adds over existing tools |
| Oct 30 | Experiment gets method and limitations (7.2.1–7.2.5), and a contribution point (1.2.3) | It is the measured academic result |
| Oct 30 | Dashboard and report covered in Ch 3, 4, 5, 8 | Major parts the TOC draft missed |
| Oct 30 | Dropped: 1.3.3 (LLMs as judges), 2.3 Security (and 2.3.1/2.3.2), YAML config (3.3.3), CLI implementation (Ch 5), logging section (5.3.3), dashboard acceptance (6.3.3), level-3s under 6.1, separate report export / logs headings in Ch 8 | Folded into other sections; see "Where content goes" |
| Oct 30 | Merged: AI cost and caching (7.1.2); reviewing and exporting (8.2.2) | Too small apart |
| Oct 30 | Abstract rewritten last, in past tense, with the experiment's results | The tool is built now |
| Oct 30 | Fact sheet and term list added to this file; every number in the report comes from the fact sheet | Chapters must not disagree |
| Oct 30 | Experiment results are quoted both ways (vs the labels and vs the set-up state), as the write-up does | The 6 false PASSes depend on one wording disagreement |
| Oct 30 | Audit run time uses `run-0042` (1 min 29 s) | Only timed full audit on record |
| Oct 30 | 15 figures and 17 tables, numbered by chapter; only where they help the reader | No filler |
| Oct 30 | Screenshots in the report come from the made-up audit ("Example Labs") or have names hidden; never raw real-account pictures | Same rule as the repo (V6 D9) |
| Oct 30 | Appendix: A full rule list, B sample audit report | Too long for the chapters |
| Oct 30 | Each chapter is written to its own file in `report/` (`Chapter N - Title.md`); figures and tables are marked with a quoted "goes here" box giving the caption and where to find it (delete the box after pasting) | Easy to paste; nothing non-text gets lost |
| Oct 30 | New diagrams are given as Mermaid source in the chapter file, to render at mermaid.live as PNG | Google Docs needs pictures |
| Oct 30 | Formal report tone; authors are "the team"; Chapter 2 rewritten to match | Vatsal asked for language fit for a report |
| Oct 30 | Chapters are written one at a time, each reviewed before the next | Each chapter gets full effort |
| Oct 30 | Figures are numbered in the order they appear in the text (Ch 4 and 5 renumbered) | Standard report practice |
| Oct 30 | Cross-check of Ch 2–5: Table 4.3 rows put in the code's real order (a silent document is FAIL before the "no evidence" row); Table 5.1 browser row clarified; "easy" removed twice; dashboard page names fixed in the fact sheet (Run audit, History, Rule detail) | Accuracy; Vatsal expects few changes of his own |
| Oct 30 | Ch 6: run-0043 left out of Table 6.3 (its PASS/FAIL counts were never recorded) and described in the text instead; coverage stated as "CI requires 70%, the team kept 100%" | Never invent a number |
| Oct 30 | Ch 7: experiment charts rendered to PNG (Chromium, 2x) in `report/figures/`; figures 7.2–7.4 reordered by first mention; results quoted against both the labels and the set-up state; run time of V4 runs shown as "not measured" | Google Docs needs PNG; no invented numbers |
| Oct 30 | Ch 8: security controls listed in 8.1.2; AWS-02 fix-and-rerun cycle used in 8.2.1; logs and troubleshooting in 8.3.2; no figures | As planned in "Where content goes" |
| Oct 30 | Ch 1: claims about the AWS reference sample come from its code (commit 9fe898c): the AI gets only step names and success/failed, and an unreadable reply becomes "Compliant". Its blog post says the model analyses screenshots; the chapter cites the code and notes the difference | The code is what runs; the Project Plan's description was right |
| Oct 30 | Commercial tools (Vanta, Drata) described only by what is safe and sourced: integrations, continuous evidence, SOC 2 mapping, closed-source, auditor still needed | Avoid unverifiable marketing claims |
| Oct 30 | References kept in this file in IEEE style, numbered by first citation | One list for the final References page |
| Oct 30 | Ch 9: four numbered conclusions (code where an API exists; AI useful but checked; never PASS on uncertainty; rule wording matters); recommendations from the V7 stretch goals and the experiment's limits; "compare runs" left out because it already exists | Conclusions match Ch 7's findings |
| Oct 30 | Abstract rewritten in past tense with results (about 330 words, three paragraphs); keeps the original title and author lines | Tool is built; results are known |
| Oct 30 | Glossary: 44 terms (the term list plus acronyms), alphabetical | Every term used in the chapters is defined |
| Oct 30 | References [12]–[14] (Cohen, Landis and Koch, Wilson) added and cited in 7.2.2–7.2.3 | Statistics need sources |
| Oct 30 | Appendix A: all 19 rules with fixes (from the rulebook, contractions removed); Appendix B: the Example Labs sample report PDF | Too long for the chapters |
| Oct 30 | Ch 4 is "how it was planned" (fields, pages, schemas, AI rules); Ch 5 is "how it works inside and problems solved" (threads, locks, triggers, retries); Ch 5 has no CLI section | Avoid repeating each other |
| Oct 30 | Ch 3 is "what and why" only; Table 3.1 sits in the chapter intro; YAML/.env and testing tools appear in Table 3.1 but get no section (configuration is 8.1.2, testing is Ch 6) | Avoid repeating Ch 4, 6, 8 |

| Oct 30 | Final read-through (Step 10). Checked: every number against the fact sheet and source docs, headings against the TOC, all section/figure/table references, figure and table order, banned words and terms, `make` commands against the Makefile. Fixed: Ch 1 paste note points to `References.md`; Ch 2 "only rule that failed in regular live audits" (break-and-fix also failed rules on purpose); Ch 6 notes run-0004's 2 rules sent to review, and the AWS-02 live fix is "planned" for the demo; Ch 7 run-0042 is "the full audit whose run time was recorded" (not "longest measured"), and the five-AI-call audit is put in V4 with four calls since V6; Ch 9 the AI read dark and small-text pages, but sent partly hidden ones to review; Tables 4.1–4.3 added to this plan's list; 4 overlong lines rewrapped | Accuracy; nothing contradicts the fact sheet |

## Open items

- **Audit run time (7.1.1):** we have one timed full audit, `run-0042`: 1 min 29 s. A
  second timing from V6 Stage 7 (live acceptance) would make it stronger; not required.
- **Template / page limit from Prof. Bond:** none known.
- **Who writes what:** not decided (Claude drafts all chapters for now).
