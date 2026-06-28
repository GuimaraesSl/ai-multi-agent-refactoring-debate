"""cProfile — deterministic profiling: wall time per function and call counts.

Executes the submitted module under ``cProfile`` and reports the hottest
functions (favouring those defined in the submitted file).
"""

from __future__ import annotations

import pstats

from refactoring_debate.core.metrics import (
    Finding,
    Severity,
    ToolCategory,
    ToolResult,
    ToolStatus,
)
from refactoring_debate.tools.base import (
    PYTHON,
    AnalysisContext,
    DynamicAnalyzer,
    run_subprocess,
)

_TOP_N = 12


class CProfileAnalyzer(DynamicAnalyzer):
    name = "cprofile"
    category = ToolCategory.DYNAMIC

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        out = ctx.workdir / "cprofile.out"
        proc = run_subprocess(
            [PYTHON, "-m", "cProfile", "-o", out.name, ctx.file_path.name],
            cwd=ctx.workdir,
            timeout=ctx.settings.dynamic_timeout,
            env=self.clean_env(),
        )
        if proc.timed_out:
            return self._result(
                status=ToolStatus.ERROR,
                summary=f"execution exceeded {ctx.settings.dynamic_timeout}s timeout",
            )
        if not out.exists():
            return self._result(
                status=ToolStatus.ERROR,
                summary="cProfile produced no output (the program may have crashed)",
                error=proc.stderr[:500],
            )

        stats = pstats.Stats(str(out))
        total_time = stats.total_tt or 0.0  # type: ignore[attr-defined]
        rows = []
        for (filename, lineno, func), (_cc, nc, tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]  # noqa: B007
            rows.append(
                {
                    "function": func,
                    "file": filename,
                    "line": lineno,
                    "ncalls": nc,
                    "tottime": round(tt, 6),
                    "cumtime": round(ct, 6),
                    "in_submission": ctx.file_path.name in str(filename),
                }
            )
        rows.sort(key=lambda r: r["cumtime"], reverse=True)
        hot = rows[:_TOP_N]

        findings: list[Finding] = []
        for row in hot:
            if not row["in_submission"] or total_time <= 0:
                continue
            frac = row["cumtime"] / total_time
            if frac < 0.15:
                continue
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.HIGH if frac > 0.4 else Severity.MEDIUM,
                    message=(
                        f"Hot path: `{row['function']}` accounts for {frac * 100:.0f}% of runtime "
                        f"({row['cumtime']:.3f}s over {row['ncalls']} calls)"
                    ),
                    symbol=row["function"],
                    line=row["line"] if isinstance(row["line"], int) else None,
                    metric="cumtime_fraction",
                    value=round(frac, 3),
                    rule="hot-path",
                )
            )

        summary = (
            f"total {total_time:.3f}s; hottest "
            f"`{hot[0]['function']}` {hot[0]['cumtime']:.3f}s"
            if hot
            else "no measurable work executed"
        )
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics={"total_time_s": round(total_time, 4), "hot_functions": hot},
            findings=findings,
        )
