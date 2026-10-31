# Abstract

> **Notes for pasting into the Google Doc** (delete this box after pasting): this text
> replaces the body of the current ABSTRACT page. Keep the title line and author line that
> are already there:
> "An AI-Powered Platform for Automated Compliance Auditing" /
> "By Vatsal Gandhi, Harishita Gupta, Dev Patel, and Indraneel Sarode".

Modern organizations must regularly prove that they meet security standards such as the
CIS Benchmarks, SOC 2 and ISO 27001. In practice, much of this proof is still gathered by
hand: staff capture and file screenshots of settings pages, dozens of them each quarter.
Existing tools solve only part of the problem. Some check cloud settings through APIs but
cannot read screenshots or written policies, while others automate the collection of
screenshots but do not judge what they show, so a screenshot of a disabled protection can
still be filed as compliant. Collecting evidence is not the same as judging it.

This project built ComplianceLens, a tool that automates both halves. Its 19 rules, across
Amazon Web Services, GitHub, an HR employee list and policy documents, are written as data
files rather than code. Connectors gather evidence through read-only access and save it
with SHA-256 hashes, so any later change can be detected. Each rule is judged by the most
reliable method available: 15 by exact code checks on API data, and 4 by an AI model
reading a screenshot or a policy document. Any uncertain result is sent to a person in a
web dashboard, and no error or unclear answer is ever allowed to become a pass. An HTML and
PDF report presents every verdict with its evidence.

A full audit took 1 minute 29 seconds and cost about $0.001 in AI fees. In a controlled
experiment on 55 screenshots of real account settings, labelled independently by two
people, the AI reached 95% decided accuracy against the labels and 99% against the actual
account state, sent every unclear screenshot to review, and ignored all instructions
hidden in the evidence. Its confidence, however, did not warn of its errors, while code
checks were correct in all 55 cases. The results show that code should decide wherever an
API exists, and that AI judgment is useful for screenshots and documents only when a
person reviews it.
