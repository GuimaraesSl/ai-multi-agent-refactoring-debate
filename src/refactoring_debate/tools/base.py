"""Base abstractions for the tools layer."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from refactoring_debate.config import Settings
from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import ToolCategory, ToolResult, ToolStatus


@dataclass(slots=True)
class AnalysisContext:
    """Everything an analyzer needs to inspect one submission."""

    code: str
    filename: str
    workdir: Path  # scratch directory unique to this request
    file_path: Path  # the submitted code written to disk inside ``workdir``
    ast: ASTRepresentation
    settings: Settings


@dataclass(slots=True)
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def binary_available(name: str) -> bool:
    """True if an executable ``name`` is on PATH."""
    return shutil.which(name) is not None


def resolve_binary(name: str) -> str | None:
    """Resolve a console-script ``name`` from the active venv's bin/ or PATH."""
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    return shutil.which(name)


def run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run ``cmd`` with a hard timeout, capturing output. Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603 - command is constructed internally
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        return SubprocessResult(proc.returncode, proc.stdout, proc.stderr, timed_out=False)
    except subprocess.TimeoutExpired as exc:
        return SubprocessResult(
            returncode=-1,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"timed out after {timeout}s",
            timed_out=True,
        )


# The interpreter running this process — guarantees the tools installed in our
# virtualenv (radon, pylint, scalene, ...) are the ones invoked as subprocesses.
PYTHON = sys.executable


class Analyzer(ABC):
    """Template for a single deterministic analyzer.

    Subclasses implement :meth:`analyze`; the :meth:`run` template method handles
    availability checks, timing and exception isolation so one failing tool never
    aborts the pipeline.
    """

    name: str
    category: ToolCategory

    def availability(self, ctx: AnalysisContext) -> tuple[ToolStatus, str]:
        """Return ``(OK, "")`` when the tool can run, otherwise a non-OK status."""
        return ToolStatus.OK, ""

    @abstractmethod
    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        """Perform the analysis and return a populated :class:`ToolResult`."""

    def run(self, ctx: AnalysisContext) -> ToolResult:
        start = time.perf_counter()
        status, reason = self.availability(ctx)
        if status is not ToolStatus.OK:
            return ToolResult(
                tool=self.name,
                category=self.category,
                status=status,
                summary=reason,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        try:
            result = self.analyze(ctx)
        except Exception as exc:  # noqa: BLE001 - isolate any tool failure
            return ToolResult(
                tool=self.name,
                category=self.category,
                status=ToolStatus.ERROR,
                summary=f"{self.name} raised: {exc}",
                error=repr(exc),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return result

    # convenience for subclasses ------------------------------------------------
    def _result(self, **kwargs) -> ToolResult:
        kwargs.setdefault("tool", self.name)
        kwargs.setdefault("category", self.category)
        return ToolResult(**kwargs)


class DynamicAnalyzer(Analyzer):
    """Base for analyzers that *execute* the submitted code.

    They are disabled unless ``RD_ENABLE_DYNAMIC_ANALYSIS`` is true (running
    arbitrary code is unsafe) and run inside a hard wall-clock timeout.
    """

    def availability(self, ctx: AnalysisContext) -> tuple[ToolStatus, str]:
        if not ctx.settings.enable_dynamic_analysis:
            return (
                ToolStatus.SKIPPED,
                "dynamic analysis disabled (set RD_ENABLE_DYNAMIC_ANALYSIS=true to run)",
            )
        if not ctx.ast.syntax_ok:
            return ToolStatus.SKIPPED, "code has syntax errors; cannot execute"
        return ToolStatus.OK, ""

    @staticmethod
    def clean_env() -> dict[str, str]:
        """Subprocess environment that keeps child output quiet and unbuffered."""
        import os

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env
