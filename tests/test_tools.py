"""Tests for the deterministic tools layer (static tools + graceful degradation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactoring_debate.config import Settings
from refactoring_debate.core.ast_parser import parse_code
from refactoring_debate.core.metrics import ToolCategory, ToolStatus
from refactoring_debate.tools.base import AnalysisContext
from refactoring_debate.tools.static.import_linter_tool import ImportLinterAnalyzer
from refactoring_debate.tools.static.pylint_tool import PylintAnalyzer
from refactoring_debate.tools.static.radon_tool import RadonAnalyzer
from refactoring_debate.tools.static.sonarqube_tool import SonarQubeAnalyzer


def _ctx(tmp_path: Path, code: str) -> AnalysisContext:
    fp = tmp_path / "m.py"
    fp.write_text(code)
    return AnalysisContext(
        code=code,
        filename="m.py",
        workdir=tmp_path,
        file_path=fp,
        ast=parse_code(code, "m.py"),
        settings=Settings(enable_dynamic_analysis=False),
    )


def test_radon_reports_metrics(tmp_path: Path, sample_code: str) -> None:
    res = RadonAnalyzer().run(_ctx(tmp_path, sample_code))
    assert res.status is ToolStatus.OK
    assert res.category is ToolCategory.STATIC
    assert "maintainability_index" in res.metrics
    assert res.metrics["max_cyclomatic_complexity"] >= 1


def test_pylint_finds_unused_import(tmp_path: Path, sample_code: str) -> None:
    res = PylintAnalyzer().run(_ctx(tmp_path, sample_code))
    assert res.status is ToolStatus.OK
    messages = " ".join(f.message.lower() for f in res.findings)
    assert "unused" in messages or res.metrics["message_count"] > 0


def test_import_linter_structural_metrics(tmp_path: Path) -> None:
    code = "from os import *\nimport sys\n"
    res = ImportLinterAnalyzer().run(_ctx(tmp_path, code))
    assert res.status is ToolStatus.OK
    assert res.metrics["wildcard_imports"] == 1
    assert any("wildcard" in f.rule for f in res.findings if f.rule)


def test_sonarqube_unavailable_when_unconfigured(tmp_path: Path) -> None:
    res = SonarQubeAnalyzer().run(_ctx(tmp_path, "x = 1\n"))
    assert res.status is ToolStatus.UNAVAILABLE
    assert "not configured" in res.summary.lower()


def test_failed_tool_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = RadonAnalyzer()
    monkeypatch.setattr(
        analyzer, "analyze", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    res = analyzer.run(_ctx(tmp_path, "x = 1\n"))
    assert res.status is ToolStatus.ERROR  # never propagates out of run()
    assert res.error is not None
