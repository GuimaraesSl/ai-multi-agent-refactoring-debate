"""Radon — structural metrics: cyclomatic complexity, maintainability index,
Halstead, and raw line counts. Pure-Python, always available.
"""

from __future__ import annotations

from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze

from refactoring_debate.core.metrics import (
    Finding,
    Severity,
    ToolCategory,
    ToolResult,
    ToolStatus,
)
from refactoring_debate.tools.base import AnalysisContext, Analyzer


def _complexity_severity(cc: int) -> Severity | None:
    if cc > 30:
        return Severity.CRITICAL
    if cc > 20:
        return Severity.HIGH
    if cc > 10:
        return Severity.MEDIUM
    return None


class RadonAnalyzer(Analyzer):
    name = "radon"
    category = ToolCategory.STATIC

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        code = ctx.code
        findings: list[Finding] = []

        # --- cyclomatic complexity per block --------------------------------
        blocks = cc_visit(code)
        complexity_map = {}
        for block in blocks:
            name = getattr(block, "classname", None)
            qual = f"{name}.{block.name}" if name else block.name
            complexity_map[qual] = block.complexity
            sev = _complexity_severity(block.complexity)
            if sev is not None:
                findings.append(
                    Finding(
                        tool=self.name,
                        category=self.category,
                        severity=sev,
                        message=(
                            f"High cyclomatic complexity ({block.complexity}); "
                            "consider extracting methods or simplifying control flow"
                        ),
                        symbol=qual,
                        line=block.lineno,
                        end_line=getattr(block, "endline", None),
                        metric="cyclomatic_complexity",
                        value=float(block.complexity),
                        rule="radon-cc",
                    )
                )

        # --- maintainability index ------------------------------------------
        mi = mi_visit(code, multi=True)
        if mi < 20:
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.HIGH if mi < 10 else Severity.MEDIUM,
                    message=(
                        f"Low maintainability index ({mi:.1f}/100); the module is hard "
                        "to maintain and is a strong refactoring candidate"
                    ),
                    metric="maintainability_index",
                    value=round(mi, 2),
                    rule="radon-mi",
                )
            )

        # --- raw line counts ------------------------------------------------
        raw = analyze(code)

        # --- Halstead volume/effort -----------------------------------------
        halstead = h_visit(code)
        h_total = halstead.total
        metrics = {
            "maintainability_index": round(mi, 2),
            "raw": {
                "loc": raw.loc,
                "lloc": raw.lloc,
                "sloc": raw.sloc,
                "comments": raw.comments,
                "blank": raw.blank,
                "comment_ratio": round(raw.comments / raw.sloc, 3) if raw.sloc else 0.0,
            },
            "halstead": {
                "volume": round(h_total.volume, 2),
                "difficulty": round(h_total.difficulty, 2),
                "effort": round(h_total.effort, 2),
                "bugs": round(h_total.bugs, 4),
            },
            "cyclomatic_complexity": complexity_map,
            "max_cyclomatic_complexity": max(complexity_map.values(), default=0),
            "avg_cyclomatic_complexity": (
                round(sum(complexity_map.values()) / len(complexity_map), 2)
                if complexity_map
                else 0.0
            ),
        }

        worst = metrics["max_cyclomatic_complexity"]
        summary = (
            f"MI={mi:.0f}/100, max CC={worst}, "
            f"{raw.sloc} SLOC, Halstead volume={h_total.volume:.0f}"
        )
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics=metrics,
            findings=findings,
        )
