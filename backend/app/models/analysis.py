"""Analysis output data models: summary and full result."""

from pydantic import BaseModel

from app.models.finding import Finding


class AnalysisSummary(BaseModel):
    """Human-readable summary of the review."""

    title: str
    overview: str
    key_points: list[str]
    risk_highlights: list[str]


class AnalysisResult(BaseModel):
    """The complete, structured review output."""

    summary: AnalysisSummary
    findings: list[Finding]
    meta: dict
    #: Per-file unified diffs (``{"path": str, "diff": str}``) so clients can
    #: render one DiffViewer per changed file.  Defaults to empty for backward
    #: compatibility with producers that do not populate it.
    files: list[dict] = []
