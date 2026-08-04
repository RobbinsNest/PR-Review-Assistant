"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def health() -> dict[str, str]:
    """Liveness probe used by Docker/CI and load balancers."""
    return {"status": "ok"}
