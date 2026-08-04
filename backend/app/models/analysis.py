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
