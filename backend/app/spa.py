"""Serve the Vite SPA from /app/static when the image includes a frontend build."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope


class LongCacheStaticFiles(StaticFiles):
    """Fingerprinted Vite assets: cache for one year."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def resolve_static_root(static_root: str | Path | None = None) -> Path | None:
    """Return a usable static directory containing index.html, else None."""
    root = Path(static_root) if static_root is not None else Path("/app/static")
    if root.is_dir() and (root / "index.html").is_file():
        return root
    return None


def _is_reserved_path(path: str) -> bool:
    """Paths that must never fall through to index.html."""
    cleaned = path.lstrip("/")
    if not cleaned:
        return False
    first = cleaned.split("/", 1)[0]
    return first in {
        "api",
        "health",
        "livez",
        "docs",
        "redoc",
        "openapi.json",
    }


def mount_spa(app: FastAPI, static_root: str | Path | None = None) -> None:
    """Mount /assets with long cache and SPA HTML fallback for deep links."""
    root = resolve_static_root(static_root)
    if root is None:
        return

    assets_dir = root / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            LongCacheStaticFiles(directory=str(assets_dir)),
            name="spa-assets",
        )

    index_path = root / "index.html"

    async def _index() -> FileResponse:
        return FileResponse(
            index_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    async def spa_root() -> FileResponse:
        return await _index()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> FileResponse:
        """Client-side routes → index.html; reserved prefixes stay JSON 404."""
        _ = request
        if _is_reserved_path(full_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        candidate = (root / full_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found") from exc
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return await _index()
