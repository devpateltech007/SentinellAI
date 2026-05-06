"use client";

import { useState, useEffect, useRef } from "react";

export type TaskState = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE" | "RETRY" | "REVOKED" | null;

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
      setState((currentState) => {
        if (currentState === "SUCCESS" || currentState === "FAILURE" || currentState === "REVOKED") {
          es.close();
        }
        return currentState;
      });
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      // Reset state for new tasks
      setState(null);
      setResult(null);
      setError(null);
    };
  }, [taskId]);

  const isComplete = state === "SUCCESS" || state === "FAILURE" || state === "REVOKED";

  return { state, result, error, isComplete };
}
