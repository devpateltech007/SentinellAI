# evidence/ — collected proof (generated, not committed)

**Version:** V1 (JSON per rule). V2 adds meta files, a run manifest and hashes.

**Purpose:** every audit run writes the raw evidence here so each verdict can be traced.

**Layout:**
```
evidence/
  2026-10-15/
    AWS-01.json          V1: one result per rule (verdict, reason, evidence, timestamp, sha256)
  2026-10-29/
    run-0007/            V2: one folder per run
      AWS-02.json        raw API data
      AWS-02.meta.json   timestamp, collector, sha256, tool version
      AWS-02.png         V3: stamped screenshot
      manifest.json      every file + hash for this run
```

**Never commit:** anything except this README. Evidence can contain user names,
emails and account settings. The whole folder is gitignored.
