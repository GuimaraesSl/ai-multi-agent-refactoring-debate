"""SonarQube — code smells, technical debt, duplication and vulnerabilities.

SonarQube is a server-based analyzer. This integration talks to the SonarQube
**Web API** (``/api/measures`` and ``/api/issues``) for a configured project,
reflecting the latest server-side analysis. When no server is configured
(``RD_SONARQUBE_URL`` / ``RD_SONARQUBE_TOKEN`` unset) the analyzer reports
``unavailable`` and the pipeline proceeds without it.

Bring a local server up with ``docker compose up -d sonarqube`` and analyze a
project with ``sonar-scanner`` to populate it.
"""

from __future__ import annotations

import httpx

from refactoring_debate.core.metrics import (
    Finding,
    Severity,
    ToolCategory,
    ToolResult,
    ToolStatus,
)
from refactoring_debate.tools.base import AnalysisContext, Analyzer

_MEASURE_METRICS = [
    "bugs",
    "vulnerabilities",
    "code_smells",
    "sqale_index",  # technical debt, in minutes
    "sqale_rating",  # maintainability rating
    "duplicated_lines_density",
    "cognitive_complexity",
    "complexity",
    "ncloc",
]

_SONAR_SEVERITY = {
    "BLOCKER": Severity.CRITICAL,
    "CRITICAL": Severity.CRITICAL,
    "MAJOR": Severity.HIGH,
    "MINOR": Severity.MEDIUM,
    "INFO": Severity.LOW,
}

_MAX_ISSUES = 40


class SonarQubeAnalyzer(Analyzer):
    name = "sonarqube"
    category = ToolCategory.STATIC

    def availability(self, ctx: AnalysisContext) -> tuple[ToolStatus, str]:
        if not ctx.settings.sonarqube_enabled:
            return (
                ToolStatus.UNAVAILABLE,
                "SonarQube not configured (set RD_SONARQUBE_URL and RD_SONARQUBE_TOKEN)",
            )
        return ToolStatus.OK, ""

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        s = ctx.settings
        base = str(s.sonarqube_url).rstrip("/")
        auth = (s.sonarqube_token or "", "")
        project = s.sonarqube_project_key

        with httpx.Client(base_url=base, auth=auth, timeout=30.0) as client:
            measures = self._fetch_measures(client, project)
            issues = self._fetch_issues(client, project)

        findings: list[Finding] = []
        for issue in issues[:_MAX_ISSUES]:
            text_range = issue.get("textRange") or {}
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=_SONAR_SEVERITY.get(issue.get("severity", "MINOR"), Severity.MEDIUM),
                    message=issue.get("message", ""),
                    rule=issue.get("rule"),
                    line=text_range.get("startLine"),
                    end_line=text_range.get("endLine"),
                )
            )

        debt_minutes = float(measures.get("sqale_index", 0) or 0)
        summary = (
            f"{measures.get('code_smells', 0)} code smells, "
            f"{measures.get('bugs', 0)} bugs, {measures.get('vulnerabilities', 0)} vulns, "
            f"debt {debt_minutes / 60:.1f}h, "
            f"duplication {measures.get('duplicated_lines_density', 0)}%"
        )
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics={"project": project, "measures": measures, "issue_count": len(issues)},
            findings=findings,
        )

    @staticmethod
    def _fetch_measures(client: httpx.Client, project: str) -> dict:
        resp = client.get(
            "/api/measures/component",
            params={"component": project, "metricKeys": ",".join(_MEASURE_METRICS)},
        )
        resp.raise_for_status()
        component = resp.json().get("component", {})
        out: dict[str, float | str] = {}
        for measure in component.get("measures", []):
            value = measure.get("value")
            try:
                out[measure["metric"]] = float(value)
            except (TypeError, ValueError):
                out[measure["metric"]] = value
        return out

    @staticmethod
    def _fetch_issues(client: httpx.Client, project: str) -> list[dict]:
        resp = client.get(
            "/api/issues/search",
            params={
                "componentKeys": project,
                "types": "CODE_SMELL,BUG,VULNERABILITY",
                "statuses": "OPEN,CONFIRMED,REOPENED",
                "ps": 100,
            },
        )
        resp.raise_for_status()
        return resp.json().get("issues", [])
