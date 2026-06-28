"""Tool registry and the agent → tools scope mapping (paper, Figure 1).

``AGENT_TOOL_SCOPES`` is the routing table the orchestrator uses to give each
specialist *only the fraction of the unified metrics relevant to its area*.
"""

from __future__ import annotations

from refactoring_debate.tools.base import Analyzer
from refactoring_debate.tools.dynamic.cprofile_tool import CProfileAnalyzer
from refactoring_debate.tools.dynamic.pyspy_tool import PySpyAnalyzer
from refactoring_debate.tools.dynamic.scalene_tool import ScaleneAnalyzer
from refactoring_debate.tools.energy.codecarbon_tool import CodeCarbonAnalyzer
from refactoring_debate.tools.static.import_linter_tool import ImportLinterAnalyzer
from refactoring_debate.tools.static.pylint_tool import PylintAnalyzer
from refactoring_debate.tools.static.radon_tool import RadonAnalyzer
from refactoring_debate.tools.static.sonarqube_tool import SonarQubeAnalyzer

# Which deterministic tools feed which specialist agent (Figure 1).
AGENT_TOOL_SCOPES: dict[str, set[str]] = {
    "sustainability": {"radon", "scalene", "codecarbon"},
    "architecture": {"sonarqube", "pylint", "import-linter"},
    "performance": {"scalene", "py-spy", "cprofile"},
}


def build_default_analyzers() -> list[Analyzer]:
    """Instantiate the full tools layer in pipeline order."""
    return [
        # static
        RadonAnalyzer(),
        SonarQubeAnalyzer(),
        PylintAnalyzer(),
        ImportLinterAnalyzer(),
        # dynamic
        ScaleneAnalyzer(),
        PySpyAnalyzer(),
        CProfileAnalyzer(),
        # energy
        CodeCarbonAnalyzer(),
    ]
