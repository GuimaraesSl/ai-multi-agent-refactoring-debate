"""py-spy — low-overhead sampling profiler.

py-spy attaches to a *running* interpreter to sample call stacks, approximating
production behaviour. It needs to read another process's memory, which on macOS
(and locked-down Linux) requires elevated privileges — when that is denied the
analyzer degrades to ``unavailable`` with a clear reason rather than failing.
"""

from __future__ import annotations

from collections import Counter

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
    resolve_binary,
    run_subprocess,
)

_PERMISSION_HINTS = ("permission", "operation not permitted", "root", "sudo", "denied")
_TOP_N = 10


class PySpyAnalyzer(DynamicAnalyzer):
    name = "py-spy"
    category = ToolCategory.DYNAMIC

    def availability(self, ctx: AnalysisContext) -> tuple[ToolStatus, str]:
        status, reason = super().availability(ctx)
        if status is not ToolStatus.OK:
            return status, reason
        if resolve_binary("py-spy") is None:
            return ToolStatus.UNAVAILABLE, "py-spy binary not found"
        return ToolStatus.OK, ""

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        binary = resolve_binary("py-spy")
        assert binary is not None  # guaranteed by availability()
        out = ctx.workdir / "pyspy.folded"
        proc = run_subprocess(
            [
                binary,
                "record",
                "--format",
                "raw",
                "--output",
                out.name,
                "--rate",
                "200",
                "--subprocesses",
                "--",
                PYTHON,
                ctx.file_path.name,
            ],
            cwd=ctx.workdir,
            timeout=ctx.settings.dynamic_timeout,
            env=self.clean_env(),
        )

        if not out.exists() or out.stat().st_size == 0:
            stderr = (proc.stderr or "").lower()
            if any(hint in stderr for hint in _PERMISSION_HINTS):
                return self._result(
                    status=ToolStatus.UNAVAILABLE,
                    summary="py-spy needs elevated privileges on this OS (run with sudo)",
                )
            if proc.timed_out:
                return self._result(status=ToolStatus.ERROR, summary="py-spy timed out")
            return self._result(
                status=ToolStatus.ERROR,
                summary="py-spy produced no samples",
                error=(proc.stderr or proc.stdout)[:500],
            )

        frames = self._parse_folded(out.read_text(encoding="utf-8"), ctx.file_path.name)
        total = sum(frames.values()) or 1
        ranked = frames.most_common(_TOP_N)

        findings: list[Finding] = []
        for frame, count in ranked:
            frac = count / total
            if frac < 0.15:
                continue
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.HIGH if frac > 0.4 else Severity.MEDIUM,
                    message=f"Sampled hot frame `{frame}` ({frac * 100:.0f}% of samples)",
                    symbol=frame,
                    metric="sample_fraction",
                    value=round(frac, 3),
                    rule="sampled-hotspot",
                )
            )

        top = ranked[0] if ranked else ("n/a", 0)
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=f"{total} samples; hottest `{top[0]}` ({top[1]} samples)",
            metrics={
                "total_samples": total,
                "top_frames": [{"frame": f, "samples": c} for f, c in ranked],
            },
            findings=findings,
        )

    @staticmethod
    def _parse_folded(text: str, filename: str) -> Counter:
        """Aggregate sample counts for leaf frames located in the submitted file."""
        counter: Counter = Counter()
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                stack, count_str = raw_line.rsplit(" ", 1)
                count = int(count_str)
            except ValueError:
                continue
            for frame in stack.split(";"):
                if filename in frame:
                    counter[frame.strip()] += count
        return counter
