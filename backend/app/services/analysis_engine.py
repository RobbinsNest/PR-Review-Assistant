"""T6-T8 analysis engine: Stage 1 candidate generation + Stage 2 verification
+ Stage 3 aggregation, orchestrated by ``run_analysis``.

Stage 1 (``stage1_generate``) issues one LLM call per :class:`AnalysisUnit`
(T4) via ``LLMClient.chat_json`` (T5) asking for raw candidate findings, then
calibrates each candidate's ``line_start``/``line_end`` onto the diff hunk
changed-line ranges.  Candidates whose range does not intersect any changed
line are dropped and counted in ``dropped_by_scope`` so the verification stage
never sees out-of-scope findings.  A failed unit (after the LLM client's own
retries) is recorded as skipped and the remaining units continue.

Stage 2 (``stage2_verify``) verifies the surviving candidates per unit with
one LLM call asking for a keep/drop/downgrade verdict per candidate, then
applies deterministic gates: a candidate whose ``file_path`` does not match
the unit, or whose range contains no true changed line (an actual ``+``/``-``
line, not just the hunk span), is dropped; ``downgrade`` lowers severity one
level and the verification confidence replaces the candidate's confidence.
Survivors become the final :class:`Finding` list.

Stage 3 (``aggregate``) asks the model for one :class:`AnalysisSummary` over
the verified findings.  ``run_analysis`` wires the stages together over a
:class:`PRContext` (T2): ``building`` (T4 units), ``analyzing``, ``verifying``,
``aggregating`` - with a ``(stage, done, total)`` progress callback - and
assembles the result ``meta`` with stage durations, token estimates, skipped
files, and the T6 cross-stage counters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.models.analysis import AnalysisResult, AnalysisSummary
from app.models.finding import Finding, FindingCandidate, Severity
from app.models.pr import PRContext, PRInfo
from app.services.context_builder import (
    AnalysisUnit,
    build_analysis_unit,
    estimate_tokens,
    extract_hunk_ranges,
)
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: Stage labels reported through the ``progress`` callback.
STAGE_BUILDING = "building"
STAGE_ANALYZING = "analyzing"
STAGE_VERIFYING = "verifying"
STAGE_AGGREGATING = "aggregating"

#: Fixed generation instructions.  Always sent as the system message so the
#: model sees the exact contract (enums, confidence range, changed-line scope,
#: change-introduced-only rule, pure JSON) even when extra instructions are
#: appended by the caller.
GENERATE_SYSTEM_PROMPT = (
    "You are an expert code reviewer analyzing a pull request diff.\n"
    "Report ONLY issues introduced by THIS change; do not report pre-existing "
    "or unrelated issues.\n"
    "Each finding must satisfy:\n"
    "- category: one of bug, security, performance, maintainability, style\n"
    "- severity: one of critical, major, minor, nit\n"
    "- confidence: a float in [0, 1]\n"
    "- line_start and line_end must fall within the changed lines of the diff "
    "hunk; use the context's line numbers\n"
    "- file_path must match the file under review\n"
    "- title, description, evidence, suggestion are non-empty strings\n"
    "Output a JSON object with a single key \"findings\": a list of finding "
    "objects with fields file_path, line_start, line_end, category, severity, "
    "confidence, title, description, evidence, suggestion.\n"
    "Output pure JSON and nothing else."
)

#: Honest coverage note appended when the unit was trimmed by T4's budget
#: guard (``truncated=True``) - findings are partial coverage, not full-file.
TRUNCATED_COVERAGE_NOTE = (
    "Note: the provided diff/context is truncated and does not cover the full "
    "file; findings are partial coverage of the changed lines."
)

#: Fixed verification instructions.  Every candidate is judged on three
#: questions (introduced by this change / within the changed lines /
#: consistent with the context), with a deliberate bias toward ``drop`` over
#: ``keep`` to control false positives.
VERIFY_SYSTEM_PROMPT = (
    "You are a verification reviewer for a pull request diff.\n"
    "For each candidate finding (identified by its index) answer three "
    "questions:\n"
    "1. Was the issue introduced by THIS change, or is it pre-existing or "
    "unrelated?\n"
    "2. Does the finding's line range fall within the changed lines of the "
    "diff?\n"
    "3. Is the finding consistent with the surrounding context (no "
    "contradiction)?\n"
    "Decide a verdict per candidate:\n"
    "- keep: the issue is real, introduced by this change, and located in the "
    "changed lines\n"
    "- drop: the issue is pre-existing, unrelated, outside the changed lines, "
    "or otherwise not actionable\n"
    "- downgrade: the issue is real but its impact is lower than stated\n"
    "When in doubt, prefer drop over keep - it is better to miss a low-value "
    "issue than to report a false positive.\n"
    "Set confidence to a float in [0, 1] reflecting how sure you are of the "
    "verdict, and give a short reason for every candidate.\n"
    "Output a JSON object with a single key \"results\": a list of objects "
    "with fields index, verdict, confidence, reason.\n"
    "Output pure JSON and nothing else."
)


#: Fixed aggregation instructions for Stage 3: one summary over the verified
#: findings, never new analysis.
AGGREGATE_SYSTEM_PROMPT = (
    "You are a senior engineering lead writing the final review summary for "
    "a pull request.\n"
    "Base the summary ONLY on the verified findings below; do not introduce "
    "new findings.\n"
    "Produce a JSON object with a single key \"summary\" containing:\n"
    "- title: a short headline for the review\n"
    "- overview: 2-3 sentences summarizing the state of the change\n"
    "- key_points: the most important takeaways for the author\n"
    "- risk_highlights: the highest-risk issues that should block or gate "
    "the merge\n"
    "Output pure JSON and nothing else."
)


class GenerateOutput(BaseModel):
    """Raw LLM output for one analysis unit."""

    findings: list[FindingCandidate]


#: Pydantic schema validated against the LLM output in Stage 1.
GENERATE_SCHEMA = GenerateOutput


class VerifyItem(BaseModel):
    """Per-candidate verdict returned by the Stage 2 verification call."""

    index: int
    verdict: Literal["keep", "drop", "downgrade"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class VerifyOutput(BaseModel):
    """LLM output for one unit's verification call."""

    results: list[VerifyItem]


