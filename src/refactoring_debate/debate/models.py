"""Domain models for recommendations and the debate record."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from refactoring_debate.core.ast_parser import ASTRepresentation
from refactoring_debate.core.metrics import MetricsReport, Severity


class Dimension(str, Enum):
    """The three competing quality dimensions, plus the mediating judge."""

    SUSTAINABILITY = "sustainability"
    ARCHITECTURE = "architecture"
    PERFORMANCE = "performance"
    JUDGE = "judge"


class Effort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Stance(str, Enum):
    """A peer's position on another agent's recommendation."""

    SUPPORT = "support"
    CONCERN = "concern"
    OPPOSE = "oppose"


class ConflictType(str, Enum):
    PERFORMANCE_VS_SUSTAINABILITY = "performance_vs_sustainability"
    PERFORMANCE_VS_ARCHITECTURE = "performance_vs_architecture"
    ARCHITECTURE_VS_SUSTAINABILITY = "architecture_vs_sustainability"
    DIRECT_CONTRADICTION = "direct_contradiction"
    OVERLAP = "overlap"  # same target tackled by multiple agents


class Status(str, Enum):
    ACCEPTED = "accepted"
    MERGED = "merged"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class Recommendation(BaseModel):
    """A single refactoring proposal from a specialist agent."""

    id: str
    dimension: Dimension
    title: str
    rationale: str = ""
    target: str | None = None  # function/class/module the change applies to
    line: int | None = None
    severity: Severity = Severity.MEDIUM
    effort: Effort = Effort.MEDIUM
    confidence: float = 0.6
    evidence: list[str] = Field(default_factory=list)  # metric-grounded support
    tags: list[str] = Field(default_factory=list)


class AgentReport(BaseModel):
    """A specialist's local analysis (paper §4.2, step 4)."""

    agent: str
    dimension: Dimension
    summary: str = ""
    recommendations: list[Recommendation] = Field(default_factory=list)
    model: str | None = None
    raw_output: str | None = None  # raw LLM text, for traceability


class Critique(BaseModel):
    """A cross-review comment from one specialist on another's recommendation."""

    from_dimension: Dimension
    target_recommendation_id: str
    stance: Stance
    message: str


class Conflict(BaseModel):
    """An explicit design conflict surfaced during the debate (Q3)."""

    id: str
    type: ConflictType
    description: str
    dimensions: list[Dimension] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)


class Tradeoff(BaseModel):
    """How the judge resolved a conflict by weighing dimensions."""

    description: str
    favored: Dimension
    sacrificed: list[Dimension] = Field(default_factory=list)
    rationale: str = ""
    weights: dict[str, float] = Field(default_factory=dict)


class DebateRound(BaseModel):
    index: int
    critiques: list[Critique] = Field(default_factory=list)


class DebateRecord(BaseModel):
    """The structured transcript of the peer-review debate."""

    rounds: list[DebateRound] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    tradeoffs: list[Tradeoff] = Field(default_factory=list)
    judge_summary: str = ""

    @property
    def all_critiques(self) -> list[Critique]:
        return [c for rnd in self.rounds for c in rnd.critiques]


class ConsolidatedRecommendation(Recommendation):
    """A recommendation after the judge's arbitration."""

    priority: int = 0  # 1 = highest
    status: Status = Status.ACCEPTED
    judge_rationale: str = ""
    supersedes: list[str] = Field(default_factory=list)


class ResearchMetrics(BaseModel):
    """Indicators backing the paper's validation questions (Q1, Q2, Q3)."""

    distinct_recommendations: int = 0  # Q1: diversity of opportunities
    quality_attributes_covered: int = 0  # Q2: breadth of attributes (0-3)
    attributes_covered: list[Dimension] = Field(default_factory=list)
    conflicts_detected: int = 0  # Q3: explicit conflicts
    cross_critiques: int = 0


class Timings(BaseModel):
    parse_ms: float = 0.0
    tools_ms: float = 0.0
    agents_ms: float = 0.0
    debate_ms: float = 0.0
    total_ms: float = 0.0


class AnalysisResult(BaseModel):
    """The full consolidated output returned by the pipeline (paper §4.2, step 6)."""

    request_id: str
    filename: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    llm_provider: str = ""
    llm_model: str = ""

    ast: ASTRepresentation
    metrics: MetricsReport
    agent_reports: list[AgentReport] = Field(default_factory=list)
    debate: DebateRecord = Field(default_factory=DebateRecord)
    consolidated: list[ConsolidatedRecommendation] = Field(default_factory=list)

    summary: str = ""
    research_metrics: ResearchMetrics = Field(default_factory=ResearchMetrics)
    timings: Timings = Field(default_factory=Timings)

    def compute_research_metrics(self) -> ResearchMetrics:
        """Derive Q1/Q2/Q3 indicators from the populated result."""
        covered = sorted(
            {r.dimension for r in self.consolidated if r.dimension != Dimension.JUDGE},
            key=lambda d: d.value,
        )
        rm = ResearchMetrics(
            distinct_recommendations=len(self.consolidated),
            quality_attributes_covered=len(covered),
            attributes_covered=covered,
            conflicts_detected=len(self.debate.conflicts),
            cross_critiques=len(self.debate.all_critiques),
        )
        self.research_metrics = rm
        return rm
