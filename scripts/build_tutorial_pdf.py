#!/usr/bin/env python
"""Render docs/EVALUATION_TUTORIAL.md to a PDF.

    uv sync --extra docs
    uv run python scripts/build_tutorial_pdf.py

Uses `markdown` + `xhtml2pdf` (pure Python, no system dependencies).
"""

from __future__ import annotations

import sys
from pathlib import Path

import markdown
from xhtml2pdf import pisa

_CSS = """
@page { size: a4 portrait; margin: 1.8cm 1.6cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #1a1a1a;
       line-height: 1.4; }
h1 { font-size: 19pt; color: #14366b; margin: 0 0 4pt 0; }
h2 { font-size: 13pt; color: #14366b; border-bottom: 1px solid #c9d4e6;
     padding-bottom: 3pt; margin-top: 16pt; }
h3 { font-size: 11pt; color: #2a2a2a; margin-top: 12pt; }
p, li { font-size: 10pt; }
a { color: #14366b; text-decoration: none; }
code { font-family: Courier, monospace; font-size: 8.5pt; background-color: #eef1f5; }
pre { background-color: #f4f6f9; border: 1px solid #dde3ec; padding: 6pt;
      font-family: Courier, monospace; font-size: 8pt; color: #20303f; }
pre code { background-color: #f4f6f9; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th { background-color: #14366b; color: #ffffff; font-size: 8.5pt; padding: 4pt;
     text-align: left; }
td { border: 1px solid #c9d4e6; font-size: 8.5pt; padding: 4pt; }
blockquote { background-color: #fbf7e8; border-left: 3px solid #d8c163;
             padding: 4pt 8pt; color: #4a4326; }
hr { border: none; border-top: 1px solid #d4dae3; margin: 12pt 0; }
"""

_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{css}</style></head><body>
<p style="font-size:8pt;color:#6b7686;">Universidade Federal do Ceará — Campus Quixadá ·
Recomendação de Refatorações via Debate Multiagente</p>
{body}
</body></html>"""


def build(src: Path, out: Path) -> int:
    md_text = src.read_text(encoding="utf-8")
    body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists", "toc"]
    )
    html = _HTML.format(css=_CSS, body=body)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        result = pisa.CreatePDF(html, dest=fh, encoding="utf-8")
    if result.err:
        print(f"error: PDF generation reported {result.err} error(s)", file=sys.stderr)
        return 1
    size_kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({size_kb:.0f} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = Path(__file__).resolve().parent.parent
    src = Path(argv[0]) if len(argv) > 0 else root / "docs" / "EVALUATION_TUTORIAL.md"
    out = Path(argv[1]) if len(argv) > 1 else root / "docs" / "EVALUATION_TUTORIAL.pdf"
    if not src.exists():
        print(f"error: source not found: {src}", file=sys.stderr)
        return 1
    return build(src, out)


if __name__ == "__main__":
    raise SystemExit(main())
