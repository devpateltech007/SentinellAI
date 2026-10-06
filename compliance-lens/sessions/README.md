# sessions/ — saved browser logins (generated, not committed)

**Version:** V3

**Purpose:** screenshots need a logged-in browser. You log in **once by hand** and the
tool saves that login here; every later audit reuses it (see `connectors/browser.py`).

```bash
python audit.py login github     # or: make login SITE=github
python audit.py login aws        # or: make login SITE=aws
```

A browser window opens. Log in (with MFA), wait until the site shows you logged in, then
press **Enter** in the terminal. The tool checks the page really is logged in before it
saves anything; if not, or if you press Ctrl+C, the old file is kept as it was.

| File | Login | Lasts |
| --- | --- | --- |
| `github.json` | Your GitHub account (owner of the test organization) | Until GitHub signs it out |
| `aws.json` | IAM user `compliancelens-audit` (read-only, **never root**) | **12 hours** (an AWS limit) |

When a login has run out, the audit keeps every API verdict and says, for example,
`8 not saved (session expired). Fix: python audit.py login aws`. Log in again.
`python audit.py run --no-screenshots` runs the API checks without a browser.

**Use an authenticator-app code for MFA** if you can: Playwright's Chromium may not
offer a passkey stored in iCloud Keychain.

## Security

A session file works like a password: anyone with it is logged in as you.

- `github.json` is a **full login to your GitHub account**, including every personal
  repo, not only the test organization. Only owners can see the settings pages the
  screenshots need, so there is no read-only alternative.
- The folder is `0700` and every file `0600` (only you can read them). Their contents are
  never printed, logged, copied into evidence or the database, or used in CI. Tests
  use a temporary folder instead (`COMPLIANCELENS_SESSIONS_DIR`), never this one.
- **Deleting a file does not log you out on the website.** To remove a login, delete the
  file **and** revoke the session: GitHub → Settings → Sessions; AWS ends by itself
  after 12 hours. If the laptop is lost or shared, revoke all GitHub sessions.

**Never commit:** anything except this README. The folder is gitignored.
