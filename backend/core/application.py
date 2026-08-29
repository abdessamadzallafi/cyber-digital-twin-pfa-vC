"""Application composition helpers shared by ASGI entry points and tests."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import api_router
from backend.core.config import settings


def install_platform_api(app: FastAPI) -> FastAPI:
    """Install DI-backed versioned endpoints without changing legacy routes."""
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(api_router)
    return app
