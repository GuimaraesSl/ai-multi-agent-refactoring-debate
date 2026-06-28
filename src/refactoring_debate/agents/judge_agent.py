"""Judge (Debate) agent — mediates the peer review and consolidates the outcome.

It detects design conflicts, applies the project's configurable decision weights to
arbitrate trade-offs, and emits a prioritized, consolidated set of recommendations
(paper §4.1/§4.2, "Agente de Debate").
"""

from __future__ import annotations

import itertools

from loguru import logger

from refactoring_debate.debate.models import (
    AgentReport,
    Conflict,
    ConflictType,
    ConsolidatedRecommendation,
    Critique,
    Dimension,
    Recommendation,
    Stance,
    Status,
    Tradeoff,
)
from refactoring_debate.llm.provider import LLMHandle

# Speed-first remedies that trade memory/energy/complexity for latency.
_TRADEOFF_TAGS = {"cache", "caching", "memoize", "memoization", "parallel", "parallelism",
                  "precompute", "vectorize", "inline", "buffer", "preload"}

_PAIR_TYPE = {
    frozenset({Dimension.PERFORMANCE, Dimension.SUSTAINABILITY}):
        ConflictType.PERFORMANCE_VS_SUSTAINABILITY,
    frozenset({Dimension.PERFORMANCE, Dimension.ARCHITECTURE}):
        ConflictType.PERFORMANCE_VS_ARCHITECTURE,
    frozenset({Dimension.ARCHITECTURE, Dimension.SUSTAINABILITY}):
        ConflictType.ARCHITECTURE_VS_SUSTAINABILITY,
}


