import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FindingsList, { type Finding } from "../components/FindingsList";

function makeFinding(overrides: Partial<Finding> & { id: string }): Finding {
  return {
    file_path: "src/app.ts",
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

describe("FindingsList", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  /** Ordered severity labels as rendered in the DOM (data-severity markers). */
  function renderedSeverities(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll("[data-severity]")).map(
      (node) => node.getAttribute("data-severity") as string
    );
  }

  /** Ordered finding ids as rendered in the DOM (data-finding-id markers). */
  function renderedIds(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll("[data-finding-id]")).map(
      (node) => node.getAttribute("data-finding-id") as string
    );
  }

  it("sorts findings by severity (critical first, then major/minor/nit)", () => {
    const findings = [
      makeFinding({ id: "f-nit", severity: "nit" }),
      makeFinding({ id: "f-major", severity: "major" }),
      makeFinding({ id: "f-critical", severity: "critical" }),
      makeFinding({ id: "f-minor", severity: "minor" }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    expect(renderedSeverities(container)).toEqual(["critical", "major", "minor", "nit"]);
  });

  it("keeps equal-severity findings stable by file:line", () => {
    const findings = [
      makeFinding({ id: "f-b", severity: "major", file_path: "src/b.ts", line_start: 2 }),
      makeFinding({ id: "f-a", severity: "major", file_path: "src/a.ts", line_start: 1 }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    expect(renderedIds(container)).toEqual(["f-a", "f-b"]);
  });

  it("filters findings by severity", () => {
    const findings = [
      makeFinding({ id: "f-critical", severity: "critical" }),
      makeFinding({ id: "f-major", severity: "major" }),
      makeFinding({ id: "f-minor", severity: "minor" }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    fireEvent.change(screen.getByLabelText("按严重度筛选"), {
      target: { value: "major" },
    });

    expect(renderedIds(container)).toEqual(["f-major"]);
  });

  it("filters findings by category", () => {
    const findings = [
      makeFinding({ id: "f-bug", category: "bug" }),
      makeFinding({ id: "f-sec", category: "security" }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    fireEvent.change(screen.getByLabelText("按类别筛选"), {
      target: { value: "security" },
    });

    expect(renderedIds(container)).toEqual(["f-sec"]);
  });
  it("falls back to nit styling for out-of-enum severities", () => {
    const findings = [
      makeFinding({ id: "f-unknown", severity: "urgent" as Finding["severity"] }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    expect(renderedSeverities(container)).toEqual(["urgent"]);
    const badges = Array.from(container.querySelectorAll('[data-severity="urgent"] span.rounded-full'));
    const severityBadge = badges.find((el) => el.className.includes("bg-severity-"));
    expect(severityBadge?.className).toContain("bg-severity-nit");
  });

  it("sorts out-of-enum severities after known ones (treated as nit)", () => {
    const findings = [
      makeFinding({ id: "f-unknown", severity: "urgent" as Finding["severity"] }),
      makeFinding({ id: "f-critical", severity: "critical" }),
      makeFinding({ id: "f-minor", severity: "minor" }),
    ];
    const { container } = render(<FindingsList findings={findings} />);

    expect(renderedIds(container)).toEqual(["f-critical", "f-minor", "f-unknown"]);
  });
});