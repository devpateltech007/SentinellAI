# Chapter 3: Technology Description

> **Notes for pasting into the Google Doc** (delete these boxes after pasting):
> boxes like this one say where a figure or table goes and where to find it. Everything
> else is report text.

This chapter describes the technologies used to build ComplianceLens and explains why each
was chosen. The technologies are grouped into three tiers. The client tier is what users
interact with: the command-line interface, the web dashboard and the audit report. The
middle tier contains the logic that connects to outside systems: the AWS and GitHub APIs,
the browser used for screenshots, and the AI models. The data tier stores the results and
the evidence.

The whole project is written in Python 3.11. Python was chosen because it has official or
well-supported libraries for every system the tool needs to reach, including AWS, GitHub,
browser automation and the major AI providers, so the entire tool could be built in a
single language. All the services used are free or nearly free, which suited a semester
project tested on personal accounts. Table 3.1 summarizes the choices.

> **Table 3.1 goes here. Caption:** "Table 3.1: Technology stack." Paste this table:

| Tier | Purpose | Technology | Reason for the choice |
| --- | --- | --- | --- |
| Client | Command-line interface | Typer | Clear commands and help text with little code |
| Client | Web dashboard | FastAPI, Jinja2, uvicorn | Real pages and addresses, secure sign-in, stays in Python |
| Client | Audit report | Jinja2 (HTML), WeasyPrint (PDF) | One template produces both formats |
| Middle | AWS access | boto3 (AWS SDK for Python) | Official AWS library |
| Middle | GitHub access | GitHub REST API with `requests` | Simple web requests; no extra library needed |
| Middle | Screenshots | Playwright with Chromium | Drives a real browser and saves login sessions |
| Middle | AI models | OpenAI and Anthropic libraries; any OpenAI-compatible model | Any provider can be used; the model is a setting |
| Data | Results | SQLite | One file, no database server |
| Data | Evidence | JSON and PNG files, SHA-256 hashes | Readable files whose changes can be detected |
| All | Configuration | YAML files and a `.env` file | Readable by non-programmers; secrets kept out of code |
| All | Testing | pytest, moto, GitHub Actions | Tests run offline on every change |

## 3.1 Client Technology

The client tier offers two ways to use the tool, a command-line interface and a web
dashboard, and one output, the audit report.

### 3.1.1 Command-line interface

The command-line interface (CLI) is built with Typer, a Python library that turns ordinary
Python functions into commands with built-in help text. It provides seven commands: `run`
to perform an audit, `history` to list past runs, `verify` to check a run's evidence,
`login` to save a browser login for screenshots, `report` to export an audit report,
`settings` to check the configuration, and `ai-test` to confirm that the AI model is set up
correctly. A short Makefile wraps the most common commands, so that, for example,
`make audit` runs a full audit.

The CLI was built first because it is simple to test and suits automation, such as a
scheduled audit. The dashboard, added later, calls the same functions, so both interfaces
always behave the same way.

### 3.1.2 Web dashboard

The web dashboard is built with FastAPI, a Python web framework, and Jinja2, a template
library that fills HTML pages with data. It is served by uvicorn, a lightweight Python web
server. This combination was chosen over simpler tools such as Streamlit because it gives
each page a real address, keeps users signed in when a page is refreshed, and can show the
progress of an audit while it runs. It also keeps the whole project in Python and shares
Jinja2 with the audit report.

The pages are plain HTML forms that work without JavaScript. The only interactive parts,
such as the live progress display and the result filters, use one small script written by
the team, so no third-party script is downloaded. For security, the dashboard answers only
on the user's own computer, requires a password, keeps the session in a signed cookie, and
protects every form against cross-site request forgery (CSRF).

### 3.1.3 HTML and PDF reports

The audit report is produced from a Jinja2 template as a single HTML page. All styles and
images are placed inside the page itself, so the report can be opened, emailed or archived
without any other files. The PDF version is produced from the same HTML file by
WeasyPrint, a Python library that converts HTML and CSS into PDF. Using one template for
both formats ensures that the HTML and PDF reports always contain the same content.

