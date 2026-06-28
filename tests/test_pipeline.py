"""End-to-end pipeline tests (heuristic mode)."""

from __future__ import annotations

from refactoring_debate.core.orchestrator import Orchestrator
from refactoring_debate.debate.models import Dimension, Status


def test_three_specialists_produce_recommendations(
    orchestrator: Orchestrator, sample_code: str
) -> None:
    result = orchestrator.analyze(sample_code, "sample.py")
    dims = {r.dimension for r in result.agent_reports}
    assert dims == {Dimension.SUSTAINABILITY, Dimension.ARCHITECTURE, Dimension.PERFORMANCE}
    assert all(r.recommendations for r in result.agent_reports)


def test_conflicts_and_tradeoffs_emerge(orchestrator: Orchestrator, sample_code: str) -> None:
    result = orchestrator.analyze(sample_code, "sample.py")
    # the quadratic find_duplicates is tackled by both performance and sustainability
    assert result.debate.conflicts, "expected at least one design conflict (Q3)"
    assert result.debate.tradeoffs, "expected the judge to negotiate a trade-off"


def test_consolidation_defers_losing_side(orchestrator: Orchestrator, sample_code: str) -> None:
    result = orchestrator.analyze(sample_code, "sample.py")
    statuses = {r.status for r in result.consolidated}
    assert Status.ACCEPTED in statuses
    assert Status.DEFERRED in statuses  # a trade-off must demote something
    # priorities are unique and contiguous
    priorities = sorted(r.priority for r in result.consolidated)
    assert priorities == list(range(1, len(priorities) + 1))


def test_research_metrics_cover_three_attributes(
    orchestrator: Orchestrator, sample_code: str
) -> None:
    result = orchestrator.analyze(sample_code, "sample.py")
    rm = result.research_metrics
    assert rm.distinct_recommendations == len(result.consolidated)  # Q1
    assert rm.quality_attributes_covered == 3  # Q2
    assert rm.conflicts_detected == len(result.debate.conflicts)  # Q3


def test_per_request_round_override(orchestrator: Orchestrator, sample_code: str) -> None:
    zero = orchestrator.analyze(sample_code, "s.py", debate_rounds=0)
    assert zero.debate.all_critiques == []
    # conflicts can still arise from target overlap even with no critique rounds
    assert zero.consolidated


def test_syntax_error_does_not_crash_pipeline(orchestrator: Orchestrator) -> None:
    result = orchestrator.analyze("def broken(:\n  pass\n", "bad.py")
    assert result.ast.syntax_ok is False
    assert result.ast.syntax_error is not None
