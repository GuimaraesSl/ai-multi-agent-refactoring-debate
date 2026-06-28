"""Scalene — high-resolution CPU and memory profiling, separating Python vs.
native time and surfacing per-line allocations (input to both the Performance
and Sustainability agents).
"""

from __future__ import annotations

import json

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

_TOP_N = 10


class ScaleneAnalyzer(DynamicAnalyzer):
    name = "scalene"
    category = ToolCategory.DYNAMIC

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        out = ctx.workdir / "scalene.json"
        proc = run_subprocess(
            [
                PYTHON,
                "-m",
                "scalene",
                "run",  # scalene's profiling subcommand
                "--cli",
                "--json",
                "--outfile",
                out.name,
                ctx.file_path.name,
            ],
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
                summary="scalene produced no profile (program may not have run long enough)",
                error=(proc.stderr or proc.stdout)[:500],
            )

        data = json.loads(out.read_text(encoding="utf-8"))
        hotspots = self._extract_hotspots(data, ctx.file_path.name)

        findings: list[Finding] = []
        for spot in hotspots[:_TOP_N]:
            cpu = spot["cpu_percent"]
            mem = spot["memory_mb"]
            if cpu >= 10:
                findings.append(
                    Finding(
                        tool=self.name,
                        category=self.category,
                        severity=Severity.HIGH if cpu >= 30 else Severity.MEDIUM,
                        message=f"CPU hotspot at line {spot['line']} ({cpu:.0f}% of CPU time)",
                        line=spot["line"],
                        metric="cpu_percent",
                        value=round(cpu, 1),
                        rule="cpu-hotspot",
                    )
                )
            if mem >= 5:
                findings.append(
                    Finding(
                        tool=self.name,
                        category=self.category,
                        severity=Severity.MEDIUM,
                        message=f"Memory allocation at line {spot['line']} (~{mem:.1f} MB)",
                        line=spot["line"],
                        metric="memory_mb",
                        value=round(mem, 2),
                        rule="memory-hotspot",
                    )
                )

        peak = max((h["memory_mb"] for h in hotspots), default=0.0)
        max_cpu = max((h["cpu_percent"] for h in hotspots), default=0.0)
        summary = f"peak line CPU {max_cpu:.0f}%, peak line memory {peak:.1f} MB"
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics={"hotspots": hotspots[:_TOP_N]},
            findings=findings,
        )

    @staticmethod
    def _extract_hotspots(data: dict, filename: str) -> list[dict]:
        spots: list[dict] = []
        files = data.get("files", {})
        for path, fdata in files.items():
            if filename not in path:
                continue
            for line in fdata.get("lines", []):
                cpu = float(line.get("n_cpu_percent_python", 0)) + float(
                    line.get("n_cpu_percent_c", 0)
                )
                mem = float(line.get("n_peak_mb", line.get("n_malloc_mb", 0)) or 0)
                if cpu <= 0 and mem <= 0:
                    continue
                spots.append(
                    {"line": line.get("lineno"), "cpu_percent": cpu, "memory_mb": mem}
                )
        spots.sort(key=lambda s: (s["cpu_percent"], s["memory_mb"]), reverse=True)
        return spots
