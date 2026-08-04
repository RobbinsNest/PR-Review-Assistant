"""History API: list, detail, delete and Markdown export of stored analyses.

Endpoints under ``/api/history``:

- ``GET /api/history``              -> paginated list ``{items, total}``
- ``GET /api/history/{id}``         -> single record (summary/findings decoded)
- ``DELETE /api/history/{id}``      -> 204 on success, 404 for unknown ids
- ``GET /api/history/{id}/export``  -> Markdown report as a download attachment

The router reads the shared ``HistoryStore`` initialized by the app lifespan
(``app.state.history_store``, the T12 seam). No store state lives on the
router; unknown ids surface as ``AppError("not_found")`` -> 404.
"""

from fastapi import APIRouter, Request, Response

from app.core.errors import AppError

router = APIRouter(prefix="/api/history", tags=["history"])

#: Attachment filename advertised by the export endpoint.
_EXPORT_FILENAME = "report.md"


def _store(request: Request):
    """Return the app-wide ``HistoryStore`` instance (set by the lifespan)."""
    return request.app.state.history_store


@router.get("")
async def list_history(request: Request, limit: int = 50, offset: int = 0) -> dict:
    """Return one page of analyses (newest first) with the true record count.

    ``limit`` is clamped to the inclusive range [1, 100] (default 50) and
    ``offset`` to ``>= 0``; ``total`` is the full number of stored records
    (``HistoryStore.count()``), not the size of the returned page.
    """
    store = _store(request)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    items = await store.list(limit=limit, offset=offset)
    return {"items": items, "total": await store.count()}


@router.get("/{history_id}")
async def get_history(request: Request, history_id: str) -> dict:
    """Return a single analysis with its summary/findings decoded as dicts."""
    item = await _store(request).get(history_id)
    if item is None:
        raise AppError("not_found", message=f"analysis {history_id} not found")
    return item


@router.delete("/{history_id}", status_code=204)
async def delete_history(request: Request, history_id: str) -> Response:
    """Hard-delete one analysis; unknown ids return 404."""
    if not await _store(request).delete(history_id):
        raise AppError("not_found", message=f"analysis {history_id} not found")
    return Response(status_code=204)


@router.get("/{history_id}/export")
async def export_history(request: Request, history_id: str) -> Response:
    """Download the stored analysis as a Markdown report attachment."""
    markdown = await _store(request).export_markdown(history_id)
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{_EXPORT_FILENAME}"'},
    )
