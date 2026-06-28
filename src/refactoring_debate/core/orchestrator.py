"""Pipeline orchestrator — the conductor of the whole flow (paper §4.2).

    code -> AST -> tools layer (metrics) -> specialist agents -> debate -> consolidated result

It owns the tools layer and the LLM-backed agents, routes the scoped metrics to each
specialist, runs the debate, and assembles the :class:`AnalysisResult`.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

from loguru import logger

from refactoring_debate.agents import build_specialists
from refactoring_debate.agents.judge_agent import JudgeAgent
from refactoring_debate.config import Settings, get_settings
from refactoring_debate.core.ast_parser import ASTRepresentation, parse_code
from refactoring_debate.core.metrics import MetricsReport
from refactoring_debate.debate.models import AgentReport, AnalysisResult, Timings
from refactoring_debate.debate.protocol import DebateProtocol
from refactoring_debate.llm.provider import LLMHandle, build_llm
from refactoring_debate.tools.base import AnalysisContext
from refactoring_debate.tools.registry import build_default_analyzers


class Orchestrator:
    """Coordinates parsing, the tools layer, the agents and the debate."""

    def __init__(self, settings: Settings | None = None, llm: LLMHandle | None = None) -> None:
        self.settings = settings or get_settings()
        self.analyzers = build_default_analyzers()
        # Resolve the LLM backend once (probes Ollama, may degrade to heuristic).
        self.llm = llm or build_llm(self.settings)

    # -- public API ---------------------------------------------------------
    def analyze(
        self,
        code: str,
        filename: str = "submitted.py",
        request_id: str | None = None,
        *,
        debate_rounds: int | None = None,
        enable_dynamic_analysis: bool | None = None,
    ) -> AnalysisResult:
        request_id = request_id or uuid.uuid4().hex[:12]
        settings = self._effective_settings(debate_rounds, enable_dynamic_analysis)
        t0 = time.perf_counter()
        timings = Timings()

        # 1. Parse into an AST representation.
        t = time.perf_counter()
        ast_rep = parse_code(code, filename)
        timings.parse_ms = _ms(t)

        # 2. Tools layer — deterministic metric extraction.
        t = time.perf_counter()
        metrics = self._run_tools(code, filename, ast_rep, settings)
        timings.tools_ms = _ms(t)

        # 3. Specialist agents — local recommendations from scoped metrics.
        specialists = build_specialists(self.llm)
        judge = JudgeAgent(self.llm, settings.decision_weights)
        t = time.perf_counter()
        reports: list[AgentReport] = [s.analyze(ast_rep, metrics) for s in specialists]
        timings.agents_ms = _ms(t)

        # 4. Peer-review debate + judge consolidation.
        t = time.perf_counter()
        protocol = DebateProtocol(specialists, judge, settings.debate_rounds)
        debate_record, consolidated = protocol.run(reports)
        timings.debate_ms = _ms(t)
        timings.total_ms = _ms(t0)

        result = AnalysisResult(
            request_id=request_id,
            filename=filename,
            llm_provider=self.llm.effective_provider.value,
            llm_model=self.llm.label,
            ast=ast_rep,
            metrics=metrics,
            agent_reports=reports,
            debate=debate_record,
            consolidated=consolidated,
            summary=debate_record.judge_summary,
            timings=timings,
        )
        result.compute_research_metrics()
        self._persist(result)
        logger.info(
            "Analyzed {} [{}]: {} recs, {} conflicts, {:.0f}ms ({})",
            filename,
            request_id,
            len(consolidated),
            len(debate_record.conflicts),
            timings.total_ms,
            self.llm.label,
        )
        return result

    def collect_metrics(
        self,
        code: str,
        filename: str = "submitted.py",
        *,
        enable_dynamic_analysis: bool | None = None,
    ) -> tuple[ASTRepresentation, MetricsReport]:
        """Parse + run the tools layer only (no agents, no debate).

        Reused by the single-agent evaluation baseline and for before/after metric
        snapshots when assessing applied refactorings (paper §4.3, indicator v).
        """
        settings = self._effective_settings(None, enable_dynamic_analysis)
        ast_rep = parse_code(code, filename)
        metrics = self._run_tools(code, filename, ast_rep, settings)
        return ast_rep, metrics

    # -- internals ----------------------------------------------------------
    def _effective_settings(
        self, debate_rounds: int | None, enable_dynamic_analysis: bool | None
    ) -> Settings:
        overrides = {}
        if debate_rounds is not None:
            overrides["debate_rounds"] = max(0, min(5, debate_rounds))
        if enable_dynamic_analysis is not None:
            overrides["enable_dynamic_analysis"] = enable_dynamic_analysis
        return self.settings.model_copy(update=overrides) if overrides else self.settings

    def _run_tools(
        self, code: str, filename: str, ast_rep, settings: Settings
    ) -> MetricsReport:
        workdir = Path(tempfile.mkdtemp(prefix="rd-"))
        safe_name = (Path(filename).stem or "submitted") + ".py"
        file_path = workdir / safe_name
        try:
            file_path.write_text(code, encoding="utf-8")
            ctx = AnalysisContext(
                code=code,
                filename=filename,
                workdir=workdir,
                file_path=file_path,
                ast=ast_rep,
                settings=settings,
            )
            report = MetricsReport()
            for analyzer in self.analyzers:
                report.results.append(analyzer.run(ctx))
            return report
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _persist(self, result: AnalysisResult) -> None:
        if not self.settings.runs_dir:
            return
        runs_dir = Path(self.settings.runs_dir)
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{result.request_id}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 2)
