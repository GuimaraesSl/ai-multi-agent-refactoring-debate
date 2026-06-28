"""Unified metrics model.

Every analyzer in the tools layer is normalized into the same shape — a
:class:`ToolResult` carrying tool-specific ``metrics`` plus a list of normalized
:class:`Finding` objects. The orchestrator aggregates them into a
:class:`MetricsReport` (the "unified JSON" of the paper) and slices it per agent
scope before handing it to the specialists.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Normalized severity shared by findings and recommendations."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self)


class ToolCategory(str, Enum):
    """Analysis category, mirroring the three boxes of the tools layer."""

    STATIC = "static"
    DYNAMIC = "dynamic"
    ENERGY = "energy"


class ToolStatus(str, Enum):
    """Outcome of running a single tool."""

    OK = "ok"
    UNAVAILABLE = "unavailable"  # binary/server/key missing
    SKIPPED = "skipped"  # disabled by configuration (e.g. dynamic analysis off)
    ERROR = "error"  # tool ran but raised


class Finding(BaseModel):
    """A single normalized signal emitted by a tool."""

    tool: str
    category: ToolCategory
    message: str
    severity: Severity = Severity.INFO
    rule: str | None = None
    symbol: str | None = None  # enclosing function/class, when known
    line: int | None = None
    end_line: int | None = None
    metric: str | None = None  # name of the underlying metric, if any
    value: float | None = None  # numeric value backing the finding

    def as_evidence(self) -> str:
        loc = f" (line {self.line})" if self.line else ""
        sym = f" in `{self.symbol}`" if self.symbol else ""
        val = f" [{self.metric}={self.value}]" if self.metric and self.value is not None else ""
        return f"{self.tool}: {self.message}{sym}{loc}{val}"


class ToolResult(BaseModel):
    """Normalized output of one analyzer."""

    tool: str
    category: ToolCategory
    status: ToolStatus = ToolStatus.OK
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def available(self) -> bool:
        return self.status is ToolStatus.OK


class MetricsReport(BaseModel):
    """The unified JSON metrics aggregated across the whole tools layer."""

    results: list[ToolResult] = Field(default_factory=list)

    # -- accessors ----------------------------------------------------------
    def by_tool(self, name: str) -> ToolResult | None:
        for result in self.results:
            if result.tool == name:
                return result
        return None

    def by_category(self, category: ToolCategory) -> list[ToolResult]:
        return [r for r in self.results if r.category is category]

    def all_findings(self) -> list[Finding]:
        return [f for r in self.results for f in r.findings]

    def slice(self, tool_names: set[str]) -> dict[str, Any]:
        """Return a compact dict with only the tools in ``tool_names``.

        This is what the orchestrator feeds to a specialist agent so it sees
        *only the fraction of the context corresponding to its area* (paper §4.2).
        """
        selected = [r for r in self.results if r.tool in tool_names]
        return {
            "tools": [
                {
                    "tool": r.tool,
                    "category": r.category.value,
                    "status": r.status.value,
                    "summary": r.summary,
                    "metrics": r.metrics,
                    "findings": [
                        f.model_dump(exclude_none=True, mode="json") for f in r.findings
                    ],
                }
                for r in selected
            ]
        }

    def status_overview(self) -> dict[str, str]:
        """Map tool name -> status string (handy for diagnostics / the API)."""
        return {r.tool: r.status.value for r in self.results}
