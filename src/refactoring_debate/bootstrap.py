"""Process bootstrap — environment hardening and logging setup.

``configure_environment`` must run *before* CrewAI / LiteLLM are imported so the
telemetry opt-out and quiet defaults take effect.
"""

from __future__ import annotations

import os
import sys
import warnings

from loguru import logger

_CONFIGURED = False


def configure_environment() -> None:
    """Opt out of third-party telemetry and silence noisy subsystems."""
    os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")  # chromadb
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")


def configure_logging(level: str = "INFO") -> None:
    """Route logging through loguru with a single concise sink."""
    global _CONFIGURED
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
            "<cyan>{name}</cyan> - <level>{message}</level>"
        ),
        colorize=True,
    )
    _CONFIGURED = True


def bootstrap(level: str = "INFO") -> None:
    configure_environment()
    if not _CONFIGURED:
        configure_logging(level)
