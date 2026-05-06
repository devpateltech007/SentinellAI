# Phase 5 — Implementation Audit Report

**Date**: 2026-05-05  
**Scope**: Phase 5 Frontend Real-Time Updates, commit `b5354a51a7c374ae0b99f37386c9bcecedf38a68`  
**Verification**: frontend lint/type/build passed; backend task API tests could not run because local PostgreSQL was unavailable; backend `ruff` and `mypy` fail on Phase 5 backend files

> Note: The requested commit `b5354a51a7c374ae0b99f37386c9bcecedf38a68` is the latest commit in this checkout, not second-latest. I audited that exact commit as the Phase 5 implementation.

---

## Plan vs. Implementation Checklist

| Task | Plan Requirement | Status | Notes |
|---|---|---|---|
| 5.1 | Add backend SSE endpoint at `/tasks/{task_id}/stream` | ✅ Mostly done | Endpoint exists and streams Celery task states |
| 5.1 | Register tasks router | ✅ Done | Router registered in `main.py` |
| 5.1 | Connector trigger returns `task_id` | ✅ Done | `ConnectorStatusResponse.task_id` added |
| 5.1 | Header auth and query-param auth both work | ❌ Likely broken | Query-param auth is blocked by `CurrentUser` dependency before manual token fallback can run |
| 5.1 | Unauthorized requests return 401 | ✅ Intended | Test exists but could not run locally due DB |
| 5.2 | Add `useTaskStream()` hook | ✅ Done | Hook opens `EventSource`, parses state/result/error, closes on terminal states |
| 5.2 | Clean connection close on unmount | ✅ Done | Cleanup closes EventSource |
| 5.3 | Connector trigger UI shows progress | ✅ Mostly done | Spinner/status messages implemented |
| 5.3 | Button disables immediately after click | ⚠️ Partial | Disabled only when SSE state becomes `PENDING`/`STARTED`; duplicate clicks are possible before first event |
| 5.3 | Auto-reset after completion | ✅ Done | Clears `taskId` after 5 seconds |
| 5.4 | Dashboard auto-refresh every 30 seconds | ✅ Done | Polling implemented |
| 5.4 | Last-updated indicator and refresh spinner | ✅ Done | Implemented |
| 5.4 | Animate changed stat cards | ⚠️ Buggy | Previous-summary ref is not updated after changed polls |
| 5.5 | Add `ControlDrawer` | ✅ Mostly done | Fetches control detail and displays core sections |
| 5.5 | Click a control row opens drawer | ⚠️ Partial | Dashboard failures open drawer; project control rows only expand, then require "View Details" |
| 5.5 | Drawer slides in/out | ⚠️ Partial | It appears as a fixed panel; no closed/open transform state or slide-out animation |
| 5.5 | Evidence links are clickable | ⚠️ Partial | Evidence item opens modal, but `source_ref` itself is not rendered as a link |
| 5.6 | Add `EvidenceModal` | ✅ Mostly done | Opens from evidence list and drawer |
| 5.6 | Integrity badge calls `/evidence/{id}/verify` | ✅ Done | Handles valid/invalid/error states |
| 5.6 | Modal closes on Escape/outside click | ✅ Done | Implemented |
| 5.6 | `source_ref` shown as link | ❌ Missing | Modal renders plain text, not a clickable link |

---

## Definition of Done Verification

| Area | Result |
|---|---|
| Backend task API tests | ⚠️ Could not run locally; PostgreSQL was not available on `localhost:5432` |
| Backend `ruff` on Phase 5 task files | ❌ Failed with 6 issues |
| Backend `mypy app` | ❌ Failed with 5 issues, including the Phase 5 `current_user=None` typing problem |
| Frontend ESLint | ✅ Passed |
| Frontend TypeScript | ✅ `npx tsc --noEmit` passed |
| Frontend production build | ✅ Passed after allowing network access for Google Fonts |
| Manual SSE stream with real Celery task | ⚠️ Not run during this audit |
| Browser/UI interaction verification | ⚠️ Not run during this audit |

Commands run:

