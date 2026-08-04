export type StageState = "pending" | "active" | "done";

interface StageBadgeProps {
  label: string;
  state: StageState;
}

const STATE_CLASSES: Record<StageState, string> = {
  pending: "border border-line bg-surface text-ink-muted",
  active: "border border-primary/30 bg-primary/10 text-primary-strong",
  done: "border border-success/30 bg-success/10 text-success",
};

/** Small rounded-full badge for one analysis stage (DESIGN.md badge spec). */
export default function StageBadge({ label, state }: StageBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATE_CLASSES[state]}`}
    >
      {label}
    </span>
  );
}