#: Pydantic schema validated against the LLM output in Stage 2.
VERIFY_SCHEMA = VerifyOutput


class AggregateOutput(BaseModel):
    """LLM output for the Stage 3 aggregation call."""

    summary: AnalysisSummary


#: Pydantic schema validated against the LLM output in Stage 3.
AGGREGATE_SCHEMA = AggregateOutput

#: Severity mapping applied when the verification verdict is ``downgrade``.
_DOWNGRADE_SEVERITY: dict[Severity, Severity] = {
    Severity.critical: Severity.major,
    Severity.major: Severity.minor,
    Severity.minor: Severity.nit,
    Severity.nit: Severity.nit,
}

#: Unified-diff hunk header; captures the new-side start line (``+c``).
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def build_generate_messages(
    unit: AnalysisUnit, instructions: str
) -> list[dict]:
    """Build the system/user message pair for one unit's generation call.

    The system message always carries the fixed instruction template (enums,
    changed-line scope, change-introduced-only rule, pure-JSON output), plus
    any caller-provided ``instructions`` and a partial-coverage note when the
    unit is truncated.  The user message carries the diff snippet and context.
    """
    parts = [GENERATE_SYSTEM_PROMPT]
    if instructions:
        parts.append(instructions)
    if unit["truncated"]:
        parts.append(TRUNCATED_COVERAGE_NOTE)
    return [
        {"role": "system", "content": "\n\n".join(parts)},
        {
            "role": "user",
            "content": (
                f"File: {unit['file_path']}\n\n"
                f"Diff:\n{unit['diff']}\n\n"
                f"Context (line-numbered):\n{unit['context']}"
            ),
        },
    ]


async def generate_for_unit(
    client: LLMClient,
    unit: AnalysisUnit,
    stats: dict | None = None,
) -> list[FindingCandidate]:
    """Run Stage 1 generation for one unit and calibrate finding line ranges.

    Calls ``chat_json`` with :data:`GENERATE_SCHEMA`, then clips every
    candidate's ``line_start``/``line_end`` onto the hunk changed-line ranges.
    Candidates with no overlap are dropped; when ``stats`` is provided the drop
    is counted under ``stats["dropped_by_scope"]``.
    """
    messages = build_generate_messages(unit, "")
    output = await client.chat_json(messages, GENERATE_SCHEMA)
    changed_lines = _changed_lines(extract_hunk_ranges(unit["diff"]))
    calibrated: list[FindingCandidate] = []
    for candidate in output.findings:
        clipped = _clip_to_changed_lines(candidate, changed_lines)
        if clipped is None:
            if stats is not None:
                stats["dropped_by_scope"] = stats.get("dropped_by_scope", 0) + 1
            continue
        calibrated.append(clipped)
    return calibrated


