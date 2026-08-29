"""Aggregate API routers here; `backend.main` only composes the application."""
from fastapi import APIRouter
from backend.api.v1 import router as v1_router
from backend.api.siem import router as siem_router
from backend.api.ai import router as ai_router
from backend.api.drone import router as drone_router
from backend.api.operations import router as operations_router

api_router = APIRouter()
api_router.include_router(v1_router)
api_router.include_router(siem_router)
api_router.include_router(ai_router)
api_router.include_router(drone_router)
api_router.include_router(operations_router)
