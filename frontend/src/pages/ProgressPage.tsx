import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { subscribeTask } from "../api/sse";
import ProgressBar from "../components/ProgressBar";
import StageBadge, { type StageState } from "../components/StageBadge";

/** Ordered analysis stages as emitted by the backend (see task_manager.py). */
const STAGES = ["fetching", "building", "analyzing", "verifying", "aggregating"];

function stageState(stage: string | null, index: number): StageState {
  if (stage === null) {
    return "pending";
  }
  const current = STAGES.indexOf(stage);
  if (current === -1 || index > current) {
    return "pending";
  }
  return index === current ? "active" : "done";
}

function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}m ${rest}s`;
}

/**
 * Live progress for one analysis task: subscribes to the task's SSE stream,
 * renders stage badges + progress bar + elapsed time, navigates to the result
 * page on "done", and shows an actionable error on failure.
 */
export default function ProgressPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const [stage, setStage] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  const startedAtRef = useRef(0);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!taskId) {
      return;
    }
    setStage(null);
    setDone(0);
    setTotal(0);
    setError(null);
    startedAtRef.current = Date.now();
    setDurationMs(0);
    timerRef.current = window.setInterval(() => {
      setDurationMs(Date.now() - startedAtRef.current);
    }, 250);

    const unsubscribe = subscribeTask(taskId, {
      onStage: (s, d, t) => {
        setStage(s);
        setDone(d);
        setTotal(t);
      },
      onDone: () => navigate(`/result/${taskId}`),
      onError: (code, message) => setError({ code, message }),
    });

    return () => {
      unsubscribe();
      if (timerRef.current !== undefined) {
        window.clearInterval(timerRef.current);
        timerRef.current = undefined;
      }
    };
  }, [taskId, navigate]);

  // A terminal error freezes the page: stop the elapsed-time tick so the
  // error state never re-renders every 250ms.
  useEffect(() => {
    if (error && timerRef.current !== undefined) {
      window.clearInterval(timerRef.current);
      timerRef.current = undefined;
    }
  }, [error]);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[1120px] flex-col items-center justify-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <header className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-ink">分析进度</h1>
          {taskId && <p className="mt-2 font-mono text-xs text-ink-muted">task: {taskId}</p>}
        </header>

        <div className="rounded-lg border border-line bg-surface p-6">
          {error ? (
            <div
              role="alert"
              className="rounded-md border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
            >
              <p className="font-medium">{error.message}</p>
              <p className="mt-1 font-mono text-xs text-ink-muted">code: {error.code}</p>
              <button type="button" onClick={() => navigate("/")} className="mt-2 underline">
                重新开始
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-wrap items-center gap-2">
                {STAGES.map((s, index) => (
                  <StageBadge key={s} label={s} state={stageState(stage, index)} />
                ))}
              </div>
              <ProgressBar label={stage ?? "pending"} done={done} total={total} />
              <p className="text-xs text-ink-secondary">
                耗时 <span className="font-mono text-ink">{formatDuration(durationMs)}</span>
              </p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
