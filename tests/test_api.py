"""REST API tests using FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from refactoring_debate.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # triggers lifespan -> builds orchestrator
        yield c


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm"]["effective_provider"] == "heuristic"
    assert {"radon", "scalene", "codecarbon"}.issubset({t["name"] for t in body["tools"]})


def test_config(client: TestClient) -> None:
    body = client.get("/api/v1/config").json()
    assert set(body["decision_weights"]) == {"sustainability", "architecture", "performance"}
    assert abs(sum(body["decision_weights"].values()) - 1.0) < 1e-6


def test_analyze_returns_full_debate(client: TestClient) -> None:
    code = (
        "def f(xs):\n"
        "    out=[]\n"
        "    for i in range(len(xs)):\n"
        "        for j in range(len(xs)):\n"
        "            if xs[i]==xs[j] and i!=j: out.append(xs[i])\n"
        "    return out\n"
    )
    resp = client.post("/api/v1/analyze", json={"code": code, "filename": "t.py"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["agent_reports"]) == 3
    assert body["consolidated"]
    assert body["research_metrics"]["quality_attributes_covered"] >= 1
    assert body["llm_provider"] == "heuristic"


def test_analyze_rejects_empty_code(client: TestClient) -> None:
    resp = client.post("/api/v1/analyze", json={"code": ""})
    assert resp.status_code == 422  # min_length=1


def test_unknown_run_is_404(client: TestClient) -> None:
    resp = client.get("/api/v1/runs/does-not-exist")
    assert resp.status_code == 404
