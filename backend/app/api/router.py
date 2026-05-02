"""Central API router — registers all v1 sub-routers."""
from fastapi import APIRouter

from app.api.v1 import auth, feedback, health, search, threads

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(threads.router)
api_router.include_router(search.router)
api_router.include_router(feedback.router)
