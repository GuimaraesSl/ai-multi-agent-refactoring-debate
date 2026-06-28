"""Shared test fixtures.

Tests run entirely in heuristic mode (no LLM, no dynamic execution) so they are
deterministic, offline and fast.
"""

from __future__ import annotations

import os

# Force a deterministic, offline configuration before any settings are read.
os.environ["RD_LLM_PROVIDER"] = "heuristic"
os.environ["RD_ENABLE_DYNAMIC_ANALYSIS"] = "false"
os.environ["RD_RUNS_DIR"] = ""
os.environ["RD_DEBATE_ROUNDS"] = "1"

import pytest  # noqa: E402

from refactoring_debate.config import Settings  # noqa: E402
from refactoring_debate.core.orchestrator import Orchestrator  # noqa: E402

QUADRATIC_GOD_CLASS = '''\
import os

def find_duplicates(items):
    out = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i != j and items[i] == items[j] and items[i] not in out:
                out.append(items[i])
    return out

class ReportManager:
    def __init__(self, data): self.data = data
    def a(self): ...
    def b(self): ...
    def c(self): ...
    def d(self): ...
    def e(self): ...
    def f(self): ...
    def g(self): ...
    def h(self): ...
    def run(self): return find_duplicates(self.data)
'''


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def orchestrator(settings: Settings) -> Orchestrator:
    return Orchestrator(settings)


@pytest.fixture()
def sample_code() -> str:
    return QUADRATIC_GOD_CLASS
