import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import HomePage, { EXAMPLE_PR_URL } from "../pages/HomePage";

const { analyzeMock, navigateMock } = vi.hoisted(() => ({
  analyzeMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("react-router-dom", () => ({ useNavigate: () => navigateMock }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, analyze: analyzeMock };
});

describe("HomePage", () => {
  beforeEach(() => {
    analyzeMock.mockReset();
    navigateMock.mockReset();
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
