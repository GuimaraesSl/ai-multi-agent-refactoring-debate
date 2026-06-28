"""Command-line entrypoint: analyze a Python file from the terminal.

    uv run refactoring-debate path/to/file.py [--rounds N] [--dynamic] [--json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from refactoring_debate.bootstrap import bootstrap

bootstrap()

from refactoring_debate.config import get_settings  # noqa: E402
from refactoring_debate.core.orchestrator import Orchestrator  # noqa: E402
from refactoring_debate.debate.models import AnalysisResult, Status  # noqa: E402

_STATUS_STYLE = {
    Status.ACCEPTED: "bold green",
    Status.MERGED: "cyan",
    Status.DEFERRED: "yellow",
    Status.REJECTED: "dim red",
}
_SEVERITY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "blue",
    "info": "dim",
}


def _read_source(path_arg: str) -> tuple[str, str]:
    if path_arg == "-":
        return sys.stdin.read(), "stdin.py"
    path = Path(path_arg)
    if not path.exists():
        raise SystemExit(f"error: file not found: {path_arg}")
    return path.read_text(encoding="utf-8"), path.name


def _render(result: AnalysisResult) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    rm = result.research_metrics

    console.print(
        Panel.fit(
            f"[bold]{result.filename}[/bold]  ·  LLM: [cyan]{result.llm_model}[/cyan]  ·  "
            f"{result.timings.total_ms:.0f} ms\n"
            f"[dim]request {result.request_id}[/dim]",
            title="Multi-Agent Refactoring Debate",
            border_style="blue",
        )
    )

    if not result.ast.syntax_ok:
        console.print(f"[bold red]Syntax error:[/bold red] {result.ast.syntax_error}")

    # Specialist reports
    for report in result.agent_reports:
        console.print(f"\n[bold]{report.agent}[/bold] [dim]({len(report.recommendations)} proposals)[/dim]")
        console.print(f"  [dim]{report.summary}[/dim]")
        for rec in report.recommendations:
            sev = _SEVERITY_STYLE.get(rec.severity.value, "white")
            console.print(f"  • [{sev}]{rec.severity.value:8}[/] {rec.id}  {rec.title}")

    # Peer-review conflicts
    if result.debate.conflicts:
        console.print("\n[bold]Design conflicts (Q3)[/bold]")
        for c in result.debate.conflicts:
            console.print(f"  [magenta]{c.type.value}[/magenta] — {c.description}")

    # Trade-offs
    if result.debate.tradeoffs:
        console.print("\n[bold]Negotiated trade-offs[/bold]")
        for t in result.debate.tradeoffs:
            sac = ", ".join(d.value for d in t.sacrificed)
            console.print(f"  favored [green]{t.favored.value}[/green] over [yellow]{sac}[/yellow] — {t.rationale}")

    # Consolidated table
    table = Table(title="\nConsolidated recommendations", title_justify="left", header_style="bold")
    table.add_column("P", justify="right")
    table.add_column("Status")
    table.add_column("Dimension")
    table.add_column("Sev")
    table.add_column("Recommendation")
    for rec in result.consolidated:
        table.add_row(
            str(rec.priority),
            f"[{_STATUS_STYLE.get(rec.status, 'white')}]{rec.status.value}[/]",
            rec.dimension.value,
            f"[{_SEVERITY_STYLE.get(rec.severity.value, 'white')}]{rec.severity.value}[/]",
            rec.title,
        )
    console.print(table)

    console.print(
        Panel(
            f"[bold]Q1[/bold] distinct opportunities: {rm.distinct_recommendations}    "
            f"[bold]Q2[/bold] quality attributes covered: {rm.quality_attributes_covered}/3 "
            f"({', '.join(d.value for d in rm.attributes_covered)})    "
            f"[bold]Q3[/bold] conflicts: {rm.conflicts_detected}  ·  critiques: {rm.cross_critiques}\n\n"
            f"[dim]{result.summary}[/dim]",
            title="Validation indicators",
            border_style="green",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refactoring-debate",
        description="Run the multi-agent refactoring debate on a Python file.",
    )
    parser.add_argument("path", help="Python file to analyze ('-' to read from stdin).")
    parser.add_argument("--rounds", type=int, default=None, help="Cross-critique rounds (0-5).")
    parser.add_argument(
        "--dynamic", action="store_true", help="Enable dynamic analysis (executes the code)."
    )
    parser.add_argument("--json", action="store_true", help="Emit the raw JSON result.")
    args = parser.parse_args(argv)

    code, filename = _read_source(args.path)
    orchestrator = Orchestrator(get_settings())
    result = orchestrator.analyze(
        code,
        filename=filename,
        debate_rounds=args.rounds,
        enable_dynamic_analysis=True if args.dynamic else None,
    )

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _render(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
