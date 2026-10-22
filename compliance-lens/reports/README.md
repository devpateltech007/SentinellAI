# reports/ — generated audit reports (not committed)

**Version:** V6.

**Purpose:** exported audit reports land here, one folder per run. The code that builds
them is in `compliancelens/reporting/`.

```
reports/run-0042/
  run-0042-r17.html          the report: one self-contained page (styles and pictures inside)
  run-0042-r17.export.json   what it was made from (run, review snapshot, the evidence
                             manifest's hash, report version) and the report files' hashes
```

- **Make one:** `python audit.py report run-0042` (or `make report RUN=run-0042`). It reads
  only the saved run: no AWS, GitHub or AI call, so it works offline.
- **`r17`** is the review snapshot: every review up to review #17 is counted. A later
  review makes a new report beside this one; an existing report is never overwritten
  (exporting the same snapshot again keeps the file that is there).
- **Not evidence.** The `.export.json` hashes describe the report files; the audit's own
  evidence hashes stay in its manifest, and exporting never changes the audit (it still
  passes `verify`).
- A run that is still running, failed, was interrupted, or doesn't verify gets no report;
  the command says why and what to do.

**Never commit:** generated reports. They contain evidence from real accounts.
The folder is gitignored. A sample report made from a made-up audit goes in `docs/`.
