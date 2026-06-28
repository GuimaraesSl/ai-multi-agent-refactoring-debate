.DEFAULT_GOAL := help
EXAMPLE ?= examples/sample_code.py
EVAL_TARGET ?= src/refactoring_debate

.PHONY: help install env api example example-dynamic evaluate tutorial test lint format typecheck contracts check sonar-up sonar-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install all dependencies (Python 3.12)
	uv sync --extra dev

env: ## Create a .env from the template
	cp -n .env.example .env || true

api: ## Run the FastAPI server with autoreload (http://localhost:8000/docs)
	uv run uvicorn refactoring_debate.main:app --reload --host $${RD_API_HOST:-0.0.0.0} --port $${RD_API_PORT:-8000}

example: ## Run the debate on the bundled example file
	uv run refactoring-debate $(EXAMPLE)

example-dynamic: ## Run the debate on the example WITH dynamic profiling/energy
	uv run refactoring-debate $(EXAMPLE) --dynamic

evaluate: ## Batch-evaluate a repo/dir (override EVAL_TARGET=path) with single-agent baseline
	uv run python scripts/evaluate.py $(EVAL_TARGET) --baseline

tutorial: ## Build the evaluation tutorial PDF (needs: uv sync --extra docs)
	uv run python scripts/build_tutorial_pdf.py

test: ## Run the test suite
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check .

format: ## Auto-format with ruff
	uv run ruff format . && uv run ruff check --fix .

typecheck: ## Type-check with mypy
	uv run mypy src

contracts: ## Verify the architectural import contracts
	uv run lint-imports

check: lint typecheck test contracts ## Run all checks

sonar-up: ## Start a local SonarQube server (requires Docker)
	docker compose up -d sonarqube

sonar-down: ## Stop the local SonarQube server
	docker compose down

clean: ## Remove caches and runtime artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache runs emissions.csv .codecarbon
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
