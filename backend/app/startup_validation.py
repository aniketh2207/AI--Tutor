"""Fail-fast production configuration checks (P0 Round 1)."""

from __future__ import annotations

from backend.app.config import Settings, get_settings

KNOWN_INSECURE_JWT_SECRETS = frozenset(
    {
        "socratic-tutor-dev-secret-key-change-in-prod-32b",
        "CHANGE_ME_IN_PRODUCTION_USE_STRONG_256_BIT_SECRET",
    }
)


def validate_production_settings(settings: Settings | None = None) -> None:
    """Raise RuntimeError if production settings are insecure or incomplete.

    Development/test environments are intentionally skipped.
    """
    active = settings or get_settings()
    env_name = active.app_env.strip().lower()
    if env_name not in {"production", "prod"}:
        return

    secret = active.jwt_secret_key.strip()
    if not secret or secret in KNOWN_INSECURE_JWT_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing, too short (<32 chars), or set to a known "
            "insecure default. Refuse to start when APP_ENV=production."
        )

    if active.debug:
        raise RuntimeError(
            "DEBUG must be false when APP_ENV=production."
        )

    client_id = active.google_client_id.strip()
    if (
        not client_id
        or client_id.startswith("mock-")
        or client_id.startswith("your-")
    ):
        raise RuntimeError(
            "GOOGLE_CLIENT_ID must be a real OAuth Web client ID when "
            "APP_ENV=production."
        )
