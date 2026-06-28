"""Specialist agents (CrewAI) + the Judge.

Each specialist analyzes *only the fraction of the unified metrics relevant to
its scope* (Figure 1) and proposes local refactorings. With an LLM backend the
reasoning is delegated to a CrewAI agent; without one (heuristic mode) the agent
applies deterministic, metric-grounded rules so the architecture still runs.
"""

from refactoring_debate.agents.architecture_agent import ArchitectureAgent
from refactoring_debate.agents.base import SpecialistAgent
from refactoring_debate.agents.judge_agent import JudgeAgent
from refactoring_debate.agents.performance_agent import PerformanceAgent
from refactoring_debate.agents.sustainability_agent import SustainabilityAgent

__all__ = [
    "SpecialistAgent",
    "SustainabilityAgent",
    "ArchitectureAgent",
    "PerformanceAgent",
    "JudgeAgent",
    "build_specialists",
]


def build_specialists(llm_handle) -> list[SpecialistAgent]:
    """Instantiate the three specialist agents in debate order."""
    return [
        SustainabilityAgent(llm_handle),
        ArchitectureAgent(llm_handle),
        PerformanceAgent(llm_handle),
    ]
