import { createBrowserRouter } from "react-router-dom";
import HistoryPage from "../pages/HistoryPage";
import HomePage from "../pages/HomePage";
import ProgressPage from "../pages/ProgressPage";
import ResultPage from "../pages/ResultPage";
import SettingsPage from "../pages/SettingsPage";

/**
 * Route table for the SPA.
 *
 * - "/"                    -> HomePage (PR form)
 * - "/progress/:taskId"    -> analysis progress + SSE
 * - "/result/:taskId"      -> result dashboard
 * - "/history"             -> stored analyses
 * - "/settings"            -> LLM settings
 */
export const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/progress/:taskId", element: <ProgressPage /> },
  { path: "/result/:taskId", element: <ResultPage /> },
  { path: "/history", element: <HistoryPage /> },
  { path: "/settings", element: <SettingsPage /> },
]);