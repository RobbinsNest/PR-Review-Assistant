import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DiffViewer from "../components/DiffViewer";
import type { Finding } from "../components/FindingsList";

/** Unified diff for src/a.py; new-file line numbers: context=1, new1=2, new2=3, keep=4, new3=5. */
const SAMPLE_DIFF = `diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,4 +1,5 @@
 def foo():
-    old
+    new1
+    new2
     keep
+    new3
`;

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

/** Returns the class list of the diff line for a given new-file line number. */
function lineClass(lineNumber: number): DOMTokenList {
  const row = document.querySelector(`[data-line="${lineNumber}"]`);
  if (!row) {
    throw new Error(`diff line ${lineNumber} was not rendered`);
  }
  return (row as HTMLElement).classList;
}

describe("DiffViewer", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("highlights the lines inside a finding's line_start..line_end range", () => {
    const findings = [makeFinding({ id: "f1", line_start: 2, line_end: 3 })];
    render(<DiffViewer filePath="src/a.py" diff={SAMPLE_DIFF} findings={findings} />);

    expect(lineClass(2).contains("highlight")).toBe(true);
    expect(lineClass(3).contains("highlight")).toBe(true);
    // Context/removed lines outside the range stay unhighlighted.
    expect(lineClass(1).contains("highlight")).toBe(false);
    expect(lineClass(4).contains("highlight")).toBe(false);
    expect(lineClass(5).contains("highlight")).toBe(false);
  });

  it("highlights multiple findings and treats ranges independently", () => {
    const findings = [
      makeFinding({ id: "f1", line_start: 2, line_end: 3 }),
      makeFinding({ id: "f2", line_start: 5, line_end: 5 }),
    ];
    render(<DiffViewer filePath="src/a.py" diff={SAMPLE_DIFF} findings={findings} />);

    expect(lineClass(2).contains("highlight")).toBe(true);
    expect(lineClass(3).contains("highlight")).toBe(true);
    expect(lineClass(5).contains("highlight")).toBe(true);
    expect(lineClass(4).contains("highlight")).toBe(false);
  });

  it("renders one clickable finding chip per finding with a severity marker", () => {
    const findings = [makeFinding({ id: "f1", title: "Null deref", line_start: 2, line_end: 3 })];
    render(<DiffViewer filePath="src/a.py" diff={SAMPLE_DIFF} findings={findings} />);

    const chip = screen.getByRole("button", { name: /Null deref/ });
    expect(chip).toBeTruthy();
  });

  it("scrolls to the finding's line when its chip is clicked", () => {
    const findings = [makeFinding({ id: "f1", title: "Null deref", line_start: 2, line_end: 3 })];
    render(<DiffViewer filePath="src/a.py" diff={SAMPLE_DIFF} findings={findings} />);

    const chip = screen.getByRole("button", { name: /Null deref/ });
    fireEvent.click(chip);

    const scrollIntoView = Element.prototype.scrollIntoView as ReturnType<typeof vi.fn>;
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect((scrollIntoView.mock.instances[0] as HTMLElement).getAttribute("data-line")).toBe("2");
  });

  it("shows an empty note when the diff has no parseable lines", () => {
    render(<DiffViewer filePath="src/a.py" diff="" findings={[]} />);
    expect(screen.getByText(/暂无 diff/)).toBeTruthy();
  });
});