def build_verify_messages(
    unit: AnalysisUnit, candidates: list[FindingCandidate]
) -> list[dict]:
    """Build the system/user message pair for one unit's verification call.

    The system message carries the three per-candidate questions (introduced
    by this change / within the changed lines / consistent with the context),
    the prefer-drop-over-keep rule, and - when the unit is truncated - the
    same partial-coverage note used in generation so the verifier knows the
    context is not the full file.  The user message carries the diff, context,
    and the candidates serialized as JSON with their indices.
    """
    candidates_json = json.dumps(
        [
            {"index": index, **candidate.model_dump(mode="json")}
            for index, candidate in enumerate(candidates)
        ],
        ensure_ascii=False,
    )
    parts = [VERIFY_SYSTEM_PROMPT]
    if unit["truncated"]:
        parts.append(TRUNCATED_COVERAGE_NOTE)
    return [
        {"role": "system", "content": "\n\n".join(parts)},
        {
            "role": "user",
            "content": (
                f"File: {unit['file_path']}\n\n"
                f"Diff:\n{unit['diff']}\n\n"
                f"Context (line-numbered):\n{unit['context']}\n\n"
                f"Candidates (JSON):\n{candidates_json}"
            ),
        },
    ]


def build_aggregate_messages(
    pr_info: PRInfo, per_file: list[tuple[str, list[Finding]]]
) -> list[dict]:
    """Build the system/user message pair for the Stage 3 aggregation call.

    The system message carries the fixed summary instructions
    (:data:`AGGREGATE_SYSTEM_PROMPT`); the user message carries the PR
    metadata (owner/repo/number, title, URL) and, per file, the verified
    findings serialized as JSON.
    """
    body = "\n\n".join(
        f"File: {path}\nFindings:\n"
        f"{json.dumps([f.model_dump(mode='json') for f in findings], ensure_ascii=False, indent=2)}"
        for path, findings in per_file
    )
    user = (
        f"Pull request: {pr_info.owner}/{pr_info.repo}#{pr_info.number}\n"
        f"Title: {pr_info.title}\n"
        f"URL: {pr_info.html_url}"
    )
    if body:
        user = f"{user}\n\n{body}"
    return [
        {"role": "system", "content": AGGREGATE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def true_changed_lines(diff: str) -> set[int]:
    """Return the new-side line numbers that are actually added/removed lines.

    Context (unchanged) lines are excluded, so findings anchored on
    context-only lines are rejected by verification instead of being accepted
    merely because they fall inside a hunk span.  An added line contributes
    its new-side line number; a removed line contributes its new-side position
    (the deletion point).  Returns an empty set when the diff carries no
    parseable ``+``/``-`` body lines, in which case callers fall back to the
    hunk spans.
    """
    changed: set[int] = set()
    new_pos: int | None = None
    for line in diff.splitlines():
        header = _HUNK_HEADER_RE.match(line)
        if header:
            new_pos = int(header.group(1))
            continue
        if new_pos is None:
            continue  # file header (---/+++ ...) before the first hunk
        if line.startswith("+"):
            changed.add(new_pos)
            new_pos += 1
        elif line.startswith("-"):
            changed.add(new_pos)
        elif line.startswith(" "):
            new_pos += 1
        # "\ No newline at end of file" and other markers shift nothing.
    return changed


def _verification_changed_lines(diff: str) -> set[int]:
    """Changed-line set used by verification.

    Prefers the true ``+``/``-`` line membership; when the diff body is not
    parseable (e.g. a header-only hunk) falls back to the hunk spans so
    verification never drops every candidate on an empty parse.
    """
    changed = true_changed_lines(diff)
    if changed:
        return changed
    return _changed_lines(extract_hunk_ranges(diff))


class AnalysisEngine:
    """Orchestrates the analysis pipeline stages over analysis units."""

    def __init__(self, llm: LLMClient, concurrency: int = 4) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.llm = llm
        self.concurrency = concurrency
        #: Cross-stage counters; consumed by T8 for meta reporting.
        self.stats: dict = {
            "dropped_by_scope": 0,
            "skipped_units": 0,
            "scaffolding_tokens": _scaffolding_tokens(),
        }

    async def stage1_generate(
        self,
        units: list[AnalysisUnit],
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[tuple[AnalysisUnit, list[FindingCandidate]]]:
        """Generate candidates for every unit in parallel.

        Concurrency is bounded by an ``asyncio.Semaphore``.  A unit that fails
        (including :class:`AppError`) is recorded as skipped and skipped from
        the result; the remaining units still complete.  ``progress`` is called
        as ``(stage, completed, total)`` after each unit finishes (success or
        skip), with stage ``analyzing``.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(units)
        completed = 0

        async def worker(
            unit: AnalysisUnit,
        ) -> tuple[AnalysisUnit, list[FindingCandidate]] | None:
            nonlocal completed
            async with semaphore:
                try:
                    findings = await generate_for_unit(
                        self.llm, unit, stats=self.stats
                    )
                    return unit, findings
                except Exception as exc:  # per-unit isolation: one bad unit must not abort the run
                    self.stats["skipped_units"] += 1
                    if isinstance(exc, AppError):
                        logger.warning(
                            "stage1 skipped unit=%s code=%s",
                            unit["file_path"],
                            exc.code,
                        )
                    else:
                        logger.warning(
                            "stage1 skipped unit=%s error=%s",
                            unit["file_path"],
                            exc.__class__.__name__,
                        )
                    return None
                finally:
                    completed += 1
                    if progress is not None:
                        progress(STAGE_ANALYZING, completed, total)

        gathered = await asyncio.gather(*(worker(unit) for unit in units))
        return [pair for pair in gathered if pair is not None]

    async def verify_candidates(
        self, unit: AnalysisUnit, candidates: list[FindingCandidate]
    ) -> list[tuple[FindingCandidate, str]]:
        """Verify one unit's candidates; return surviving ``(candidate, verdict)`` pairs.

        Calls ``chat_json`` with :data:`VERIFY_SCHEMA`, then applies
        deterministic gates before the model verdict: a candidate whose
        ``file_path`` does not match the unit, or whose range contains no true
        changed line (an actual ``+``/``-`` line), is dropped.  Survivors get
        their confidence replaced by the verification output, and their
        severity lowered one level when the verdict is ``downgrade``; ``drop``
        removes the candidate.  A candidate missing from the LLM results is
        conservatively dropped (prefer a miss over a false positive).
        """
        if not candidates:
            return []
        messages = build_verify_messages(unit, candidates)
        output = await self.llm.chat_json(messages, VERIFY_SCHEMA)
        verdict_by_index = {item.index: item for item in output.results}
        changed_lines = _verification_changed_lines(unit["diff"])
        verified: list[tuple[FindingCandidate, str]] = []
        for index, candidate in enumerate(candidates):
            item = verdict_by_index.get(index)
            if item is None:
                continue  # no verdict produced for this candidate: drop
            if candidate.file_path != unit["file_path"]:
                continue  # deterministic gate: wrong file
            clipped = _clip_to_line_set(candidate, changed_lines)
            if clipped is None:
                continue  # deterministic gate: no true changed line in range
            if item.verdict == "drop":
                continue
            update: dict = {"confidence": item.confidence}
            if item.verdict == "downgrade":
                update["severity"] = _DOWNGRADE_SEVERITY[clipped.severity]
            verified.append((clipped.model_copy(update=update), item.verdict))
        return verified

    async def stage2_verify(
        self,
        pairs: list[tuple[AnalysisUnit, list[FindingCandidate]]],
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[Finding]:
        """Verify every unit's candidates in parallel and collect findings.

        Concurrency is bounded by an ``asyncio.Semaphore``.  A unit that fails
        (including :class:`AppError`) contributes no findings - unverified
        candidates must not reach the result - while the remaining units still
        complete.  ``progress`` is called as ``(stage, completed, total)``
        after each unit finishes (success or failure), with stage
        ``verifying``.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(pairs)
        completed = 0

        async def worker(
            pair: tuple[AnalysisUnit, list[FindingCandidate]],
        ) -> list[Finding]:
            nonlocal completed
            unit, candidates = pair
            async with semaphore:
                try:
                    verified = await self.verify_candidates(unit, candidates)
                except Exception as exc:  # per-unit isolation: unverified findings must not leak
                    if isinstance(exc, AppError):
                        logger.warning(
                            "stage2 dropped unit=%s code=%s",
                            unit["file_path"],
                            exc.code,
                        )
                    else:
                        logger.warning(
                            "stage2 dropped unit=%s error=%s",
                            unit["file_path"],
                            exc.__class__.__name__,
                        )
                    return []
                finally:
                    completed += 1
                    if progress is not None:
                        progress(STAGE_VERIFYING, completed, total)
                return [_to_finding(candidate) for candidate, _ in verified]

        gathered = await asyncio.gather(*(worker(pair) for pair in pairs))
        return [finding for findings in gathered for finding in findings]

    async def aggregate(
        self, pr_info: PRInfo, findings: list[Finding]
    ) -> AnalysisSummary:
        """Summarize the verified findings with one Stage 3 LLM call.

        Findings are grouped by ``file_path`` (first-seen order) so the model
        sees per-file sections; the returned :class:`AnalysisSummary` becomes
        the review's headline summary.  A failure here propagates to the
        caller - ``run_analysis`` isolates it and falls back to an empty
        summary so verified findings are never lost.
        """
        by_file: dict[str, list[Finding]] = {}
        for finding in findings:
            by_file.setdefault(finding.file_path, []).append(finding)
        per_file = list(by_file.items())
        messages = build_aggregate_messages(pr_info, per_file)
        output = await self.llm.chat_json(messages, AGGREGATE_SCHEMA)
        return output.summary

    async def run_analysis(
        self,
        ctx: PRContext,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> AnalysisResult:
        """Run the full pipeline over a PR context.

        Stages: ``building`` (T4 units per file; unbuildable files are
        recorded skipped), ``analyzing`` (Stage 1), ``verifying`` (Stage 2),
        ``aggregating`` (Stage 3).  ``progress`` fires as ``(stage, done,
        total)`` with per-file totals in ``building`` and per-unit totals in
        ``analyzing``/``verifying``.

        Partial-failure semantics: a file that cannot be built is skipped; as
        long as at least one file produces units a result is returned with
        ``meta["partial"]`` marking the partial success.  When no file is
        analyzable an ``AppError("no_analyzable_files")`` is raised, and when
        aggregation fails the result falls back to an empty summary
        (``aggregate_failed`` in meta) rather than losing the verified
        findings.  ``meta`` carries ``stage_durations``, ``token_estimate``,
        ``skipped_files``, and the T6 cross-stage counters
        (``dropped_by_scope``/``skipped_units``/``scaffolding_tokens``).
        """
        stage_durations: dict[str, float] = {}
        skipped_files: list[str] = []
        units: list[AnalysisUnit] = []

        # -- building: T4 units per file; unbuildable files are skipped ------
        building_started = time.monotonic()
        total_files = len(ctx.files)
        completed = 0
        for file in ctx.files:
            try:
                file_units = build_analysis_unit(file)
            except Exception as exc:
                skipped_files.append(file.path)
                if isinstance(exc, AppError):
                    logger.warning(
                        "build skipped file=%s code=%s", file.path, exc.code
                    )
                else:
                    logger.warning(
                        "build skipped file=%s error=%s",
                        file.path,
                        exc.__class__.__name__,
                    )
            else:
                if file_units:
                    units.extend(file_units)
                else:
                    skipped_files.append(file.path)
            completed += 1
            if progress is not None:
                progress(STAGE_BUILDING, completed, total_files)
        stage_durations["building"] = round(
            time.monotonic() - building_started, 4
        )

        if not units:
            raise AppError(
                "no_analyzable_files",
                message="no analyzable files in the pull request",
            )

        # -- analyzing: Stage 1 candidate generation ------------------------
        analyzing_started = time.monotonic()
        pairs = await self.stage1_generate(units, progress=progress)
        stage_durations["analyzing"] = round(
            time.monotonic() - analyzing_started, 4
        )

        # -- verifying: Stage 2 verification --------------------------------
        verifying_started = time.monotonic()
        findings = await self.stage2_verify(pairs, progress=progress)
        stage_durations["verifying"] = round(
            time.monotonic() - verifying_started, 4
        )

        # -- aggregating: Stage 3 summary -----------------------------------
        aggregating_started = time.monotonic()
        aggregate_failed = False
        try:
            summary = await self.aggregate(ctx.info, findings)
        except Exception as exc:  # verified findings must survive a bad summary
            aggregate_failed = True
            if isinstance(exc, AppError):
                logger.warning("stage3 aggregation failed code=%s", exc.code)
            else:
                logger.warning(
                    "stage3 aggregation failed error=%s",
                    exc.__class__.__name__,
                )
            summary = AnalysisSummary(
                title="", overview="", key_points=[], risk_highlights=[]
            )
        stage_durations["aggregating"] = round(
            time.monotonic() - aggregating_started, 4
        )
        if progress is not None:
            progress(STAGE_AGGREGATING, 1, 1)

        meta: dict = {
            "stage_durations": stage_durations,
            "token_estimate": _token_estimate(
                units, self.stats["scaffolding_tokens"]
            ),
            "skipped_files": skipped_files,
            "dropped_by_scope": self.stats["dropped_by_scope"],
            "skipped_units": self.stats["skipped_units"],
            "scaffolding_tokens": self.stats["scaffolding_tokens"],
            "partial": bool(
                skipped_files
                or self.stats["skipped_units"]
                or aggregate_failed
            ),
        }
        if aggregate_failed:
            meta["aggregate_failed"] = True
        return AnalysisResult(summary=summary, findings=findings, meta=meta)


def _changed_lines(ranges: list[tuple[int, int]]) -> set[int]:
    """Expand hunk new-file ranges into a set of changed line numbers."""
    lines: set[int] = set()
    for start, end in ranges:
        lines.update(range(start, end + 1))
    return lines


def _clip_to_changed_lines(
    candidate: FindingCandidate, changed_lines: set[int]
) -> FindingCandidate | None:
    """Clip a candidate range to the changed lines; None when no overlap.

    Endpoints of the clipped range always land on changed lines, so the
    ``line_start``/``line_end``-within-changed-lines invariant holds.
    """
    return _clip_to_line_set(candidate, changed_lines)


def _clip_to_line_set(
    candidate: FindingCandidate, lines: set[int]
) -> FindingCandidate | None:
    """Clip a candidate range to ``lines``; None when no overlap.

    The search window is bounded by ``min(lines)``/``max(lines)`` so a
    pathological range (e.g. ``line_end = 1e9``) never materializes a huge
    range.  Endpoints of the clipped range always land on ``lines``.
    """
    if not lines:
        return None
    lower, upper = min(lines), max(lines)
    start = max(candidate.line_start, lower)
    end = min(candidate.line_end, upper)
    if start > end:
        return None
    overlap = [line for line in range(start, end + 1) if line in lines]
    if not overlap:
        return None
    new_start, new_end = overlap[0], overlap[-1]
    if new_start == candidate.line_start and new_end == candidate.line_end:
        return candidate
    return candidate.model_copy(
        update={"line_start": new_start, "line_end": new_end}
    )


def _to_finding(candidate: FindingCandidate) -> Finding:
    """Promote a verified candidate to a final :class:`Finding` (id/verified)."""
    return Finding.model_validate(candidate.model_dump())


def _scaffolding_tokens() -> int:
    """Estimate tokens of the fixed prompt scaffolding for one unit.

    ``estimate_tokens`` (T4) covers diff + context only; this adds the system
    instructions, user-message template labels, and schema description so the
    effective per-file budget accounting stays honest for T8's meta.
    """
    empty_unit: AnalysisUnit = {
        "file_path": "x.py",
        "diff": "",
        "context": "",
        "truncated": False,
    }
    messages = build_generate_messages(empty_unit, "")
    return sum(estimate_tokens(message["content"]) for message in messages)


def _token_estimate(
    units: list[AnalysisUnit], scaffolding_tokens: int
) -> dict:
    """Estimate input tokens per unit and in total for ``meta.token_estimate``.

    Per-unit input is the diff + context (T4's ``estimate_tokens``) plus the
    fixed prompt scaffolding that every call carries (T6's
    ``scaffolding_tokens``).
    """
    per_unit = [
        {
            "file_path": unit["file_path"],
            "input_tokens": (
                estimate_tokens(unit["diff"])
                + estimate_tokens(unit["context"])
                + scaffolding_tokens
            ),
        }
        for unit in units
    ]
    return {
        "units": per_unit,
        "total_input_tokens": sum(item["input_tokens"] for item in per_unit),
    }
