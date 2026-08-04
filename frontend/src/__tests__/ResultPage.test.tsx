import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Finding } from "../components/FindingsList";
import ResultPage from "../pages/ResultPage";

const { getTaskMock, navigateMock, paramsHolder } = vi.hoisted(() => ({
  getTaskMock: vi.fn(),
  navigateMock: vi.fn(),
  paramsHolder: { taskId: "task-123" as string | undefined },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ taskId: paramsHolder.taskId }),
}));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, getTask: getTaskMock };
});

const EMPTY_SUMMARY = { title: "", overview: "", key_points: [], risk_highlights: [] };
// Chinese UI strings asserted below (kept as escapes to avoid encoding drift).
const EMPTY_NOTE = "暂无 diff 数据";
const EXPORT_LABEL = "导出";
const FINDINGS_SUFFIX = "个发现";
const NO_FILES_NOTE = "无文件级发现";

function makeFinding(overrides: Partial<Finding> & { id: string }): Finding {
  return {
    file_path: "src/a.py",
    line_start: 1,
    line_end: 1,
    category: "bug",
    severity: "minor",
    confidence: 0.8,
    title: "title",
    description: "description",
    evidence: "evidence",
    suggestion: "suggestion",
    ...overrides,
  };
}

function succeededState(result: unknown) {
  return { status: "succeeded", result };
}

describe("ResultPage", () => {
  beforeEach(() => {
    getTaskMock.mockReset();
    navigateMock.mockReset();
    paramsHolder.taskId = "task-123";
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders one DiffViewer per file in result.files, including files without findings", async () => {
    getTaskMock.mockResolvedValue(
      succeededState({
        summary: EMPTY_SUMMARY,
        findings: [makeFinding({ id: "f1", file_path: "src/a.py", title: "Bug A" })],
        meta: {},
        files: [
          { path: "src/a.py", diff: "@@ -1,2 +1,2 @@\n-x\n+y" },
          { path: "src/b.py", diff: "@@ -1,1 +1,1 @@\n-x\n+z" },
        ],
      })
    );
    render(<ResultPage />);

    const a = await screen.findByRole("region", { name: "src/a.py" });
    const b = screen.getByRole("region", { name: "src/b.py" });
    // Every changed file gets a DiffViewer, even b.py with zero findings.
    expect(b).toBeTruthy();
    // Findings are attached only to their own file's DiffViewer.
    expect(within(a).getByRole("button", { name: /Bug A/ })).toBeTruthy();
    expect(within(b).queryByRole("button")).toBeNull();
    // Per-file finding counts in each DiffViewer header.
    expect(within(a).getByText(new RegExp(`1\\s*${FINDINGS_SUFFIX}`))).toBeTruthy();
    expect(within(b).getByText(new RegExp(`0\\s*${FINDINGS_SUFFIX}`))).toBeTruthy();
  });

  it("shows the empty-diff note for a file without diff text", async () => {
    getTaskMock.mockResolvedValue(
      succeededState({
        summary: EMPTY_SUMMARY,
        findings: [],
        meta: {},
        files: [{ path: "src/c.py", diff: "" }],
      })
    );
    render(<ResultPage />);

    await screen.findByRole("region", { name: "src/c.py" });
    expect(screen.getByText(EMPTY_NOTE)).toBeTruthy();
  });

  it("renders ExportButton when meta.history_id is present", async () => {
    getTaskMock.mockResolvedValue(
      succeededState({
        summary: EMPTY_SUMMARY,
        findings: [],
        meta: { history_id: "hist-1" },
        files: [],
      })
    );
    render(<ResultPage />);

    expect(await screen.findByRole("button", { name: EXPORT_LABEL })).toBeTruthy();
  });

  it("hides ExportButton when meta.history_id is absent", async () => {
    getTaskMock.mockResolvedValue(
      succeededState({ summary: EMPTY_SUMMARY, findings: [], meta: {}, files: [] })
    );
    render(<ResultPage />);

    await screen.findByText(NO_FILES_NOTE);
    expect(screen.queryByRole("button", { name: EXPORT_LABEL })).toBeNull();
  });

  it("keeps rendering finding-only files when result.files is missing (legacy)", async () => {
    getTaskMock.mockResolvedValue(
      succeededState({
        summary: EMPTY_SUMMARY,
        findings: [makeFinding({ id: "f1", file_path: "src/a.py", title: "Bug A" })],
        meta: {},
      })
    );
    render(<ResultPage />);

    const a = await screen.findByRole("region", { name: "src/a.py" });
    expect(within(a).getByRole("button", { name: /Bug A/ })).toBeTruthy();
    expect(within(a).getByText(EMPTY_NOTE)).toBeTruthy();
  });
  it("renders 结果不可用 instead of hanging on 加载中… when taskId is missing", () => {
    paramsHolder.taskId = undefined;
    render(<ResultPage />);

    expect(screen.getByText("结果不可用")).toBeTruthy();
    expect(getTaskMock).not.toHaveBeenCalled();
  });
});
