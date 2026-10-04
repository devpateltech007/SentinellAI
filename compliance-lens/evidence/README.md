# evidence/ — collected proof (generated, not committed)

**Version:** V1 (JSON per rule per day). V2: one folder per run, meta files, manifest, hashes.

**Purpose:** every audit run writes the raw evidence here so each verdict can be traced.
Override the location with `COMPLIANCELENS_EVIDENCE_DIR`.

**Layout:**
```
evidence/
  2026-10-15/
    AWS-01.json          V1: one result per rule (old runs are left as they are)
  2026-10-29/            the run's start date, in UTC
    run-0007/            V2: one folder per run; the number comes from compliance.db
      AWS-02.json        raw evidence: exactly what the collector returned
      AWS-02.meta.json   rule, verdict, reason, method, confidence, collector,
                         timestamp, tool version, evidence file name + sha256
      AWS-02.png         V3: stamped screenshot
      manifest.json      run ID, start/finish times, tool version, every file + sha256 + size
```

Files are written atomically (temporary file, then rename), so a crash never leaves
half a file. Every hash is the SHA-256 of the exact bytes on disk.

**Checking a run:** `python audit.py verify run-0007` (or `make verify RUN=run-0007`):

1. The manifest's hash must match the one in the database.
2. Every file in the manifest must exist and match its hash.
3. Every raw evidence and meta file must also match the hash in the database.
4. Extra files are reported as warnings (`.DS_Store` is ignored).

Any problem gives exit code 1. **Limit:** this is tamper-*evident*, not tamper-proof.
It catches files changed after the audit, but someone who rewrites the files, the
manifest and the database together can hide a change.

**Try it safely:** edit a copy, not the only evidence you have:
`cp -R evidence/2026-10-29/run-0007 /tmp/run-0007-backup`, edit `AWS-02.json`, run
`verify` (FAILED), then copy the backup back and `verify` again (OK).

**Never commit:** anything except this README. Evidence can contain user names,
account IDs and settings. The whole folder is gitignored.
