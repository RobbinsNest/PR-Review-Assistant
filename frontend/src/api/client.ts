/**
 * Typed client for the backend HTTP API (see backend/app/api/analyze.py,
 * history.py, settings.py for the contract).
 *
 * All requests go through the same relative "/api/..." paths; in dev Vite
 * proxies "/api" to http://localhost:8000, in production the SPA is served
 * same-origin by the backend.
 */

export interface AnalyzeResponse {
  task_id: string;
}

/** Public task state as returned by GET /api/tasks/{id} (backend TaskState). */
export interface TaskState {
  id: string;
  status: string;
  stage: string;
  progress_done: number;
  progress_total: number;
  result: unknown;
  error: string | null;
  /** Present on failed tasks; backend stores it on the state dict. */
  error_code?: string | null;
  created_at: string;
  updated_at: string;
}

/** One stored analysis record as returned by the history endpoints. */
export interface HistoryItem {
  id: string;
  owner: string;
  repo: string;
  pr_number: number;
  pr_title: string;
  pr_url: string;
  base_sha: string;
  head_sha: string;
  status: string;
  summary: unknown;
  findings: unknown[];
  error: string | null;
  config_snapshot: unknown;
  duration_ms: number;
  created_at: string;
  updated_at: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
}

/** Masked LLM settings returned by the settings endpoints. */
export interface LLMSettings {
  base_url: string;
  model: string;
  api_key_configured: boolean;
  api_key_masked: string | null;
}

/** Optional fields accepted by PUT /api/settings/llm. */
export interface SettingsUpdate {
  base_url?: string;
  model?: string;
  api_key?: string;
}

/** Result of POST /api/settings/llm/test (connectivity probe). */
export interface SettingsTestResult {
  ok: boolean;
  latency_ms: number;
  error: string | null;
}

/** Error carrying the HTTP status of a failed backend response. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      error?: { message?: string };
      detail?: unknown;
    };
    if (typeof body.error?.message === "string" && body.error.message) {
      return body.error.message;
    }
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Non-JSON error body; fall back to the status line.
  }
  return `HTTP ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Start an analysis task; resolves to the created task id. */
export function analyze(prUrl: string, githubToken?: string): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      githubToken ? { pr_url: prUrl, github_token: githubToken } : { pr_url: prUrl }
    ),
  });
}

/** Fetch the current state of a task (404 -> ApiError). */
export function getTask(taskId: string): Promise<TaskState> {
  return request<TaskState>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

/** List stored analyses, newest first. */
export function getHistory(limit = 50, offset = 0): Promise<HistoryPage> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<HistoryPage>(`/api/history?${params.toString()}`);
}

/** Hard-delete one stored analysis (204). */
export async function deleteHistory(id: string): Promise<void> {
  await request<void>(`/api/history/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Browser URL for the Markdown export of a stored analysis. */
export function exportUrl(id: string): string {
  return `/api/history/${encodeURIComponent(id)}/export`;
}

/** Current (masked) LLM settings. */
export function getSettings(): Promise<LLMSettings> {
  return request<LLMSettings>("/api/settings/llm");
}

/** Update LLM settings (only provided fields; empty api_key is a no-op). */
export function updateSettings(payload: SettingsUpdate): Promise<LLMSettings> {
  return request<LLMSettings>("/api/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Clear the stored LLM API key. */
export function clearSettings(): Promise<LLMSettings> {
  return request<LLMSettings>("/api/settings/llm", { method: "DELETE" });
}

/** Run a connectivity probe with the current LLM config. */
export function testSettings(): Promise<SettingsTestResult> {
  return request<SettingsTestResult>("/api/settings/llm/test", { method: "POST" });
}
