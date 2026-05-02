"""Health check endpoint."""
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": settings.app_version, "env": settings.app_env}
