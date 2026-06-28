"""Centralized configuration.

All settings are read from environment variables (prefix ``RD_``) and an
optional ``.env`` file. See ``.env.example`` for documentation of every field.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM backends for the specialist and judge agents."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HEURISTIC = "heuristic"  # no LLM — deterministic rule-based agents


class Settings(BaseSettings):
    """Runtime configuration for the whole system."""

    model_config = SettingsConfigDict(
        env_prefix="RD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM backend -------------------------------------------------------
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    llm_model: str = "ollama/llama3"
    ollama_base_url: str = "http://localhost:11434"
    llm_api_key: str | None = None
    llm_temperature: float = 0.2
    llm_timeout: int = 120

    # --- Debate protocol ---------------------------------------------------
    debate_rounds: int = Field(default=1, ge=0, le=5)
    weight_sustainability: float = Field(default=0.34, ge=0.0, le=1.0)
    weight_architecture: float = Field(default=0.33, ge=0.0, le=1.0)
    weight_performance: float = Field(default=0.33, ge=0.0, le=1.0)

    # --- Static analysis: SonarQube (optional) -----------------------------
    sonarqube_url: str | None = None
    sonarqube_token: str | None = None
    sonarqube_project_key: str = "refactoring-debate"

    # --- Dynamic analysis --------------------------------------------------
    enable_dynamic_analysis: bool = False
    dynamic_timeout: int = Field(default=30, ge=1, le=600)

    # --- API ---------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    runs_dir: str | None = "runs"
    log_level: str = "INFO"

    # --- Validators / derived ----------------------------------------------
    @field_validator("sonarqube_url", "llm_api_key", "runs_dir", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Treat empty strings from .env as unset (None)."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def is_heuristic(self) -> bool:
        return self.llm_provider is LLMProvider.HEURISTIC

    @property
    def sonarqube_enabled(self) -> bool:
        return bool(self.sonarqube_url and self.sonarqube_token)

    @property
    def decision_weights(self) -> dict[str, float]:
        """Normalized per-dimension decision weights used by the Judge."""
        raw = {
            "sustainability": self.weight_sustainability,
            "architecture": self.weight_architecture,
            "performance": self.weight_performance,
        }
        total = sum(raw.values()) or 1.0
        return {key: round(value / total, 4) for key, value in raw.items()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