```bash
venv/bin/python -m pytest tests/test_api/test_tasks.py
venv/bin/ruff check app/api/tasks.py tests/test_api/test_tasks.py
venv/bin/mypy app
npm run lint
npx tsc --noEmit
npm run build
```

The frontend checks passed:

```text
npm run lint      ✅
npx tsc --noEmit  ✅
npm run build     ✅ with network access for Google Fonts
```

The backend task API tests errored before exercising behavior because the test DB connection failed:

```text
PermissionError: [Errno 1] Operation not permitted
```

When retried with elevated local network access in previous API test runs, the environment still had no PostgreSQL server listening on `localhost:5432`.

---

## Issues Found

### Bug 1: Query-param SSE auth is likely unreachable

**Severity: High**

The plan explicitly calls out the browser `EventSource` auth caveat: since `EventSource` cannot send custom `Authorization` headers, the backend must accept `?token=...`.

The implementation tries to do that:

```python
async def stream_task_status(
    task_id: str,
    current_user: CurrentUser = None,
    token: str = Query(default=None),
):
```

But `CurrentUser` is an `Annotated[..., Depends(get_current_user)]` alias. FastAPI will resolve that dependency before entering the route. Without an `Authorization` header, `OAuth2PasswordBearer` raises `401`, so the manual `if not current_user and token:` fallback is unlikely to execute for real browser `EventSource` calls.

`mypy` also flags this as incompatible:

```text
app/api/tasks.py:15: error: Incompatible default for parameter "current_user"
```

**Recommended fix**: Do not use `CurrentUser` directly for this endpoint. Use an optional auth dependency that checks the header if present, otherwise validates the query token manually. Add a test that sends only `?token=<valid token>` and no Authorization header.

### Bug 2: Task API tests depend on missing `pytest-mock`

**Severity: Medium**

`test_stream_task_status_authorized()` uses the `mocker` fixture:

```python
async def test_stream_task_status_authorized(..., mocker):
```

But `pytest-mock` is not listed in `backend/requirements.txt`, and the active pytest plugin list does not include it. Once the DB blocker is fixed, this test will likely fail with `fixture 'mocker' not found`.

**Recommended fix**: Either add `pytest-mock` to requirements or use `unittest.mock.patch` directly.

### Bug 3: Dashboard change animation compares against stale data

**Severity: Medium**

`StatusSummaryCards` stores `prevSummaryRef`, computes changed keys, and returns a cleanup when changes exist:

```tsx
if (changes.size > 0) {
  const timer = setTimeout(() => setChangedKeys(new Set()), 1000);
  return () => clearTimeout(timer);
}
prevSummaryRef.current = summary;
```

When a poll actually changes counts, the early return prevents `prevSummaryRef.current` from being updated to the new summary. After that, future polls can keep comparing against stale data and re-trigger animations even when the latest data did not change.

**Recommended fix**: Assign `prevSummaryRef.current = summary` before returning the cleanup, or restructure the effect so the previous snapshot is always advanced.

### Bug 4: Connector trigger can be double-clicked before first SSE state arrives

**Severity: Medium**

The trigger button is disabled only when `state === "STARTED" || state === "PENDING"`:

```tsx
disabled={state === "STARTED" || state === "PENDING"}
```

After `POST /connectors/{id}/trigger` returns and `taskId` is set, `state` remains `null` until the first SSE event arrives. During that gap, the button still says "Trigger" and can dispatch duplicate Celery tasks.

**Recommended fix**: Add a local `isTriggering` state or disable whenever `taskId` is non-null and not complete.

### Bug 5: Backend Phase 5 code is not lint-clean

**Severity: Low**

`ruff` fails on `app/api/tasks.py` and `tests/test_api/test_tasks.py`:

```text
I001 import block unsorted
F401 fastapi.Depends imported but unused
W293 blank line contains whitespace
```

**Recommended fix**: Sort imports, remove `Depends`, and strip whitespace.

### Gap 6: SSE tests do not prove the browser path

**Severity: Medium**

The authorized test intends to use query-param auth:

