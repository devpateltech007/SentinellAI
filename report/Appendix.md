# Appendix

> **Notes for pasting into the Google Doc** (delete these boxes after pasting).

## Appendix A: The Rulebook

Table A.1 lists all 19 rules in the ComplianceLens rulebook, the method used to judge
each one, its severity, the matching item in a security standard where one exists, and the
suggested fix that the audit report shows when the rule fails. The suggested fixes are
written by hand in each rule card and are never generated from evidence.

> **Table A.1 goes here. Caption:** "Table A.1: The 19 rules." Paste this table. In
> Google Docs, a landscape page or a smaller font (9 pt) may help it fit.

| ID | Rule | Judged by | Severity | Standard | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| AWS-01 | Password policy requires 12+ characters | Code | Medium | CIS AWS 1.8 | IAM > Account settings > Password policy: set the minimum length to 12 characters or more (14 is the usual choice). Existing passwords follow the new policy when they are next changed. |
| AWS-02 | Every IAM user with a console password has MFA | Code | High | CIS AWS 1.10 | For each user named: IAM > Users > the user > Security credentials > Assign MFA device. If the user does not need the console, remove their console password instead. |
| AWS-03 | Root account has MFA | Code | High | CIS AWS 1.5 | Sign in as the root user and assign an MFA device (Security credentials > Multi-factor authentication). Prefer a hardware key and keep its recovery details offline. |
| AWS-04 | No active access key is older than 90 days | Code | Medium | CIS AWS 1.14 | For each key named: create a new access key, move whatever uses the old one to it, then deactivate and delete the old key. Prefer roles or short-lived credentials over long-lived keys. |
| AWS-05 | Every S3 bucket blocks public access | Code | High | CIS AWS 2.1.4 | For each bucket named: bucket > Permissions > Block public access, turn on all four settings. Turn them on for the whole account too, unless a bucket must be public by design. |
| AWS-06 | Every S3 bucket has versioning on | Code | Low | – | For each bucket named: bucket > Properties > Bucket Versioning > Enable. A lifecycle rule that expires old versions keeps the storage cost bounded. |
| AWS-07 | At least one CloudTrail trail is logging | Code | High | CIS AWS 3.1 | CloudTrail > Trails: start logging on the stopped trail, or create a multi-region trail that delivers to its own S3 bucket with versioning on. |
| AWS-08 | No IAM user has been inactive for more than 90 days | Code | Medium | CIS AWS 1.12 (adapted; CIS uses 45 days) | For each user named: confirm with their manager, then delete the user, or remove their console password and access keys if the account must stay. |
| GH-01 | Main branch requires at least 1 review | Code | High | CIS GitHub 1.1.3 | Repository Settings > Branches > edit the classic protection rule for the branch: tick "Require a pull request before merging" with at least 1 required approval. |
| GH-02 | Force pushes to main are blocked | Code | High | – | Repository Settings > Branches > edit the classic protection rule for the branch: leave "Allow force pushes" unticked (and "Allow deletions" too). |
| GH-03 | Secret scanning is enabled | Code | Medium | – | Repository Settings > Advanced Security: turn on Secret Protection (secret scanning), together with push protection. |
| GH-04 | Dependabot alerts are enabled | Code | Medium | – | Repository Settings > Advanced Security: turn on Dependabot alerts. |
| GH-05 | Every organization member has 2FA | Code | High | – | Ask each member named to turn on two-factor authentication, then require it for the organization (Settings > Authentication security). Members without it are removed when it is required. |
| GH-06 | Organization base repository permission is Read or None | Code | Medium | – | Organization Settings > Member privileges > Base permissions: choose Read or No permission, and give write access per team or per repository instead. |
| GH-07 | Members cannot delete or transfer repositories | AI (screenshot) | Medium | – | Organization Settings > Member privileges: untick "Allow members to delete or transfer repositories for this organization". |
| HR-01 | Every AWS and GitHub account belongs to an active employee | Code | High | SOC 2 CC6.2 | For each account named: if the person has left, remove the AWS user or the GitHub member; if it is a service account, add it to the allowed service accounts in the settings file; if it belongs to a current employee, correct the employee list. |
| DOC-01 | Password policy requires 12+ characters | AI (document) | Medium | – | Change the password policy so every password must be at least 12 characters long, with no exception that allows a shorter one, and have its owner approve and publish it. |
| DOC-02 | Policy requires MFA for every AWS console user | AI (document) | High | – | Change the access control policy to require MFA for every user who can sign in to the AWS console, not only for administrators, and have its owner approve and publish it. |
| DOC-03 | Offboarding removes AWS and GitHub access within 24 hours | AI (document) | High | – | Change the offboarding policy so both AWS and GitHub access are removed within 24 hours of someone leaving, and have its owner approve and publish it. |

## Appendix B: Sample Audit Report

This appendix contains a complete audit report produced by ComplianceLens. It was
generated from a made-up audit of a fictional company, "Example Labs", which is also used
by the project's automated report test. A made-up audit was used so that the report shows
no real account names, account numbers or settings. The report has five parts: a cover
page with the score and what was audited, a summary of every verdict, the findings with
failures first, the human reviews, and an appendix listing the SHA-256 hash of every
evidence file.

> **Report pages go here.**
> **Where to find them:** `compliance-lens/docs/sample-report.pdf` (8 A4 pages). Either
> insert each page as an image (open the PDF, take a screenshot of each page, and insert
> them one per page with the caption "Figure B.n: Sample audit report, page n of 8"), or,
> if the final report is submitted as a PDF, append the sample PDF's pages after this
> page.
