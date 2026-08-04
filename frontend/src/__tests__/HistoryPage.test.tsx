import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HistoryItem } from "../api/client";
import HistoryPage from "../pages/HistoryPage";

const { getHistoryMock, deleteHistoryMock, navigateMock } = vi.hoisted(() => ({
  getHistoryMock: vi.fn(),
  deleteHistoryMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("react-router-dom", () => ({ useNavigate: () => navigateMock }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, getHistory: getHistoryMock, deleteHistory: deleteHistoryMock };
});

function makeItem(id: string, prNumber: number): HistoryItem {
  return {
    id,
    owner: "owner",
    repo: "repo",
    pr_number: prNumber,
    pr_title: `PR ${prNumber}`,
    pr_url: `https://github.com/owner/repo/pull/${prNumber}`,
    base_sha: "base",
    head_sha: "head",
    status: "succeeded",
    summary: null,
    findings: [],
    error: null,
    config_snapshot: null,
    duration_ms: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("HistoryPage", () => {
  beforeEach(() => {
    getHistoryMock.mockReset();
    deleteHistoryMock.mockReset();
    navigateMock.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the total count from the API, not just the loaded items", async () => {
    getHistoryMock.mockResolvedValue({
      items: [makeItem("a", 1), makeItem("b", 2)],
      total: 120,
    });
    render(<HistoryPage />);

    await screen.findByText(/共\s*120\s*条/);
    expect(getHistoryMock).toHaveBeenCalledWith(50, 0);
  });

  it("loads the next page and appends items when 加载更多 is clicked", async () => {
    getHistoryMock
      .mockResolvedValueOnce({ items: [makeItem("a", 1)], total: 3 })
      .mockResolvedValueOnce({ items: [makeItem("b", 2)], total: 3 });
    render(<HistoryPage />);

    await screen.findByText("PR 1");
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));

    await waitFor(() => {
      expect(getHistoryMock).toHaveBeenCalledWith(50, 1);
    });
    await screen.findByText("PR 2");
    expect(screen.getByText("PR 1")).toBeTruthy();
  });

  it("hides 加载更多 once all items are loaded", async () => {
    getHistoryMock.mockResolvedValue({ items: [makeItem("a", 1)], total: 1 });
    render(<HistoryPage />);

    await screen.findByText("PR 1");
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull();
  });
});
