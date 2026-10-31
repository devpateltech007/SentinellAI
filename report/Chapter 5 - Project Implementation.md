# Chapter 5: Project Implementation

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

This chapter explains how the designs in Chapter 4 were implemented. It focuses on how
each part works internally and on the main problems the team solved while building it. The
tool was built in versions over the semester: the rule engine and the AWS and GitHub
connectors first, then the evidence store, screenshots, the AI evaluator, the dashboard,
and finally the audit report. The finished tool contains about 10,000 lines of Python.

## 5.1 Client Implementation

The command-line interface is a thin layer over the same functions that the dashboard
uses, so this section concentrates on the dashboard and on report generation.

### 5.1.1 Dashboard

The dashboard is a FastAPI application whose pages are filled from Jinja2 templates. The
main implementation challenge was running an audit, which takes about one and a half
minutes, without making the page wait. When a user starts an audit, the dashboard runs it
in a background thread and returns immediately. The audit reports its progress through
events (run started, rule started, rule finished, run finished), and the page asks for the
latest progress once every second. Because the audit belongs to the dashboard process and
not to the browser tab, reloading or closing the page does not stop it.

Only one audit may run at a time, because two audits would mix their browser sessions,
AI spending limits and database writes. This is enforced with an operating-system file
lock that every audit takes first, whether it was started from the dashboard, the command
line or the research experiment. The operating system releases the lock automatically if
the program crashes, so the lock can never be left stuck. A run that is still marked
"running" while no one holds the lock is shown as interrupted.

Security was implemented at several levels. The dashboard accepts requests only from the
user's own computer, which protects against attacks from other websites. The password is
compared in constant time, and each wrong attempt is delayed by one second to slow down
guessing. Pages are sent with a strict content security policy that blocks scripts from
other sources and prevents the dashboard from being embedded in another site. Evidence
files are served only from inside the evidence folder and only as text or images, never
as web pages, so that a malicious file cannot run code in the browser. Figure 5.1 shows the
Rule detail page, where a reviewer sees all of this evidence in one place.

> **Figure 5.1 goes here. Caption:** "Figure 5.1: The Rule detail page, with the
> evidence, the reason and the review form."
> **Where to find it:** `compliance-lens/docs/images/dashboard-detail.png` (from a
> made-up audit).

### 5.1.2 Report generation

Report generation is implemented in three steps. First, a data loader reads everything the
report needs from one finished run in a single database transaction, so the data cannot
change halfway through. It refuses any run that is unfinished or whose evidence fails
verification, and it checks every file against its saved hash as it reads it. All
information comes from what the run itself saved, including the rules and settings as they
were at the time. For older runs that did not save some of this information, the report
shows "not recorded" rather than filling it in from today's files.

Second, the HTML page is rendered from the Jinja2 template. All styles and images are
embedded in the page, every value is escaped so that evidence text cannot change the page,
and the page contains no scripts. Third, if a PDF is requested, WeasyPrint converts that
same HTML file into an A4 PDF with page numbers and table headings repeated on each page.
Each export also writes a small record of what it was made from, including the hashes of
the report files. A new export never overwrites an earlier one, so a report that has
already been shared is always preserved.

## 5.2 Middle-Tier Implementation

The middle tier holds the audit logic: the engine and runner that drive each audit, the
connectors that collect evidence, and the AI evaluator.

### 5.2.1 Engine and runner

The engine handles single rules: it loads and validates the rulebook, finds the collector
each rule names, and applies the check. The runner handles a complete audit (Figure 5.2).
It first reads the rulebook once, so that the rules that run, the hash that is recorded and
the copy that is saved all come from exactly the same file. It then records the run in the
database as "running", creates the evidence folder, and processes each rule in turn:
collect the evidence, judge it, take the screenshot, run the AI check if the rule has one,
and save the files and the result. Finally, it writes the manifest and marks the run
"complete" with its totals. If saving fails at any point, the run is marked "failed", so an
incomplete audit can never look finished.

A run is labelled "full" only when every rule in the rulebook ran; otherwise it is
"partial", for example when a user runs only AWS-02 after fixing it. Only full runs count
towards the score on the dashboard's Home page. The runner also logs how long each rule
took to collect, screenshot and judge, and the command line prints the three slowest rules
after each audit.

The engine never lets an error stop the audit. Each rule runs inside a final safety net:
if any unexpected error occurs, that rule becomes NEEDS REVIEW with the error as its reason,
and the audit continues with the next rule.

> **Figure 5.2 goes here. Caption:** "Figure 5.2: The steps of one audit run."
> **Where to find it:** this is a new diagram. Paste the source below into
> https://mermaid.live and download the PNG.
>
> ```mermaid
> flowchart TD
>     a["Take the audit lock"] --> b["Read and validate the rulebook once"]
>     b --> c["Record the run as 'running'<br/>and create its evidence folder"]
>     c --> d["Next rule"]
>     d --> e["Collect evidence<br/>(connector)"]
>     e --> f["Judge it<br/>(code check)"]
>     f --> g["Take the screenshot<br/>(if the rule has one)"]
>     g --> h["Run the AI check<br/>(if the rule has one)"]
>     h --> i["Save the files and the result"]
>     i --> j{"More rules?"}
>     j -- Yes --> d
>     j -- No --> k["Write the manifest"]
>     k --> l["Mark the run 'complete'<br/>with its totals"]
>     c -. "if saving fails" .-> m["Mark the run 'failed'"]
> ```

