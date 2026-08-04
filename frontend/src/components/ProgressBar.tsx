interface ProgressBarProps {
  /** Optional stage label rendered next to the done/total counter. */
  label?: string;
  done: number;
  total: number;
}

/** Progress track + fill per DESIGN.md (8px, rounded-full, primary fill). */
export default function ProgressBar({ label, done, total }: ProgressBarProps) {
  const percent = total > 0 ? Math.min(100, Math.max(0, (done / total) * 100)) : 0;
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
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={label ?? "进度"}
        className="h-2 w-full overflow-hidden rounded-full bg-line"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
