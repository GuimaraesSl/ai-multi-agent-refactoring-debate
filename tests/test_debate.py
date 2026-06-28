"""Unit tests for the Judge's conflict detection and arbitration."""

from __future__ import annotations

import pytest

from refactoring_debate.agents.judge_agent import JudgeAgent
from refactoring_debate.config import Settings
from refactoring_debate.debate.models import (
    ConflictType,
    Dimension,
    Recommendation,
    Severity,
    Status,
)
from refactoring_debate.llm.provider import build_llm


@pytest.fixture()
def judge() -> JudgeAgent:
    settings = Settings()  # heuristic via conftest env
    return JudgeAgent(build_llm(settings), settings.decision_weights)


def _rec(rid: str, dim: Dimension, target: str, tags: list[str], sev=Severity.MEDIUM) -> Recommendation:
    return Recommendation(id=rid, dimension=dim, title=f"{dim.value} on {target}",
                          target=target, severity=sev, tags=tags, confidence=0.7)


def test_detects_performance_vs_sustainability(judge: JudgeAgent) -> None:
    recs = [
        _rec("PER-1", Dimension.PERFORMANCE, "f", ["cache", "nested-loop"]),
        _rec("SUS-1", Dimension.SUSTAINABILITY, "f", ["nested-loop", "green-smell"]),
    ]
    conflicts = judge.detect_conflicts(recs, [])
    assert any(c.type is ConflictType.PERFORMANCE_VS_SUSTAINABILITY for c in conflicts)


def test_overlap_without_tradeoff_tags_is_overlap(judge: JudgeAgent) -> None:
    recs = [
        _rec("ARC-1", Dimension.ARCHITECTURE, "g", ["extract"]),
        _rec("SUS-1", Dimension.SUSTAINABILITY, "g", ["complexity"]),
    ]
    conflicts = judge.detect_conflicts(recs, [])
    assert conflicts and conflicts[0].type is ConflictType.OVERLAP


def test_arbitration_defers_lower_weighted_dimension(judge: JudgeAgent) -> None:
    recs = [
        _rec("PER-1", Dimension.PERFORMANCE, "f", ["cache"]),
        _rec("SUS-1", Dimension.SUSTAINABILITY, "f", ["green-smell"]),
    ]
    rec_by_id = {r.id: r for r in recs}
    conflicts = judge.detect_conflicts(recs, [])
    tradeoffs, statuses = judge.arbitrate(conflicts, rec_by_id)
    # sustainability has the highest default weight, so performance is deferred
    assert statuses["SUS-1"] is Status.ACCEPTED
    assert statuses["PER-1"] is Status.DEFERRED
    assert tradeoffs and tradeoffs[0].favored is Dimension.SUSTAINABILITY


def test_overlap_merges_lower_priority(judge: JudgeAgent) -> None:
    recs = [
        _rec("ARC-1", Dimension.ARCHITECTURE, "g", ["extract"], sev=Severity.HIGH),
        _rec("SUS-1", Dimension.SUSTAINABILITY, "g", ["complexity"], sev=Severity.LOW),
    ]
    rec_by_id = {r.id: r for r in recs}
    conflicts = judge.detect_conflicts(recs, [])
    _, statuses = judge.arbitrate(conflicts, rec_by_id)
    assert Status.MERGED in statuses.values()


def test_weights_change_the_winner() -> None:
    settings = Settings(weight_performance=0.9, weight_sustainability=0.05, weight_architecture=0.05)
    judge = JudgeAgent(build_llm(settings), settings.decision_weights)
    recs = [
        _rec("PER-1", Dimension.PERFORMANCE, "f", ["cache"]),
        _rec("SUS-1", Dimension.SUSTAINABILITY, "f", ["green-smell"]),
    ]
    rec_by_id = {r.id: r for r in recs}
    conflicts = judge.detect_conflicts(recs, [])
    _, statuses = judge.arbitrate(conflicts, rec_by_id)
    # now performance dominates
    assert statuses["PER-1"] is Status.ACCEPTED
    assert statuses["SUS-1"] is Status.DEFERRED
