import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getTask } from "../api/client";
import DiffViewer from "../components/DiffViewer";
import ExportButton from "../components/ExportButton";
import FindingsList, { type Finding } from "../components/FindingsList";
import SummaryCard, { type AnalysisSummary } from "../components/SummaryCard";

/** Per-file unified diff (forward-compatible: mirrors backend PRContext.files). */
interface ResultFileDiff {
  path: string;
  diff: string;
}

/** Decoded task result: backend AnalysisResult { summary, findings, meta }. */
interface AnalysisResultData {
  summary: AnalysisSummary;
  findings: Finding[];
  meta?: Record<string, unknown>;
  files?: ResultFileDiff[];
}

const STATUS_SUCCEEDED = "succeeded";
const TERMINAL_FAILED = new Set(["failed", "cancelled"]);

/**
 * Result dashboard for one finished analysis task.
 *
 * Loads the task via getTask: terminal succeeded tasks render directly,
 * in-flight tasks redirect to the progress page, and failed/cancelled tasks
 * show an actionable error. The summary, findings list, per-file diff viewer
 * and (when the backend records a history id) export button are rendered
 * from the task result.
 */
export default function ResultPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResultData | null>(null);

  useEffect(() => {
    if (!taskId) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setRedirecting(false);
    setError(null);
    getTask(taskId)
      .then((state) => {
        if (cancelled) {
          return;
        }
        if (state.status === STATUS_SUCCEEDED) {
          setResult((state.result as AnalysisResultData) ?? null);
        } else if (TERMINAL_FAILED.has(state.status)) {
          setError(state.error ?? "任务失败");
        } else {
          // Still running: the live progress page owns this task now.
          setRedirecting(true);
          navigate(`/progress/${taskId}`, { replace: true });
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : "加载结果失败");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, navigate]);

  if (loading || redirecting) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-[1120px] px-6 py-10">
        <p className="text-sm text-ink-secondary">加载中…</p>
      </main>
    );
  }

  if (error || !result) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-[1120px] px-6 py-10">
        <div
          role="alert"
          className="rounded-md border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
        >
          <p className="font-medium">{error ?? "结果不可用"}</p>
          <button type="button" onClick={() => navigate("/")} className="mt-2 underline">
            重新开始
          </button>
        </div>
      </main>
    );
  }

  const findings = result.findings ?? [];
  const files = result.files ?? [];
  // Export requires a stored history record id (set by the backend when a
  // successful analysis is persisted), so the button only appears when the
  // result carries one.
  const historyId =
    typeof result.meta?.history_id === "string" ? result.meta.history_id : undefined;

  // Render one DiffViewer per changed file: iterate result.files (ALL files,
  // not only files-with-findings) and attach only the findings scoped to that
  // file. Files without diff text fall back to the empty-diff note inside
  // DiffViewer. Finding-only paths missing from result.files (legacy backend)
  // are appended so findings never silently disappear.
  const diffByPath = new Map<string, string>();
  for (const file of files) {
    diffByPath.set(file.path, file.diff ?? "");
  }
  for (const finding of findings) {
    if (!diffByPath.has(finding.file_path)) {
      diffByPath.set(finding.file_path, "");
    }
  }
  const fileEntries = Array.from(diffByPath.entries());

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1120px] space-y-4 px-6 py-10">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">评审结果</h1>
          {taskId && <p className="mt-1 font-mono text-xs text-ink-muted">task: {taskId}</p>}
        </div>
        {historyId && <ExportButton id={historyId} />}
      </header>

      {result.summary && <SummaryCard summary={result.summary} />}
      <FindingsList findings={findings} />

      <section className="space-y-4" aria-label="变更 Diff">
        <h2 className="text-lg font-semibold text-ink">变更 Diff</h2>
        {fileEntries.length === 0 ? (
          <p className="text-sm text-ink-muted">无文件级发现</p>
        ) : (
          fileEntries.map(([filePath, diff]) => (
            <DiffViewer
              key={filePath}
              filePath={filePath}
              diff={diff}
              findings={findings.filter((finding) => finding.file_path === filePath)}
            />
          ))
        )}
      </section>
    </main>
  );
}