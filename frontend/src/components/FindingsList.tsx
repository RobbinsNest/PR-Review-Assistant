import { useMemo, useState } from "react";

export type FindingCategory =
  | "bug"
  | "security"
  | "performance"
  | "maintainability"
  | "style";

export type FindingSeverity = "critical" | "major" | "minor" | "nit";

/** A verified finding, mirroring backend app.models.finding.Finding. */
export interface Finding {
  id: string;
  file_path: string;
  line_start: number;
  line_end: number;
  category: FindingCategory;
  severity: FindingSeverity;
  confidence: number;
  title: string;
  description: string;
  evidence: string;
  suggestion: string;
}

/** Severity display order, most severe first (DESIGN.md §2.2). */
export const SEVERITY_ORDER: FindingSeverity[] = ["critical", "major", "minor", "nit"];

const CATEGORIES: FindingCategory[] = [
  "bug",
  "security",
  "performance",
  "maintainability",
  "style",
];

/** Severity badge styling: semantic-color 10% bg + semantic-color text. */
export const SEVERITY_TEXT: Record<FindingSeverity, string> = {
  critical: "bg-severity-critical/10 text-severity-critical",
  major: "bg-severity-major/10 text-severity-major",
  minor: "bg-severity-minor/10 text-severity-minor",
  nit: "bg-severity-nit/10 text-severity-nit",
};

/** Severity highlight background for diff lines (semantic-color 10%). */
export const SEVERITY_BG: Record<FindingSeverity, string> = {
  critical: "bg-severity-critical/10",
  major: "bg-severity-major/10",
  minor: "bg-severity-minor/10",
  nit: "bg-severity-nit/10",
};

/**
 * Map any severity string to a known severity, falling back to "nit" styling
 * for out-of-enum values emitted by older/foreign backends.
 */
export function normalizeSeverity(severity: string): FindingSeverity {
  return (SEVERITY_ORDER as readonly string[]).includes(severity)
    ? (severity as FindingSeverity)
    : "nit";
}

interface FindingsListProps {
  findings: Finding[];
}

/** Severity rank: lower = more severe = rendered first. */
function severityRank(severity: string): number {
  return SEVERITY_ORDER.indexOf(normalizeSeverity(severity));
}

/**
 * Sortable/filterable finding list.
 *
 * Always sorted by severity (critical first), then file path + line start for
 * a stable order. Category/severity filters use memoized derived state.
 */
export default function FindingsList({ findings }: FindingsListProps) {
  const [category, setCategory] = useState<FindingCategory | "all">("all");
  const [severity, setSeverity] = useState<FindingSeverity | "all">("all");

  const visible = useMemo(() => {
    const filtered = findings.filter(
      (finding) =>
        (category === "all" || finding.category === category) &&
        (severity === "all" || finding.severity === severity)
    );
    return [...filtered].sort((a, b) => {
      const bySeverity = severityRank(a.severity) - severityRank(b.severity);
      if (bySeverity !== 0) {
        return bySeverity;
      }
      if (a.file_path !== b.file_path) {
        return a.file_path < b.file_path ? -1 : 1;
      }
      return a.line_start - b.line_start;
    });
  }, [findings, category, severity]);

  return (
    <section className="rounded-lg border border-line bg-surface p-6" aria-label="风险发现">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-ink">风险发现</h2>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            类别
            <select
              aria-label="按类别筛选"
              value={category}
              onChange={(event) => setCategory(event.target.value as FindingCategory | "all")}
              className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink focus:border-primary focus:outline-none"
            >
              <option value="all">全部</option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            严重度
            <select
              aria-label="按严重度筛选"
              value={severity}
              onChange={(event) => setSeverity(event.target.value as FindingSeverity | "all")}
              className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink focus:border-primary focus:outline-none"
            >
              <option value="all">全部</option>
              {SEVERITY_ORDER.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-ink-muted">没有符合条件的发现</p>
      ) : (
        <ol className="space-y-4">
          {visible.map((finding) => (
            <li
              key={finding.id}
              data-finding-id={finding.id}
              data-severity={finding.severity}
              className="rounded-md border border-line bg-surface-subtle p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-line bg-surface px-2 py-0.5 text-xs font-medium text-ink-secondary">
                  {finding.category}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_TEXT[normalizeSeverity(finding.severity)]}`}
                >
                  {finding.severity}
                </span>
                <span className="font-mono text-xs text-ink-muted">
                  置信度 {finding.confidence.toFixed(2)}
                </span>
                <span className="font-mono text-xs text-ink-secondary">
                  {finding.file_path}:{finding.line_start}
                  {finding.line_end !== finding.line_start ? `-${finding.line_end}` : ""}
                </span>
              </div>
              <h3 className="mt-2 text-sm font-semibold text-ink">{finding.title}</h3>
              <p className="mt-1 text-sm leading-6 text-ink-secondary">{finding.description}</p>
              {finding.evidence && (
                <pre className="mt-2 overflow-x-auto rounded-md border border-line bg-surface p-2 font-mono text-xs leading-5 text-ink">
                  {finding.evidence}
                </pre>
              )}
              {finding.suggestion && (
                <p className="mt-2 text-sm leading-6 text-ink-secondary">
                  <span className="font-medium text-ink">建议：</span>
                  {finding.suggestion}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}