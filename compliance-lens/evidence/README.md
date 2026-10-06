# evidence/ — collected proof (generated, not committed)

**Version:** V1 (JSON per rule per day). V2: one folder per run, meta files, manifest, hashes.
V3: stamped screenshots.

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
      AWS-02.png         V3: the page screenshot with a banner on top
      manifest.json      run ID, start/finish times, tool version, every file + sha256 + size
```

Files are written atomically (temporary file, then rename), so a crash never leaves
half a file. Every hash is the SHA-256 of the exact bytes on disk.

**Screenshots (V3).** Rules with a web page also get `<ID>.png`: the browser's picture
with a 32-pixel banner added **above** it (so it hides nothing), reading
`ComplianceLens | <rule> | <UTC time> | <URL>`. The URL is cleaned: no passwords,
no token-like query values, no AWS account ID. The meta file's `screenshot` block holds:

| Field | Meaning |
| --- | --- |
| `status`, `reason` | `captured`, or why not (e.g. `session_expired`) |
| `file`, `stamped_sha256` | The PNG on disk and its hash (checked by `verify`) |
| `raw_sha256` | Hash of the browser's picture **before** the banner. The raw picture is not kept, so this can't be re-checked; V4 uses it as the AI cache key |
| `captured_at`, `requested_url`, `final_url` | When, and which page (cleaned) |
| `width`, `height`, `banner_height`, `full_page` | Picture size; V4 cuts `banner_height` off to get the raw picture back |

A failed screenshot writes no PNG; its status and reason are still in the meta file and
the database. A screenshot-only rule's `<ID>.json` is `{"screenshot_only": true}`.

For AWS-05 and AWS-06 the screenshot shows the test bucket only; the JSON covers every
bucket and stays the real proof.

**Checking a run:** `python audit.py verify run-0007` (or `make verify RUN=run-0007`):

1. The manifest's hash must match the one in the database.
2. Every file in the manifest must exist and match its hash.
3. Every raw evidence, meta and PNG file must also match the hash in the database.
4. Every meta file's `stamped_sha256` must match its PNG.
5. Extra files are reported as warnings (`.DS_Store` is ignored).

Any problem gives exit code 1. **Limit:** this is tamper-*evident*, not tamper-proof.
It catches files changed after the audit, but someone who rewrites the files, the
manifest and the database together can hide a change.

**Try it safely:** edit a copy, not the only evidence you have:
`cp -R evidence/2026-10-29/run-0007 /tmp/run-0007-backup`, edit `AWS-02.json` (or open
`GH-01.png` in Preview, draw on it and save), run `verify` (FAILED), then copy the backup
back and `verify` again (OK).

**Never commit:** anything except this README. Evidence can contain user names,
account IDs and settings, and screenshots show them as pictures. The whole folder is
gitignored.
