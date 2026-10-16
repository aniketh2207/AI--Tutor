"""Application settings and environment configuration via Pydantic v2 Settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized typed configuration for the Neuro-Symbolic Socratic Virtual Tutor."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Metadata
    app_name: str = "Neuro-Symbolic Socratic Virtual Tutor"
    app_env: str = "development"
    debug: bool = True
    port: int = 8000

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///./socratic_tutor.db"
    test_database_url: str = "sqlite+aiosqlite:///./test_socratic_tutor.db"

    # Hybrid Authentication (JWT + Google OAuth2)
    jwt_secret_key: str = "socratic-tutor-dev-secret-key-change-in-prod-32b"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    google_client_id: str = "mock-google-client-id.apps.googleusercontent.com"

    # Google Cloud Vertex AI & Multi-Model Gemini Cascade
    google_genai_use_vertexai: bool = True
    google_cloud_project: str = "ai-tutor-511715"
    google_cloud_location: str = "us-central1"
    gemini_api_key: Optional[str] = None
    gemini_primary_model: str = "gemini-3.1-flash-lite"
    gemini_secondary_model: str = "gemini-3.5-flash-lite"
    gemini_tertiary_model: str = "gemini-3.7-flash"
    gemini_emergency_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dim: int = 768

    # Socratic Loop & Symbolic Guardrails
    max_socratic_retries: int = 3
    rag_similarity_threshold: float = 0.65
    rag_max_pdf_pages: int = 15
    rag_max_pdf_bytes: int = 5_242_880
    ast_sandbox_timeout_seconds: float = 2.0

    # CORS Configuration
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def model_cascade(self) -> list[str]:
        """Return the strict 4-model fallback cascade defined in document.md Section 3."""
        return [
            self.gemini_primary_model,
            self.gemini_secondary_model,
            self.gemini_tertiary_model,
            self.gemini_emergency_model,
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
