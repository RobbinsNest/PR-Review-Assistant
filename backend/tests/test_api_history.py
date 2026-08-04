"""End-to-end tests for the /api/history endpoints.

The analyze pipeline (T9, WT-2) does not exist in this worktree, so records
are seeded directly through the shared ``HistoryStore`` on ``app.state``
(the T12 seam) and every endpoint is exercised through the real ASGI app.
"""

import httpx
import pytest

from app.models.analysis import AnalysisResult, AnalysisSummary
from app.models.pr import PRInfo


def _sample_result(title: str, overview: str) -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(
            title=title,
            overview=overview,
            key_points=["point-a", "point-b"],
            risk_highlights=["risk-x"],
        ),
        findings=[],
        meta={},
    )


@pytest.fixture()
async def api_client(tmp_path, monkeypatch):
    """Async HTTP client with the real app lifespan running in this loop."""
    monkeypatch.setenv("LLM_API_KEY", "test-llm-api-key")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test-analyses.db"))
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


async def test_list_detail_export_delete_lifecycle(api_client):
    """Seeded record is listable, viewable, exportable and deletable via the API."""
    from app.main import app

    store = app.state.history_store
    pr = PRInfo(
        owner="acme",
        repo="widgets",
        number=42,
        title="Fix flaky test",
        html_url="https://github.com/acme/widgets/pull/42",
        base_sha="abc123",
        head_sha="def456",
    )
    analysis_id = await store.save(
        pr,
        _sample_result("Fix flaky test", "Stabilises CI"),
        {"model": "deepseek-v4-flash"},
        123,
    )

    # List contains the seeded record with decoded summary/findings.
    r = await api_client.get("/api/history")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == analysis_id
    assert item["owner"] == "acme"
    assert item["repo"] == "widgets"
    assert item["pr_number"] == 42
    assert item["status"] == "succeeded"
    assert item["summary"]["title"] == "Fix flaky test"
    assert item["findings"] == []

    # Detail returns the single record with summary/findings as dicts.
    r = await api_client.get(f"/api/history/{analysis_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == analysis_id
    assert detail["summary"]["overview"] == "Stabilises CI"
    assert detail["summary"]["key_points"] == ["point-a", "point-b"]
    assert detail["findings"] == []

    # Export returns a Markdown attachment.
    r = await api_client.get(f"/api/history/{analysis_id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'attachment; filename="report.md"' in r.headers["content-disposition"]
    assert "Fix flaky test" in r.text
    assert "Stabilises CI" in r.text

    # Delete returns 204 and the list is empty afterwards.
    r = await api_client.delete(f"/api/history/{analysis_id}")
    assert r.status_code == 204
    body = (await api_client.get("/api/history")).json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_pagination(api_client):
    """limit/offset page through the newest-first list."""
    from app.main import app

    store = app.state.history_store
    for number in range(1, 4):
        pr = PRInfo(
            owner="acme",
            repo="widgets",
            number=number,
            title=f"PR {number}",
            html_url=f"https://github.com/acme/widgets/pull/{number}",
            base_sha="a",
            head_sha="b",
        )
        await store.save(pr, _sample_result(f"PR {number}", "overview"), {}, number)

    first = (await api_client.get("/api/history", params={"limit": 2, "offset": 0})).json()
    assert len(first["items"]) == 2
    rest = (await api_client.get("/api/history", params={"limit": 2, "offset": 2})).json()
    assert len(rest["items"]) == 1
    seen = {item["pr_number"] for item in first["items"]} | {
        item["pr_number"] for item in rest["items"]
    }
    assert seen == {1, 2, 3}


async def test_unknown_id_returns_404(api_client):
    """Detail, export and delete of a missing id yield a 404 error payload."""
    r = await api_client.get("/api/history/missing-id")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"

    r = await api_client.get("/api/history/missing-id/export")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"

    r = await api_client.delete("/api/history/missing-id")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
