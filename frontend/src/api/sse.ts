import type { TaskState } from "./client";

/** Progress event pushed by GET /api/tasks/{id}/events (backend SSE). */
export interface StageEvent {
  type: "stage";
  stage: string;
  done: number;
  total: number;
}

/** Terminal success event carrying the analysis result. */
export interface DoneEvent {
  type: "done";
  result: unknown;
}

/** Terminal failure event. */
export interface ErrorEvent {
  type: "error";
  code: string;
  message: string;
}

export type TaskEvent = StageEvent | DoneEvent | ErrorEvent;

export interface SSEHandlers {
  onStage?: (stage: string, done: number, total: number) => void;
  onDone?: (result: unknown) => void;
  onError?: (code: string, message: string) => void;
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

function eventsUrl(taskId: string): string {
  return `/api/tasks/${encodeURIComponent(taskId)}/events`;
}

function taskUrl(taskId: string): string {
  return `/api/tasks/${encodeURIComponent(taskId)}`;
}

function parseEvent(raw: string): TaskEvent | null {
  try {
    return JSON.parse(raw) as TaskEvent;
  } catch {
    return null;
  }
}

/**
 * Subscribe to a task's SSE progress stream via native EventSource.
 *
 * Returns an unsubscribe function. On a connection error the handler checks
 * the task's current state: if the task already reached a terminal status
 * (succeeded/failed/cancelled) the terminal event is delivered from the
 * state and the subscription stops; otherwise it reconnects after 1s.
 */
export function subscribeTask(taskId: string, handlers: SSEHandlers): () => void {
  let source: EventSource | null = null;
  let closed = false;
  let retryTimer: number | undefined;

  const stop = () => {
    closed = true;
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer);
      retryTimer = undefined;
    }
    source?.close();
    source = null;
  };

  const handleTerminalState = async () => {
    if (closed) {
      return;
    }
    let state: TaskState | null = null;
    try {
      const response = await fetch(taskUrl(taskId));
      if (response.ok) {
        state = (await response.json()) as TaskState;
      }
    } catch {
      // Backend unreachable; fall through and retry.
    }
    if (closed) {
      return;
    }
    if (state && TERMINAL_STATUSES.has(state.status)) {
      if (state.status === "succeeded") {
        handlers.onDone?.(state.result);
      } else {
        handlers.onError?.(state.error_code ?? "task_failed", state.error ?? "task failed");
      }
      stop();
      return;
    }
    retryTimer = window.setTimeout(connect, 1000);
  };

  const connect = () => {
    if (closed) {
      return;
    }
    source = new EventSource(eventsUrl(taskId));
    source.onmessage = (event) => {
      const parsed = parseEvent(event.data);
      if (!parsed) {
        return;
      }
      switch (parsed.type) {
        case "stage":
          handlers.onStage?.(parsed.stage, parsed.done, parsed.total);
          break;
        case "done":
          handlers.onDone?.(parsed.result);
          stop();
          break;
        case "error":
          handlers.onError?.(parsed.code, parsed.message);
          stop();
          break;
      }
    };
    source.onerror = () => {
      // EventSource already closed the connection; check the task state to
      // decide between stopping and reconnecting after 1s.
      source?.close();
      source = null;
      void handleTerminalState();
    };
  };

  connect();
  return stop;
}
