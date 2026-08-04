"""Analysis-engine tests: T6 Stage 1 generation, T7 Stage 2 verification, T8 Stage 3 aggregation + orchestrator."""

import asyncio

from app.services.analysis_engine import (
    AnalysisEngine,
    build_generate_messages,
    generate_for_unit,
)
from app.services.llm_client import LLMClient


class FakeLLM:
    """Reusable stub: validates ``out`` against the requested schema.

    ``by_schema`` maps a pydantic schema class to its canned payload so one
    fake can serve every stage of the pipeline (T8) while plain ``out`` keeps
    the T6/T7 call sites unchanged.
    """

    def __init__(self, out, by_schema=None):
        self.out = out
        self.by_schema = by_schema
        self.calls = 0

    async def chat_json(self, messages, schema, temperature=0.2):
        self.calls += 1
        payload = self.by_schema[schema] if self.by_schema is not None else self.out
        return schema.model_validate(payload)


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

# ---------------------------------------------------------------------------
# T7 Stage 2 verification: build_verify_messages / verify_candidates / stage2_verify
# ---------------------------------------------------------------------------

from app.models.finding import FindingCandidate
from app.services.analysis_engine import (
    build_verify_messages,
    true_changed_lines,
)


def cand(line_start=1, line_end=2, severity="major", confidence=0.9, file_path="a.py"):
    return FindingCandidate(
        file_path=file_path, line_start=line_start, line_end=line_end,
        category="bug", severity=severity, confidence=confidence,
        title="t", description="d", evidence="e", suggestion="s",
    )


def verify_unit():
    return {
        "file_path": "a.py",
        "diff": "@@ -1,2 +1,2 @@",
        "context": "def f():\n    pass",
        "truncated": False,
    }


async def test_stage2_verdicts_applied():
    # The brief's draft fixture ordered the results keep/drop/downgrade, which
    # contradicts its own "critical downgraded to major" assertion.  The
    # verdicts here are keep/downgrade/drop so every assertion checks the
    # intended semantics: keep survives, drop is removed, downgrade maps
    # critical -> major.
    class FakeVerifyLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            return schema.model_validate({"results": [
                {"index": 0, "verdict": "keep", "confidence": 0.7, "reason": "ok"},
                {"index": 1, "verdict": "downgrade", "confidence": 0.5, "reason": "low impact"},
                {"index": 2, "verdict": "drop", "confidence": 0.1, "reason": "pre-existing"},
            ]})

    engine = AnalysisEngine(FakeVerifyLLM())
    findings = await engine.stage2_verify(
        [(verify_unit(), [cand(), cand(severity="critical"), cand()])]
    )
    assert len(findings) == 2                      # drop 移除
    assert findings[0].verified is True and findings[0].confidence == 0.7
    assert findings[1].severity == "major"         # critical downgraded to major
    assert findings[0].id and findings[1].id


async def test_build_verify_messages_has_three_questions_and_candidates_json():
    msgs = build_verify_messages(verify_unit(), [cand()])
    assert [m["role"] for m in msgs] == ["system", "user"]
    system = msgs[0]["content"]
    assert "introduced" in system
    assert "changed lines" in system
    assert "context" in system
    user = msgs[1]["content"]
    assert "a.py" in user and "@@ -1,2 +1,2 @@" in user and "def f():" in user
    assert '"index": 0' in user and '"severity": "major"' in user


async def test_verify_candidates_applies_verdicts_and_confidence():
    llm = FakeLLM({"results": [
        {"index": 0, "verdict": "keep", "confidence": 0.7, "reason": "ok"},
        {"index": 1, "verdict": "downgrade", "confidence": 0.4, "reason": "low"},
        {"index": 2, "verdict": "drop", "confidence": 0.1, "reason": "pre-existing"},
    ]})
    engine = AnalysisEngine(llm)
    out = await engine.verify_candidates(
        verify_unit(), [cand(), cand(), cand()]
    )
    assert len(out) == 2
    assert out[0][1] == "keep" and out[0][0].confidence == 0.7
    assert out[1][1] == "downgrade" and out[1][0].severity == "minor"


