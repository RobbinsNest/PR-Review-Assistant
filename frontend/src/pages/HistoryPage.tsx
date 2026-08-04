import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteHistory, getHistory, type HistoryItem } from "../api/client";
import ExportButton from "../components/ExportButton";
import FindingsList, { type Finding } from "../components/FindingsList";
import SummaryCard, { type AnalysisSummary } from "../components/SummaryCard";

/** Render an ISO timestamp as a readable local time string. */
function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

/** Number of records fetched per history page. */
const PAGE_SIZE = 50;

/**
 * History page: stored analyses (PR title / repo / time / status) with
 * inline detail (summary + findings), Markdown export, hard delete and
 * offset-based pagination (加载更多).
 */
export default function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getHistory(PAGE_SIZE, 0)
      .then((page) => {
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "加载历史失败");
      })
      .finally(() => setLoading(false));
  };

  // Fetch the next page (offset = currently loaded count) and append it.
  const loadMore = () => {
    setLoadingMore(true);
    setError(null);
    getHistory(PAGE_SIZE, items.length)
      .then((page) => {
        setItems((prev) => [...prev, ...page.items]);
        setTotal(page.total);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "加载历史失败");
      })
      .finally(() => setLoadingMore(false));
  };

  useEffect(load, []);

  const handleDelete = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await deleteHistory(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      setTotal((prev) => Math.max(0, prev - 1));
      setExpandedId((prev) => (prev === id ? null : prev));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1120px] space-y-4 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">历史记录</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          {loading ? "" : `共 ${total} 条分析记录`}
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
        >
          <p className="font-medium">{error}</p>
          <button type="button" onClick={load} className="mt-2 underline">
            重试
          </button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-ink-secondary">加载中…</p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-line bg-surface p-6 text-center">
          <p className="text-sm text-ink-secondary">暂无历史记录</p>
          <button
            type="button"
            onClick={() => navigate("/")}
            className="mt-3 rounded-md bg-primary px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-primary-strong"
          >
            去分析
          </button>
        </div>
      ) : (
        <ol className="space-y-3">
          {items.map((item) => {
            const expanded = expandedId === item.id;
            return (
              <li key={item.id} className="rounded-lg border border-line bg-surface p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold text-ink">{item.pr_title}</h2>
                    <p className="mt-1 font-mono text-xs text-ink-secondary">
                      {item.owner}/{item.repo} #{item.pr_number}
                    </p>
                    <p className="mt-1 text-xs text-ink-muted">{formatDateTime(item.created_at)}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
                      {item.status}
                    </span>
                    <button
                      type="button"
                      onClick={() => setExpandedId(expanded ? null : item.id)}
                      className="rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:bg-surface-subtle"
                    >
                      {expanded ? "收起" : "详情"}
                    </button>
                    <ExportButton id={item.id} />
                    <button
                      type="button"
                      onClick={() => void handleDelete(item.id)}
                      disabled={busyId === item.id}
                      className="rounded-md bg-error px-3 py-1.5 text-sm font-medium text-surface transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {busyId === item.id ? "删除中…" : "删除"}
                    </button>
                  </div>
                </div>

                {expanded && (
                  <div className="mt-4 space-y-4 border-t border-line pt-4">
                    {item.summary ? (
                      <SummaryCard summary={item.summary as AnalysisSummary} />
                    ) : null}
                    {Array.isArray(item.findings) && item.findings.length > 0 ? (
                      <FindingsList findings={item.findings as Finding[]} />
                    ) : null}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {!loading && items.length > 0 && items.length < total && (
        <div className="flex justify-center pt-2">
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="rounded-md border border-line-strong bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loadingMore ? "加载中…" : "加载更多"}
          </button>
        </div>
      )}
    </main>
  );
}