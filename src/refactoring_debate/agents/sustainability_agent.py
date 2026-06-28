"""Software Sustainability agent — energy impact & resource efficiency (green smells).

Scope (Figure 1): Radon, Scalene, CodeCarbon.
"""

from __future__ import annotations

from refactoring_debate.agents.base import SpecialistAgent
from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import MetricsReport, Severity
from refactoring_debate.debate.models import Dimension, Effort, Recommendation


class SustainabilityAgent(SpecialistAgent):
    dimension = Dimension.SUSTAINABILITY
    name = "Software Sustainability Agent"
    id_prefix = "SUS"
    tool_scope = {"radon", "scalene", "codecarbon"}

    role = "Software Sustainability Specialist"
    goal = (
        "Identify green smells and resource waste — wasted CPU cycles, persistent memory "
        "allocations and energy-intensive patterns — and recommend refactorings that lower "
        "the long-term resource and carbon footprint without breaking behaviour."
    )
    backstory = (
        "You assess code through the lens of sustainability and energy efficiency. You know "
        "that superlinear loops, redundant computation and needless allocations translate "
        "directly into wasted energy, and you weigh every optimization against its footprint."
    )

    def _heuristic_recommendations(
        self, ast_rep: ASTRepresentation, metrics: MetricsReport
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        seen_targets: set[str] = set()
        idx = 1

        # 1. Nested loops are the strongest green smell (superlinear CPU/energy).
        for fn in sorted(ast_rep.functions, key=lambda f: f.max_loop_depth, reverse=True):
            if fn.max_loop_depth >= 2 and fn.qualname not in seen_targets:
                seen_targets.add(fn.qualname)
                recs.append(
                    self._rec(
                        idx,
                        title=f"Eliminate nested loops in `{fn.qualname}` to cut wasted CPU/energy",
                        target=fn.qualname,
                        line=fn.lineno,
                        severity=Severity.HIGH if fn.max_loop_depth >= 3 else Severity.MEDIUM,
                        effort=Effort.MEDIUM,
                        confidence=0.75,
                        rationale=(
                            f"`{fn.qualname}` nests loops {fn.max_loop_depth} deep, implying "
                            "superlinear work; each redundant iteration consumes energy. A better "
                            "algorithm or data structure (set/dict lookup, precomputation) reduces it."
                        ),
                        evidence=[f"AST: max_loop_depth={fn.max_loop_depth} in {fn.qualname}"],
                        tags=["nested-loop", "algorithm", "green-smell", "hot-path"],
                    )
                )
                idx += 1
            if len(recs) >= 3:
                break

        # 2. Scalene CPU / memory hotspots = energy hotspots.
        scalene = metrics.by_tool("scalene")
        if scalene and scalene.available:
            for finding in scalene.findings[:2]:
                recs.append(
                    self._rec(
                        idx,
                        title=f"Reduce {finding.metric} hotspot near line {finding.line}",
                        line=finding.line,
                        severity=finding.severity,
                        effort=Effort.MEDIUM,
                        confidence=0.65,
                        rationale=(
                            "Scalene attributes a disproportionate share of runtime resources here; "
                            "trimming it directly lowers energy use."
                        ),
                        evidence=[finding.as_evidence()],
                        tags=["green-smell", "hotspot", finding.metric or "cpu"],
                    )
                )
                idx += 1

        # 3. High complexity → harder to run efficiently and to optimize.
        radon = metrics.by_tool("radon")
        if radon and radon.available:
            for finding in radon.findings:
                if finding.metric == "cyclomatic_complexity" and finding.symbol not in seen_targets:
                    seen_targets.add(finding.symbol or "")
                    recs.append(
                        self._rec(
                            idx,
                            title=f"Simplify `{finding.symbol}` to remove redundant computation",
                            target=finding.symbol,
                            line=finding.line,
                            severity=Severity.LOW,
                            effort=Effort.MEDIUM,
                            confidence=0.5,
                            rationale=(
                                "High cyclomatic complexity often hides repeated or dead computation "
                                "that wastes cycles; simplifying improves energy efficiency."
                            ),
                            evidence=[finding.as_evidence()],
                            tags=["complexity", "green-smell"],
                        )
                    )
                    idx += 1
                    break

        # 4. Surface the measured footprint as a sustainability baseline.
        codecarbon = metrics.by_tool("codecarbon")
        if codecarbon and codecarbon.available and codecarbon.metrics.get("energy_wh", 0):
            energy = codecarbon.metrics["energy_wh"]
            recs.append(
                self._rec(
                    idx,
                    title="Track and reduce the measured energy footprint of hot paths",
                    severity=Severity.INFO,
                    effort=Effort.LOW,
                    confidence=0.6,
                    rationale=(
                        f"CodeCarbon measured ~{energy:.3f} Wh for this run; use it as a baseline "
                        "and verify refactorings actually reduce it."
                    ),
                    evidence=[codecarbon.summary],
                    tags=["energy", "measurement"],
                )
            )
            idx += 1

        return recs[:5]

    def _heuristic_summary(self, recs: list[Recommendation]) -> str:
        if not recs:
            return "No significant green smells detected in the analyzed scope."
        green = sum(1 for r in recs if "green-smell" in r.tags)
        return (
            f"Found {len(recs)} sustainability opportunities ({green} green smells), focused on "
            "removing superlinear loops and resource hotspots to lower the energy footprint."
        )
