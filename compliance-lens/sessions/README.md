# sessions/ — saved browser logins (generated, not committed)

**Version:** V3 (empty until then)

**Purpose:** Playwright saves a logged-in browser session here (e.g. `github.json`)
after you log in once by hand with `python audit.py login github`. Later runs reuse it
to take screenshots.

**Never commit:** anything except this README. A session file works like a password:
anyone with it is logged in as you. The folder is gitignored.
