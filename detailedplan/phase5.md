# Phase 5 — Frontend Real-Time Updates

> **Estimated Total**: 20 engineering hours
> **Dependencies**: Phase 1 Task 1.3 (integrity endpoint) for the evidence integrity badge. Phase 4 Task 4.7 (AI suggestions) for displaying evaluation rationale.
> **Rationale**: The frontend currently shows static data fetched once on page load. For a compliance platform that runs background evaluations every 5 minutes, users need to see changes without refreshing. This phase adds Server-Sent Events (SSE) for task progress, auto-refreshing dashboards, and interactive drill-down components.

---

## Current Frontend State

| Component | Path | Status |
|---|---|---|
| API Client | `src/lib/api.ts` | ✅ Generic `request<T>()` wrapper with auth |
| Type Definitions | `src/lib/types.ts` | ✅ Comprehensive interfaces for all entities |
| Auth Layout | `src/app/(authenticated)/layout.tsx` | ✅ Token check + Sidebar + Header |
| Dashboard Page | `src/app/(authenticated)/dashboard/page.tsx` | 🟡 Static fetch, no auto-refresh |
| Connectors Page | `src/app/(authenticated)/connectors/` | 🟡 List only, trigger returns no progress |
| Components | `src/components/` | 🟡 Basic shells for controls, dashboard, evidence, reports |

**Key frontend infrastructure already in place**:
- `api.ts` — typed fetch wrapper with Bearer token injection
- `types.ts` — full TypeScript interfaces matching every backend Pydantic schema
- Tailwind CSS 4 + Recharts for charts
- `lucide-react` for icons

---

## Task 5.1: Add SSE Endpoint for Celery Task Status

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/api/tasks.py`

**Files to Edit**:
- `backend/app/main.py` — register new router
- `backend/app/api/connectors.py` — return `task_id` from trigger endpoint

**Detailed Logic Brief**:

When a user triggers a connector or a framework control generation, they currently get back a 200 OK with no way to track the background task's progress. SSE (Server-Sent Events) provides a lightweight, unidirectional stream from server to client — perfect for progress updates.

**Step 1 — SSE Endpoint** in `api/tasks.py`:

```python
import asyncio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.api.deps import CurrentUser
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    current_user: CurrentUser,
):
    """Stream Celery task status via Server-Sent Events."""

    async def event_generator():
        previous_state = None
        while True:
            result = celery_app.AsyncResult(task_id)
            state = result.state  # PENDING, STARTED, SUCCESS, FAILURE, RETRY

            if state != previous_state:
                # Build SSE event payload
                data = {
                    "task_id": task_id,
                    "state": state,
                    "result": None,
                    "error": None,
                }

                if state == "SUCCESS":
                    data["result"] = result.result
                elif state == "FAILURE":
                    data["error"] = str(result.info)

                import json
                yield f"data: {json.dumps(data)}\n\n"
                previous_state = state

            # Stop streaming on terminal states
            if state in ("SUCCESS", "FAILURE", "REVOKED"):
                break

            await asyncio.sleep(2)  # Poll every 2 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

**Step 2 — Return task_id from connector trigger**: Update `connectors.py` trigger endpoint to include the Celery task ID in its response:

```python
@router.post("/{connector_id}/trigger", response_model=ConnectorStatusResponse)
async def trigger_connector(...):
    # ... existing validation ...
    task = collect_evidence.delay(str(connector.id))  # Celery returns AsyncResult
    return ConnectorStatusResponse(
        connector_id=connector.id,
        status="triggered",
        task_id=str(task.id),  # NEW — return the Celery task ID
    )
```

Update `ConnectorStatusResponse` schema to include `task_id: str | None = None`.

**Why SSE instead of WebSockets?** SSE is simpler (unidirectional, HTTP-based, auto-reconnects), requires no special library on the client (`EventSource` is built into browsers), and is sufficient since we only need server→client updates. WebSockets add complexity with no benefit here.

**Why poll every 2 seconds?** Celery task state changes are infrequent (a typical collection takes 5-30 seconds). Polling at 2s provides responsive UX without excessive Redis lookups.

**Definition of Done**:
1. Trigger a connector via POST. Response includes `task_id`.
2. Open `curl -N http://localhost:8000/api/v1/tasks/{task_id}/stream -H "Authorization: Bearer $TOKEN"` — see SSE events streaming: `data: {"state": "STARTED", ...}` then `data: {"state": "SUCCESS", "result": {...}}`.
3. Stream automatically closes after SUCCESS.
4. Unauthorized requests return 401.

---

## Task 5.2: Create React Hook for SSE Consumption

**Estimated Time**: 3 hours

