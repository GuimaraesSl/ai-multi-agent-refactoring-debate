"""Tools layer — deterministic extraction of quality, performance and energy metrics.

The layer is split into three categories mirroring the paper's tools box:

* ``static``  — Radon, SonarQube, Pylint, import-linter
* ``dynamic`` — Scalene, py-spy, cProfile
* ``energy``  — CodeCarbon

Every analyzer is normalized to a :class:`~refactoring_debate.core.metrics.ToolResult`
and degrades gracefully (``unavailable`` / ``skipped`` / ``error``) when its backend
is missing or disabled, so the pipeline never hard-fails on a missing tool.
"""

from refactoring_debate.tools.base import AnalysisContext, Analyzer
from refactoring_debate.tools.registry import (
    AGENT_TOOL_SCOPES,
    build_default_analyzers,
)

__all__ = [
    "Analyzer",
    "AnalysisContext",
    "AGENT_TOOL_SCOPES",
    "build_default_analyzers",
]
