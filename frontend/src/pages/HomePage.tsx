import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { analyze, ApiError } from "../api/client";

/**
 * Example PR used by the "示例 PR 一键体验" quick-start button.
 *
 * Frontend constant for now: ideally this should come from a backend config
 * endpoint (the backend keeps `Settings.example_pr`, default
 * "owner/repo/pull/1") so the SPA never hard-codes a repo. Future extension.
 */
export const EXAMPLE_PR_URL = "https://github.com/RobbinsNest/PR-Review-Assistant/pull/1";

/** Friendly hints per HTTP status for analyze-start failures (backend mapping). */
const STATUS_HINTS: Record<number, string> = {
  401: "GitHub token 无效或已过期，请检查后重试",
  404: "仓库或 Pull Request 不存在，请确认链接正确（私有仓库需要提供 GitHub token）",
  413: "PR 超过可分析大小上限（50 个文件或 2MB diff）",
  429: "请求过于频繁，请稍后重试",
  504: "分析超时，请稍后重试",
};

function startErrorHint(err: unknown): string {
  if (err instanceof ApiError) {
    const hint = STATUS_HINTS[err.status];
    if (hint) {
      return hint;
    }
    if (err.code) {
      return err.message ? `${err.message}（${err.code}）` : `分析启动失败（${err.code}）`;
    }
    return err.message || `分析启动失败（HTTP ${err.status}）`;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return "分析启动失败，请稍后重试";
}

export default function HomePage() {
  const navigate = useNavigate();
  const [prUrl, setPrUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Synchronous guard against double-submit races: set before any async work
  // (state updates are async, so `submitting` alone can be stale) and reset
  // on error/finish. The disabled buttons remain as the visible feedback.
  const submittingRef = useRef(false);

  const startAnalysis = async (url: string, token: string) => {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const { task_id } = await analyze(url, token.trim() ? token.trim() : undefined);
      navigate(`/progress/${task_id}`);
    } catch (err) {
      setError(startErrorHint(err));
    } finally {
      setSubmitting(false);
      submittingRef.current = false;
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const url = prUrl.trim();
    if (!url) {
      setError("请输入 PR 链接");
      return;
    }
    void startAnalysis(url, githubToken);
  };

  const handleExample = () => {
    setPrUrl(EXAMPLE_PR_URL);
    void startAnalysis(EXAMPLE_PR_URL, githubToken);
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[1120px] flex-col items-center justify-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <header className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-ink">PR Review Assistant</h1>
          <p className="mt-2 text-sm text-ink-secondary">AI 驱动的 GitHub Pull Request 评审助手</p>
        </header>

        <form onSubmit={handleSubmit} className="rounded-lg border border-line bg-surface p-6">
          <div className="space-y-3">
            <div>
              <label htmlFor="pr-url" className="mb-1 block text-sm font-medium text-ink">
                PR 链接
              </label>
              <input
                id="pr-url"
                type="url"
                value={prUrl}
                onChange={(event) => setPrUrl(event.target.value)}
                placeholder="https://github.com/owner/repo/pull/1"
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
            <div>
              <label htmlFor="github-token" className="mb-1 block text-sm font-medium text-ink">
                GitHub Token（可选，私有仓库）
              </label>
              <input
                id="github-token"
                type="password"
                value={githubToken}
                onChange={(event) => setGithubToken(event.target.value)}
                placeholder="ghp_..."
                autoComplete="off"
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-sm text-error"
              >
                {error}
              </p>
            )}

            <div className="flex items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={submitting}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? "提交中…" : "开始分析"}
              </button>
              <button
                type="button"
                onClick={handleExample}
                disabled={submitting}
                className="rounded-md border border-line-strong bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
              >
                示例 PR 一键体验
              </button>
            </div>
          </div>
        </form>
      </div>
    </main>
  );
}
