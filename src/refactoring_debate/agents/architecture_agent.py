"""Architecture agent — structural quality, best practices, coupling & cohesion.

Scope (Figure 1): SonarQube, Pylint, import-linter.
"""

from __future__ import annotations

from refactoring_debate.agents.base import SpecialistAgent
from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import MetricsReport, Severity
from refactoring_debate.debate.models import Dimension, Effort, Recommendation

_GOD_CLASS_METHODS = 8
_LONG_FUNCTION_LINES = 40
_TOO_MANY_ARGS = 5
_STRUCTURAL_RULES = (
    "too-many",
    "too-few",
    "duplicate",
    "cyclic",
    "import",
    "redefined",
    "no-self",
    "attribute-defined",
)


class ArchitectureAgent(SpecialistAgent):
    dimension = Dimension.ARCHITECTURE
    name = "Architecture Agent"
    id_prefix = "ARC"
    tool_scope = {"sonarqube", "pylint", "import-linter"}

    role = "Software Architecture Specialist"
    goal = (
        "Improve structural quality: enforce high cohesion and low coupling, isolate "
        "responsibilities, and remove code smells and architectural violations, keeping the "
        "module readable and maintainable."
    )
    backstory = (
        "You think in terms of modules, boundaries and dependencies. You spot god classes, "
        "long methods, leaky imports and coupling that will make the system expensive to evolve, "
        "and you defend maintainability even when it costs raw speed."
    )

    def _heuristic_recommendations(
        self, ast_rep: ASTRepresentation, metrics: MetricsReport
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        idx = 1

        # 1. God classes — too many responsibilities (low cohesion).
        for cls in ast_rep.classes:
            if cls.num_methods >= _GOD_CLASS_METHODS:
                recs.append(
                    self._rec(
                        idx,
                        title=f"Split god class `{cls.name}` by responsibility",
                        target=cls.name,
                        line=cls.lineno,
                        severity=Severity.HIGH,
                        effort=Effort.HIGH,
                        confidence=0.7,
                        rationale=(
                            f"`{cls.name}` exposes {cls.num_methods} methods, a sign of low cohesion. "
                            "Extracting collaborators reduces coupling and clarifies boundaries."
                        ),
                        evidence=[f"AST: {cls.num_methods} methods in class {cls.name}"],
                        tags=["god-class", "cohesion", "split", "decouple"],
                    )
                )
                idx += 1

        # 2. Long functions / too many parameters.
        for fn in ast_rep.functions:
            if fn.length >= _LONG_FUNCTION_LINES:
                recs.append(
                    self._rec(
                        idx,
                        title=f"Extract methods from long function `{fn.qualname}`",
                        target=fn.qualname,
                        line=fn.lineno,
                        severity=Severity.MEDIUM,
                        effort=Effort.MEDIUM,
                        confidence=0.65,
                        rationale=(
                            f"`{fn.qualname}` spans {fn.length} lines; extracting cohesive blocks "
                            "improves readability and testability."
                        ),
                        evidence=[f"AST: {fn.length} lines in {fn.qualname}"],
                        tags=["long-method", "extract", "readability"],
                    )
                )
                idx += 1
            elif fn.num_args > _TOO_MANY_ARGS:
                recs.append(
                    self._rec(
                        idx,
                        title=f"Reduce the parameter list of `{fn.qualname}`",
                        target=fn.qualname,
                        line=fn.lineno,
                        severity=Severity.LOW,
                        effort=Effort.MEDIUM,
                        confidence=0.55,
                        rationale=(
                            f"`{fn.qualname}` takes {fn.num_args} parameters; a parameter object or "
                            "dataclass clarifies intent and lowers coupling."
                        ),
                        evidence=[f"AST: {fn.num_args} parameters in {fn.qualname}"],
                        tags=["parameters", "dataclass", "abstraction"],
                    )
                )
                idx += 1
            if idx > 4:
                break

        # 3. Import coupling / leaky boundaries (import-linter).
        imp = metrics.by_tool("import-linter")
        if imp and imp.available:
            for finding in imp.findings[:2]:
                recs.append(
                    self._rec(
                        idx,
                        title=finding.message.split(";")[0][:80],
                        line=finding.line,
                        severity=finding.severity,
                        effort=Effort.LOW,
                        confidence=0.6,
                        rationale=finding.message,
                        evidence=[finding.as_evidence()],
                        tags=["coupling", "imports", "decouple"],
                    )
                )
                idx += 1

        # 4. Structural code smells from Pylint / SonarQube.
        for tool_name in ("pylint", "sonarqube"):
            tool = metrics.by_tool(tool_name)
            if not (tool and tool.available):
                continue
            structural = [
                f
                for f in tool.findings
                if f.rule and any(key in f.rule for key in _STRUCTURAL_RULES)
            ] or tool.findings
            for finding in structural[:2]:
                recs.append(
                    self._rec(
                        idx,
                        title=f"Resolve {tool_name} smell: {finding.message[:70]}",
                        line=finding.line,
                        severity=finding.severity,
                        effort=Effort.LOW,
                        confidence=0.55,
                        rationale=finding.message,
                        evidence=[finding.as_evidence()],
                        tags=["code-smell", "best-practice"],
                    )
                )
                idx += 1
            break  # prefer pylint when both present

        return recs[:5]

    def _heuristic_summary(self, recs: list[Recommendation]) -> str:
        if not recs:
            return "Structure looks sound within the analyzed scope; no major smells found."
        return (
            f"Identified {len(recs)} architectural opportunities targeting cohesion, coupling and "
            "maintainability (god classes, long methods, leaky imports and code smells)."
        )
