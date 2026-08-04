import { useMemo, useRef } from "react";
import { parsePatch } from "diff";
import {
  SEVERITY_BG,
  SEVERITY_ORDER,
  SEVERITY_TEXT,
  type Finding,
  type FindingSeverity,
} from "./FindingsList";

interface DiffViewerProps {
  /** Path of the file whose unified diff is rendered. */
  filePath: string;
  /** Unified diff text for this file (new-file line numbers). */
  diff: string;
  /** Findings scoped to this file; line_start..line_end are new-file lines. */
  findings: Finding[];
}

type DiffLineType = "add" | "remove" | "context" | "meta";

interface DiffLine {
  key: string;
  type: DiffLineType;
  oldLineNo: number | null;
  newLineNo: number | null;
  content: string;
}

/** Severity rank: lower = more severe (used to pick the strongest highlight). */
function severityRank(severity: FindingSeverity): number {
  return SEVERITY_ORDER.indexOf(severity);
}

const PREFIX: Record<DiffLineType, string> = {
  add: "+",
  remove: "-",
  context: " ",
  meta: "\\",
};

/**
 * Parse a unified diff into renderable lines with old/new line numbers.
 *
 * The `diff` package's parsePatch returns raw prefixed lines per hunk; we
 * walk each hunk and track the old/new counters so every line carries the
 * line numbers used for finding highlighting and scroll targets.
 */
function parseDiffLines(diff: string): DiffLine[] {
  let patches;
  try {
    patches = parsePatch(diff);
  } catch {
    return [];
  }
  const lines: DiffLine[] = [];
  for (const patch of patches) {
    for (const hunk of patch.hunks) {
      let oldNo = hunk.oldStart;
      let newNo = hunk.newStart;
      for (const raw of hunk.lines) {
        const prefix = raw[0] ?? "";
        const content = raw.slice(1);
        if (prefix === "+") {
          lines.push({
            key: `h${hunk.oldStart}-n${newNo}`,
            type: "add",
            oldLineNo: null,
            newLineNo: newNo,
            content,
          });
          newNo += 1;
        } else if (prefix === "-") {
          lines.push({
            key: `h${hunk.oldStart}-o${oldNo}`,
            type: "remove",
            oldLineNo: oldNo,
            newLineNo: null,
            content,
          });
          oldNo += 1;
        } else if (prefix === " ") {
          lines.push({
            key: `h${hunk.oldStart}-c${newNo}`,
            type: "context",
            oldLineNo: oldNo,
            newLineNo: newNo,
            content,
          });
          oldNo += 1;
          newNo += 1;
        } else {
          // "\ No newline at end of file" markers carry no line number.
          lines.push({
            key: `h${hunk.oldStart}-m${lines.length}`,
            type: "meta",
            oldLineNo: null,
            newLineNo: null,
            content,
          });
        }
      }
    }
  }
  return lines;
}

/**
 * One-file unified diff viewer: mono font, line numbers, +/- line tint, and
 * finding ranges highlighted with a `highlight` class + severity-color 10%
 * background (DESIGN.md DiffViewer spec). Clicking a finding chip scrolls the
 * diff to that finding's first line.
 */
export default function DiffViewer({ filePath, diff, findings }: DiffViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const lines = useMemo(() => parseDiffLines(diff), [diff]);

  // new-file line number -> strongest severity covering it.
  const highlights = useMemo(() => {
    const map = new Map<number, FindingSeverity>();
    for (const line of lines) {
      if (line.newLineNo === null) {
        continue;
      }
      let best: FindingSeverity | null = null;
      for (const finding of findings) {
        if (
          line.newLineNo >= finding.line_start &&
          line.newLineNo <= finding.line_end &&
          (best === null || severityRank(finding.severity) < severityRank(best))
        ) {
          best = finding.severity;
        }
      }
      if (best !== null) {
        map.set(line.newLineNo, best);
      }
    }
    return map;
  }, [lines, findings]);

  const scrollToFinding = (lineStart: number, lineEnd: number) => {
    const root = containerRef.current;
    if (!root) {
      return;
    }
    const start = root.querySelector(`[data-line="${lineStart}"]`);
    const target =
      start ?? root.querySelector(`[data-line="${lineEnd}"]`);
    (target as HTMLElement | null)?.scrollIntoView?.({ block: "center" });
  };

  return (
    <section className="rounded-lg border border-line bg-surface" aria-label={filePath}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
        <h3 className="font-mono text-sm font-medium text-ink">{filePath}</h3>
        <span className="text-xs text-ink-muted">
          {findings.length} 个发现
        </span>
      </header>

      {findings.length > 0 && (
        <div className="flex flex-wrap gap-2 px-4 pt-3">
          {findings.map((finding) => (
            <button
              key={finding.id}
              type="button"
              onClick={() => scrollToFinding(finding.line_start, finding.line_end)}
              className={`inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-xs font-medium ${SEVERITY_TEXT[finding.severity]}`}
            >
              <span>{finding.severity}</span>
              <span className="text-ink">{finding.title}</span>
            </button>
          ))}
        </div>
      )}

      <div ref={containerRef} className="overflow-x-auto px-4 py-3">
        {lines.length === 0 ? (
          <p className="py-2 font-sans text-xs text-ink-muted">暂无 diff 数据</p>
        ) : (
          lines.map((line) => {
            const highlight =
              line.newLineNo !== null ? highlights.get(line.newLineNo) : undefined;
            const typeClass =
              line.type === "add"
                ? "text-success"
                : line.type === "remove"
                  ? "text-error"
                  : "text-ink";
            const rowClass = [
              "flex gap-3 px-2 font-mono text-[13px] leading-5",
              typeClass,
              highlight ? `highlight ${SEVERITY_BG[highlight]}` : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div
                key={line.key}
                data-line={line.newLineNo ?? undefined}
                className={rowClass}
              >
                <span className="w-8 shrink-0 select-none text-right text-ink-muted">
                  {line.newLineNo ?? line.oldLineNo ?? ""}
                </span>
                <span className="w-4 shrink-0 select-none text-ink-muted">
                  {PREFIX[line.type]}
                </span>
                <span className="whitespace-pre-wrap break-all">{line.content}</span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}