import { createBrowserRouter } from "react-router-dom";
import HomePage from "../pages/HomePage";
import ProgressPage from "../pages/ProgressPage";

/**
 * Route table for the SPA.
 *
 * - "/"                    -> HomePage (PR form; implemented in T15)
 * - "/progress/:taskId"    -> analysis progress + SSE (T15)
 * - "/result/:taskId"      -> result dashboard (T16)
 * - "/history"             -> stored analyses (T16)
 * - "/settings"            -> LLM settings (T16)
 *
 * Routes whose pages arrive in later tasks render a shared placeholder so
 * the route table is stable from the scaffold on.
 */
function PlaceholderPage({ title }: { title: string }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-3 px-6">
      <h1 className="text-xl font-semibold text-ink">{title}</h1>
      <p className="text-sm text-ink-secondary">该页面将在后续任务中实现</p>
    </main>
  );
}

export const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/progress/:taskId", element: <ProgressPage /> },
  { path: "/result/:taskId", element: <PlaceholderPage title="评审结果" /> },
  { path: "/history", element: <PlaceholderPage title="历史记录" /> },
  { path: "/settings", element: <PlaceholderPage title="设置" /> },
]);
