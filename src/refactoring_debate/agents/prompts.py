"""Prompt construction and tolerant JSON extraction for LLM-backed agents."""

from __future__ import annotations

import json
from typing import Any

from refactoring_debate.core.ast_parser import ASTRepresentation

ANALYZE_INSTRUCTIONS = """\
You are reviewing a single Python module as part of a peer-review-style debate.
Using ONLY the syntactic structure and the deterministic metrics provided, propose
concrete refactorings strictly within your area of expertise. Ground every proposal
in a specific metric or code location — never invent issues the data does not support.

Return a SINGLE JSON object, no prose, with exactly this shape:
{
  "summary": "<2-3 sentence overview of what you found>",
  "recommendations": [
    {
      "title": "<imperative, specific refactoring>",
      "target": "<function/class/module it applies to, or null>",
      "line": <int or null>,
      "severity": "info|low|medium|high|critical",
      "effort": "low|medium|high",
      "confidence": <float 0..1>,
      "rationale": "<why, referencing the metric/evidence>",
      "evidence": ["<metric or finding that supports this>"],
      "tags": ["<short keywords, e.g. caching, coupling, nested-loop>"]
    }
  ]
}
Propose at most 5 recommendations. If the data shows no issue in your area, return an
empty "recommendations" list.
"""

CRITIQUE_INSTRUCTIONS = """\
You are critiquing refactoring proposals made by OTHER specialists, from the viewpoint
of your own expertise. For each proposal that affects your concerns, state whether you
SUPPORT it, raise a CONCERN, or OPPOSE it, and why (e.g. a performance optimization that
harms maintainability or increases energy use).

Return a SINGLE JSON object, no prose:
{
  "critiques": [
    {"target_id": "<recommendation id>", "stance": "support|concern|oppose", "message": "<one sentence>"}
  ]
}
Only comment where your expertise genuinely applies; an empty list is valid.
"""


def render_context(ast_rep: ASTRepresentation, scoped_metrics: dict[str, Any]) -> str:
    """Compact, deterministic context block shared by analyze prompts."""
    return (
        "## Syntactic structure (AST)\n"
        + json.dumps(ast_rep.prompt_summary(), indent=2)
        + "\n\n## Metrics in your scope\n"
        + json.dumps(scoped_metrics, indent=2)
    )


def render_recommendations(recs: list[dict[str, Any]]) -> str:
    return json.dumps(recs, indent=2)


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of the first JSON object from an LLM response.

    Handles ```json fences, leading/trailing prose, and unbalanced tails.
    """
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        # take the content of the first fenced block
        parts = cleaned.split("```")
        for part in parts:
            candidate = part[4:] if part.lower().startswith("json") else part
            obj = _try_balanced(candidate)
            if obj is not None:
                return obj
    return _try_balanced(cleaned)


def _try_balanced(text: str) -> dict | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None
