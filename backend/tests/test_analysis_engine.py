"""T6 Stage 1 candidate generation: build_generate_messages / generate_for_unit / AnalysisEngine."""

from app.services.analysis_engine import (
    AnalysisEngine,
    build_generate_messages,
    generate_for_unit,
)
from app.services.llm_client import LLMClient


class FakeLLM:
    def __init__(self, out):
        self.out = out
        self.calls = 0

    async def chat_json(self, messages, schema, temperature=0.2):
        self.calls += 1
        return schema.model_validate(self.out)


def unit():
    return {
        "file_path": "a.py",
        "diff": "@@ -1,2 +1,2 @@",
        "context": "def f():\n    pass",
        "truncated": False,
    }


def finding(**overrides):
    base = {
        "file_path": "a.py", "line_start": 1, "line_end": 2,
        "category": "bug", "severity": "major", "confidence": 0.8,
        "title": "t", "description": "d", "evidence": "e", "suggestion": "s",
    }
    base.update(overrides)
    return base


async def test_build_generate_messages_contains_enum_hint():
    msgs = build_generate_messages(unit(), "instructions")
    assert any("bug" in m["content"] for m in msgs)


async def test_build_generate_messages_has_user_diff_and_context():
    msgs = build_generate_messages(unit(), "instructions")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert "a.py" in user and "@@ -1,2 +1,2 @@" in user and "def f():" in user


async def test_build_generate_messages_notes_truncation():
    u = {**unit(), "truncated": True}
    msgs = build_generate_messages(u, "instructions")
    system = msgs[0]["content"]
    assert "truncated" in system.lower() or "partial" in system.lower()


async def test_generate_for_unit_returns_calibrated_findings():
    llm = FakeLLM({"findings": [finding()]})
    stats = {"dropped_by_scope": 0}
    out = await generate_for_unit(llm, unit(), stats=stats)
    assert len(out) == 1
    assert out[0].line_start == 1 and out[0].line_end == 2
    assert stats["dropped_by_scope"] == 0


async def test_generate_for_unit_drops_out_of_scope_finding():
    llm = FakeLLM({"findings": [finding(line_start=10, line_end=12)]})
    stats = {"dropped_by_scope": 0}
    out = await generate_for_unit(llm, unit(), stats=stats)
    assert out == []
    assert stats["dropped_by_scope"] == 1


async def test_generate_for_unit_clips_partial_overlap():
    # Hunk covers new-file lines 3-4; candidate spans 1-5 -> clipped to 3-4.
    llm = FakeLLM({"findings": [finding(line_start=1, line_end=5)]})
    u = {**unit(), "diff": "@@ -1,5 +3,2 @@"}
    out = await generate_for_unit(llm, u)
    assert len(out) == 1
    assert out[0].line_start == 3 and out[0].line_end == 4


async def test_stage1_parallel_and_collect():
    llm = FakeLLM({"findings": [finding()]})
    engine = AnalysisEngine(llm, concurrency=2)
    results = await engine.stage1_generate([unit(), unit()])
    assert len(results) == 2 and llm.calls == 2


async def test_stage1_skips_failed_unit():
    class FlakyLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            raise RuntimeError("boom")

    engine = AnalysisEngine(FlakyLLM())
    results = await engine.stage1_generate([unit()])
    assert results == []


async def test_stage1_records_skipped_units():
    class FlakyLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            raise RuntimeError("boom")

    engine = AnalysisEngine(FlakyLLM())
    await engine.stage1_generate([unit(), unit()])
    assert engine.stats["skipped_units"] == 2


async def test_stage1_tracks_dropped_by_scope():
    llm = FakeLLM({"findings": [finding(line_start=9, line_end=10)]})
    engine = AnalysisEngine(llm)
    results = await engine.stage1_generate([unit()])
    assert results[0][1] == []
    assert engine.stats["dropped_by_scope"] == 1


async def test_stage1_progress_callback():
    llm = FakeLLM({"findings": []})
    engine = AnalysisEngine(llm, concurrency=2)
    events = []
    await engine.stage1_generate(
        [unit(), unit(), unit()],
        progress=lambda stage, done, total: events.append((stage, done, total)),
    )
    assert events[-1] == ("analyzing", 3, 3)
    assert all(stage == "analyzing" for stage, _, _ in events)
    assert [done for _, done, _ in events] == [1, 2, 3]
