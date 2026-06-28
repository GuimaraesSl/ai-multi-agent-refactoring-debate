"""The peer-review debate protocol (paper §4.2, step 5).

Specialists cross-critique each other's proposals over one or more rounds; the
Judge then makes conflicts explicit, negotiates trade-offs and consolidates the
final, prioritized recommendations.
"""

from __future__ import annotations

from refactoring_debate.agents.base import SpecialistAgent
from refactoring_debate.agents.judge_agent import JudgeAgent
from refactoring_debate.debate.models import (
    AgentReport,
    ConsolidatedRecommendation,
    Critique,
    DebateRecord,
    DebateRound,
)


class DebateProtocol:
    """Coordinates the cross-critique rounds and the judge's arbitration."""

    def __init__(
        self, specialists: list[SpecialistAgent], judge: JudgeAgent, rounds: int
    ) -> None:
        self.specialists = specialists
        self.judge = judge
        self.rounds = rounds

    def run(
        self, reports: list[AgentReport]
    ) -> tuple[DebateRecord, list[ConsolidatedRecommendation]]:
        all_recs = [rec for report in reports for rec in report.recommendations]
        rec_by_id = {rec.id: rec for rec in all_recs}

        # --- peer-review rounds: each specialist critiques the others -------
        debate_rounds: list[DebateRound] = []
        all_critiques: list[Critique] = []
        for i in range(self.rounds):
            round_critiques: list[Critique] = []
            for specialist in self.specialists:
                round_critiques.extend(specialist.critique(all_recs))
            debate_rounds.append(DebateRound(index=i + 1, critiques=round_critiques))
            all_critiques.extend(round_critiques)

        # --- judge: conflicts -> trade-offs -> consolidation ---------------
        conflicts = self.judge.detect_conflicts(all_recs, all_critiques)
        tradeoffs, statuses = self.judge.arbitrate(conflicts, rec_by_id)
        consolidated = self.judge.consolidate(reports, statuses, rec_by_id)
        summary = self.judge.summarize(consolidated, conflicts, tradeoffs)

        record = DebateRecord(
            rounds=debate_rounds,
            conflicts=conflicts,
            tradeoffs=tradeoffs,
            judge_summary=summary,
        )
        return record, consolidated
