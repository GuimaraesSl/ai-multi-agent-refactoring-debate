"""Base class for the specialist agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from refactoring_debate.agents.prompts import (
    ANALYZE_INSTRUCTIONS,
    CRITIQUE_INSTRUCTIONS,
    extract_json,
    render_context,
    render_recommendations,
)
from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import MetricsReport, Severity
from refactoring_debate.debate.models import (
    AgentReport,
    Critique,
    Dimension,
    Effort,
    Recommendation,
    Stance,
)
from refactoring_debate.llm.provider import LLMHandle

# Keywords that signal a proposal from another dimension may hurt *this* dimension.
# Used for deterministic peer-review critiques when no LLM is available.
_CONCERN_KEYWORDS: dict[Dimension, set[str]] = {
    Dimension.SUSTAINABILITY: {
        "cache", "caching", "memoize", "memoization", "parallel", "parallelism",
        "thread", "multiprocess", "precompute", "buffer", "in-memory", "preload",
    },
    Dimension.ARCHITECTURE: {
        "cache", "parallel", "inline", "micro-optimization", "unroll", "global",
        "manual", "low-level", "bit-twiddle",
    },
    Dimension.PERFORMANCE: {
        "decouple", "abstraction", "indirection", "layer", "wrapper", "validation",
        "logging", "interface", "dependency-injection", "dataclass",
    },
}
# Keywords where a proposal *helps* this dimension too (so we support it).
_SUPPORT_KEYWORDS: dict[Dimension, set[str]] = {
    Dimension.SUSTAINABILITY: {"nested-loop", "complexity", "algorithm", "o(n^2)", "hot-path"},
    Dimension.ARCHITECTURE: {"extract", "split", "cohesion", "docstring", "readability", "naming"},
    Dimension.PERFORMANCE: {"nested-loop", "algorithm", "o(n^2)", "vectorize", "hot-path"},
}


class SpecialistAgent(ABC):
    """One specialist perspective in the debate."""

    dimension: Dimension
    name: str
    role: str
    goal: str
    backstory: str
    id_prefix: str
    tool_scope: set[str]

    def __init__(self, llm: LLMHandle) -> None:
        self.llm = llm
        self._agent: Any | None = None

    # -- public API ---------------------------------------------------------
    def analyze(self, ast_rep: ASTRepresentation, metrics: MetricsReport) -> AgentReport:
        """Produce the specialist's local recommendations (paper §4.2, step 4)."""
        scoped = metrics.slice(self.tool_scope)
        if self.llm.uses_llm:
            try:
                return self._llm_analyze(ast_rep, scoped)
            except Exception as exc:  # noqa: BLE001
                logger.warning("{} LLM analysis failed ({}); using heuristic.", self.name, exc)

        recs = self._heuristic_recommendations(ast_rep, metrics)
        return AgentReport(
            agent=self.name,
            dimension=self.dimension,
            summary=self._heuristic_summary(recs),
            recommendations=recs,
            model=self.llm.label,
        )

    def critique(self, others: list[Recommendation]) -> list[Critique]:
        """Peer-review the *other* specialists' proposals."""
        targets = [r for r in others if r.dimension != self.dimension]
        if not targets:
            return []
        if self.llm.uses_llm:
            try:
                return self._llm_critique(targets)
            except Exception as exc:  # noqa: BLE001
                logger.warning("{} LLM critique failed ({}); using heuristic.", self.name, exc)
        return self._heuristic_critique(targets)

    # -- LLM path -----------------------------------------------------------
    def _llm_analyze(self, ast_rep: ASTRepresentation, scoped: dict) -> AgentReport:
        description = f"{ANALYZE_INSTRUCTIONS}\n\n{render_context(ast_rep, scoped)}"
        raw = self._run_task(description, "A single JSON object with summary and recommendations.")
        data = extract_json(raw) or {}
        recs = self._parse_recommendations(data.get("recommendations", []))
        summary = data.get("summary") or self._heuristic_summary(recs)
        return AgentReport(
            agent=self.name,
            dimension=self.dimension,
            summary=summary,
            recommendations=recs,
            model=self.llm.label,
            raw_output=raw,
        )

    def _llm_critique(self, targets: list[Recommendation]) -> list[Critique]:
        payload = [
            {"id": r.id, "dimension": r.dimension.value, "title": r.title, "tags": r.tags}
            for r in targets
        ]
        description = (
            f"{CRITIQUE_INSTRUCTIONS}\n\n## Proposals to review\n"
            + render_recommendations(payload)
        )
        raw = self._run_task(description, "A single JSON object with critiques.")
        data = extract_json(raw) or {}
        valid_ids = {r.id for r in targets}
        out: list[Critique] = []
        for item in data.get("critiques", []) or []:
            tid = item.get("target_id")
            if tid not in valid_ids:
                continue
            out.append(
                Critique(
                    from_dimension=self.dimension,
                    target_recommendation_id=tid,
                    stance=_coerce_stance(item.get("stance")),
                    message=str(item.get("message", "")).strip(),
                )
            )
        return out

    def _run_task(self, description: str, expected_output: str) -> str:
        from crewai import Agent, Crew, Process, Task

        if self._agent is None:
            self._agent = Agent(
                role=self.role,
                goal=self.goal,
                backstory=self.backstory,
                llm=self.llm.crew_llm,
                allow_delegation=False,
                verbose=False,
                max_iter=3,
            )
        task = Task(description=description, expected_output=expected_output, agent=self._agent)
        crew = Crew(
            agents=[self._agent], tasks=[task], process=Process.sequential, verbose=False
        )
        output = crew.kickoff()
        return getattr(output, "raw", None) or str(output)

    def _parse_recommendations(self, items: list[dict]) -> list[Recommendation]:
        recs: list[Recommendation] = []
        for i, item in enumerate(items[:5], start=1):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            recs.append(
                Recommendation(
                    id=f"{self.id_prefix}-{i}",
                    dimension=self.dimension,
                    title=str(item["title"]).strip(),
                    rationale=str(item.get("rationale", "")).strip(),
                    target=item.get("target") or None,
                    line=_coerce_int(item.get("line")),
                    severity=_coerce_severity(item.get("severity")),
                    effort=_coerce_effort(item.get("effort")),
                    confidence=_coerce_float(item.get("confidence"), 0.6),
                    evidence=[str(e) for e in (item.get("evidence") or [])][:6],
                    tags=[str(t).lower() for t in (item.get("tags") or [])][:6],
                )
            )
        return recs

    # -- heuristic path (subclass responsibilities) -------------------------
    @abstractmethod
    def _heuristic_recommendations(
        self, ast_rep: ASTRepresentation, metrics: MetricsReport
    ) -> list[Recommendation]:
        ...

    @abstractmethod
    def _heuristic_summary(self, recs: list[Recommendation]) -> str:
        ...

    def _heuristic_critique(self, targets: list[Recommendation]) -> list[Critique]:
        """Deterministic peer review based on tag/keyword tension between dimensions."""
        concerns = _CONCERN_KEYWORDS[self.dimension]
        supports = _SUPPORT_KEYWORDS[self.dimension]
        out: list[Critique] = []
        for rec in targets:
            haystack = {*rec.tags, *rec.title.lower().split()}
            if concerns & haystack:
                out.append(
                    Critique(
                        from_dimension=self.dimension,
                        target_recommendation_id=rec.id,
                        stance=Stance.CONCERN,
                        message=self._concern_message(rec),
                    )
                )
            elif supports & haystack:
                out.append(
                    Critique(
                        from_dimension=self.dimension,
                        target_recommendation_id=rec.id,
                        stance=Stance.SUPPORT,
                        message=(
                            f"From a {self.dimension.value} standpoint this also helps: "
                            "simplifying this structure reduces cost in my dimension too."
                        ),
                    )
                )
        return out

    def _concern_message(self, rec: Recommendation) -> str:
        reasons = {
            Dimension.SUSTAINABILITY: "this trades memory/energy for speed and may raise the footprint",
            Dimension.ARCHITECTURE: "this risks added complexity and reduced readability/maintainability",
            Dimension.PERFORMANCE: "this adds indirection/overhead that can slow the hot path",
        }
        return f"As {self.dimension.value} specialist, {reasons[self.dimension]}."

    # convenience for heuristic rules --------------------------------------
    def _rec(self, idx: int, **kwargs) -> Recommendation:
        kwargs.setdefault("dimension", self.dimension)
        return Recommendation(id=f"{self.id_prefix}-{idx}", **kwargs)


# --- tolerant coercion helpers -------------------------------------------- #
def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _coerce_severity(value: Any) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError:
        return Severity.MEDIUM


def _coerce_effort(value: Any) -> Effort:
    try:
        return Effort(str(value).lower())
    except ValueError:
        return Effort.MEDIUM


def _coerce_stance(value: Any) -> Stance:
    try:
        return Stance(str(value).lower())
    except ValueError:
        return Stance.CONCERN