async def test_verify_downgrade_maps_every_severity_one_step():
    llm = FakeLLM({"results": [
        {"index": i, "verdict": "downgrade", "confidence": 0.5, "reason": "r"}
        for i in range(4)
    ]})
    engine = AnalysisEngine(llm)
    out = await engine.verify_candidates(
        verify_unit(),
        [cand(severity="critical"), cand(severity="major"),
         cand(severity="minor"), cand(severity="nit")],
    )
    assert [c.severity for c, _ in out] == ["major", "minor", "nit", "nit"]


async def test_true_changed_lines_ignores_context_lines():
    # Context lines 1, 3, 4 are unchanged; only new-side line 2 is touched.
    diff = "@@ -1,4 +1,4 @@\n a\n-b\n+b\n c\n d"
    assert true_changed_lines(diff) == {2}


async def test_verify_drops_candidate_not_on_true_changed_lines():
    # Hunk body: context line 1, -/+ on line 2, context lines 3-4.  The LLM
    # says "keep" for both, but line 3 is context-only and must be dropped.
    diff = "@@ -1,4 +1,4 @@\n a\n-b\n+b\n c\n d"
    llm = FakeLLM({"results": [
        {"index": 0, "verdict": "keep", "confidence": 0.9, "reason": "ok"},
        {"index": 1, "verdict": "keep", "confidence": 0.9, "reason": "ok"},
    ]})
    engine = AnalysisEngine(llm)
    unit = {**verify_unit(), "diff": diff}
    out = await engine.verify_candidates(
        unit, [cand(line_start=2, line_end=2), cand(line_start=3, line_end=3)]
    )
    assert len(out) == 1
    assert out[0][0].line_start == 2 and out[0][0].line_end == 2


async def test_verify_drops_file_path_mismatch():
    llm = FakeLLM({"results": [
        {"index": 0, "verdict": "keep", "confidence": 0.9, "reason": "ok"},
        {"index": 1, "verdict": "keep", "confidence": 0.9, "reason": "ok"},
    ]})
    engine = AnalysisEngine(llm)
    out = await engine.verify_candidates(
        verify_unit(), [cand(file_path="a.py"), cand(file_path="b.py")]
    )
    assert len(out) == 1 and out[0][0].file_path == "a.py"


async def test_verify_clamps_pathological_line_range():
    # line_end = 1e9 must not loop/allocate unboundedly; clipped to changed
    # lines (hunk span 1-2 for the header-only diff).
    llm = FakeLLM({"results": [
        {"index": 0, "verdict": "keep", "confidence": 0.9, "reason": "ok"},
    ]})
    engine = AnalysisEngine(llm)
    out = await engine.verify_candidates(
        verify_unit(), [cand(line_start=1, line_end=10**9)]
    )
    assert len(out) == 1
    assert out[0][0].line_start == 1 and out[0][0].line_end <= 2


async def test_verify_drops_candidate_missing_from_llm_results():
    llm = FakeLLM({"results": [
        {"index": 1, "verdict": "keep", "confidence": 0.8, "reason": "ok"},
    ]})
    engine = AnalysisEngine(llm)
    out = await engine.verify_candidates(verify_unit(), [cand(), cand()])
    assert len(out) == 1
    assert out[0][0].line_start == 1


async def test_stage2_parallel_progress_and_verifying_stage():
    llm = FakeLLM({"results": [
        {"index": 0, "verdict": "keep", "confidence": 0.8, "reason": "ok"},
    ]})
    engine = AnalysisEngine(llm, concurrency=2)
    events = []
    findings = await engine.stage2_verify(
        [(verify_unit(), [cand()]), (verify_unit(), [cand()])],
        progress=lambda stage, done, total: events.append((stage, done, total)),
    )
    assert len(findings) == 2 and llm.calls == 2
    assert events[-1] == ("verifying", 2, 2)
    assert [done for _, done, _ in events] == [1, 2]


async def test_stage2_drops_unit_when_verify_fails():
    class FlakyVerifyLLM:
        def __init__(self):
            self.failures = 1

        async def chat_json(self, messages, schema, temperature=0.2):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("boom")
            return schema.model_validate({
                "results": [{"index": 0, "verdict": "keep",
                             "confidence": 0.8, "reason": "ok"}],
            })

    engine = AnalysisEngine(FlakyVerifyLLM())
    findings = await engine.stage2_verify(
        [(verify_unit(), [cand()]), (verify_unit(), [cand()])]
    )
    assert len(findings) == 1


