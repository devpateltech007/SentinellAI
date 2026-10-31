# Chapter 9: Summary, Conclusions, and Recommendations

> **Notes for pasting into the Google Doc:** this chapter is text only; there are no
> figures or tables.

This chapter summarizes what the team built and measured, states the conclusions drawn
from the work, and recommends directions for further development and research.

## 9.1 Summary

Companies must regularly prove to auditors that they follow security standards such as the
CIS Benchmarks, SOC 2 and ISO/IEC 27001. Much of this proof is still gathered by hand, and
existing tools tend either to check settings through APIs without reading screenshots or
documents, or to collect screenshots without judging what they show. This project built
ComplianceLens, a tool that automates both the collection and the judgment of compliance
evidence.

ComplianceLens checks 19 rules across AWS, GitHub, an HR employee list and written policy
documents. Each rule is written as a rule card, a short YAML entry that states what the
rule is and how its evidence is collected and judged. Connectors gather the evidence
through read-only access, and every evidence file is saved with a SHA-256 hash, so any
later change can be detected with the `verify` command. The evaluator decides each verdict
using the most reliable method available: 15 rules are decided by exact code checks on API
data, and 4 rules, which have only a screenshot or a policy document as evidence, are
decided by an AI model under strict safeguards. Any result that cannot be decided safely
becomes NEEDS REVIEW and is settled by a person in a web dashboard, where every review is
recorded with a note and never edited. Finally, an HTML and PDF audit report presents the
results, the reviews and the hash of every evidence file.

The tool was built in versions over a 15-week semester and tested with 1,573 automated
tests covering all of its code, together with live checks on real AWS and GitHub accounts.
A full audit of all 19 rules took 1 minute 29 seconds, and a normal audit cost about
$0.001 in AI fees. In a controlled experiment on 55 screenshots of real account settings,
labelled independently by two people, the AI's decided accuracy was 95% against the
labels and 99% against the actual account state. It sent every unclear screenshot to
review and never followed instructions hidden in the evidence. The code checks matched the
actual account state in all 55 cases.

## 9.2 Conclusion

The project shows that compliance evidence can be both collected and judged automatically,
provided that each kind of evidence is given to the right judge. Four conclusions follow
from the work.

First, **where an API exists, code should decide.** Code checks were correct in every case
in the experiment, cost nothing and always gave the same answer. This finding changed the
tool itself: rule GH-06, which had been judged by AI from its screenshot, was moved to a
code check once the experiment showed that its value was available through the API.

Second, **AI is useful for evidence that code cannot read, but it must be checked.** The AI
read dark-theme and small-text pages correctly, ignored prompt injections, and sent
unclear or partly hidden pictures to review instead of guessing. However, its confidence gave no warning of
its errors: all of its false PASS answers against the labels were given with high
confidence. Its answers are therefore treated as reliable only when they are clear,
consistent and supported by a quote, and a person remains responsible for the final
decision.

Third, **a compliance tool must never turn uncertainty into a PASS.** Throughout testing,
missing logins, expired sessions, changed web pages, failed AI requests and tampered files
were each reported with a clear reason, and none of them ever produced a PASS that the
evidence did not support. This principle, more than any single feature, is what makes the tool's results trustworthy
enough to give to an auditor.

Fourth, **the wording of a rule matters as much as the judge.** The largest effect in the
experiment came not from the AI but from one rule whose written condition two careful
people read differently from the AI, the code and the actual account state. Rules intended
for automated judgment must be written so that they allow only one reading.

ComplianceLens supports an auditor rather than replacing one. It reduces repetitive work,
keeps tamper-evident proof of every check, and directs human attention to the results that
need it.

## 9.3 Recommendations for Further Research

The following directions would extend the tool and strengthen the research findings:

- **A larger and broader experiment.** The experiment used 55 cases, five rules, one AI
  model and one day. Repeating it with more cases, more rules, several models and at
  different times would give narrower confidence intervals and show whether the results
  hold as models and web pages change.
- **Measuring AI on evidence without an API.** The experiment compared the AI with code on
  rules where code was available, so that the correct answer was known. The AI's main use
  in the tool, however, is policy documents and settings that have no API. A study with
  expert-labelled policy documents would measure its accuracy where it matters most.
- **Testing how rule wording affects agreement.** The AWS-02 disagreement suggests a
  study in which the same rules are written in different ways and judged by several people
  and AI models, to find wording that produces consistent judgments.
- **Turning policy documents into rule cards.** An AI could read a company's written policy
  and draft rule cards from it, which a person would then review and approve. This would
  make it faster to adapt the rulebook to a new company.
- **More systems and standards.** Additional connectors, for example for Okta or Google
  Workspace, would widen the tool's coverage. Mapping every rule to its control number in
  the CIS, SOC 2 and ISO 27001 standards would let the report be organized by standard.
- **Scheduled audits and alerts.** Running audits on a schedule and sending an alert, for
  example by email or Slack, when a rule changes from PASS to FAIL would turn the tool from
  a periodic check into continuous monitoring.
- **Stronger evidence protection and multiple reviewers.** The evidence is currently
  tamper-evident but not tamper-proof, and the dashboard has a single administrator. Storing
  evidence in write-once storage or signing it with a trusted timestamp, and supporting
  separate reviewer accounts, would make the records stronger for formal audits.
