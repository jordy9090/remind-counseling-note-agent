"""Health check routes."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Application health check."""
    return {"status": "ok"}


@router.get("/api/health")
async def api_health_check():
    """API-prefixed health check."""
    return {"status": "ok"}