async def test_stage2_verify_empty_pairs():
    engine = AnalysisEngine(FakeLLM({"results": []}))
    assert await engine.stage2_verify([]) == []

# ---------------------------------------------------------------------------
# T8 Stage 3 aggregation + run_analysis orchestrator
# ---------------------------------------------------------------------------

import pytest

from app.core.errors import AppError
from app.models.analysis import AnalysisSummary
from app.models.finding import Finding
from app.models.pr import ChangedFile, PRContext, PRInfo
from app.services.analysis_engine import (
    AGGREGATE_SCHEMA,
    GENERATE_SCHEMA,
    VERIFY_SCHEMA,
    build_aggregate_messages,
)


EMPTY_SUMMARY = {
    "title": "",
    "overview": "",
    "key_points": [],
    "risk_highlights": [],
}


def pr_info(**overrides):
    base = {
        "owner": "o", "repo": "r", "number": 1, "title": "t",
        "html_url": "u", "base_sha": "a", "head_sha": "b",
    }
    base.update(overrides)
    return PRInfo(**base)


def changed_file(path="a.py", **overrides):
    base = {
        "path": path, "status": "modified", "additions": 1, "deletions": 1,
        "diff": "@@ -1,2 +1,2 @@\n-x\n+y",
        "head_content": "def f():\n    x = 1\n    y = 2\n",
    }
    base.update(overrides)
    return ChangedFile(**base)


def pipeline_llm():
    """Fake LLM returning schema-appropriate empty outputs for the pipeline."""
    return FakeLLM({"findings": []}, by_schema={
        GENERATE_SCHEMA: {"findings": []},
        VERIFY_SCHEMA: {"results": []},
        AGGREGATE_SCHEMA: {"summary": EMPTY_SUMMARY},
    })


async def test_build_verify_messages_notes_truncation():
    # A truncated unit must carry the same honest partial-coverage note in the
    # verification call as in generation, or the verifier may misjudge scope.
    u = {**verify_unit(), "truncated": True}
    msgs = build_verify_messages(u, [cand()])
    system = msgs[0]["content"]
    assert "truncated" in system.lower() or "partial" in system.lower()


async def test_true_changed_lines_multi_hunk():
    # Two hunks: line 2 touched in the first, line 11 in the second.
    diff = "@@ -1,2 +1,2 @@\n a\n-b\n+b\n@@ -10,2 +10,2 @@\n c\n-d\n+d"
    assert true_changed_lines(diff) == {2, 11}


async def test_true_changed_lines_pure_deletion():
    # A deletion-only hunk anchors both removed lines at the insertion point.
    diff = "@@ -1,2 +1,0 @@\n-a\n-b"
    assert true_changed_lines(diff) == {1}


async def test_build_aggregate_messages_contains_pr_and_findings():
    info = pr_info(title="Fix flaky test")
    f = Finding.model_validate(finding())
    msgs = build_aggregate_messages(info, [("a.py", [f])])
    assert [m["role"] for m in msgs] == ["system", "user"]
    system = msgs[0]["content"]
    assert "summary" in system and "title" in system
    user = msgs[1]["content"]
    assert "o/r#1" in user and "Fix flaky test" in user
    assert "a.py" in user and "bug" in user


async def test_aggregate_returns_summary_from_llm():
    llm = FakeLLM({"findings": []}, by_schema={
        AGGREGATE_SCHEMA: {"summary": {
            "title": "Review title",
            "overview": "overview text",
            "key_points": ["k1"],
            "risk_highlights": ["r1"],
        }},
    })
    engine = AnalysisEngine(llm)
    summary = await engine.aggregate(pr_info(), [])
    assert isinstance(summary, AnalysisSummary)
    assert summary.title == "Review title"
    assert summary.key_points == ["k1"]


