"""REST endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from refactoring_debate import __version__
from refactoring_debate.api.schemas import (
    AnalyzeRequest,
    ConfigResponse,
    HealthResponse,
    LLMStatus,
    ToolStatusItem,
)
from refactoring_debate.core.orchestrator import Orchestrator
from refactoring_debate.debate.models import AnalysisResult

router = APIRouter()


def _orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


@router.post(
    "/api/v1/analyze",
    response_model=AnalysisResult,
    summary="Run the multi-agent refactoring debate on a Python snippet",
    tags=["analysis"],
)
def analyze(req: AnalyzeRequest, request: Request) -> AnalysisResult:
    """Parse the code, extract metrics, run the specialist agents and the debate,
    and return the consolidated, prioritized recommendations with the full debate record.
    """
    orch = _orchestrator(request)
    return orch.analyze(
        req.code,
        filename=req.filename,
        debate_rounds=req.debate_rounds,
        enable_dynamic_analysis=req.enable_dynamic_analysis,
    )


@router.get(
    "/api/v1/runs/{request_id}",
    response_model=AnalysisResult,
    summary="Fetch a previously persisted analysis run",
    tags=["analysis"],
)
def get_run(request_id: str, request: Request) -> AnalysisResult:
    orch = _orchestrator(request)
    runs_dir = orch.settings.runs_dir
    if not runs_dir:
        raise HTTPException(status_code=404, detail="Run persistence is disabled (RD_RUNS_DIR unset)")
    path = Path(runs_dir) / f"{Path(request_id).name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No run found for id '{request_id}'")
    return AnalysisResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


@router.get("/health", response_model=HealthResponse, summary="Service health", tags=["meta"])
def health(request: Request) -> HealthResponse:
    orch = _orchestrator(request)
    return HealthResponse(
        version=__version__,
        llm=LLMStatus(
            requested_provider=orch.llm.requested_provider.value,
            effective_provider=orch.llm.effective_provider.value,
            label=orch.llm.label,
            uses_llm=orch.llm.uses_llm,
            note=orch.llm.note,
        ),
        tools=[ToolStatusItem(name=a.name, category=a.category.value) for a in orch.analyzers],
        dynamic_analysis_enabled=orch.settings.enable_dynamic_analysis,
        sonarqube_enabled=orch.settings.sonarqube_enabled,
    )


@router.get("/api/v1/config", response_model=ConfigResponse, summary="Effective config", tags=["meta"])
def config(request: Request) -> ConfigResponse:
    s = _orchestrator(request).settings
    return ConfigResponse(
        llm_provider=s.llm_provider.value,
        llm_model=s.llm_model,
        debate_rounds=s.debate_rounds,
        decision_weights=s.decision_weights,
        enable_dynamic_analysis=s.enable_dynamic_analysis,
        dynamic_timeout=s.dynamic_timeout,
        sonarqube_enabled=s.sonarqube_enabled,
        runs_dir=s.runs_dir,
    )
