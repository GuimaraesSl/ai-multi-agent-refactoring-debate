"""Request/response schemas for the REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Body for ``POST /api/v1/analyze``."""

    code: str = Field(min_length=1, description="Python source code to analyze.")
    filename: str = Field(default="submitted.py", description="Logical filename (for reporting).")
    debate_rounds: int | None = Field(
        default=None, ge=0, le=5, description="Override the number of cross-critique rounds."
    )
    enable_dynamic_analysis: bool | None = Field(
        default=None,
        description="Override dynamic analysis (executes the code — use only for trusted input).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filename": "example.py",
                    "code": (
                        "def find_duplicates(items):\n"
                        "    out = []\n"
                        "    for i in range(len(items)):\n"
                        "        for j in range(len(items)):\n"
                        "            if i != j and items[i] == items[j] and items[i] not in out:\n"
                        "                out.append(items[i])\n"
                        "    return out\n"
                    ),
                }
            ]
        }
    }


class LLMStatus(BaseModel):
    requested_provider: str
    effective_provider: str
    label: str
    uses_llm: bool
    note: str = ""


class ToolStatusItem(BaseModel):
    name: str
    category: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    llm: LLMStatus
    tools: list[ToolStatusItem]
    dynamic_analysis_enabled: bool
    sonarqube_enabled: bool


class ConfigResponse(BaseModel):
    """Non-secret view of the effective configuration."""

    llm_provider: str
    llm_model: str
    debate_rounds: int
    decision_weights: dict[str, float]
    enable_dynamic_analysis: bool
    dynamic_timeout: int
    sonarqube_enabled: bool
    runs_dir: str | None