async def test_aggregate_groups_findings_by_file_in_user_message():
    captured = {}

    class CaptureLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            captured["user"] = messages[1]["content"]
            return schema.model_validate({"summary": EMPTY_SUMMARY})

    engine = AnalysisEngine(CaptureLLM())
    f1 = Finding.model_validate(finding())
    f2 = Finding.model_validate(finding(file_path="b.py"))
    await engine.aggregate(pr_info(), [f1, f2])
    assert "a.py" in captured["user"] and "b.py" in captured["user"]


async def test_run_analysis_full_pipeline():
    engine = AnalysisEngine(pipeline_llm())
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    events = []
    result = await engine.run_analysis(
        ctx,
        progress=lambda stage, done, total: events.append((stage, done, total)),
    )
    assert isinstance(result.summary, AnalysisSummary)
    assert result.summary.title == ""
    assert result.findings == []
    assert "skipped_files" in result.meta
    assert "stage_durations" in result.meta
    assert "token_estimate" in result.meta
    stages = {e[0] for e in events}
    assert {"building", "analyzing", "verifying", "aggregating"} <= stages


async def test_run_analysis_meta_includes_t6_stats():
    engine = AnalysisEngine(pipeline_llm())
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    result = await engine.run_analysis(ctx)
    assert result.meta["dropped_by_scope"] == engine.stats["dropped_by_scope"]
    assert result.meta["skipped_units"] == engine.stats["skipped_units"]
    assert result.meta["scaffolding_tokens"] == engine.stats["scaffolding_tokens"]
    assert set(result.meta["stage_durations"]) >= {
        "building", "analyzing", "verifying", "aggregating",
    }
    assert result.meta["token_estimate"]["total_input_tokens"] > 0


async def test_run_analysis_records_build_failure_as_skipped(monkeypatch):
    import app.services.analysis_engine as engine_mod

    real = engine_mod.build_analysis_unit

    def flaky(file):
        if file.path == "bad.py":
            raise RuntimeError("boom")
        return real(file)

    monkeypatch.setattr(engine_mod, "build_analysis_unit", flaky)
    llm = pipeline_llm()
    engine = AnalysisEngine(llm)
    ctx = PRContext(info=pr_info(), files=[
        changed_file(path="bad.py"), changed_file(path="good.py"),
    ])
    result = await engine.run_analysis(ctx)
    assert result.meta["skipped_files"] == ["bad.py"]
    assert result.meta["partial"] is True
    assert llm.calls >= 1  # the surviving file still reached the pipeline


async def test_run_analysis_falls_back_when_aggregate_fails():
    # With the T9 short-circuit, aggregation is only attempted when verified
    # findings exist, so this fixture must thread findings through the stages.
    class FailingAggregateLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            if schema is AGGREGATE_SCHEMA:
                raise RuntimeError("boom")
            if schema is GENERATE_SCHEMA:
                return schema.model_validate({"findings": [finding()]})
            return schema.model_validate({"results": [
                {"index": 0, "verdict": "keep", "confidence": 0.8, "reason": "ok"},
            ]})

    engine = AnalysisEngine(FailingAggregateLLM())
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    result = await engine.run_analysis(ctx)
    assert len(result.findings) == 1
    assert isinstance(result.summary, AnalysisSummary)
    assert result.summary.title == ""
    assert result.meta.get("aggregate_failed") is True


async def test_run_analysis_raises_when_no_files_analyzable():
    engine = AnalysisEngine(pipeline_llm())
    ctx = PRContext(info=pr_info(), files=[])
    with pytest.raises(AppError) as excinfo:
        await engine.run_analysis(ctx)
    assert excinfo.value.code == "no_analyzable_files"


# ---------------------------------------------------------------------------
# T9 fold-ins: stats reset between runs, aggregate short-circuit,
# no_analyzable_files error mapping, end-to-end run with non-empty findings
# ---------------------------------------------------------------------------

from app.core.errors import ERROR_HTTP, ErrorCode


