"""T6 analysis engine Stage 1: file-level parallel candidate generation.

For every :class:`AnalysisUnit` (T4) the engine issues one LLM call via
``LLMClient.chat_json`` (T5) asking for raw candidate findings, then calibrates
each candidate's ``line_start``/``line_end`` onto the diff hunk changed-line
ranges.  Candidates whose range does not intersect any changed line are dropped
and counted in ``dropped_by_scope`` so the verification stage never sees
out-of-scope findings.  A failed unit (after the LLM client's own retries) is
recorded as skipped and the remaining units continue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from pydantic import BaseModel

from app.core.errors import AppError
from app.models.finding import FindingCandidate
from app.services.context_builder import (
    AnalysisUnit,
    estimate_tokens,
    extract_hunk_ranges,
)
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: Stage label reported through the ``progress`` callback during Stage 1.
STAGE_ANALYZING = "analyzing"

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


class GenerateOutput(BaseModel):
    """Raw LLM output for one analysis unit."""

    findings: list[FindingCandidate]


#: Pydantic schema validated against the LLM output in Stage 1.
GENERATE_SCHEMA = GenerateOutput


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


class AnalysisEngine:
    """Orchestrates the analysis pipeline stages over analysis units."""

    def __init__(self, llm: LLMClient, concurrency: int = 4) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.llm = llm
        self.concurrency = concurrency
        #: Cross-stage counters; consumed by T7/T8 for meta reporting.
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
    overlap = [
        line
        for line in range(candidate.line_start, candidate.line_end + 1)
        if line in changed_lines
    ]
    if not overlap:
        return None
    new_start, new_end = overlap[0], overlap[-1]
    if new_start == candidate.line_start and new_end == candidate.line_end:
        return candidate
    return candidate.model_copy(
        update={"line_start": new_start, "line_end": new_end}
    )


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
