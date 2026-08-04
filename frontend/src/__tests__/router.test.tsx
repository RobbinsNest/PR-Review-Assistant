import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../app/router";

// The real client would fire network requests in jsdom; stub it so router
// integration tests only exercise navigation/layout.
vi.mock("../api/client", () => ({
  getSettings: vi.fn().mockResolvedValue({
    base_url: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
    api_key_configured: false,
    api_key_masked: null,
    example_pr: "https://github.com/RobbinsNest/PR-Review-Assistant/pull/1",
  }),
  getHistory: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  analyze: vi.fn(),
  getTask: vi.fn(),
  deleteHistory: vi.fn(),
  clearSettings: vi.fn(),
  testSettings: vi.fn(),
  updateSettings: vi.fn(),
  exportUrl: vi.fn((id: string) => `/api/history/${id}/export`),
  ApiError: class ApiError extends Error {
    status = 0;
    code: string | undefined;
  },
}));

describe("router layout", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("persists the NavBar across pages (history page shows nav links)", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/history"] });
    render(<RouterProvider router={router} />);

    expect(await screen.findByText("历史记录")).toBeTruthy();
    expect(screen.getByRole("link", { name: "首页" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "历史" }).getAttribute("href")).toBe("/history");
    expect(screen.getByRole("link", { name: "设置" }).getAttribute("href")).toBe("/settings");
  });

  it("renders a friendly 404 with a home link for unknown paths", () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/does-not-exist"] });
    render(<RouterProvider router={router} />);

    expect(screen.getByText("页面不存在")).toBeTruthy();
    expect(screen.getByRole("link", { name: "返回首页" }).getAttribute("href")).toBe("/");
  });
});
