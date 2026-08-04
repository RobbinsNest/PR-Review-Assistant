"""T4 context builder: hunk range parsing and enclosing function/class context windows.

Consumes ``ChangedFile`` (T2) and produces ``AnalysisUnit`` chunks consumed by the
analysis engine (T6/T7). Each unit carries a diff plus the union of the enclosing
function/class windows of every hunk; when the per-file token budget is exceeded
the hunks are split into contiguous groups so each chunk stays within budget.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from app.models.pr import ChangedFile

#: ``@@ -a,b +c,d @@`` -> new-side start ``c`` and optional new-side count ``d``.
_HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
#: Start of a function/class definition (python ``def``/``class``, js ``function``).
_DEF_LINE_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class|function)\b")

#: Languages whose scope end is found by indentation.
_INDENT_LANGUAGES = frozenset({"python", "py"})
#: Languages whose scope end is found by brace pairing.
_BRACE_LANGUAGES = frozenset({
    "javascript", "js", "typescript", "ts", "go", "golang", "rust", "rs",
    "java", "c", "cpp", "c++", "c#", "cs", "swift", "kotlin", "php", "scala", "dart",
})

_UNKNOWN_FALLBACK_LINES = 20


class AnalysisUnit(TypedDict):
    """One LLM-analysis chunk for a changed file."""

    file_path: str
    diff: str
    context: str
    truncated: bool


def estimate_tokens(text: str) -> int:
    """Rough token estimate: one token per ~4 characters."""
    return len(text) // 4


def extract_hunk_ranges(diff: str) -> list[tuple[int, int]]:
    """Parse each hunk's new-file line range from a unified diff.

    ``@@ -a,b +c,d @@`` becomes ``(c, c + d - 1)``. When the new-side count is
    omitted the hunk covers a single line, and when it is 0 (pure deletion) the
    range anchors at the first line, ``(c, c)``.
    """
    ranges: list[tuple[int, int]] = []
    for match in _HUNK_RE.finditer(diff):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) else 1
        end = start + count - 1 if count > 0 else start
        # Keep ranges well-formed and 1-based: a pure-deletion hunk has no
        # new-file lines, so anchor at the insertion point (clamped to line 1).
        start = max(start, 1)
        end = max(end, start)
        ranges.append((start, end))
    return ranges


def find_enclosing_function(
    content: str, line: int, language: str = "python"
) -> tuple[int, int]:
    """Return the minimal 1-based function/class window containing ``line``.

    Heuristic: scan upward from ``line`` for a ``def``/``class``/``function``
    keyword line, then find the scope end by indentation (python) or brace
    pairing (js/ts/go/rust and other brace languages). Unknown languages fall
    back to ``line +/- 20``. When nothing encloses ``line``, return
    ``(line, line)``.
    """
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return (line, line)

    lang = (language or "").lower()
    if lang in _INDENT_LANGUAGES:
        window = _find_by_indentation(lines, line)
    elif lang in _BRACE_LANGUAGES:
        window = _find_by_braces(lines, line)
    else:
        return (max(1, line - _UNKNOWN_FALLBACK_LINES),
                min(len(lines), line + _UNKNOWN_FALLBACK_LINES))

    if window is None:
        return (line, line)
    start, end = window
    if start <= line <= end:
        return (start, end)
    return (line, line)


def _find_by_indentation(lines: list[str], line: int) -> tuple[int, int] | None:
    """Locate the nearest enclosing def/class via indentation (0-based -> 1-based)."""
    def_start = _scan_up_for_definition(lines, line)
    if def_start is None:
        return None
    indent = len(lines[def_start]) - len(lines[def_start].lstrip())
    end = def_start
    for idx in range(def_start + 1, len(lines)):
        current = lines[idx]
        if not current.strip():
            continue
        if len(current) - len(current.lstrip()) <= indent:
            break
        end = idx
    return (def_start + 1, end + 1)


def _find_by_braces(lines: list[str], line: int) -> tuple[int, int] | None:
    """Locate the nearest enclosing def/class via ``{``/``}`` pairing."""
    def_start = _scan_up_for_definition(lines, line)
    if def_start is None:
        return None
    brace_idx = None
    for idx in range(def_start, len(lines)):
        if "{" in lines[idx]:
            brace_idx = idx
            break
    if brace_idx is None:
        return None
    balance = 0
    end = brace_idx
    for idx in range(brace_idx, len(lines)):
        balance += lines[idx].count("{") - lines[idx].count("}")
        end = idx
        if balance <= 0:
            break
    return (def_start + 1, end + 1)


def _scan_up_for_definition(lines: list[str], line: int) -> int | None:
    """Return the 0-based index of the nearest definition line at/above ``line``."""
    for idx in range(line - 1, -1, -1):
        if _DEF_LINE_RE.match(lines[idx]):
            return idx
    return None


def build_analysis_unit(
    file: ChangedFile, budget_in: int = 8000
) -> list[AnalysisUnit]:
    """Build analysis units for one changed file.

    Context is the union of every function/class window covering a hunk
    (line-number-prefixed). If the combined diff + context fits ``budget_in``,
    a single unit is returned with ``truncated=False``; otherwise the hunks are
    split into contiguous groups, each returning a unit whose diff + context
    stays within budget, all marked ``truncated=True``.
    """
    diff = file.diff
    head_content = file.head_content or ""
    language = _language_for_path(file.path)
    hunk_ranges = extract_hunk_ranges(diff)
    hunk_blocks = _split_hunk_blocks(diff)
    header = _diff_header(diff)

    intervals = [
        find_enclosing_function(head_content, start, language)
        for start, _end in hunk_ranges
    ]

    full_context = _context_text(head_content, _merge_intervals(intervals))
    if estimate_tokens(full_context) + estimate_tokens(diff) <= budget_in:
        return [AnalysisUnit(
            file_path=file.path, diff=diff, context=full_context, truncated=False,
        )]

    units: list[AnalysisUnit] = []
    group_indices: list[int] = []
    group_intervals: list[tuple[int, int]] = []

    def flush() -> None:
        nonlocal group_indices, group_intervals
        chunk_context = _context_text(
            head_content, _merge_intervals(group_intervals)
        )
        chunk_diff = _join_diff(header, [hunk_blocks[i] for i in group_indices])
        units.append(AnalysisUnit(
            file_path=file.path, diff=chunk_diff,
            context=chunk_context, truncated=True,
        ))
        group_indices = []
        group_intervals = []

    for index in range(len(hunk_ranges)):
        candidate_indices = group_indices + [index]
        candidate_intervals = group_intervals + [intervals[index]]
        candidate_context = _context_text(
            head_content, _merge_intervals(candidate_intervals)
        )
        candidate_diff = _join_diff(
            header, [hunk_blocks[i] for i in candidate_indices]
        )
        fits = estimate_tokens(candidate_context) + estimate_tokens(candidate_diff) <= budget_in
        if fits:
            group_indices = candidate_indices
            group_intervals = candidate_intervals
        else:
            if group_indices:
                flush()
            # Start a new group with this hunk; a single huge hunk may still
            # exceed the budget (graceful degradation, truncated stays True).
            group_indices = [index]
            group_intervals = [intervals[index]]
    if group_indices:
        flush()
    return units


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".pyw": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
    }.get(suffix, "unknown")


def _context_text(content: str, intervals: list[tuple[int, int]]) -> str:
    """Render 1-based line-number-prefixed text for the merged intervals."""
    lines = content.splitlines()
    parts: list[str] = []
    for start, end in intervals:
        for idx in range(start, min(end, len(lines)) + 1):
            if 1 <= idx <= len(lines):
                parts.append(f"{idx}:{lines[idx - 1]}")
    return "\n".join(parts)


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping intervals, preserving order."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _split_hunk_blocks(diff: str) -> list[str]:
    """Split a unified diff into hunk blocks, each starting with an ``@@`` line."""
    blocks: list[str] = []
    current: list[str] | None = None
    for line in diff.splitlines():
        if line.startswith("@@"):
            if current is not None:
                blocks.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def _diff_header(diff: str) -> str:
    """Return the file header (lines before the first hunk), e.g. ``--- a/...``."""
    header: list[str] = []
    for line in diff.splitlines():
        if line.startswith("@@"):
            break
        header.append(line)
    return "\n".join(header)


def _join_diff(header: str, blocks: list[str]) -> str:
    """Reassemble a (possibly empty) header plus selected hunk blocks."""
    return "\n".join([part for part in [header, *blocks] if part])