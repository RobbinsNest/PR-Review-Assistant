import { exportUrl } from "../api/client";

interface ExportButtonProps {
  /** History record id used to build the Markdown export URL. */
  id: string;
  /** Optional custom label; defaults to 导出. */
  label?: string;
}

/** Secondary button that opens the backend Markdown export in a new tab. */
export default function ExportButton({ id, label = "导出" }: ExportButtonProps) {
  return (
    <button
      type="button"
      onClick={() => window.open(exportUrl(id))}
      className="rounded-md border border-line-strong bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface-subtle"
    >
      {label}
    </button>
  );
}