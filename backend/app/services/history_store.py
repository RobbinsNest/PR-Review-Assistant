"""SQLite-backed history store for analysis results (SPEC §6).

Persists completed analyses in an ``analyses`` table via ``aiosqlite``.
Summary / findings / config snapshots are stored as JSON TEXT; no token or
key is ever written. Also renders a Markdown report for a stored record.
"""

import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from app.core.errors import AppError
from app.models.analysis import AnalysisResult
from app.models.pr import PRInfo

#: Fixed status written for saved (successful) analyses.
STATUS_SUCCEEDED = "succeeded"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_title TEXT NOT NULL,
    pr_url TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings TEXT NOT NULL,
    error TEXT,
    config_snapshot TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

#: Columns that hold JSON-encoded payloads; decoded back on read.
_JSON_COLUMNS = ("summary", "findings", "config_snapshot")

_NOT_INITIALIZED = "HistoryStore.init() must be called before use"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _md_cell(value: object) -> str:
    """Escape a value so it is safe inside a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


class HistoryStore:
    """Async CRUD + Markdown export over the ``analyses`` table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the SQLite database and create the ``analyses`` table."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the SQLite connection; safe when never initialized."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def save(
        self,
        pr: PRInfo,
        result: AnalysisResult,
        config_snapshot: dict,
        duration_ms: int,
    ) -> str:
        """Persist one analysis record and return its new id."""
        if self._conn is None:
            raise RuntimeError(_NOT_INITIALIZED)
        serialized = self._serialize_result(result)
        analysis_id = str(uuid.uuid4())
        now = _now_iso()
        await self._conn.execute(
            """INSERT INTO analyses (
                id, owner, repo, pr_number, pr_title, pr_url, base_sha,
                head_sha, status, summary, findings, error, config_snapshot,
                duration_ms, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis_id,
                pr.owner,
                pr.repo,
                pr.number,
                pr.title,
                pr.html_url,
                pr.base_sha,
                pr.head_sha,
                STATUS_SUCCEEDED,
                json.dumps(serialized["summary"], ensure_ascii=False),
                json.dumps(serialized["findings"], ensure_ascii=False),
                None,
                json.dumps(config_snapshot, ensure_ascii=False),
                duration_ms,
                now,
                now,
            ),
        )
        await self._conn.commit()
        return analysis_id

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return analyses ordered by ``created_at`` descending."""
        if self._conn is None:
            raise RuntimeError(_NOT_INITIALIZED)
        cursor = await self._conn.execute(
            "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get(self, id: str) -> dict | None:
        """Return a single analysis with JSON fields decoded, or ``None``."""
        if self._conn is None:
            raise RuntimeError(_NOT_INITIALIZED)
        cursor = await self._conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row is not None else None

    async def delete(self, id: str) -> bool:
        """Hard-delete an analysis; return ``True`` when a row was removed."""
        if self._conn is None:
            raise RuntimeError(_NOT_INITIALIZED)
        cursor = await self._conn.execute(
            "DELETE FROM analyses WHERE id = ?", (id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def export_markdown(self, id: str) -> str:
        """Render a stored analysis as a Markdown report.

        Raises ``AppError("not_found")`` when no record matches ``id``.
        """
        row = await self.get(id)
        if row is None:
            raise AppError("not_found", message=f"analysis {id} not found")
        summary = row["summary"] or {}
        lines = [
            "# PR 评审报告",
            "",
            "## 变更总结",
            "",
            f"**标题**：{_md_cell(row['pr_title'])}",
            f"**仓库**：{_md_cell(row['owner'])}/{_md_cell(row['repo'])} #{row['pr_number']}",
            f"**链接**：{_md_cell(row['pr_url'])}",
            f"**base_sha**：{_md_cell(row['base_sha'])} → **head_sha**：{_md_cell(row['head_sha'])}",
            f"**耗时**：{row['duration_ms']}ms",
            "",
        ]
        overview = summary.get("overview")
        if overview:
            lines += [f"**概览**：{_md_cell(overview)}", ""]
        key_points = summary.get("key_points") or []
        if key_points:
            lines += ["**要点**：", *[f"- {_md_cell(point)}" for point in key_points], ""]
        risk_highlights = summary.get("risk_highlights") or []
        if risk_highlights:
            lines += [
                "**风险高亮**：",
                *[f"- {_md_cell(item)}" for item in risk_highlights],
                "",
            ]

        lines += [
            "## 风险发现",
            "",
            "| 类别 | 严重度 | 置信度 | 文件:行 | 标题 | 建议 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        findings = row["findings"] or []
        if findings:
            for finding in findings:
                line_start = finding.get("line_start")
                line_end = finding.get("line_end")
                location = f"{finding.get('file_path')}:{line_start}"
                if line_end is not None and line_end != line_start:
                    location += f"-{line_end}"
                cells = [
                    _md_cell(finding.get("category")),
                    _md_cell(finding.get("severity")),
                    _md_cell(finding.get("confidence")),
                    _md_cell(location),
                    _md_cell(finding.get("title")),
                    _md_cell(finding.get("suggestion")),
                ]
                lines.append("| " + " | ".join(cells) + " |")
        else:
            lines.append("| （无） | | | | | |")

        lines += ["", "## 评审建议", ""]
        suggestions = [f["suggestion"] for f in findings if f.get("suggestion")]
        if suggestions:
            lines += [f"- {_md_cell(item)}" for item in suggestions]
        else:
            lines.append("- （无）")
        return "\n".join(lines)

    def _serialize_result(self, result: AnalysisResult) -> dict:
        """Convert summary/findings into a JSON-safe dict."""
        return {
            "summary": result.summary.model_dump(mode="json"),
            "findings": [finding.model_dump(mode="json") for finding in result.findings],
        }

    def _row_to_dict(self, row: aiosqlite.Row) -> dict:
        """Decode JSON columns of a raw row into plain Python values."""
        data = dict(row)
        for column in _JSON_COLUMNS:
            raw = data.get(column)
            try:
                data[column] = json.loads(raw)
            except (TypeError, ValueError):
                data[column] = None
        return data