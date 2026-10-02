# compliancelens/dashboard/ — web dashboard

**Version:** V5 (empty until then)

**Purpose:** a web page so a non-technical person can run an audit, read results
and override verdicts.

**What goes here (V5):**
- `app.py`: Streamlit app with the pages Home, Results, Rule detail, Review queue,
  History and Rules.
- The audit runs in a background thread so the page does not freeze.
- Overrides never edit a result; they add a row to the `overrides` table, and a note is required.
- A single admin password from `.env` (`DASHBOARD_PASSWORD`), even on localhost.

**Library added in V5:** `streamlit` (or FastAPI + HTML templates if more control is needed).

**Never commit:** passwords or screenshots of real accounts.