WeasyPrint relies on Pango, a text layout library, which must be installed on the
computer separately. For safety, WeasyPrint is configured so that it cannot load any file
or web address while producing the PDF.

## 3.2 Middle-Tier Technology

The middle tier connects ComplianceLens to the systems it audits and to the AI models that
judge screenshots and documents.

### 3.2.1 AWS and GitHub APIs

AWS is accessed through boto3, the official AWS library for Python. The tool signs in as a
dedicated IAM user that has only the AWS-managed **SecurityAudit** policy, which allows
reading security settings but not changing them. This user has no stored access keys;
instead, it signs in with the `aws login` command, which issues a session that renews
itself. For the running example AWS-02, boto3 lists every IAM user, checks which users have
a console password, and asks AWS for each user's MFA devices.

GitHub is accessed through its REST API using the `requests` library. A REST API is
reached with ordinary web requests, so no additional GitHub library was needed. The tool
uses a fine-grained GitHub token that is owned by the organization, is limited to the test
repository, and has only read-only permissions. With these settings, the tool cannot change
anything in either system, even if it contained a mistake.

### 3.2.2 Browser automation

Screenshots are captured with Playwright, a browser automation library that controls a
real Chromium browser. Playwright was chosen for three reasons. First, it is driven from
Python, so it runs in the same program as the rest of the tool. Second, it can wait for a
specific piece of text to appear and scroll to a setting before capturing it. Third, it can
save a login session to a file and reuse it later.

AWS and GitHub logins require MFA, which an automated tool should not handle. A user
therefore signs in once by hand with the `login` command, and Playwright saves the session
for later audits. An AWS console session lasts 12 hours, after which the user signs in
again. If a login has expired, the tool detects the signed-out page and records the problem
rather than saving a misleading screenshot.

### 3.2.3 LLM providers

A large language model (LLM) is an AI model that reads text, and in many cases images, and
writes an answer. ComplianceLens uses an LLM to judge screenshots and policy documents. The
tool supports three kinds of provider: OpenAI and Anthropic through their official Python
libraries, and any other service or local model that follows the OpenAI request format,
such as Ollama or LM Studio. The model is chosen with a single setting, so the tool is not
tied to one provider.

The model used in this project is `openai/gpt-6-luna`. It was selected after the team
measured five low-cost models on a small test with known answers; it was the cheapest model
that answered every question correctly, at about $0.0001 per check. To control cost, the
tool records the tokens and price of every call and stops calling the AI once a spending
limit per run is reached (by default, $2).

## 3.3 Data-Tier Technology

The data tier keeps two kinds of records: the results of each audit in a database, and the
evidence behind each result in files.

### 3.3.1 SQLite

Results are stored in SQLite, a database contained in a single file that needs no separate
server. This suits a tool that runs on one computer, and it allows the database to be
backed up or moved as a single file. SQLite still provides the features the tool depends
on: transactions, so that a run is saved completely or not at all; foreign keys, so that
records stay linked correctly;
and a write-ahead log, so that the dashboard can read results while an audit is writing
them. The database records its own schema version and upgrades itself when a newer version
of the tool first opens it.

### 3.3.2 Evidence store and hashing

Evidence is stored as ordinary files in one folder per run: JSON for API data and AI
answers, PNG for screenshots, and the original file for policy documents. Plain files were
chosen so that an auditor can open the evidence with common tools, without needing
ComplianceLens.

Each file is protected by a SHA-256 hash, calculated with Python's built-in `hashlib`
library. A hash is a short fingerprint of a file's exact contents; changing even one byte
of the file produces a completely different hash. The hashes are stored both in a manifest
file inside the run folder and in the database, which allows the `verify` command to detect
any file that was changed after the audit.

The next chapter shows how these technologies were combined in the detailed design of each
tier.
