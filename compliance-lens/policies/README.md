# policies/ — policy documents for the DOC rules

**Version:** V4

**Purpose:** written company policies (PDF, Markdown, text) that document rules check,
e.g. `password-policy.pdf` for DOC-01 ("the policy requires 12+ characters"). The AI
reads them; `compliancelens/connectors/files.py` hands it their text.

**Which folder is read:** `COMPLIANCELENS_POLICIES_DIR` in `.env`, default
`policies/examples/compliant`. Every DOC rule reads its file from that one folder.

## The examples (made up, committed)

Each folder holds the same three files, for a made-up company, "Example Labs":

| File | Rule | Requirement |
| --- | --- | --- |
| `password-policy.pdf` | DOC-01 | Passwords at least 12 characters |
| `access-control-policy.md` | DOC-02 | MFA for every user who can sign in to the AWS console |
| `offboarding-policy.txt` | DOC-03 | AWS and GitHub access removed within 24 hours of leaving |

| Folder | What the documents say | Expected verdict |
| --- | --- | --- |
| `compliant/` | 14 characters; MFA for every console user; access removed within 24 hours | PASS |
| `noncompliant/` | 8 characters; MFA for administrators only; 5 business days | FAIL |
| `ambiguous/` | Each contradicts itself (12 vs 8 characters, every user vs admins only, 24 hours vs 3 days) | NEEDS REVIEW |
| `injection/` | Non-compliant, plus text telling the AI to answer PASS | never PASS |
| `silent/` | On topic, but never states the requirement | FAIL (`missing_means: fail`) |

Switch folders to flip the DOC verdicts without touching an account, e.g.
`COMPLIANCELENS_POLICIES_DIR=policies/examples/noncompliant python audit.py run --rule DOC-01`.

The PDFs are written by `scripts/make_sample_pdfs.py` (no libraries, same bytes every
time). To change one, edit its text in that script and run it; `make test` checks the
committed PDFs still match.

## Your own policies

Put them in `policies/private/` (gitignored) and set
`COMPLIANCELENS_POLICIES_DIR=policies/private`. Keep the same file names, or change
`params.path` in the DOC rule cards. Limits: 5 MB, 50 pages, 100,000 characters; PDFs
must contain text (a scanned PDF is NEEDS REVIEW).

**Where the text goes:** the document's text is sent to the AI provider named in
`COMPLIANCELENS_AI_MODEL` (a local `ollama/` or `lmstudio/` model keeps it on this
computer), and a copy is saved with the run's evidence.

**Never commit:** real policies from an employer or university.