**Files to Create**:
- `frontend/src/lib/useTaskStream.ts`

**Detailed Logic Brief**:

Create a custom React hook that wraps the browser's native `EventSource` API to consume the SSE endpoint. It manages connection lifecycle, reconnection, and provides reactive state updates.

```typescript
"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export type TaskState = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE" | "RETRY" | null;

interface TaskStreamResult {
  state: TaskState;
  result: Record<string, unknown> | null;
  error: string | null;
  isComplete: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useTaskStream(taskId: string | null): TaskStreamResult {
  const [state, setState] = useState<TaskState>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) return;

    // Get token for auth — SSE doesn't support headers natively,
    // so we pass it as a query parameter
    const token = localStorage.getItem("sentinellai_token");
    if (!token) return;

    const url = `${API_BASE}/api/v1/tasks/${taskId}/stream?token=${token}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setState(data.state);
        if (data.result) setResult(data.result);
        if (data.error) setError(data.error);

        // Close on terminal states
        if (["SUCCESS", "FAILURE", "REVOKED"].includes(data.state)) {
          es.close();
        }
      } catch (e) {
        console.error("Failed to parse SSE event:", e);
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects on error, but if task
      // is already complete, just close
      if (state === "SUCCESS" || state === "FAILURE") {
        es.close();
      }
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [taskId]);

  const isComplete = state === "SUCCESS" || state === "FAILURE";

  return { state, result, error, isComplete };
}
```

**Important SSE auth caveat**: The browser's `EventSource` API does NOT support custom headers. Since our backend requires `Authorization: Bearer <token>`, we pass the token as a query parameter. Update the backend SSE endpoint to also accept `token` as a query param:

```python
from fastapi import Query

@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    current_user: CurrentUser = None,
    token: str = Query(default=None),
):
    # If current_user wasn't resolved via header, try query param
    if not current_user and token:
        # Manually decode the token — reuse deps.get_current_user logic
        ...
```

**Definition of Done**:
1. Call `useTaskStream("some-task-id")` in a React component.
2. `state` reactively updates from `PENDING` → `STARTED` → `SUCCESS`.
3. On `SUCCESS`, `result` contains the Celery task return value.
4. On `FAILURE`, `error` contains the error string.
5. `isComplete` flips to `true` on terminal states.
6. EventSource connection closes cleanly on unmount (no memory leaks).

---

## Task 5.3: Add Connector Trigger with Progress Indicator

**Estimated Time**: 3 hours

**Files to Edit**:
- `frontend/src/app/(authenticated)/connectors/page.tsx`

**Files to Reference**:
- `frontend/src/lib/useTaskStream.ts` (from Task 5.2)
- `frontend/src/lib/types.ts` — `Connector` interface

**Detailed Logic Brief**:

Update the Connectors page so that clicking "Trigger" shows real-time progress feedback instead of a static success/error message.

**UX Flow**:
1. User clicks "Trigger" button on a connector row.
2. Button text changes to "Starting..." with a spinner icon.
3. POST `/connectors/{id}/trigger` returns `{ task_id }`.
4. Pass `task_id` to `useTaskStream()`.
5. While `state === "STARTED"`: show pulsing blue dot + "Collecting evidence..."
6. On `state === "SUCCESS"`: show green checkmark + "Collected {result.items_collected} items" for 5 seconds, then reset.
7. On `state === "FAILURE"`: show red X + error message in a tooltip.

```tsx
function ConnectorRow({ connector }: { connector: Connector }) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const { state, result, error, isComplete } = useTaskStream(taskId);

  const handleTrigger = async () => {
    try {
      const res = await api.post<{ task_id: string }>(
        `/connectors/${connector.id}/trigger`
      );
      setTaskId(res.task_id);
    } catch (e) {
      // Handle API error
    }
  };

  const renderStatus = () => {
    if (!taskId) return null;
    switch (state) {
      case "PENDING":
      case "STARTED":
        return (
          <span className="flex items-center gap-2 text-blue-600">
            <Loader2 className="h-4 w-4 animate-spin" />
            Collecting evidence...
          </span>
        );
      case "SUCCESS":
        return (
          <span className="flex items-center gap-2 text-green-600">
            <CheckCircle className="h-4 w-4" />
            {(result as any)?.items_collected ?? 0} items collected
          </span>
        );
      case "FAILURE":
        return (
          <span className="flex items-center gap-2 text-red-600"
                title={error || "Unknown error"}>
            <XCircle className="h-4 w-4" />
            Collection failed
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <tr>
      {/* ... connector info cells ... */}
      <td>
        <button
          onClick={handleTrigger}
          disabled={state === "STARTED" || state === "PENDING"}
          className="rounded bg-indigo-600 px-3 py-1 text-white disabled:opacity-50"
        >
          {state === "STARTED" ? "Running..." : "Trigger"}
        </button>
        {renderStatus()}
      </td>
    </tr>
  );
}
```

**Auto-reset after success**: Use a `useEffect` that clears `taskId` after 5 seconds on `isComplete`:

```tsx
useEffect(() => {
  if (isComplete) {
    const timer = setTimeout(() => setTaskId(null), 5000);
    return () => clearTimeout(timer);
  }
}, [isComplete]);
```

**Definition of Done**:
1. Click "Trigger" → button disables, spinner appears.
2. Progress text updates: "Collecting evidence..." → "4 items collected" (or similar).
3. Green checkmark shows for 5 seconds, then resets.
4. On failure, red X with error tooltip appears.
5. Button re-enables after completion.

---

## Task 5.4: Add Real-Time Dashboard Auto-Refresh

**Estimated Time**: 3 hours

**Files to Edit**:
- `frontend/src/app/(authenticated)/dashboard/page.tsx`

**Detailed Logic Brief**:

The dashboard currently fetches `GET /dashboard/summary` once on mount. Add periodic polling with visual feedback when data changes.

**Implementation**:

```tsx
export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const prevSummaryRef = useRef<DashboardSummary | null>(null);

  const fetchSummary = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const data = await api.get<DashboardSummary>("/dashboard/summary");
      setSummary(data);
      setLastUpdated(new Date());
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Initial fetch + 30-second polling
  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 30_000);
    return () => clearInterval(interval);
  }, [fetchSummary]);
