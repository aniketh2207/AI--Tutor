"""Round 3 deployment tests: compose env, Google boot, SPA, health, CI secrets."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

from backend.app.config import Settings, get_settings
from backend.app.main import create_app
from backend.app.startup_validation import validate_production_settings

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_compose_backend_uses_development_env() -> None:
    """Local docker compose must set APP_ENV=development and DEBUG=true."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "APP_ENV" in compose and "development" in compose
    assert "DEBUG" in compose and "true" in compose.lower()
    # Production defaults stay in the image ENV; compose overrides for local.
    backend_block = compose.split("backend:")[1].split("frontend:")[0]
    assert "APP_ENV: development" in backend_block or 'APP_ENV: "development"' in backend_block
    assert "DEBUG: \"true\"" in backend_block or "DEBUG: true" in backend_block or "DEBUG: 'true'" in backend_block


def test_dockerfile_builds_frontend_into_static() -> None:
    """Image must build the Vite app and copy dist to /app/static with empty API base."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:" in dockerfile or "FROM node@" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "/app/static" in dockerfile
    assert "ENV VITE_API_BASE_URL=" in dockerfile
    assert "http://" not in dockerfile.split("ENV VITE_API_BASE_URL=")[1].splitlines()[0]


@pytest.fixture()
def spa_static_dir(tmp_path: Path) -> Path:
    """Minimal Vite-like dist tree for SPA mounting tests."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>SPA</div></body></html>",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
async def spa_prod_client(
    spa_static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """App with SPA mounted and an isolated in-memory DB for /health readiness."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from backend.app.database import get_session

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "development")  # skip JWT prod gate in unit tests
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_maker() as session:
            yield session

    app = create_app(static_root=spa_static_dir)
    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()
    get_settings.cache_clear()


async def test_livez_and_health_endpoints(spa_prod_client: AsyncClient) -> None:
    """ /livez is cheap OK; /health requires a working DB session."""
    live = await spa_prod_client.get("/livez")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    health = await spa_prod_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"


async def test_health_returns_503_when_database_fails(
    spa_static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness must surface DB failures as HTTP 503."""
    from unittest.mock import AsyncMock, MagicMock

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()

    broken = MagicMock()
    broken.execute = AsyncMock(side_effect=RuntimeError("db down"))

    async def override_session() -> AsyncGenerator[object, None]:
        yield broken

    app = create_app(static_root=spa_static_dir)
    from backend.app.database import get_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 503
    assert "database" in resp.json()["detail"].lower()
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_spa_routes_and_api_404(
    spa_prod_client: AsyncClient,
) -> None:
    """/ and deep links serve index.html; unknown /api is JSON 404; public-config works."""
    root = await spa_prod_client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    assert "SPA" in root.text

    deep = await spa_prod_client.get("/chat/123")
    assert deep.status_code == 200
    assert "SPA" in deep.text

    missing_api = await spa_prod_client.get("/api/does-not-exist")
    assert missing_api.status_code == 404
    body = missing_api.json()
    assert "detail" in body
    assert "SPA" not in missing_api.text

    public = await spa_prod_client.get("/api/auth/public-config")
    assert public.status_code == 200
    assert "google_sign_in_enabled" in public.json()

    docs = await spa_prod_client.get("/docs")
    assert docs.status_code == 404


def test_cicd_uses_secret_manager_and_smoke_rollback() -> None:
    """Deploy workflow must use --set-secrets and roll back on smoke failure."""
    cicd = (REPO_ROOT / ".github" / "workflows" / "ci_cd.yml").read_text(
        encoding="utf-8"
    )
    assert "--set-secrets=" in cicd
    assert "JWT_SECRET_KEY=JWT_SECRET_KEY:latest" in cicd
    assert "DATABASE_URL=DATABASE_URL:latest" in cicd
    assert "GOOGLE_CLIENT_ID" in cicd
    assert "CORS_ORIGINS" in cicd
    assert "smoke_post_deploy.py" in cicd
    assert "update-traffic" in cicd
    assert "to-revisions" in cicd


def test_readme_documents_deploy_rollback_and_spa_serving() -> None:
    """README must document deploy/rollback and that FastAPI serves the SPA."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Deploy and roll back" in readme
    assert "Secret Manager" in readme
    assert "--set-secrets" in readme
    assert "served by the FastAPI backend" in readme
    assert "update-traffic" in readme


def test_client_ip_debug_logs_xff_and_chosen_key(caplog: pytest.LogCaptureFixture) -> None:
    """DEBUG logs must show raw XFF and the rate-limit subject key."""
    import logging
    from unittest.mock import MagicMock

    from backend.app.services.rate_limit_service import client_ip_from_request

    request = MagicMock()
    request.headers = {"x-forwarded-for": "1.1.1.1, 35.191.0.1"}
    request.client = MagicMock(host="127.0.0.1")
    with caplog.at_level(logging.DEBUG, logger="backend.app.services.rate_limit_service"):
        chosen = client_ip_from_request(request)
    assert chosen == "35.191.0.1"
    assert "x_forwarded_for" in caplog.text
    assert "1.1.1.1" in caplog.text
    assert "35.191.0.1" in caplog.text
    assert "chosen_key" in caplog.text


def test_production_allows_missing_google_client_but_rejects_placeholders() -> None:
    """Missing GOOGLE_CLIENT_ID boots (Google disabled); mock-/your- still refuse."""
    strong_jwt = "a-sufficiently-long-production-secret-key-32b-plus"
    validate_production_settings(
        Settings(
            app_env="production",
            debug=False,
            jwt_secret_key=strong_jwt,
            google_client_id="",
        )
    )
    validate_production_settings(
        Settings(
            app_env="production",
            debug=False,
            jwt_secret_key=strong_jwt,
            google_client_id="   ",
        )
    )
    for bad in (
        "mock-google-client-id.apps.googleusercontent.com",
        "your-google-oauth-client-id.apps.googleusercontent.com",
    ):
        with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
            validate_production_settings(
                Settings(
                    app_env="production",
                    debug=False,
                    jwt_secret_key=strong_jwt,
                    google_client_id=bad,
                )
            )
