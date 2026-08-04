import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import HomePage, { EXAMPLE_PR_URL } from "../pages/HomePage";

const { analyzeMock, getSettingsMock, navigateMock } = vi.hoisted(() => ({
  analyzeMock: vi.fn(),
  getSettingsMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("react-router-dom", () => ({ useNavigate: () => navigateMock }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, analyze: analyzeMock, getSettings: getSettingsMock };
});

/** Minimal LLM settings payload for the getSettings mock. */
function settings(examplePr: string) {
  return {
    base_url: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
    api_key_configured: false,
    api_key_masked: null,
    example_pr: examplePr,
  };
}

describe("HomePage", () => {
  beforeEach(() => {
    analyzeMock.mockReset();
    getSettingsMock.mockReset();
    navigateMock.mockReset();
    getSettingsMock.mockResolvedValue(settings(EXAMPLE_PR_URL));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the PR form (URL, optional token, submit, example PR button)", () => {
    render(<HomePage />);
    expect(screen.getByLabelText("PR 链接")).toBeTruthy();
    expect(screen.getByLabelText(/GitHub Token/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /示例 PR/ })).toBeTruthy();
  });

  it("calls analyze with the typed URL and navigates to /progress/:taskId", async () => {
    analyzeMock.mockResolvedValue({ task_id: "task-123" });
    render(<HomePage />);

    fireEvent.change(screen.getByLabelText("PR 链接"), {
      target: { value: "https://github.com/owner/repo/pull/42" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() => {
      expect(analyzeMock).toHaveBeenCalledWith("https://github.com/owner/repo/pull/42", undefined);
    });
    expect(navigateMock).toHaveBeenCalledWith("/progress/task-123");
  });

  it("fills and submits the example PR URL when the example button is clicked", async () => {
    analyzeMock.mockResolvedValue({ task_id: "task-example" });
    render(<HomePage />);

    fireEvent.click(screen.getByRole("button", { name: /示例 PR/ }));

    await waitFor(() => {
      expect(analyzeMock).toHaveBeenCalledWith(EXAMPLE_PR_URL, undefined);
    });
    expect((screen.getByLabelText("PR 链接") as HTMLInputElement).value).toBe(EXAMPLE_PR_URL);
    expect(navigateMock).toHaveBeenCalledWith("/progress/task-example");
  });

  it("uses the backend-provided example PR for the quick-start button", async () => {
    const backendUrl = "https://github.com/owner/repo/pull/99";
    getSettingsMock.mockResolvedValue(settings(backendUrl));
    analyzeMock.mockResolvedValue({ task_id: "task-example" });
    render(<HomePage />);

    // Let the config fetch resolve and flush into state before clicking.
    await act(async () => {
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: /示例 PR/ }));
    await waitFor(() => {
      expect(analyzeMock).toHaveBeenCalledWith(backendUrl, undefined);
    });
    expect((screen.getByLabelText("PR 链接") as HTMLInputElement).value).toBe(backendUrl);
  });

  it("falls back to the bundled example PR URL when fetching config fails", async () => {
    getSettingsMock.mockRejectedValue(new Error("network down"));
    analyzeMock.mockResolvedValue({ task_id: "task-example" });
    render(<HomePage />);

    fireEvent.click(screen.getByRole("button", { name: /示例 PR/ }));
    await waitFor(() => {
      expect(analyzeMock).toHaveBeenCalledWith(EXAMPLE_PR_URL, undefined);
    });
  });

  it("shows a friendly error for a mapped HTTP status and re-enables the submit button", async () => {
    analyzeMock.mockRejectedValue(new ApiError(404, "task not found"));
    render(<HomePage />);

    fireEvent.change(screen.getByLabelText("PR 链接"), {
      target: { value: "https://github.com/owner/repo/pull/404" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("不存在");
    });
    const submit = screen.getByRole("button", { name: "开始分析" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });
});