### 5.2.2 Connector implementations

Table 5.1 lists the five connectors and what each reads. Each collector function is short
and returns only the data its rule needs. Several practical problems had to be solved
while implementing them:

- **AWS-02 and the tool's own user.** The tool signs in as a user without a console
  password. A naive check would report this user as "without MFA" and the rule would
  always fail. The collector therefore checks MFA only for users who can actually sign in
  to the console, which matches the CIS benchmark.
- **AWS credential report.** Some AWS rules read a credential report, which AWS builds on
  request. The collector asks AWS to build it and waits until it is ready; building the
  report does not change any setting.
- **GitHub permissions.** Some GitHub settings, such as which members lack two-factor
  authentication, are visible only to organization owners. The connector reports a clear
  reason when the token lacks the needed permission, and the rule becomes NEEDS REVIEW.
- **Slow-loading pages.** The AWS Users page shows its table before the MFA column has
  loaded. The screenshot for AWS-02 therefore waits until no column is still loading, so
  the picture never shows an incomplete table.
- **Signed-out pages.** When a saved login has expired, AWS and GitHub redirect to a sign-in
  page. The browser connector recognizes these pages and records "session expired" instead
  of saving a picture of the sign-in page as evidence.
- **Privacy.** The HR connector saves only account names, never employee names or emails.
  Screenshots hide the user's account menu and every 12-digit AWS account number.

> **Table 5.1 goes here. Caption:** "Table 5.1: Connectors and what each reads." Paste
> this table:

| Connector | Reads | Used by |
| --- | --- | --- |
| AWS | Password policy, IAM users and their MFA devices, access key ages, the credential report, S3 bucket settings, CloudTrail trails (through boto3) | AWS-01 to AWS-08, HR-01 |
| GitHub | Branch protection, security features, organization members without two-factor authentication, organization settings (through the REST API) | GH-01 to GH-06, HR-01 |
| HR list | A CSV file that maps each active employee to their AWS user and GitHub login | HR-01 |
| Documents | A policy document in text, Markdown or PDF format | DOC-01 to DOC-03 |
| Browser | Screenshots of settings pages through Playwright, using saved logins | The 16 rules with a screenshot; for GH-07 the screenshot is the only evidence |

### 5.2.3 AI evaluator

The AI evaluator is implemented in layers so that the rest of the tool never depends on a
specific AI company. A neutral request and reply format sits between the evaluator and the
providers. Two small adapters translate this format into calls to the OpenAI and Anthropic
libraries; the OpenAI adapter also serves local and other compatible models. Every adapter
follows the same rules: a time limit on every call, no automatic retries inside the
library, and the full reply returned for the record.

The evaluator itself prepares the evidence, sends the request and checks the answer.
Screenshots are shrunk, never enlarged, to fit each model's image limits. If a picture
would have to be shrunk so much that small text becomes unreadable, it is not sent at all,
and the rule becomes NEEDS REVIEW. Failed requests are retried: a dropped connection up to
three more times, and other temporary errors once. The reply is then read strictly as the
JSON format described in Section 4.2.3 and passed through the checks in Table 4.3. For
documents, the quote is compared with the document text after making spacing and
punctuation consistent, so a correct quote is not rejected for a minor formatting
difference.

The cache and the spending limit are implemented around this process. Before calling the
model, the evaluator calculates a cache key from the evidence, the rule's wording, the
model and its settings, and the prompt version; if a matching accepted answer exists, it
is reused at no cost. After each call, the tokens used are converted to a cost and added
to the run's total, and no further calls are made once the limit is reached. The
`ai-test` command uses one made-up document and one made-up screenshot with known answers
to confirm that a model is set up correctly before a real audit.

## 5.3 Data-Tier Implementation

The data tier was implemented so that the stored records are always complete and cannot be
changed without detection.

### 5.3.1 Database and evidence writing

Every evidence file is written safely: the data is first written to a temporary file, which
is then renamed into place. If the program crashes during a write, the folder holds either
the old file or the new one, never half a file. Each write uses its own temporary name, so
two exports running at the same moment cannot interfere with each other.

The database protects its records with triggers, which are small rules stored in the
database itself. Results can never be edited or deleted, a finished run can never be
changed, and a review can never be edited or deleted and must always include a reviewer
and a note. These rules apply to every program that opens the database, not only to
ComplianceLens, so a mistake in the code cannot quietly change past results. The
database also uses write-ahead logging, so the dashboard can read results while an audit
is writing new ones.

### 5.3.2 The verify command

The `verify` command checks that a run's evidence has not changed since the audit. It
treats the database as the trusted record. It first checks the manifest file against the
manifest hash stored in the database. Only if the manifest matches does it re-calculate
the hash of every file in the run folder and compare each one with both the manifest and
the database. It reports any file that was changed, removed or added. Each meta file also
lists the hashes of its rule's screenshot, document and AI answers, and `verify` confirms
that these are the same files that were saved with the result.

The dashboard runs the same check whenever it shows a run's results or a rule's
evidence, and displays whether the evidence still verifies. The report export refuses any
run that fails the check, so a report can never be produced from altered evidence. As
explained in Chapter 2, this protection is tamper-evident rather than tamper-proof: a person who changes the files, the
manifest and the database together could hide the change.

The next chapter describes how the team tested ComplianceLens and confirmed that it
behaves correctly on real accounts.