class JudgeAgent:
    dimension = Dimension.JUDGE
    name = "Debate Agent"

    role = "Debate Moderator and Decision Authority"
    goal = (
        "Mediate the peer review between specialists, make design conflicts explicit, negotiate "
        "trade-offs using the project's decision weights, and consolidate a prioritized set of "
        "refactoring recommendations."
    )
    backstory = (
        "You are an impartial senior reviewer. You never optimize a single dimension blindly; you "
        "weigh sustainability, architecture and performance against each other and justify every "
        "decision with evidence and the agreed priorities."
    )

    def __init__(self, llm: LLMHandle, weights: dict[str, float]) -> None:
        self.llm = llm
        self.weights = weights

    # -- conflict detection -------------------------------------------------
    def detect_conflicts(
        self, recommendations: list[Recommendation], critiques: list[Critique]
    ) -> list[Conflict]:
        rec_by_id = {r.id: r for r in recommendations}
        conflicts: list[Conflict] = []
        seen: set[tuple] = set()
        counter = itertools.count(1)

        def add(ctype: ConflictType, dims: set[Dimension], ids: list[str], desc: str) -> None:
            key = (ctype, tuple(sorted(d.value for d in dims)), tuple(sorted(ids)))
            if key in seen:
                return
            seen.add(key)
            conflicts.append(
                Conflict(
                    id=f"C{next(counter)}",
                    type=ctype,
                    description=desc,
                    dimensions=sorted(dims, key=lambda d: d.value),
                    recommendation_ids=sorted(ids),
                )
            )

        # 1. Two specialists touching the same target — overlap or tension.
        by_target: dict[str, list[Recommendation]] = {}
        for rec in recommendations:
            if rec.target:
                by_target.setdefault(rec.target.lower(), []).append(rec)
        for target, recs in by_target.items():
            dims = {r.dimension for r in recs}
            if len(dims) < 2:
                continue
            ids = [r.id for r in recs]
            has_tradeoff = any(_TRADEOFF_TAGS & set(r.tags) for r in recs)
            if has_tradeoff:
                pair = self._dominant_pair(dims)
                add(
                    _PAIR_TYPE.get(pair, ConflictType.DIRECT_CONTRADICTION),
                    dims,
                    ids,
                    f"Competing remedies for `{target}`: "
                    + "; ".join(f"{r.dimension.value} wants '{r.title}'" for r in recs),
                )
            else:
                add(
                    ConflictType.OVERLAP,
                    dims,
                    ids,
                    f"Multiple specialists ({', '.join(d.value for d in sorted(dims, key=lambda x: x.value))}) "
                    f"propose aligned changes to `{target}`.",
                )

        # 2. Conflicts grounded in the peer-review critiques.
        for crit in critiques:
            if crit.stance is Stance.SUPPORT:
                continue
            target_rec = rec_by_id.get(crit.target_recommendation_id)
            if not target_rec or target_rec.dimension == crit.from_dimension:
                continue
            dims = {crit.from_dimension, target_rec.dimension}
            pair = frozenset(dims)
            add(
                _PAIR_TYPE.get(pair, ConflictType.DIRECT_CONTRADICTION),
                dims,
                [target_rec.id],
                f"{crit.from_dimension.value} {crit.stance.value}s {target_rec.id} "
                f"('{target_rec.title}'): {crit.message}",
            )

        return conflicts

    # -- arbitration --------------------------------------------------------
    def arbitrate(
        self, conflicts: list[Conflict], rec_by_id: dict[str, Recommendation]
    ) -> tuple[list[Tradeoff], dict[str, Status]]:
        statuses: dict[str, Status] = dict.fromkeys(rec_by_id, Status.ACCEPTED)
        supersedes: dict[str, list[str]] = {}
        tradeoffs: list[Tradeoff] = []

        for conflict in conflicts:
            participants = [rec_by_id[i] for i in conflict.recommendation_ids if i in rec_by_id]
            if len(participants) < 2 and conflict.type is not ConflictType.OVERLAP:
                # critique-only conflict on a single rec: record the tension, no demotion
                continue
            if not participants:
                continue
            ranked = sorted(participants, key=self._claim_strength, reverse=True)
            primary = ranked[0]

            if conflict.type is ConflictType.OVERLAP:
                for other in ranked[1:]:
                    if statuses[other.id] is Status.ACCEPTED:
                        statuses[other.id] = Status.MERGED
                        supersedes.setdefault(primary.id, []).append(other.id)
            else:
                favored = primary.dimension
                sacrificed = []
                for other in ranked[1:]:
                    if other.dimension != favored and statuses[other.id] is Status.ACCEPTED:
                        statuses[other.id] = Status.DEFERRED
                        sacrificed.append(other.dimension)
                if sacrificed:
                    tradeoffs.append(
                        Tradeoff(
                            description=conflict.description,
                            favored=favored,
                            sacrificed=sorted(set(sacrificed), key=lambda d: d.value),
                            rationale=(
                                f"Favored {favored.value} (weight {self.weights.get(favored.value, 0):.2f}) "
                                f"on `{primary.target or primary.id}`: higher weighted severity×confidence "
                                "than the competing proposals."
                            ),
                            weights=self.weights,
                        )
                    )

        self._supersedes = supersedes  # consumed by consolidate()
        return tradeoffs, statuses

    # -- consolidation ------------------------------------------------------
    def consolidate(
        self,
        reports: list[AgentReport],
        statuses: dict[str, Status],
        rec_by_id: dict[str, Recommendation],
    ) -> list[ConsolidatedRecommendation]:
        supersedes = getattr(self, "_supersedes", {})
        status_rank = {Status.ACCEPTED: 0, Status.MERGED: 1, Status.DEFERRED: 2, Status.REJECTED: 3}

        scored: list[tuple[float, Recommendation]] = []
        for rec in rec_by_id.values():
            scored.append((self._claim_strength(rec), rec))
        scored.sort(key=lambda pair: (status_rank[statuses[pair[1].id]], -pair[0]))

        consolidated: list[ConsolidatedRecommendation] = []
        for priority, (score, rec) in enumerate(scored, start=1):
            status = statuses[rec.id]
            consolidated.append(
                ConsolidatedRecommendation(
                    **rec.model_dump(),
                    priority=priority,
                    status=status,
                    supersedes=supersedes.get(rec.id, []),
                    judge_rationale=self._rationale(rec, status, score, supersedes.get(rec.id, [])),
                )
            )
        return consolidated

    # -- summary ------------------------------------------------------------
    def summarize(
        self,
        consolidated: list[ConsolidatedRecommendation],
        conflicts: list[Conflict],
        tradeoffs: list[Tradeoff],
    ) -> str:
        if self.llm.uses_llm:
            try:
                return self._llm_summary(consolidated, conflicts, tradeoffs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Judge LLM summary failed ({}); using heuristic.", exc)
        accepted = [c for c in consolidated if c.status in (Status.ACCEPTED, Status.MERGED)]
        top = "; ".join(f"[{c.priority}] {c.title}" for c in accepted[:3])
        return (
            f"Consolidated {len(accepted)} recommendations across "
            f"{len({c.dimension for c in accepted})} quality dimensions after weighing "
            f"{len(conflicts)} conflict(s) and {len(tradeoffs)} trade-off(s). "
            f"Top priorities: {top or 'none'}."
        )

    def _llm_summary(
        self,
        consolidated: list[ConsolidatedRecommendation],
        conflicts: list[Conflict],
        tradeoffs: list[Tradeoff],
    ) -> str:
        import json

        from crewai import Agent, Crew, Process, Task

        payload = {
            "weights": self.weights,
            "recommendations": [
                {"id": c.id, "dimension": c.dimension.value, "title": c.title,
                 "priority": c.priority, "status": c.status.value}
                for c in consolidated
            ],
            "conflicts": [{"type": c.type.value, "description": c.description} for c in conflicts],
            "tradeoffs": [{"favored": t.favored.value, "rationale": t.rationale} for t in tradeoffs],
        }
        agent = Agent(role=self.role, goal=self.goal, backstory=self.backstory,
                      llm=self.llm.crew_llm, allow_delegation=False, verbose=False, max_iter=2)
        task = Task(
            description=(
                "Write a concise (3-5 sentence) executive summary of this consolidated refactoring "
                "review. Explain the main conflicts and how the decision weights resolved the "
                "trade-offs. Do not list every item.\n\n" + json.dumps(payload, indent=2)
            ),
            expected_output="A short plain-text executive summary.",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        return (getattr(crew.kickoff(), "raw", None) or "").strip()

    # -- scoring helpers ----------------------------------------------------
    def _claim_strength(self, rec: Recommendation) -> float:
        weight = self.weights.get(rec.dimension.value, 0.33)
        return weight * (rec.severity.rank + 1) * (0.5 + rec.confidence)

    def _dominant_pair(self, dims: set[Dimension]) -> frozenset:
        ordered = sorted(dims, key=lambda d: self.weights.get(d.value, 0), reverse=True)
        return frozenset(ordered[:2])

    def _rationale(
        self, rec: Recommendation, status: Status, score: float, merged: list[str]
    ) -> str:
        if status is Status.DEFERRED:
            return (
                "Deferred: a higher-weighted dimension took precedence on the same code; revisit if "
                "priorities change."
            )
        if status is Status.MERGED:
            return "Merged into a higher-priority overlapping recommendation on the same target."
        base = (
            f"Accepted (weighted score {score:.2f}; {rec.dimension.value} weight "
            f"{self.weights.get(rec.dimension.value, 0):.2f}, severity {rec.severity.value})."
        )
        if merged:
            base += f" Subsumes {', '.join(merged)}."
        return base
