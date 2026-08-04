import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SSEHandlers } from "../api/sse";
import ProgressPage from "../pages/ProgressPage";

const { subscribeTaskMock, navigateMock } = vi.hoisted(() => ({
  subscribeTaskMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ taskId: "task-123" }),
}));

vi.mock("../api/sse", () => ({ subscribeTask: subscribeTaskMock }));

/** The five analysis stages in backend order (must match ProgressPage). */
const STAGES = ["fetching", "building", "analyzing", "verifying", "aggregating"];

/** Distinct class marker per StageBadge state (see StageBadge.tsx STATE_CLASSES). */
const STATE_CLASS: Record<string, string> = {
  pending: "text-ink-muted",
  active: "text-primary-strong",
  done: "text-success",
};

describe("ProgressPage", () => {
  let handlers: SSEHandlers;

  beforeEach(() => {
    subscribeTaskMock.mockReset();
    navigateMock.mockReset();
    subscribeTaskMock.mockImplementation((_taskId: string, h: SSEHandlers) => {
      handlers = h;
      return vi.fn();
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  /** Returns the className of the stage badge element for the given label. */
  function badgeClass(label: string): string {
    const badge = screen.getAllByText(label).find((node) => node.className.includes("rounded-full"));
    expect(badge).toBeTruthy();
    return (badge as HTMLElement).className;
  }

  it("renders all five badges as pending before the first stage event", () => {
    render(<ProgressPage />);

    STAGES.forEach((stage) => {
      expect(badgeClass(stage)).toContain(STATE_CLASS.pending);
    });
  });

  it("maps a mid-run stage to done/active/pending badges (verifying => done, done, done, active, pending)", () => {
    render(<ProgressPage />);

    act(() => {
      handlers.onStage?.("verifying", 4, 5);
    });

    const expected = ["done", "done", "done", "active", "pending"];
    STAGES.forEach((stage, index) => {
      expect(badgeClass(stage)).toContain(STATE_CLASS[expected[index]]);
    });
  });

  it("navigates to the result page when the stream reports done", () => {
    render(<ProgressPage />);

    act(() => {
      handlers.onDone?.({});
    });

    expect(navigateMock).toHaveBeenCalledWith("/result/task-123");
  });

  it("shows a terminal error with a restart action that navigates home", () => {
    render(<ProgressPage />);

    act(() => {
      handlers.onError?.("task_failed", "analysis failed");
    });

    expect(screen.getByRole("alert")).toBeTruthy();
    const restart = screen.getByRole("button", { name: "重新开始" });
    fireEvent.click(restart);
    expect(navigateMock).toHaveBeenCalledWith("/");
  });
  it("stops the elapsed-time tick once a terminal error is set", () => {
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    render(<ProgressPage />);

    act(() => {
      handlers.onError?.("task_failed", "analysis failed");
    });

    expect(clearIntervalSpy).toHaveBeenCalled();
    clearIntervalSpy.mockRestore();
  });
});
