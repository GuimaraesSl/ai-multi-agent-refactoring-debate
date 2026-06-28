"""FastAPI application entrypoint.

Run with::

    uv run uvicorn refactoring_debate.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

# Harden the environment BEFORE crewai/litellm get imported anywhere.
from refactoring_debate.bootstrap import bootstrap

bootstrap()

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from loguru import logger  # noqa: E402

from refactoring_debate import __version__  # noqa: E402
from refactoring_debate.api.routes import router  # noqa: E402
from refactoring_debate.bootstrap import configure_logging  # noqa: E402
from refactoring_debate.config import get_settings  # noqa: E402
from refactoring_debate.core.orchestrator import Orchestrator  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Multi-Agent Refactoring Debate API v{}", __version__)
    # Build the orchestrator once (probes the LLM backend, may degrade to heuristic).
    app.state.orchestrator = Orchestrator(settings)
    logger.info("LLM backend: {} | dynamic analysis: {}",
                app.state.orchestrator.llm.label, settings.enable_dynamic_analysis)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Multi-Agent Refactoring Debate",
    description=(
        "Refactoring recommendations for Python code via a peer-review-inspired debate "
        "between LLM-based specialist agents (Sustainability, Architecture, Performance) "
        "mediated by a Judge agent."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/docs")
