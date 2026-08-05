import { createBrowserRouter, Link, Outlet, type RouteObject } from "react-router-dom";
import NavBar from "../components/NavBar";
import HistoryPage from "../pages/HistoryPage";
import HomePage from "../pages/HomePage";
import ProgressPage from "../pages/ProgressPage";
import ResultPage from "../pages/ResultPage";
import SettingsPage from "../pages/SettingsPage";

/**
 * Root layout shell: persistent NavBar around every route via <Outlet/>.
 */
function AppLayout() {
  return (
    <div className="min-h-screen bg-surface">
      <NavBar />
      <Outlet />
    </div>
  );
}

/** Friendly fallback for unknown paths (catch-all "*" route). */
function NotFound() {
  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-[1120px] flex-col items-center justify-center px-6 py-10 text-center">
      <p className="text-2xl font-semibold tracking-tight text-ink">页面不存在</p>
      <p className="mt-2 text-sm text-ink-secondary">你访问的页面不存在或已被移除。</p>
      <Link
        to="/"
        className="mt-4 rounded-md bg-primary glow-cyan px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-primary-strong"
      >
        返回首页
      </Link>
    </main>
  );
}

/**
 * Route table for the SPA. Exported separately from the browser router so
 * tests can build an in-memory router from the same routes.
 *
 * - "/"                    -> HomePage (PR form)
 * - "/progress/:taskId"    -> analysis progress + SSE
 * - "/result/:taskId"      -> result dashboard
 * - "/history"             -> stored analyses
 * - "/settings"            -> LLM settings
 * - "*"                    -> friendly 404
 */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/progress/:taskId", element: <ProgressPage /> },
      { path: "/result/:taskId", element: <ResultPage /> },
      { path: "/history", element: <HistoryPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