```

**Animated stat cards**: When a count changes, apply a brief CSS animation:

```tsx
function StatCard({ label, count, prevCount, color, icon }: StatCardProps) {
  const changed = prevCount !== undefined && prevCount !== count;

  return (
    <div className={`rounded-xl border-l-4 p-6 transition-all duration-500
                     ${changed ? "scale-105 shadow-lg" : ""}
                     border-${color}-500 bg-${color}-50`}>
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold transition-all duration-700
                     ${changed ? "text-" + color + "-700" : "text-gray-900"}`}>
        {count}
      </p>
    </div>
  );
}
```

**"Last updated" indicator** in the dashboard header:

```tsx
<p className="text-sm text-gray-400 flex items-center gap-2">
  {isRefreshing && <Loader2 className="h-3 w-3 animate-spin" />}
  Last updated: {formatDistanceToNow(lastUpdated)} ago
</p>
```

Use a simple relative time formatter (or install `date-fns` if not already present). Track previous values using `useRef` to detect changes for animation triggers.

**Definition of Done**:
1. Dashboard loads and shows current stats.
2. Leave dashboard open. In another terminal, trigger an evaluation that changes a control status.
3. Within 30 seconds, dashboard stats update with a brief scale animation on the changed card.
4. "Last updated: X seconds ago" text updates in real time.
5. Small spinner icon shows during refresh.

---

## Task 5.5: Add Control Detail Drawer

**Estimated Time**: 4 hours

**Files to Create**:
- `frontend/src/components/controls/ControlDrawer.tsx`

**Detailed Logic Brief**:

Create a slide-in drawer component that shows full control details when clicking any control row (from Dashboard failures list or Project controls list). This is the primary interface for compliance managers to understand WHY a control passed or failed.

**Component Structure**:

```tsx
interface ControlDrawerProps {
  controlId: string | null;   // null = closed
  onClose: () => void;
}

export function ControlDrawer({ controlId, onClose }: ControlDrawerProps) {
  const [control, setControl] = useState<ControlDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!controlId) return;
    setLoading(true);
    api.get<ControlDetail>(`/controls/${controlId}`)
      .then(setControl)
      .finally(() => setLoading(false));
  }, [controlId]);
```

**Drawer Layout** (4 sections):

1. **Header**: Control code + title + status badge (color-coded). Close button (X icon).

2. **Details Section**: Description, source citation (in an italic blockquote), and source text. If `remediation` is present (control is failing), show it in a warning alert box.

3. **Evidence Section**: List of linked evidence items. Each shows `source_type` icon, `source_ref` as a clickable link, `collected_at` date, and truncated `sha256_hash` with a copy button.

4. **Status Timeline**: Vertical timeline of `status_history` entries. Each entry shows a colored dot (green/red/yellow), the date, and the rationale text. Most recent entry at top.

**Slide-in animation**:
```css
/* Overlay */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 40;
  transition: opacity 300ms;
}

/* Panel */
.drawer-panel {
  position: fixed;
  right: 0;
  top: 0;
  height: 100vh;
  width: 560px;
  max-width: 90vw;
  background: white;
  z-index: 50;
  transform: translateX(100%);
  transition: transform 300ms ease-out;
}
.drawer-panel.open {
  transform: translateX(0);
}
```

**Click-outside-to-close**: Add an `onClick` handler on the overlay div that calls `onClose()`.

**Definition of Done**:
1. Click a control row on the Dashboard "Recent Failures" list → drawer slides in from the right.
2. Drawer shows control title, status badge, description, citation, linked evidence, and timeline.
3. For failed controls, remediation box shows the failure reason in a yellow/red alert.
4. Click overlay or X button → drawer slides out.
5. Responsive: on mobile (< 640px), drawer takes full width.

---

## Task 5.6: Add Evidence Detail Modal with Integrity Badge

**Estimated Time**: 3 hours

**Files to Create**:
- `frontend/src/components/evidence/EvidenceModal.tsx`

**Detailed Logic Brief**:

When a user clicks an evidence item (from the Evidence page or from within the Control Drawer), show a modal with the full evidence content and an integrity verification badge.

**Modal Content**:

1. **Header**: Source type icon + source_ref as a link + collected_at date.
2. **Metadata Bar**: SHA-256 hash (first 16 chars + copy button), `redacted` badge (yellow if true), integrity badge.
3. **JSON Viewer**: `content_json` displayed in a formatted, syntax-highlighted `<pre>` block with proper indentation.

**Integrity Badge Logic**:

```tsx
function IntegrityBadge({ evidenceId }: { evidenceId: string }) {
  const [status, setStatus] = useState<"loading" | "valid" | "invalid" | "error">("loading");

  useEffect(() => {
    api.get<{ integrity_valid: boolean }>(`/evidence/${evidenceId}/verify`)
      .then((res) => setStatus(res.integrity_valid ? "valid" : "invalid"))
      .catch(() => setStatus("error"));
  }, [evidenceId]);

  const configs = {
    loading: { icon: Loader2, text: "Verifying...", className: "text-gray-400 animate-spin" },
    valid:   { icon: ShieldCheck, text: "Integrity Verified", className: "text-green-600" },
    invalid: { icon: ShieldAlert, text: "TAMPERED", className: "text-red-600 font-bold" },
    error:   { icon: ShieldQuestion, text: "Check unavailable", className: "text-gray-400" },
  };

  const config = configs[status];
  const Icon = config.icon;

  return (
    <span className={`flex items-center gap-1.5 text-sm ${config.className}`}>
      <Icon className="h-4 w-4" /> {config.text}
    </span>
  );
}
```

The badge calls `GET /evidence/{id}/verify` (from Phase 1 Task 1.3) on mount. It shows a spinner while loading, green shield on valid, and red "TAMPERED" warning on invalid. The `error` state handles cases where the user doesn't have ADMIN/AUDITOR role (403).

**JSON Viewer**: Simple formatted display — no external library needed:

```tsx
<pre className="max-h-96 overflow-auto rounded-lg bg-gray-900 p-4 text-sm text-green-400">
  {JSON.stringify(control.content_json, null, 2)}
</pre>
```

**Definition of Done**:
1. Click an evidence item → modal opens with formatted JSON and metadata.
2. Integrity badge shows green "Integrity Verified" for untampered evidence.
3. Tamper evidence in DB → reopen modal → badge shows red "TAMPERED".
4. Non-admin user → badge shows "Check unavailable" (403 handled gracefully).
5. Modal closes on Escape key or clicking outside.

---

## Phase 5 — Dependency Graph

```
Task 5.1 (SSE Backend Endpoint)        — No dependencies (but benefits from Phase 1 Task 1.3)
Task 5.2 (useTaskStream Hook)          — Depends on 5.1
Task 5.3 (Connector Progress UI)       — Depends on 5.2
Task 5.4 (Dashboard Auto-Refresh)      — No dependencies
Task 5.5 (Control Detail Drawer)       — No dependencies
Task 5.6 (Evidence Modal + Integrity)  — Depends on Phase 1 Task 1.3
```

**Parallelization**: Tasks 5.1, 5.4, and 5.5 can all start simultaneously. Task 5.6 can start as soon as the Phase 1 integrity endpoint exists. Tasks 5.2→5.3 are sequential.

**Recommended assignment**:
- **Person A**: Tasks 5.1 → 5.2 → 5.3 (SSE pipeline end-to-end)
- **Person B**: Task 5.4 (dashboard refresh — quick win)
- **Person C**: Task 5.5 (control drawer — largest frontend task)
- **Person D**: Task 5.6 (evidence modal + integrity badge)
