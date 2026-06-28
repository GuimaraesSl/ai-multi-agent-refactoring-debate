"""import-linter — architectural import structure and contract validation.

For a multi-module project with an import contract (``.importlinter`` /
``[importlinter]`` in ``setup.cfg``/``pyproject.toml``), this runs the
``lint-imports`` checker and surfaces layer/independence violations.

For a single submitted module (the common API case) there is no contract to
enforce, so the analyzer instead derives **structural import signals** —
coupling/fan-out, wildcard imports and deep relative imports — which are the
architectural smells import-linter exists to police.
"""

from __future__ import annotations

import sys
from pathlib import Path

from refactoring_debate.core.metrics import (
    Finding,
    Severity,
    ToolCategory,
    ToolResult,
    ToolStatus,
)
from refactoring_debate.tools.base import PYTHON, AnalysisContext, Analyzer, run_subprocess

_STDLIB = set(getattr(sys, "stdlib_module_names", frozenset()))
_CONTRACT_FILES = (".importlinter", "setup.cfg", "pyproject.toml")
_FANOUT_THRESHOLD = 15


class ImportLinterAnalyzer(Analyzer):
    name = "import-linter"
    category = ToolCategory.STATIC

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        findings: list[Finding] = []
        imports = ctx.ast.imports

        top_modules = {imp.module.split(".")[0] for imp in imports if imp.module}
        third_party = sorted(m for m in top_modules if m and m not in _STDLIB)
        stdlib = sorted(m for m in top_modules if m in _STDLIB)
        wildcard = [imp for imp in imports if "*" in imp.names]
        deep_relative = [imp for imp in imports if imp.level >= 2]

        for imp in wildcard:
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.MEDIUM,
                    message=(
                        f"Wildcard import `from {imp.module} import *` hides the dependency "
                        "surface and weakens module boundaries"
                    ),
                    line=imp.lineno,
                    rule="wildcard-import",
                    metric="wildcard_imports",
                    value=1.0,
                )
            )
        for imp in deep_relative:
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.LOW,
                    message=(
                        f"Deep relative import (level {imp.level}) signals fragile package "
                        "layering"
                    ),
                    line=imp.lineno,
                    rule="deep-relative-import",
                )
            )
        if len(top_modules) > _FANOUT_THRESHOLD:
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.MEDIUM,
                    message=(
                        f"High import fan-out ({len(top_modules)} distinct modules); the module "
                        "has many responsibilities and is tightly coupled"
                    ),
                    metric="import_fanout",
                    value=float(len(top_modules)),
                    rule="high-fan-out",
                )
            )

        metrics = {
            "total_imports": len(imports),
            "import_fanout": len(top_modules),
            "third_party": third_party,
            "stdlib": stdlib,
            "wildcard_imports": len(wildcard),
            "deep_relative_imports": len(deep_relative),
        }

        # Run the real contract checker when a contract is present in the workdir.
        contract = self._find_contract(ctx.workdir)
        if contract is not None:
            self._run_contract_check(ctx, contract, findings, metrics)

        summary = (
            f"{len(imports)} imports, fan-out {len(top_modules)} "
            f"({len(third_party)} third-party), {len(wildcard)} wildcard"
        )
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics=metrics,
            findings=findings,
        )

    @staticmethod
    def _find_contract(workdir: Path) -> Path | None:
        for name in _CONTRACT_FILES:
            candidate = workdir / name
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                if "importlinter" in text or name == ".importlinter":
                    return candidate
        return None

    def _run_contract_check(
        self,
        ctx: AnalysisContext,
        contract: Path,
        findings: list[Finding],
        metrics: dict,
    ) -> None:
        cmd = [PYTHON, "-m", "importlinter.cli", "lint-imports"]
        if contract.name not in ("setup.cfg", "pyproject.toml"):
            cmd += ["--config", contract.name]
        proc = run_subprocess(cmd, cwd=ctx.workdir, timeout=ctx.settings.dynamic_timeout)
        metrics["contract_checked"] = True
        metrics["contract_passed"] = proc.returncode == 0
        if proc.returncode != 0 and proc.stdout:
            for line in proc.stdout.splitlines():
                if "BROKEN" in line or "is not allowed" in line:
                    findings.append(
                        Finding(
                            tool=self.name,
                            category=self.category,
                            severity=Severity.HIGH,
                            message=f"Import contract violation: {line.strip()}",
                            rule="import-contract",
                        )
                    )