async def test_run_analysis_resets_stats_between_runs():
    llm = FakeLLM({"findings": []}, by_schema={
        GENERATE_SCHEMA: {"findings": [finding(line_start=10, line_end=12)]},
        VERIFY_SCHEMA: {"results": []},
        AGGREGATE_SCHEMA: {"summary": EMPTY_SUMMARY},
    })
    engine = AnalysisEngine(llm)
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    first = await engine.run_analysis(ctx)
    assert first.meta["dropped_by_scope"] == 1
    llm.by_schema[GENERATE_SCHEMA] = {"findings": []}
    second = await engine.run_analysis(ctx)
    assert second.meta["dropped_by_scope"] == 0
    assert second.meta["skipped_units"] == 0
    assert engine.stats["dropped_by_scope"] == 0
    assert engine.stats["skipped_units"] == 0
    assert engine.stats["scaffolding_tokens"] > 0  # preserved across runs


async def test_run_analysis_skips_aggregate_call_when_no_findings():
    class NoAggregateLLM:
        def __init__(self):
            self.schemas = []

        async def chat_json(self, messages, schema, temperature=0.2):
            self.schemas.append(schema)
            return schema.model_validate({"findings": []})

    engine = AnalysisEngine(NoAggregateLLM())
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    result = await engine.run_analysis(ctx)
    assert result.findings == []
    assert isinstance(result.summary, AnalysisSummary)
    assert result.summary.title == ""
    assert AGGREGATE_SCHEMA not in engine.llm.schemas


async def test_no_analyzable_files_error_code_maps_to_422():
    assert ErrorCode.NO_ANALYZABLE_FILES.value == "no_analyzable_files"
    assert ERROR_HTTP[ErrorCode.NO_ANALYZABLE_FILES.value] == 422
    err = AppError(
        "no_analyzable_files", message="no analyzable files in the pull request"
    )
    assert err.status_code == 422


async def test_run_analysis_end_to_end_with_findings():
    # Composed end-to-end run: findings flow stage1 -> verify -> aggregate.
    llm = FakeLLM({"findings": []}, by_schema={
        GENERATE_SCHEMA: {"findings": [finding()]},
        VERIFY_SCHEMA: {"results": [
            {"index": 0, "verdict": "keep", "confidence": 0.8, "reason": "ok"},
        ]},
        AGGREGATE_SCHEMA: {"summary": {
            "title": "Review title", "overview": "overview text",
            "key_points": ["k1"], "risk_highlights": ["r1"],
        }},
    })
    engine = AnalysisEngine(llm)
    ctx = PRContext(info=pr_info(), files=[changed_file()])
    result = await engine.run_analysis(ctx)
    assert len(result.findings) == 1
    assert result.findings[0].file_path == "a.py"
    assert result.findings[0].verified is True
    assert result.findings[0].confidence == 0.8
    assert result.summary.title == "Review title"
    assert result.summary.key_points == ["k1"]
    assert llm.calls == 3  # generate -> verify -> aggregate


async def test_run_analysis_concurrent_runs_isolate_stats():
    # Two overlapping runs on ONE engine must each report only their own meta
    # counters.  A shared stats dict would leak dropped_by_scope / skipped_units
    # across the concurrent runs.
    class OverlappingLLM:
        def __init__(self):
            self.generation_entered = 0
            self.both_entered = asyncio.Event()

        async def chat_json(self, messages, schema, temperature=0.2):
            # Barrier: both runs' stage1 calls must be in flight before either
            # returns, so any shared-dict corruption becomes visible in meta.
            self.generation_entered += 1
            if self.generation_entered == 2:
                self.both_entered.set()
            await self.both_entered.wait()
            user = messages[1]["content"]
            if "a.py" in user:
                # Candidate anchored outside the changed lines -> dropped.
                return schema.model_validate(
                    {"findings": [finding(line_start=10, line_end=12)]}
                )
            raise RuntimeError("boom")  # unit fails -> skipped_units

    engine = AnalysisEngine(OverlappingLLM(), concurrency=2)
    ctx_a = PRContext(info=pr_info(), files=[changed_file(path="a.py")])
    ctx_b = PRContext(info=pr_info(), files=[changed_file(path="b.py")])
    result_a, result_b = await asyncio.gather(
        engine.run_analysis(ctx_a),
        engine.run_analysis(ctx_b),
    )
    assert result_a.meta["dropped_by_scope"] == 1
    assert result_a.meta["skipped_units"] == 0
    assert result_b.meta["dropped_by_scope"] == 0
    assert result_b.meta["skipped_units"] == 1
