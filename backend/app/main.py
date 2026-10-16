"""FastAPI application entry point with lifespan management and CORS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.database import async_session_factory, init_db
from backend.app.routers import auth, rag, subjects, tutor
from backend.app.routers import health as health_router
from backend.app.routers.subjects import seed_default_curriculum
from backend.app.spa import mount_spa
from backend.app.startup_validation import validate_production_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize database schema and seed default curriculum problems on startup."""
    await init_db()
    async with async_session_factory() as session:
        await seed_default_curriculum(session)
    yield


def create_app(static_root: str | Path | None = None) -> FastAPI:
    """Construct and configure the FastAPI application (API first, SPA last)."""
    settings = get_settings()
    validate_production_settings(settings)
    docs_on = bool(settings.debug)
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "End-to-End Neuro-Symbolic Socratic Virtual Tutor powered by "
            "LangGraph, Gemini Multi-Model Cascade, SymPy, Python AST, and Grounded RAG."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(auth.router)
    app.include_router(subjects.router)
    app.include_router(tutor.router)
    app.include_router(rag.router)

    @app.get("/api/health", tags=["System"], include_in_schema=False)
    async def legacy_api_health() -> dict[str, str]:
        """Backward-compatible alias of /health without a DB round-trip."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "primary_model": settings.gemini_primary_model,
        }

    # SPA after API routers so /api/* always wins over the HTML fallback.
    mount_spa(app, static_root=static_root)
    return app


app = create_app()
