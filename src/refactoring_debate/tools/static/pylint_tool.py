"""Pylint — style, best practices, potential errors, PEP8 conformance and,
notably, ``refactor`` messages. Invoked as a subprocess with JSON output.
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
from refactoring_debate.tools.base import PYTHON, AnalysisContext, Analyzer, run_subprocess

_TYPE_SEVERITY = {
    "fatal": Severity.CRITICAL,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "refactor": Severity.MEDIUM,
    "convention": Severity.LOW,
    "information": Severity.INFO,
}

_MAX_FINDINGS = 40


class PylintAnalyzer(Analyzer):
    name = "pylint"
    category = ToolCategory.STATIC

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        proc = run_subprocess(
            [
                PYTHON,
                "-m",
                "pylint",
                ctx.file_path.name,
                "--output-format=json2",
                "--score=y",
                "--persistent=no",
            ],
            cwd=ctx.workdir,
            timeout=ctx.settings.dynamic_timeout + 30,
        )
        if proc.timed_out:
            return self._result(status=ToolStatus.ERROR, summary="pylint timed out")

        messages, score = self._parse(proc.stdout)
        if messages is None:
            return self._result(
                status=ToolStatus.ERROR,
                summary="could not parse pylint output",
                error=proc.stderr[:500] or proc.stdout[:500],
            )

        by_type: dict[str, int] = {}
        findings: list[Finding] = []
        for msg in messages:
            mtype = msg.get("type", "convention")
            by_type[mtype] = by_type.get(mtype, 0) + 1
            if len(findings) < _MAX_FINDINGS:
                findings.append(
                    Finding(
                        tool=self.name,
                        category=self.category,
                        severity=_TYPE_SEVERITY.get(mtype, Severity.LOW),
                        message=msg.get("message", ""),
                        rule=msg.get("symbol") or msg.get("messageId"),
                        symbol=(msg.get("obj") or None),
                        line=msg.get("line"),
                        end_line=msg.get("endLine"),
                    )
                )

        findings.sort(key=lambda f: f.severity.rank, reverse=True)
        findings = findings[:_MAX_FINDINGS]

        metrics = {
            "score": score,
            "message_count": len(messages),
            "by_type": by_type,
            "refactor_suggestions": by_type.get("refactor", 0),
        }
        score_str = f"{score:.1f}/10" if score is not None else "n/a"
        summary = (
            f"pylint score {score_str}, {len(messages)} messages "
            f"({by_type.get('refactor', 0)} refactor, {by_type.get('warning', 0)} warning, "
            f"{by_type.get('error', 0) + by_type.get('fatal', 0)} error)"
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
    def _parse(stdout: str) -> tuple[list[dict] | None, float | None]:
        stdout = stdout.strip()
        if not stdout:
            return [], None
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return None, None
        # json2 format: {"messages": [...], "statistics": {"score": ...}}
        if isinstance(data, dict):
            messages = data.get("messages", [])
            score = (data.get("statistics") or {}).get("score")
            return messages, score
        # legacy json format: a bare list of messages
        if isinstance(data, list):
            return data, None
        return None, None
