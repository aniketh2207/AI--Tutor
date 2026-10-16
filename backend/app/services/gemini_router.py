"""Multi-Model Gemini Router (Vertex AI) with 4-tier fallback cascade & cost guardrails."""

from __future__ import annotations

import time
from typing import Any
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft

DEFAULT_SOCRATIC_SYSTEM_INSTRUCTION = (
    "You are a Neuro-Symbolic Socratic Virtual Tutor. "
    "Analyze the student's work, extract a deterministic symbolic claim, and ask a "
    "guiding Socratic question. NEVER reveal or leak the final answer in socratic_question."
)


class GeminiRouter:
    """Routes all LLM & embedding calls through the locked 4-model Vertex AI Gemini cascade."""

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        use_vertexai: bool | None = None,
        api_key: str | None = None,
        client: genai.Client | None = None,
        cascade_models: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.use_vertexai: bool = (
            settings.google_genai_use_vertexai
            if use_vertexai is None
            else use_vertexai
        )
        self.project: str = project or settings.google_cloud_project
        self.location: str = location or settings.google_cloud_location
        self.api_key: str | None = api_key or settings.gemini_api_key
        self._client = client
        self.cascade_models: list[str] = cascade_models or settings.model_cascade
        self.embedding_model: str = settings.gemini_embedding_model
        self.embedding_dim: int = settings.gemini_embedding_dim

    @property
    def client(self) -> genai.Client:
        """Lazily initialize the official google-genai Client via Vertex AI ADC."""
        if self._client is None:
            if self.use_vertexai:
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project,
                    location=self.location,
                )
            else:
                self._client = genai.Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def build_generation_config(
        model_name: str,
        system_instruction: str | None = None,
    ) -> types.GenerateContentConfig:
        """Construct strict JSON-schema config with zero search grounding."""
        thinking_cfg = (
            types.ThinkingConfig(thinking_budget=0)
            if "flash-lite" in model_name.lower()
            else None
        )
        return types.GenerateContentConfig(
            system_instruction=system_instruction or DEFAULT_SOCRATIC_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=NeuralSocraticDraft,
            temperature=0.2,
            max_output_tokens=512,
            tools=None,  # Strictly forbidden to enable google_search grounding
            thinking_config=thinking_cfg,
        )

    def _ordered_cascade(self, start_tier: int = 0) -> list[str]:
        """Return cascade sequence starting at start_tier and falling through remaining models."""
        if not self.cascade_models:
            return []
        bounded_start = max(0, min(start_tier, len(self.cascade_models) - 1))
        return self.cascade_models[bounded_start:] + self.cascade_models[:bounded_start]

    @staticmethod
    def _parse_draft(response: Any) -> NeuralSocraticDraft:
        """Validate raw Gemini response against NeuralSocraticDraft Pydantic v2 schema."""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, NeuralSocraticDraft):
            return parsed
        if isinstance(parsed, dict):
            return NeuralSocraticDraft.model_validate(parsed)

        raw_text = getattr(response, "text", None)
        if isinstance(raw_text, str) and raw_text.strip():
            return NeuralSocraticDraft.model_validate_json(raw_text)

        return NeuralSocraticDraft.model_validate_json("{}")

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        """Execute generative Socratic draft call with automatic 4-model failover."""
        ordered_models = self._ordered_cascade(start_tier=start_tier)
        failed_models: list[str] = []
        last_error: Exception | None = None
        start_ts = time.perf_counter()

        for attempt_idx, model_name in enumerate(ordered_models, start=1):
            config = self.build_generation_config(
                model_name=model_name,
                system_instruction=system_instruction,
            )
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                draft = self._parse_draft(response)
                elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
                telemetry = ModelTelemetry(
                    model_used=model_name,
                    attempt_index=attempt_idx,
                    fallback_triggered=len(failed_models) > 0,
                    failed_models=failed_models,
                    latency_ms=elapsed_ms,
                )
                return draft, telemetry
            except (
                errors.ClientError,
                errors.ServerError,
                errors.APIError,
                ValidationError,
            ) as exc:
                failed_models.append(model_name)
                last_error = exc
                continue

        raise RuntimeError(
            f"All Gemini models in cascade failed ({failed_models}). Last error: {last_error}"
        ) from last_error

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed text chunks into 768-dim vectors using gemini-embedding-001 on Vertex AI."""
        if not texts:
            return []
        embed_config = types.EmbedContentConfig(
            output_dimensionality=self.embedding_dim,
        )
        result = self.client.models.embed_content(
            model=self.embedding_model,
            contents=texts,
            config=embed_config,
        )
        embeddings = getattr(result, "embeddings", None) or []
        return [list(item.values) for item in embeddings]


_default_router: GeminiRouter | None = None


def get_gemini_router() -> GeminiRouter:
    """Return singleton GeminiRouter instance."""
    global _default_router
    if _default_router is None:
        _default_router = GeminiRouter()
    return _default_router
