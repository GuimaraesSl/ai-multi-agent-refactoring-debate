# Multi-Agent Refactoring Debate

> Recomendação de Refatorações via Debate Multiagente: Uma Arquitetura Inspirada em Revisão por Pares
> — Gabriel Al-Samir G. Sales & Marcos Antonio de Oliveira (UFC – Campus Quixadá)

A refactoring **recommendation** tool for Python code grounded in a **peer-review-inspired
debate** between autonomous LLM-based agents. Instead of a single agent that optimizes a
metric in isolation, the system distributes the analysis across **specialist agents**
(Software Sustainability, Architecture, Performance) and delegates the mediation of design
conflicts to a **Judge (Debate) Agent**. Everything is grounded in **deterministic metrics**
extracted from the code's **Abstract Syntax Tree (AST)** and exposed through a **FastAPI
REST API**.

This repository is the executable implementation of the architecture described in the paper
(Section 4 — *Metodologia*, Figure 1).

---

## Why this design

A single LLM acting in a *single pass* suffers from a **limited observation scope**: it
concentrates on a narrow subset of metrics and ignores global constraints. Software quality
is not one-dimensional — it is a **Pareto frontier** of competing attributes. This system
makes those tensions explicit through **Multi-Agent Debate (MAD)**: specialists propose local
refactorings, **cross-critique** each other (peer review), and a Judge **arbitrates the
trade-offs** before consolidating the final recommendations.

---

## Architecture

```
1. INPUT           2. PARSING         3. TOOLS LAYER            4. SPECIALIST AGENTS       5. JUDGE
   Python code  ->   AST Parser   ->   (deterministic metrics)   (semantic reasoning)   ->  Debate Agent
                     (ast module)      static / dynamic / energy  local recommendations      arbitration
                                                                                              |
                                                                          6. CONSOLIDATED OUTPUT (REST)
```

Two layers, exactly as in the paper:

| Layer | Responsibility | Components |
|-------|----------------|------------|
| **Tools** | Deterministic metric extraction | **Static:** Radon, SonarQube, Pylint, import-linter · **Dynamic:** Scalene, py-spy, cProfile · **Energy:** CodeCarbon |
| **Agents** | Semantic reasoning & recommendation | **Sustainability**, **Architecture**, **Performance** specialists + **Debate/Judge** mediator (orchestrated with **CrewAI**) |

Each specialist receives **only the fraction of the unified JSON metrics** relevant to its
scope (sustainability ← Radon/Scalene/CodeCarbon, architecture ← SonarQube/Pylint/import-linter,
performance ← Scalene/py-spy/cProfile), generates local recommendations, then the Judge runs
the debate and returns a **consolidated, prioritized report with explicit trade-offs**.

```
src/refactoring_debate/
├── api/            FastAPI app: routes + request/response schemas
├── core/           AST parser, unified metric model, pipeline orchestrator
├── tools/          Deterministic analyzers (static / dynamic / energy) with graceful fallback
├── llm/            Pluggable LLM provider (Ollama default, OpenAI/Anthropic, heuristic)
├── agents/         CrewAI specialist agents + Judge
└── debate/         Peer-review debate protocol, conflict detection, trade-off negotiation
```

---

## Requirements

- **Python 3.12** (managed automatically by [`uv`](https://docs.astral.sh/uv/))
- Optional: **Ollama** for local LLMs (`brew install ollama` then `ollama pull llama3`)
- Optional: **Docker** for a SonarQube server (`docker compose up -d sonarqube`)

The system **runs end-to-end without Ollama, Docker, or any cloud key** by using the built-in
`heuristic` LLM provider and graceful degradation of unavailable tools — so you can try the
full pipeline immediately and plug in the heavyweight backends later.

---

## Quick start

```bash
# 1. Install (creates a Python 3.12 virtualenv and resolves all dependencies)
uv sync --extra dev

# 2. Configure
cp .env.example .env          # defaults are sane; edit to taste

# 3a. Try it with zero external services (deterministic agents)
RD_LLM_PROVIDER=heuristic uv run refactoring-debate examples/sample_code.py

# 3b. Or with local LLMs as in the paper
#     (requires: ollama serve && ollama pull llama3)
RD_LLM_PROVIDER=ollama uv run refactoring-debate examples/sample_code.py

# 4. Run the REST API
uv run uvicorn refactoring_debate.main:app --reload
#    -> Swagger UI at http://localhost:8000/docs
```

### Analyze code over HTTP

```bash
curl -s http://localhost:8000/api/v1/analyze \
  -H 'content-type: application/json' \
  -d '{"filename": "sample.py", "code": "def f(x):\n    return [i for i in range(x)]\n"}' | jq
```

---

## Configuration

Everything is configured via environment variables (prefix `RD_`) or `.env`. The most
important switches:

| Variable | Default | Purpose |
|----------|---------|---------|
| `RD_LLM_PROVIDER` | `ollama` | `ollama` \| `openai` \| `anthropic` \| `heuristic` |
| `RD_LLM_MODEL` | `ollama/llama3` | model id passed to the provider |
| `RD_DEBATE_ROUNDS` | `1` | number of cross-critique rounds |
| `RD_WEIGHT_*` | `~0.33` | Judge decision weights per dimension |
| `RD_ENABLE_DYNAMIC_ANALYSIS` | `false` | run Scalene/py-spy/cProfile (executes the code!) |
| `RD_SONARQUBE_URL` / `_TOKEN` | empty | enable SonarQube when set |

See [`.env.example`](.env.example) for the full list (defaults to the paper's local
Ollama+Llama3 backend). To run the debate on a hosted model instead — handy for comparing a
small local model against a larger one across the experiment repos — copy the ready-made
[`.env.anthropic.example`](.env.anthropic.example) (Claude, with an OpenAI variant included):

```bash
uv sync --extra anthropic        # one-time: CrewAI gates the Claude provider behind this extra
cp .env.anthropic.example .env   # then paste your key into RD_LLM_API_KEY
```
(OpenAI needs no extra — set `RD_LLM_PROVIDER=openai` and `RD_LLM_MODEL=openai/gpt-4o-mini`.)

> **Safety note:** Dynamic analysis *executes the submitted code*. It is disabled by default.
> Only enable it for code you trust, ideally inside a container/sandbox.

---

## Research questions

The system is built to investigate the paper's research questions:

- **Q1** — Do multi-agent systems increase the **diversity** of identified refactorings vs. a single agent?
- **Q2** — Does specialization let the system consider a **broader set of quality attributes**?
- **Q3** — Which **conflicts** emerge between agents during recommendation?

The API records, for every request, the per-agent findings, the cross-critiques, the detected
conflicts, the negotiated trade-offs, and processing time — the raw material for the validation
plan (frequencies and medians, no statistical means).

---

## Evaluating on open-source repos

A batch harness runs the debate over every Python file in a cloned repo and aggregates the
paper's indicators as **frequencies and medians** (with a single-agent baseline for Q1):

```bash
git clone --depth 1 https://github.com/pallets/typer corpus/typer
uv run python scripts/evaluate.py corpus/typer --baseline --max-files 30
# -> per_file.csv, summary.json, summary.md (Q1/Q2/Q3, conflict types, medians)

# Fast, LLM-free metric snapshot for before/after comparison (indicator v):
uv run python scripts/evaluate.py corpus/typer --metrics-only
```

The full walkthrough is in [`docs/EVALUATION_TUTORIAL.md`](docs/EVALUATION_TUTORIAL.md)
(build the PDF with `uv sync --extra docs && make tutorial`).

---

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy src        # type-check
```

## License

MIT.
