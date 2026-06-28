#!/usr/bin/env python
"""Batch evaluation harness for the paper's validation plan (§4.3).

Runs the multi-agent debate over every Python file in a cloned open-source repo,
optionally compares against a single-agent baseline (for Q1), and aggregates the
results into **frequencies and medians** (the paper deliberately avoids means).

Usage:
    uv run python scripts/evaluate.py <path-to-repo-or-file> [options]

Options:
    --out DIR          output directory (default: evaluation_results/<name>)
    --max-files N      cap the number of files analyzed (default: 60)
    --max-loc N        skip files larger than N lines (default: 400)
    --rounds N         debate cross-critique rounds (default: config)
    --baseline         also run a single generic agent (Q1 comparison)
    --dynamic          enable dynamic analysis — EXECUTES code (sandbox only!)

Outputs (in --out): per_file.csv, summary.json, summary.md
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from refactoring_debate.bootstrap import bootstrap

bootstrap()

from refactoring_debate.agents.prompts import (  # noqa: E402
    ANALYZE_INSTRUCTIONS,
    extract_json,
    render_context,
)
from refactoring_debate.config import get_settings  # noqa: E402
from refactoring_debate.core.ast_parser import ASTRepresentation  # noqa: E402
from refactoring_debate.core.metrics import MetricsReport  # noqa: E402
from refactoring_debate.core.orchestrator import Orchestrator  # noqa: E402
from refactoring_debate.debate.models import Status  # noqa: E402
from refactoring_debate.llm.provider import LLMHandle  # noqa: E402

_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "build", "dist", "node_modules", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "migrations", "site-packages",
}
# Primary quality dimension per tool, for classifying baseline recommendations (Fig. 1).
_PRIMARY_DIM = {
    "radon": "sustainability", "codecarbon": "sustainability",
    "scalene": "performance", "py-spy": "performance", "cprofile": "performance",
    "pylint": "architecture", "import-linter": "architecture", "sonarqube": "architecture",
}
_KW = {
    "performance": ("latency", "hot path", "bottleneck", "cache", "optimi", "o(n", "speed", "cpu"),
    "sustainability": ("energy", "carbon", "memory", "allocation", "footprint", "green", "waste"),
    "architecture": ("coupling", "cohesion", "import", "class", "docstring", "naming", "smell",
                     "duplicate", "argument", "responsibilit", "module", "extract"),
}


# --------------------------------------------------------------------------- #
#  File discovery
# --------------------------------------------------------------------------- #
def discover(root: Path, max_loc: int, max_files: int) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            loc = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if 0 < loc <= max_loc:
            found.append(path)
    return found[:max_files]


# --------------------------------------------------------------------------- #
#  Single-agent baseline (for Q1: diversity vs a single generic agent)
# --------------------------------------------------------------------------- #
def _classify(text: str) -> str | None:
    low = text.lower()
    for dim, kws in _KW.items():
        if any(k in low for k in kws):
            return dim
    return None


def single_agent_baseline(
    llm: LLMHandle, ast_rep: ASTRepresentation, metrics: MetricsReport
) -> dict:
    """One generic agent, full (unscoped) metrics, single pass, no debate."""
    t0 = time.perf_counter()
    recs = _baseline_llm(llm, ast_rep, metrics) if llm.uses_llm else _baseline_heuristic(metrics)
    attrs = {d for d in (rec.get("dimension") for rec in recs) if d}
    return {
        "distinct": len(recs),
        "attributes": len(attrs),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
    }


def _baseline_heuristic(metrics: MetricsReport) -> list[dict]:
    findings = sorted(metrics.all_findings(), key=lambda f: f.severity.rank, reverse=True)
    seen: set[tuple] = set()
    recs: list[dict] = []
    for f in findings:
        key = (f.tool, f.message[:60])
        if key in seen:
            continue
        seen.add(key)
        recs.append({"title": f.message, "dimension": _classify(f.message) or _PRIMARY_DIM.get(f.tool)})
        if len(recs) >= 6:  # a single agent's limited observation scope
            break
    return recs


def _baseline_llm(llm: LLMHandle, ast_rep: ASTRepresentation, metrics: MetricsReport) -> list[dict]:
    from crewai import Agent, Crew, Process, Task

    all_tools = {r.tool for r in metrics.results}
    context = render_context(ast_rep, metrics.slice(all_tools))
    agent = Agent(
        role="Senior Software Engineer",
        goal="Recommend the most important refactorings for this module in a single pass.",
        backstory="A generalist who considers performance, architecture and sustainability "
        "together, without a structured debate.",
        llm=llm.crew_llm, allow_delegation=False, verbose=False, max_iter=3,
    )
    task = Task(description=f"{ANALYZE_INSTRUCTIONS}\n\n{context}",
                expected_output="A single JSON object with summary and recommendations.",
                agent=agent)
    raw = getattr(Crew(agents=[agent], tasks=[task], process=Process.sequential).kickoff(), "raw", "")
    data = extract_json(raw) or {}
    out = []
    for item in (data.get("recommendations") or [])[:6]:
        if isinstance(item, dict) and item.get("title"):
            out.append({"title": item["title"], "dimension": _classify(str(item))})
    return out


# --------------------------------------------------------------------------- #
#  Per-file evaluation
# --------------------------------------------------------------------------- #
def evaluate_file(orch: Orchestrator, path: Path, root: Path, rounds, dynamic, baseline) -> dict:
    code = path.read_text(encoding="utf-8", errors="ignore")
    rel = str(path.relative_to(root)) if root.is_dir() else path.name
    result = orch.analyze(code, filename=rel, debate_rounds=rounds,
                          enable_dynamic_analysis=dynamic)
    rm = result.research_metrics
    radon = result.metrics.by_tool("radon")
    pylint = result.metrics.by_tool("pylint")
    sonar = result.metrics.by_tool("sonarqube")
    by_dim = Counter(r.dimension.value for r in result.consolidated)

    row = {
        "file": rel,
        "loc": result.ast.loc,
        "syntax_ok": result.ast.syntax_ok,
        "q1_distinct": rm.distinct_recommendations,
        "q2_attributes": rm.quality_attributes_covered,
        "q3_conflicts": rm.conflicts_detected,
        "tradeoffs": len(result.debate.tradeoffs),
        "critiques": rm.cross_critiques,
        "n_sustainability": by_dim.get("sustainability", 0),
        "n_architecture": by_dim.get("architecture", 0),
        "n_performance": by_dim.get("performance", 0),
        "n_deferred": sum(1 for r in result.consolidated if r.status is Status.DEFERRED),
        # metrics for before/after analysis (indicator v)
        "maintainability_index": (radon.metrics.get("maintainability_index") if radon and radon.available else None),
        "max_cc": (radon.metrics.get("max_cyclomatic_complexity") if radon and radon.available else None),
        "pylint_score": (pylint.metrics.get("score") if pylint and pylint.available else None),
        "code_smells": (sonar.metrics.get("measures", {}).get("code_smells") if sonar and sonar.available else None),
        "total_ms": result.timings.total_ms,
        "conflict_types": [c.type.value for c in result.debate.conflicts],
    }
    if baseline:
        base = single_agent_baseline(orch.llm, result.ast, result.metrics)
        row["baseline_q1_distinct"] = base["distinct"]
        row["baseline_q2_attributes"] = base["attributes"]
        row["baseline_ms"] = base["ms"]
    return row


# --------------------------------------------------------------------------- #
#  Aggregation — frequencies and medians (no means, per §4.3)
# --------------------------------------------------------------------------- #
def _median(values: list[float]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(nums), 2) if nums else None


def aggregate(rows: list[dict], baseline: bool) -> dict:
    n = len(rows)
    files_with_conflict = sum(1 for r in rows if r["q3_conflicts"] > 0)
    attr_dist = Counter(r["q2_attributes"] for r in rows)
    conflict_types = Counter(t for r in rows for t in r["conflict_types"])
    total_recs_by_dim = {
        d: sum(r[f"n_{d}"] for r in rows)
        for d in ("sustainability", "architecture", "performance")
    }

    summary = {
        "files_analyzed": n,
        # Q1 — diversity of refactoring opportunities
        "q1_median_distinct_recommendations": _median([r["q1_distinct"] for r in rows]),
        # Q2 — breadth of quality attributes (0..3)
        "q2_median_attributes_covered": _median([r["q2_attributes"] for r in rows]),
        "q2_attribute_coverage_frequency": {str(k): attr_dist[k] for k in sorted(attr_dist)},
        "q2_total_recommendations_by_dimension": total_recs_by_dim,
        # Q3 — explicit design conflicts
        "q3_files_with_conflict": files_with_conflict,
        "q3_freq_files_with_conflict": round(files_with_conflict / n, 3) if n else 0,
        "q3_median_conflicts_per_file": _median([r["q3_conflicts"] for r in rows]),
        "q3_conflict_type_frequency": dict(conflict_types.most_common()),
        # iv — processing time
        "median_total_ms": _median([r["total_ms"] for r in rows]),
        # supporting metric medians (for before/after, indicator v)
        "median_maintainability_index": _median([r["maintainability_index"] for r in rows]),
        "median_max_cyclomatic_complexity": _median([r["max_cc"] for r in rows]),
    }
    if baseline:
        summary["q1_baseline_median_distinct"] = _median([r.get("baseline_q1_distinct") for r in rows])
        summary["q2_baseline_median_attributes"] = _median([r.get("baseline_q2_attributes") for r in rows])
    return summary


# --------------------------------------------------------------------------- #
#  Output
# --------------------------------------------------------------------------- #
def write_outputs(out: Path, rows: list[dict], summary: dict, meta: dict, md_text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fields = [k for k in rows[0] if k != "conflict_types"] if rows else []
    with (out / "per_file.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, indent=2))
    (out / "summary.md").write_text(md_text)


# --------------------------------------------------------------------------- #
#  Metrics-only mode (indicator v: before/after metric variation, no LLM)
# --------------------------------------------------------------------------- #
def evaluate_file_metrics_only(orch: Orchestrator, path: Path, root: Path, dynamic) -> dict:
    code = path.read_text(encoding="utf-8", errors="ignore")
    rel = str(path.relative_to(root)) if root.is_dir() else path.name
    ast_rep, metrics = orch.collect_metrics(code, rel, enable_dynamic_analysis=dynamic)
    radon = metrics.by_tool("radon")
    pylint = metrics.by_tool("pylint")
    sonar = metrics.by_tool("sonarqube")
    energy = metrics.by_tool("codecarbon")
    return {
        "file": rel,
        "loc": ast_rep.loc,
        "syntax_ok": ast_rep.syntax_ok,
        "maintainability_index": radon.metrics.get("maintainability_index") if radon and radon.available else None,
        "max_cc": radon.metrics.get("max_cyclomatic_complexity") if radon and radon.available else None,
        "pylint_score": pylint.metrics.get("score") if pylint and pylint.available else None,
        "code_smells": sonar.metrics.get("measures", {}).get("code_smells") if sonar and sonar.available else None,
        "energy_wh": energy.metrics.get("energy_wh") if energy and energy.available else None,
    }


def aggregate_metrics_only(rows: list[dict]) -> dict:
    return {
        "files_analyzed": len(rows),
        "median_maintainability_index": _median([r["maintainability_index"] for r in rows]),
        "median_max_cyclomatic_complexity": _median([r["max_cc"] for r in rows]),
        "median_pylint_score": _median([r["pylint_score"] for r in rows]),
        "median_code_smells": _median([r["code_smells"] for r in rows]),
        "median_energy_wh": _median([r["energy_wh"] for r in rows]),
    }


def _summary_md_metrics(s: dict, meta: dict) -> str:
    return "\n".join([
        f"# Metric snapshot — {meta['target']}",
        "",
        f"- Files analyzed: **{s['files_analyzed']}**  ·  dynamic: {meta['dynamic']}",
        "",
        "## Median static/dynamic metrics (for before/after comparison, §4.3 indicator v)",
        f"- Maintainability index: **{s['median_maintainability_index']}**",
        f"- Max cyclomatic complexity: **{s['median_max_cyclomatic_complexity']}**",
        f"- Pylint score: **{s['median_pylint_score']}**",
        f"- SonarQube code smells: **{s['median_code_smells']}**",
        f"- Energy (Wh, dynamic only): **{s['median_energy_wh']}**",
    ]) + "\n"


def _summary_md(s: dict, meta: dict) -> str:
    lines = [
        f"# Evaluation summary — {meta['target']}",
        "",
        f"- Files analyzed: **{s['files_analyzed']}**",
        f"- LLM backend: **{meta['llm']}**  ·  debate rounds: {meta['rounds']}  ·  "
        f"dynamic: {meta['dynamic']}",
        "",
        "## Q1 — Diversity of refactoring opportunities",
        f"- Median distinct recommendations (multi-agent): **{s['q1_median_distinct_recommendations']}**",
    ]
    if "q1_baseline_median_distinct" in s:
        lines.append(f"- Median distinct (single-agent baseline): **{s['q1_baseline_median_distinct']}**")
    lines += [
        "",
        "## Q2 — Quality attributes covered (0–3)",
        f"- Median attributes covered (multi-agent): **{s['q2_median_attributes_covered']}**",
    ]
    if "q2_baseline_median_attributes" in s:
        lines.append(f"- Median attributes (single-agent baseline): **{s['q2_baseline_median_attributes']}**")
    lines += [
        f"- Coverage frequency (files by #attributes): `{s['q2_attribute_coverage_frequency']}`",
        f"- Total recommendations by dimension: `{s['q2_total_recommendations_by_dimension']}`",
        "",
        "## Q3 — Explicit design conflicts",
        f"- Files with ≥1 conflict: **{s['q3_files_with_conflict']}** "
        f"({s['q3_freq_files_with_conflict'] * 100:.0f}% of files)",
        f"- Median conflicts per file: **{s['q3_median_conflicts_per_file']}**",
        f"- Conflict type frequency: `{s['q3_conflict_type_frequency']}`",
        "",
        "## Processing time & metric baselines",
        f"- Median total time per file: **{s['median_total_ms']} ms**",
        f"- Median maintainability index: **{s['median_maintainability_index']}**",
        f"- Median max cyclomatic complexity: **{s['median_max_cyclomatic_complexity']}**",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the tool over a repo/file corpus.")
    parser.add_argument("target", help="Path to a cloned repo, a directory, or a single .py file.")
    parser.add_argument("--out", default=None)
    parser.add_argument("--max-files", type=int, default=60)
    parser.add_argument("--max-loc", type=int, default=400)
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--dynamic", action="store_true")
    parser.add_argument("--metrics-only", action="store_true",
                        help="Only snapshot static/dynamic metrics (fast, no LLM) for "
                             "before/after comparison (indicator v).")
    args = parser.parse_args(argv)

    root = Path(args.target).resolve()
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path("evaluation_results") / root.name

    files = discover(root, args.max_loc, args.max_files)
    if not files:
        print("error: no Python files matched the filters.", file=sys.stderr)
        return 1

    orch = Orchestrator(get_settings())
    meta = {
        "target": root.name, "llm": orch.llm.label, "rounds": args.rounds if args.rounds is not None
        else orch.settings.debate_rounds, "dynamic": bool(args.dynamic),
    }
    print(f"Analyzing {len(files)} files from {root}  (LLM: {orch.llm.label})")

    dyn = True if args.dynamic else None
    rows: list[dict] = []
    errors = 0
    for i, path in enumerate(files, 1):
        try:
            if args.metrics_only:
                row = evaluate_file_metrics_only(orch, path, root, dyn)
                prog = f"MI={row['maintainability_index']} maxCC={row['max_cc']}"
            else:
                row = evaluate_file(orch, path, root, args.rounds, dyn, args.baseline)
                prog = f"Q1={row['q1_distinct']} Q2={row['q2_attributes']} Q3={row['q3_conflicts']}"
            rows.append(row)
            print(f"  [{i}/{len(files)}] {row['file']}: {prog}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  [{i}/{len(files)}] {path.name}: ERROR {exc}", file=sys.stderr)

    if not rows:
        print("error: every file failed.", file=sys.stderr)
        return 1

    meta["errors"] = errors
    if args.metrics_only:
        summary = aggregate_metrics_only(rows)
        md = _summary_md_metrics(summary, meta)
    else:
        summary = aggregate(rows, args.baseline)
        md = _summary_md(summary, meta)
    write_outputs(out, rows, summary, meta, md)
    print(f"\nDone. {len(rows)} ok, {errors} errors. Wrote: {out}/per_file.csv, summary.json, summary.md")
    print(f"\n{md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
