# Glossary

> **Notes for pasting into the Google Doc** (delete this box after pasting): paste the
> table below under the "Glossary" heading. Terms are in alphabetical order.

| Term | Meaning |
| --- | --- |
| **AI check** | The written conditions (expected state, PASS, FAIL and REVIEW conditions) that an AI model uses to judge a screenshot or a policy document. |
| **API** | Application Programming Interface. A way for one program to request data from another; ComplianceLens reads AWS and GitHub settings through their APIs. |
| **Audit** | One full pass over the rules, producing a verdict for each. Also called a run. |
| **Audit report** | The HTML page, also available as a PDF, generated from one finished run for an auditor. |
| **AWS** | Amazon Web Services, a cloud computing platform. |
| **Break-and-fix** | A test in which a real account setting is made non-compliant on purpose, the audit is run, and the setting is then restored, to prove that the tool examines the setting. |
| **Cache (AI cache)** | Stored accepted AI answers, reused when the same evidence is judged again with the same rule, model and prompt. |
| **Check** | The code test in a rule card, made of a field, a check operator and an expected value. |
| **Check operator** | The comparison a check uses, such as `==`, `>=` or `all_true`. |
| **CI** | Continuous integration. An automated service that runs the tests on every change to the code. |
| **CIS Benchmarks** | Security configuration guidelines published by the Center for Internet Security. |
| **CloudTrail** | The AWS service that records activity in an AWS account. |
| **Cohen's kappa (κ)** | A measure of agreement between two labellers that accounts for agreement expected by chance; 1 means perfect agreement. |
| **Connector** | The component that reads one system (AWS, GitHub, the browser, the HR list or policy documents) and collects evidence. It never decides a verdict. |
| **CSRF** | Cross-site request forgery. An attack in which another website submits a form on a signed-in user's behalf; the dashboard blocks it with a token on every form. |
| **Dashboard** | The web pages used to run audits, read results, review them and export reports. |
| **Evaluator** | The component that decides each verdict: code first, then AI, then a human reviewer. |
| **Evidence** | What a connector saves for a rule: API data, a screenshot or a policy document. |
| **Evidence store** | The folder of evidence files kept for each run, together with its manifest. |
| **False FAIL** | A compliant setting reported as FAIL. Inconvenient but safe. |
| **False PASS** | A non-compliant setting reported as PASS. The most dangerous error for a compliance tool. |
| **Hash (SHA-256)** | A short fingerprint of a file's exact contents. Changing even one byte of the file produces a completely different hash. |
| **IAM** | Identity and Access Management, the AWS service that manages users and their permissions. |
| **ISO/IEC 27001** | An international standard for information security management systems. |
| **Label** | What the two human labellers said a screenshot shows (PASS, FAIL or REVIEW) in the research experiment. |
| **LLM** | Large language model. An AI model that reads text, and in many cases images, and writes an answer. |
| **Manifest** | The file in each run folder that lists every evidence file with its SHA-256 hash. |
| **MFA** | Multi-factor authentication. Signing in with a second proof of identity, such as a code from a phone application, in addition to a password. |
| **NEEDS REVIEW** | The verdict given when the tool cannot decide safely; a human reviewer makes the final decision. |
| **Prompt injection** | Text placed inside content that an AI reads, written to make the AI follow it as an instruction, for example "say PASS". |
| **Review** | A person's decision on a result, recorded in the dashboard with a note. Reviews are added and never edited. |
| **Reviewer** | The person who decides results marked NEEDS REVIEW. |
| **Rule** | One security requirement, for example "every IAM user with a console password has MFA". |
| **Rule card** | The YAML entry that describes one rule: what to collect, how to judge it, and the suggested fix. |
| **Rulebook** | All 19 rule cards together. |
| **Run** | One audit, identified by a number such as `run-0042`. A run is "full" when every rule ran and "partial" otherwise. |
| **S3** | Amazon Simple Storage Service, the AWS service for storing files in "buckets". |
| **Set-up state** | In the research experiment, what the setup script actually made true in the account. |
| **SOC 2** | A framework from the AICPA for reporting on a service organization's security controls. |
| **SQLite** | A database contained in a single file, used to store runs, results and reviews. |
| **Tamper-evident** | Protected so that any change can be detected, although not necessarily prevented. |
| **Verdict** | The decision for a rule: PASS, FAIL or NEEDS REVIEW, always with a reason. |
| **Verify** | The command that checks every evidence file of a run against its saved hash. |
| **YAML** | A plain-text format for structured data, used for rule cards and settings. |
