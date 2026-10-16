"""Fail-fast production configuration checks (fail closed outside local/test)."""

from __future__ import annotations

from backend.app.config import Settings, get_settings

KNOWN_INSECURE_JWT_SECRETS = frozenset(
    {
        "socratic-tutor-dev-secret-key-change-in-prod-32b",
        "CHANGE_ME_IN_PRODUCTION_USE_STRONG_256_BIT_SECRET",
    }
)

# Only these envs skip the production safety gate (fail-open for local work).
LOCAL_OR_TEST_ENVS = frozenset({"development", "dev", "test", "testing"})


def validate_production_settings(settings: Settings | None = None) -> None:
    """Raise RuntimeError if non-local settings are insecure or incomplete.

    Anything other than an explicit development/test env is treated as production.
    """
    active = settings or get_settings()
    env_name = active.app_env.strip().lower()
    if env_name in LOCAL_OR_TEST_ENVS:
        return

    secret = active.jwt_secret_key.strip()
    if not secret or secret in KNOWN_INSECURE_JWT_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing, too short (<32 chars), or set to a known "
            "insecure default. Refuse to start outside development/test."
        )

    if active.debug:
        raise RuntimeError(
            "DEBUG must be false outside development/test environments."
        )

    # Missing/blank GOOGLE_CLIENT_ID is allowed: Google Sign-In stays disabled via
    # /api/auth/public-config. Placeholder values are still refused so a half-configured
    # deploy cannot pretend Google auth is live.
    client_id = active.google_client_id.strip()
    if client_id.startswith("mock-") or client_id.startswith("your-"):
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is set to a placeholder (mock-/your-). "
            "Unset it to disable Google Sign-In, or provide a real OAuth Web client ID."
        )
