interface ProgressBarProps {
  /** Optional stage label rendered next to the done/total counter. */
  label?: string;
  done: number;
  total: number;
}

/** Progress track + fill per DESIGN.md (8px, rounded-full, primary fill). */
export default function ProgressBar({ label, done, total }: ProgressBarProps) {
  const percent = total > 0 ? Math.min(100, Math.max(0, (done / total) * 100)) : 0;
  // Clamp ARIA values so the pre-first-event 0/0 state is not degenerate:
  // aria-valuemax must stay >= 1 and aria-valuenow must stay within [0, max].
  const max = Math.max(total, 1);
  const now = Math.min(done, max);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-ink-secondary">
        <span>{label ?? "进度"}</span>
        <span className="font-mono text-ink-muted">
          {done}/{total}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={now}
        aria-label={label ?? "进度"}
        className="h-2 w-full overflow-hidden rounded-full bg-line"
      >
        <div
          className="h-full rounded-full bg-primary glow-cyan transition-[width] duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
