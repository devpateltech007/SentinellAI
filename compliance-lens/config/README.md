# config/ — project settings

**Version:** V5 (rules turned off). V6 adds repo names and the AWS region.

**Purpose:** one settings file so nothing is hard-coded.

**`settings.yaml`** (read by `compliancelens/config.py`):

```yaml
disabled_rules: [AWS-04, HR-01]   # V5: left out of audits; every other rule runs
```

- Every rule is on unless it is listed, so a rule added to the rulebook later is on.
  No file means every rule is on.
- The dashboard's Rules page writes it (V5); you can also edit it by hand. A change
  applies to the next audit. The rulebook itself (`rules/`) is never changed.
- `python audit.py run` leaves the listed rules out and says so; the run is then
  partial. A rule named with `--rule` runs even when it is turned off.
- Each run records the rules it ran and keeps a copy of the rulebook it read
  (`rulebook.yaml` in its evidence folder), so a later change here never rewrites history.
- It is a local preference: gitignored. Use another file with `COMPLIANCELENS_SETTINGS=...`.

**Never commit:** tokens or passwords. Those stay in `.env`.
