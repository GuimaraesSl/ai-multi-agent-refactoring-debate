"""Performance agent — computational bottlenecks, hot paths and optimization.

Scope (Figure 1): Scalene, py-spy, cProfile (plus the shared AST for algorithmic
complexity). Its speed-first remedies (caching, memoization, parallelism)
intentionally create trade-offs against sustainability and architecture, which the
Judge must then arbitrate.
"""

from __future__ import annotations

from refactoring_debate.agents.base import SpecialistAgent
from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import MetricsReport, Severity
from refactoring_debate.debate.models import Dimension, Effort, Recommendation


class PerformanceAgent(SpecialistAgent):
    dimension = Dimension.PERFORMANCE
    name = "Performance Agent"
    id_prefix = "PER"
    tool_scope = {"scalene", "py-spy", "cprofile"}

    role = "Performance Engineering Specialist"
    goal = (
        "Find computational bottlenecks and hot paths and recommend optimizations — better "
        "algorithms and data structures, caching/memoization, and removal of redundant work — "
        "to minimize latency and CPU time."
    )
    backstory = (
        "You are obsessed with throughput and latency. You read profiles, spot quadratic loops "
        "and hot functions, and reach for caches, precomputation and vectorization. You push for "
        "speed, trusting the debate to temper your proposals against memory and maintainability."
    )

    def _heuristic_recommendations(
        self, ast_rep: ASTRepresentation, metrics: MetricsReport
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        seen: set[str] = set()
        idx = 1

        # 1. Algorithmic bottlenecks: nested loops imply superlinear time.
        for fn in sorted(ast_rep.functions, key=lambda f: f.max_loop_depth, reverse=True):
            if fn.max_loop_depth >= 2:
                seen.add(fn.qualname)
                recs.append(
                    self._rec(
                        idx,
                        title=f"Optimize quadratic hot path in `{fn.qualname}` (cache/precompute)",
                        target=fn.qualname,
                        line=fn.lineno,
                        severity=Severity.HIGH if fn.max_loop_depth >= 3 else Severity.MEDIUM,
                        effort=Effort.MEDIUM,
                        confidence=0.75,
                        rationale=(
                            f"`{fn.qualname}` nests loops {fn.max_loop_depth} deep (~O(n^"
                            f"{fn.max_loop_depth})). Memoizing repeated lookups, precomputing, or "
                            "switching to hash-based access removes the bottleneck."
                        ),
                        evidence=[f"AST: max_loop_depth={fn.max_loop_depth} in {fn.qualname}"],
                        tags=["nested-loop", "cache", "precompute", "hot-path", "algorithm"],
                    )
                )
                idx += 1
            if idx > 3:
                break

        # 2. Profiler-confirmed hot paths (cProfile / Scalene / py-spy).
        for tool_name in ("cprofile", "scalene", "py-spy"):
            tool = metrics.by_tool(tool_name)
            if not (tool and tool.available):
                continue
            for finding in tool.findings[:2]:
                key = finding.symbol or f"line:{finding.line}"
                if key in seen:
                    continue
                seen.add(key)
                recs.append(
                    self._rec(
                        idx,
                        title=f"Optimize hot path identified by {tool_name}: {finding.message[:55]}",
                        target=finding.symbol,
                        line=finding.line,
                        severity=finding.severity,
                        effort=Effort.MEDIUM,
                        confidence=0.7,
                        rationale=(
                            f"{tool_name} attributes a large share of runtime here; reducing this "
                            "call's cost (caching, batching, cheaper data structures) cuts latency."
                        ),
                        evidence=[finding.as_evidence()],
                        tags=["hot-path", "cache", "profiling", tool_name],
                    )
                )
                idx += 1

        # 3. Many calls inside loops -> overhead worth hoisting/caching.
        if not recs:
            for fn in ast_rep.functions:
                if fn.num_loops >= 1 and fn.num_calls >= 6:
                    recs.append(
                        self._rec(
                            idx,
                            title=f"Hoist/cache repeated calls in `{fn.qualname}`",
                            target=fn.qualname,
                            line=fn.lineno,
                            severity=Severity.LOW,
                            effort=Effort.LOW,
                            confidence=0.5,
                            rationale=(
                                f"`{fn.qualname}` makes {fn.num_calls} calls across {fn.num_loops} "
                                "loop(s); hoisting loop-invariant calls or caching results avoids "
                                "repeated work."
                            ),
                            evidence=[
                                f"AST: {fn.num_calls} calls / {fn.num_loops} loops in {fn.qualname}"
                            ],
                            tags=["loop-invariant", "cache", "micro-optimization"],
                        )
                    )
                    idx += 1
                    break

        return recs[:5]

    def _heuristic_summary(self, recs: list[Recommendation]) -> str:
        if not recs:
            return "No measurable performance bottlenecks found in the analyzed scope."
        return (
            f"Flagged {len(recs)} performance bottlenecks (quadratic loops and profiled hot paths) "
            "with caching/algorithmic optimizations to reduce CPU time and latency."
        )