```python
client.stream("GET", f"/api/v1/tasks/test-task-id/stream?token={token}")
```

But because the test could not run, the critical browser path is unverified. More importantly, the implementation shape suggests the test would expose the auth bug if it ran with a real DB and no Authorization header.

**Recommended fix**: Add a focused test that avoids full DB setup where possible by unit-testing the auth helper/event generator, and add an API test that explicitly omits the Authorization header.

### Gap 7: ControlDrawer does not fully meet the planned interaction

**Severity: Low**

The component displays the planned data sections, but it does not implement a true slide-in/slide-out state. It mounts directly as a fixed right panel with transition classes but no `translate-x-full` closed state or delayed unmount for slide-out.

Also, in the project controls table, clicking a row expands it; the drawer opens only after clicking "View Details". The plan says clicking any control row from dashboard failures or project controls should open the drawer.

**Recommended fix**: Add controlled open/closing animation state and wire row click, or document the expand-then-details interaction as an intentional UX deviation.

### Gap 8: Evidence source references are not clickable links

**Severity: Low**

The plan says evidence entries should show `source_ref` as a clickable link. In both `ControlDrawer` and `EvidenceModal`, `source_ref` is rendered as text. The evidence item itself is clickable to open the modal, but the source reference does not navigate to the underlying source.

**Recommended fix**: Render `source_ref` as an `<a>` when it is an HTTP(S) URL, with safe `target="_blank"` and `rel="noreferrer"`.

---

## Test Quality Assessment

### `test_tasks.py`

✅ Intended coverage:
- Missing token returns `401`
- Invalid token returns `401`
- Authorized SSE stream returns a `SUCCESS` event with result payload

⚠️ Problems:
- Could not execute due unavailable test DB
- Uses `mocker` without declaring `pytest-mock` dependency
- Does not verify header-based auth still works
- Does not verify `PENDING` → `STARTED` → `SUCCESS` sequence
- Does not verify stream closes after terminal state beyond reading one immediate terminal response
- Does not prove the browser `EventSource` query-token path because the dependency setup likely rejects it first

### Frontend Tests

No frontend unit/component tests were added for Phase 5. The TypeScript compiler and ESLint pass, which is good, but there are no tests for:

- `useTaskStream()` event parsing and cleanup
- Connector double-click prevention
- Dashboard changed-card animation behavior
- Drawer close/open behavior
- Evidence modal integrity badge states

This leaves the most interactive parts of Phase 5 dependent on manual QA.

---

## Changes Beyond Plan Scope

Mostly acceptable:

- `ControlTable` now embeds a "View Details" path to the drawer in expanded rows. This is useful, though it differs from direct row-click drawer opening.
- `EvidenceList` opens the new modal directly from row click, which aligns with the intended evidence drill-down experience.

Potentially problematic:

- The frontend implementation assumes query-param SSE auth works, but the backend route still uses the strict `CurrentUser` dependency.

---

## Overall Alignment Verdict

Phase 5 is **partially aligned**. The broad feature set is present: backend task streaming, task IDs on connector trigger, a React SSE hook, connector progress UI, dashboard auto-refresh, control drawer, and evidence modal with integrity badge.

However, the most important end-to-end path, connector trigger → task ID → browser `EventSource` stream, is likely broken because query-param auth is not actually optional at the backend dependency layer. There are also meaningful UI correctness gaps around duplicate trigger prevention and dashboard change detection.

| Item | Priority |
|---|---|
| Fix SSE query-token auth so browser `EventSource` works | High |
| Add/repair backend SSE tests, including `pytest-mock` dependency or equivalent patching | High |
| Prevent duplicate connector triggers before first SSE event | Medium |
| Fix dashboard stale previous-summary animation logic | Medium |
| Clean backend Phase 5 `ruff` and `mypy` failures | Medium |
| Add frontend component/hook tests for the interactive pieces | Medium |
| Make evidence `source_ref` values clickable where appropriate | Low |
| Add real slide-out animation or document the drawer UX deviation | Low |

Phase 5 should not be treated as complete until the SSE browser auth path is verified with a real valid token and no Authorization header.
