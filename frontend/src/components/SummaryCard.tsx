/** Analysis summary, mirroring backend app.models.analysis.AnalysisSummary. */
export interface AnalysisSummary {
  title: string;
  overview: string;
  key_points: string[];
  risk_highlights: string[];
}

interface SummaryCardProps {
  summary: AnalysisSummary;
}

/** Change-summary card: overview + key points + risk highlights (DESIGN.md card). */
export default function SummaryCard({ summary }: SummaryCardProps) {
  return (
    <section className="rounded-lg border border-line bg-surface p-6" aria-label="变更总结">
      <h2 className="text-lg font-semibold text-ink">变更总结</h2>
      {summary.title && (
        <h3 className="mt-1 text-sm font-medium text-ink-secondary">{summary.title}</h3>
      )}
      {summary.overview && (
        <p className="mt-3 text-sm leading-6 text-ink">{summary.overview}</p>
      )}
      {summary.key_points.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-ink">要点</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink-secondary">
            {summary.key_points.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
        </div>
      )}
      {summary.risk_highlights.length > 0 && (
        <div className="mt-4 rounded-md border border-warning/30 bg-warning/5 p-3">
          <h4 className="text-sm font-medium text-warning">风险高亮</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
            {summary.risk_highlights.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}