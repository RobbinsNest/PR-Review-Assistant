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
