import pytest
from pydantic import ValidationError
from app.models.finding import Category, Severity, FindingCandidate
from app.models.analysis import AnalysisResult

def test_category_enum_values():
    assert {c.value for c in Category} == {"bug", "security", "performance", "maintainability", "style"}

def test_severity_enum_values():
    assert {c.value for c in Severity} == {"critical", "major", "minor", "nit"}

def test_finding_confidence_range():
    with pytest.raises(ValidationError):
        FindingCandidate(file_path="a.py", line_start=1, line_end=2, category="bug",
                         severity="major", confidence=1.5, title="t", description="d",
                         evidence="e", suggestion="s")

def test_analysis_result_accepts_empty_findings():
    r = AnalysisResult(summary={"title": "t", "overview": "o", "key_points": [], "risk_highlights": []},
                       findings=[], meta={})
    assert r.findings == []
