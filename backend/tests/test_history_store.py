import pytest
from app.services.history_store import HistoryStore
from app.models.analysis import AnalysisSummary, AnalysisResult
from app.models.pr import PRInfo
from app.core.errors import AppError

@pytest.mark.asyncio
async def test_save_list_get_delete(tmp_path):
    store = HistoryStore(str(tmp_path / "a.db"))
    await store.init()
    pr = PRInfo(owner="o", repo="r", number=1, title="t", html_url="u", base_sha="a", head_sha="b")
    res = AnalysisResult(summary=AnalysisSummary(title="t", overview="o", key_points=[], risk_highlights=[]), findings=[], meta={})
    aid = await store.save(pr, res, {"model": "m"}, 100)
    rows = await store.list()
    assert len(rows) == 1 and rows[0]["id"] == aid
    got = await store.get(aid)
    assert got["pr_number"] == 1
    assert await store.delete(aid) is True
    assert await store.get(aid) is None

@pytest.mark.asyncio
async def test_export_markdown(tmp_path):
    store = HistoryStore(str(tmp_path / "a.db"))
    await store.init()
    pr = PRInfo(owner="o", repo="r", number=1, title="Fix", html_url="u", base_sha="a", head_sha="b")
    res = AnalysisResult(summary=AnalysisSummary(title="Fix", overview="ov", key_points=["k"], risk_highlights=["r"]), findings=[], meta={})
    aid = await store.save(pr, res, {}, 1)
    md = await store.export_markdown(aid)
    assert "# PR 评审报告" in md and "Fix" in md