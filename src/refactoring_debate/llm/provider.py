"""LLM provider abstraction.

The paper's reference backend is **Ollama + Llama3** (local models). This layer
also supports OpenAI/Anthropic and a fully deterministic **heuristic** mode (no
LLM at all). If a configured backend is unreachable (e.g. Ollama not running),
the system *gracefully degrades to heuristic mode* instead of failing, so the
full pipeline always runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from refactoring_debate.config import LLMProvider, Settings


@dataclass(slots=True)
class LLMHandle:
    """Resolved LLM backend handed to the agents."""

    requested_provider: LLMProvider
    effective_provider: LLMProvider
    model: str
    crew_llm: Any | None  # a crewai.LLM instance, or None in heuristic mode
    note: str = ""

    @property
    def uses_llm(self) -> bool:
        return self.effective_provider is not LLMProvider.HEURISTIC and self.crew_llm is not None

    @property
    def label(self) -> str:
        if self.uses_llm:
            return f"{self.effective_provider.value}:{self.model}"
        return "heuristic"


def _ollama_reachable(base_url: str, model: str) -> tuple[bool, str]:
    """Probe an Ollama server and confirm the model is available."""
    tag = model.split("/", 1)[-1]  # "ollama/llama3" -> "llama3"
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.5)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama unreachable at {base_url} ({exc.__class__.__name__})"
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    if not any(name.split(":", 1)[0] == tag.split(":", 1)[0] for name in names):
        return False, f"Ollama is up but model '{tag}' is not pulled (`ollama pull {tag}`)"
    return True, ""


def _make_crew_llm(settings: Settings) -> Any:
    """Construct a crewai.LLM for the configured cloud/local provider."""
    from crewai import LLM

    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_provider is LLMProvider.OLLAMA:
        kwargs["base_url"] = settings.ollama_base_url
    elif settings.llm_api_key:
        kwargs["api_key"] = settings.llm_api_key
    return LLM(**kwargs)


def build_llm(settings: Settings) -> LLMHandle:
    """Resolve the effective LLM backend, degrading to heuristic when needed."""
    requested = settings.llm_provider

    if settings.is_heuristic:
        return LLMHandle(requested, LLMProvider.HEURISTIC, settings.llm_model, None,
                         note="heuristic mode (no LLM)")

    # Pre-flight check for Ollama so we fail fast and degrade cleanly.
    if requested is LLMProvider.OLLAMA:
        ok, reason = _ollama_reachable(settings.ollama_base_url, settings.llm_model)
        if not ok:
            logger.warning("{} — falling back to heuristic agents.", reason)
            return LLMHandle(requested, LLMProvider.HEURISTIC, settings.llm_model, None, note=reason)

    if requested in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC) and not settings.llm_api_key:
        note = f"{requested.value} selected but RD_LLM_API_KEY is empty — using heuristic agents."
        logger.warning(note)
        return LLMHandle(requested, LLMProvider.HEURISTIC, settings.llm_model, None, note=note)

    try:
        crew_llm = _make_crew_llm(settings)
    except Exception as exc:  # noqa: BLE001
        note = f"could not initialise {requested.value} LLM ({exc}); using heuristic agents."
        logger.warning(note)
        return LLMHandle(requested, LLMProvider.HEURISTIC, settings.llm_model, None, note=note)

    logger.info("LLM backend ready: {}:{}", requested.value, settings.llm_model)
    return LLMHandle(requested, requested, settings.llm_model, crew_llm)
